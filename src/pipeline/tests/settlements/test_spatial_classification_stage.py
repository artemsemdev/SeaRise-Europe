from __future__ import annotations

from collections import namedtuple
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import duckdb
import pytest

from searise_pipeline.settlements import full_source_stage as source_stage
from searise_pipeline.settlements import normalized_catalogue_stage as catalogue_stage
from searise_pipeline.settlements import spatial_classification as classification
from searise_pipeline.settlements import spatial_classification_stage as stage
from searise_pipeline.settlements import spatial_toolchain as toolchain
from searise_pipeline.settlements.alternate_names import NameVariant
from searise_pipeline.settlements.catalogue import CataloguePlace
from searise_pipeline.settlements.geonames import Lineage

ROOT = Path(__file__).parents[4]
FIXTURE = ROOT / "src/pipeline/tests/settlements/fixtures/spatial/fixture-manifest.json"
TOOLCHAIN = ROOT / "src/pipeline/toolchain/duckdb-spatial-extensions.json"
GEOMETRY = classification.load_fixture_geometry_bindings(FIXTURE, repository_root=ROOT)
PIN = toolchain.load_spatial_manifest(TOOLCHAIN).platforms["linux-x86_64"]
# fmt: off
EVIDENCE = toolchain.SpatialToolchainEvidence("linux-x86_64", "1.5.4", PIN.extension.relative_path, PIN.extension.sha256, (12.5, 41.9), 5.0)  # noqa: E501

Case = namedtuple("Case", "sourceLine placeId name latitude longitude population supportCovers coastalCovers distanceToShorelineMeters")  # noqa: E501
CASES = tuple(Case(*row) for row in (
    (1, "geonames:900000101", "Inland City", 52.0, 3.0, 1200, True, False, 205754),
    (2, "geonames:900000102", "Coastal Village", 52.0, 0.5, 0, True, True, 34291),
    (5, "geonames:900000105", "Excluded City", 52.0, 5.0, 4000, False, False, 342820),
))
# fmt: on


def _place(case: Case) -> CataloguePlace:
    source_id = int(case.placeId.removeprefix("geonames:"))
    # fmt: off
    return CataloguePlace(
        case.placeId, case.name, NameVariant(case.name, None, "Latn"), case.name, (), "XX",
        None, None, case.latitude, case.longitude, case.population, "PPL", date(2026, 8, 10),
        (Lineage("synthetic-spatial-cases", "fixture-manifest.json#cases", "synthetic-v1",
                 case.sourceLine, source_id, classification.SPATIAL_FIXTURE_SHA256),),
    )
    # fmt: on


def _catalogue(path: Path) -> None:
    with duckdb.connect(str(path)) as connection:
        connection.execute(
            "CREATE TABLE catalogue_places(geoname_id UBIGINT, place_id VARCHAR, document VARCHAR)"
        )
        for place in map(_place, CASES):
            geoname_id = int(place.id.removeprefix("geonames:"))
            connection.execute(
                "INSERT INTO catalogue_places VALUES (?, ?, ?)",
                [geoname_id, place.id, source_stage._canonical_json(place)],
            )


def _options(tmp_path: Path) -> dict[str, object]:
    inputs = stage.SpatialAssetInputs(
        ROOT, tmp_path, tmp_path / "work", TOOLCHAIN, EVIDENCE, GEOMETRY
    )
    return {"asset_inputs": inputs}


def _stub_authority(monkeypatch: pytest.MonkeyPatch) -> None:
    @contextmanager
    def prepared(**inputs):  # type: ignore[no-untyped-def]
        geometry, evidence = inputs["geometry"], inputs["evidence"]
        private = Path("/private/.spatial-assets-authority")
        snapshots = tuple(
            SimpleNamespace(role=item.role, path=private / item.role, sha256=item.sha256)
            for item in geometry.items
        )
        # fmt: off
        yield stage.SpatialAssetPaths(
            TOOLCHAIN, stage.SPATIAL_TOOLCHAIN_MANIFEST_SHA256, private / "spatial.duckdb_extension",  # noqa: E501
            evidence.extension_sha256, snapshots, geometry.contract_sha256, evidence,
        )
        # fmt: on

    monkeypatch.setattr(stage, "prepare_spatial_asset_authority", prepared)
    monkeypatch.setattr(stage._NativeSpatialCapability, "_load", lambda *_: None)


def _materialize(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    catalogue_path = tmp_path / "catalogue.duckdb"
    candidate_path = tmp_path / "spatial.duckdb"
    _catalogue(catalogue_path)
    receipt = {"fixture": True}
    values = [
        classification.SpatialResultRow(
            case.placeId, case.supportCovers, case.coastalCovers, case.distanceToShorelineMeters
        )
        for case in CASES
    ]
    _stub_authority(monkeypatch)
    monkeypatch.setattr(stage, "_catalogue_authority", lambda *_: {"fixture": True})
    monkeypatch.setattr(stage, "_spatial_rows", lambda *args: iter(values))
    (tmp_path / "work").mkdir()
    with (
        duckdb.connect(str(catalogue_path), read_only=True) as catalogue,
        duckdb.connect(str(candidate_path)) as candidate,
    ):
        assert stage._schema_objects(candidate) == set()
        identity = stage.materialize_spatial_candidate(
            catalogue, candidate, receipt, **_options(tmp_path)
        )
    return catalogue_path, candidate_path, receipt, identity


def test_candidate_is_exact_reconciled_and_resource_bounded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(stage, "MAX_BATCH_ROWS", 2)
    catalogue, candidate, receipt, identity = _materialize(tmp_path, monkeypatch)
    document = stage.spatial_receipt(identity)
    with (
        duckdb.connect(str(catalogue), read_only=True) as opened_catalogue,
        duckdb.connect(str(candidate), read_only=True) as opened_candidate,
    ):
        validated = stage.validate_spatial_candidate(
            opened_catalogue, opened_candidate, receipt, document, **_options(tmp_path)
        )
        assert validated == identity


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("UPDATE spatial_places SET document='{}' WHERE geoname_id=900000101", "replay"),
        ("CREATE VIEW leaked AS SELECT * FROM read_csv_auto('/etc/passwd')", "objects"),
        ("CREATE SCHEMA alien", "objects"),
        (
            "ALTER TABLE spatial_places ALTER geoname_id DROP NOT NULL;"
            "CREATE TEMP TABLE spatial_places(geoname_id UBIGINT NOT NULL,"
            "place_id VARCHAR NOT NULL,document VARCHAR NOT NULL);"
            "CREATE TEMP TABLE spatial_rejections(geoname_id UBIGINT NOT NULL,"
            "place_id VARCHAR NOT NULL,reason VARCHAR NOT NULL,document VARCHAR NOT NULL)",
            "columns",
        ),
    ],
)
def test_validation_rejects_candidate_drift_and_persistent_objects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation: str, message: str
) -> None:
    catalogue, candidate, receipt, identity = _materialize(tmp_path, monkeypatch)
    with duckdb.connect(str(candidate)) as connection:
        connection.execute(mutation)
    with (
        duckdb.connect(str(catalogue), read_only=True) as opened_catalogue,
        duckdb.connect(str(candidate), read_only=True) as opened_candidate,
    ):
        with pytest.raises(stage.SpatialStageError, match=message):
            document = stage.spatial_receipt(identity)
            stage.validate_spatial_candidate(
                opened_catalogue, opened_candidate, receipt, document, **_options(tmp_path)
            )


# fmt: off
@pytest.mark.parametrize("mutation", ("CREATE TEMP TABLE alien_table(value INTEGER)", "CREATE TEMP VIEW alien_view AS SELECT 1 AS value", "CREATE TEMP MACRO alien_macro(value) AS value + 1"))  # noqa: E501
# fmt: on
def test_schema_boundaries_reject_temp_objects(mutation: str) -> None:
    for schema_exists in (False, True):
        with duckdb.connect() as connection:
            if schema_exists:
                stage._create_schema(connection)
            connection.execute(mutation)
            validator = stage._validate_schema if schema_exists else stage._create_schema
            with pytest.raises(stage.SpatialStageError):
                validator(connection)


def test_streaming_is_bounded_and_temp_lifecycle_is_reusable(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    class Cursor:
        remaining = 100_001

        def fetchmany(self, size):  # type: ignore[no-untyped-def]
            assert size == 17
            count = min(size, self.remaining)
            self.remaining -= count
            return [(None,)] * count

        def fetchall(self):  # type: ignore[no-untyped-def]
            raise AssertionError("unbounded fetch is prohibited")

    assert sum(1 for _ in catalogue_stage._rows(Cursor(), 17)) == 100_001
    tables = set()

    def execute(sql, *_):  # type: ignore[no-untyped-def]
        if sql.startswith("CREATE TEMP TABLE"):
            name = sql.split()[3].split("(")[0]
            assert name not in tables
            tables.add(name)
        elif sql.startswith("DROP TABLE"):
            tables.clear()
        elif sql == stage.classification_sql():
            return SimpleNamespace(fetchmany=lambda _: ())
        return connection

    connection = SimpleNamespace(execute=execute, executemany=lambda *_: None)
    capability = SimpleNamespace(_read_geometries=lambda _: None)
    monkeypatch.setattr(stage, "_catalogue_places", lambda _: iter(()))
    assert [list(stage._spatial_rows(connection, None, capability)) for _ in range(2)] == [[], []]
    # fmt: off
    monkeypatch.setattr(stage, "_catalogue_places", lambda _: (_ for _ in ()).throw(RuntimeError("classification failed")))  # noqa: E501
    # fmt: on
    with pytest.raises(RuntimeError, match="classification failed"):
        list(stage._spatial_rows(connection, None, capability))
    assert tables == set()


def test_public_validation_normalizes_dependency_failure(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    failure = source_stage.FullSourceStageError("malformed spatial receipt")
    monkeypatch.setattr(stage, "_validation_snapshots", lambda *_: (_ for _ in ()).throw(failure))
    with pytest.raises(stage.SpatialStageError) as caught:
        stage.validate_spatial_stage(tmp_path, tmp_path, tmp_path, tmp_path, **_options(tmp_path))
    assert isinstance(caught.value.__cause__, source_stage.FullSourceStageError)


def test_validation_cleanup_preserves_primary_and_alien_entry(tmp_path: Path) -> None:
    work = tmp_path / "work"
    work.mkdir()
    paths = {}
    for name in ("catalogue.duckdb", "spatial.duckdb", "catalogue.json", "spatial.json"):
        path = tmp_path / name
        path.write_bytes(name.encode())
        paths[name] = path
    primary = RuntimeError("primary validation failure")
    with pytest.raises(RuntimeError) as caught:
        with stage._validation_snapshots(paths, work) as (root, _):
            (root / "alien").mkdir()
            raise primary
    assert caught.value is primary
    assert "alien entry" in " ".join(getattr(primary, "__notes__", ()))
    assert (next(work.glob(".spatial-assets-*")) / "alien").is_dir()
