from __future__ import annotations

import hashlib
import io
import json
from datetime import date
from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from searise_pipeline.settlements import full_source_stage as source_stage
from searise_pipeline.settlements import spatial_classification as classification
from searise_pipeline.settlements import spatial_classification_stage as spatial_stage
from searise_pipeline.settlements import spatial_geoparquet as module
from searise_pipeline.settlements.alternate_names import NameVariant
from searise_pipeline.settlements.catalogue import CataloguePlace
from searise_pipeline.settlements.geonames import ALL_COUNTRIES_SOURCE, Lineage
from searise_pipeline.settlements.spatial_toolchain import SpatialToolchainEvidence

ROOT = Path(__file__).parents[4]
RELEASE = "searise-europe-v1.0.0-20260812-34974982e794"


def _write_receipt(path: Path, candidate: dict) -> None:  # type: ignore[type-arg]
    candidate.pop("deterministicIdentity", None)
    candidate["deterministicIdentity"] = hashlib.sha256(
        (source_stage._canonical_json(candidate) + "\n").encode()
    ).hexdigest()
    path.write_text(source_stage._canonical_json(spatial_stage.spatial_receipt(candidate)) + "\n")


def _document(identifier: int) -> str:
    source = ALL_COUNTRIES_SOURCE
    # fmt: off
    lineage = Lineage(source.asset_id, source.source_file, source.source_release, identifier, identifier, source.source_sha256)  # noqa: E501
    place = CataloguePlace(
        f"geonames:{identifier}", f"Place {identifier}", NameVariant(f"Place {identifier}", "en", "Latn"),  # noqa: E501
        f"Place {identifier}", (), "DE", "BE", "Berlin", 52.0 + identifier / 1_000_000,
        13.0 + identifier / 1_000_000, 600, "PPL", date(2026, 8, 10), (lineage,),
    )
    # fmt: on
    return source_stage._canonical_json(
        {
            "catalogMembership": ("europe-core",),
            "coastalCovers": False,
            "distanceToShorelineMeters": identifier,
            "place": place,
            "supportCovers": True,
        }
    )


def _fixture(tmp_path: Path, rows: int = 2) -> tuple[Path, Path, Path]:
    database, receipt, work = tmp_path / "spatial.db", tmp_path / "spatial.json", tmp_path / "work"
    work.mkdir()
    documents = [_document(101 + index) for index in range(rows)]
    with duckdb.connect(str(database)) as connection:
        spatial_stage._create_schema(connection)
        connection.executemany(
            "INSERT INTO spatial_places VALUES (?,?,?)",
            [
                (101 + index, f"geonames:{101 + index}", value)
                for index, value in enumerate(documents)
            ],
        )
        connection.execute("CHECKPOINT")
    geometry = classification.production_geometry_bindings(ROOT)
    counts = dict.fromkeys(module._COUNT_KEYS, 0)
    counts.update(normalizedPlaces=rows, classifiedPlaces=rows, europeCoreMemberships=rows)
    hashes = {
        "classifiedPlaces": hashlib.sha256(
            b"".join(value.encode() + b"\n" for value in documents)
        ).hexdigest(),
        "spatialRejections": hashlib.sha256().hexdigest(),
    }
    evidence = SpatialToolchainEvidence(
        "linux-x86_64", "1.5.4", "spatial", "b" * 64, (12.5, 41.9), 5.0
    )
    candidate = spatial_stage._candidate_identity(
        {"deterministicIdentity": "a" * 64}, geometry, evidence, counts, hashes
    )
    _write_receipt(receipt, candidate)
    return database, receipt, work


def _serialize(
    paths: tuple[Path, Path, Path],
) -> tuple[io.BytesIO, module.SpatialGeoParquetEvidence]:
    stream = io.BytesIO()
    evidence = module.serialize_spatial_geoparquet(
        paths[0], paths[1], stream, data_release_id=RELEASE, work_dir=paths[2]
    )
    return stream, evidence


def test_deterministic_stream_binds_exact_receipt_and_full_v3_metadata(tmp_path: Path) -> None:
    paths = _fixture(tmp_path)
    first, evidence = _serialize(paths)
    second, second_evidence = _serialize(paths)
    assert first.getvalue() == second.getvalue() and evidence == second_evidence
    assert evidence == module.validate_spatial_geoparquet(first, *paths[:2], work_dir=paths[2])
    metadata = pq.ParquetFile(first).schema_arrow.metadata
    envelope = json.loads(metadata[b"searise:settlement"])
    binding = json.loads(metadata[b"searise:spatial-receipt"])
    assert len(envelope["arrowFields"]) == 32 and envelope["publicationEligible"] is False and envelope["scientificApprovalClaim"] is False  # noqa: E501  # fmt: skip
    assert binding["receiptSha256"] == hashlib.sha256(paths[1].read_bytes()).hexdigest()


def test_validator_rejects_a_different_but_self_consistent_receipt(tmp_path: Path) -> None:
    paths = _fixture(tmp_path)
    stream, _ = _serialize(paths)
    document = json.loads(paths[1].read_text())
    candidate = document["candidate"]
    candidate["inputCatalogue"] = {"deterministicIdentity": "b" * 64}
    _write_receipt(paths[1], candidate)
    with pytest.raises(module.SpatialGeoParquetError, match="schema or metadata"):
        module.validate_spatial_geoparquet(stream, *paths[:2], work_dir=paths[2])


@pytest.mark.parametrize("mutation", ["truncate", "fabricate", "metadata", "groups"])
def test_validator_rejects_row_and_schema_mutations(tmp_path: Path, mutation: str) -> None:
    paths = _fixture(tmp_path)
    stream, _ = _serialize(paths)
    table = pq.read_table(stream)
    if mutation == "truncate":
        table = table.slice(0, 1)
    elif mutation == "fabricate":
        table = table.take(pa.array([1, 0]))
    elif mutation == "metadata":
        table = table.replace_schema_metadata({})
    stream.seek(0)
    stream.truncate(0)
    pq.write_table(table, stream, compression="zstd", compression_level=9, use_dictionary=False, row_group_size=1 if mutation == "groups" else None)  # noqa: E501  # fmt: skip
    with pytest.raises(module.SpatialGeoParquetError):
        module.validate_spatial_geoparquet(stream, *paths[:2], work_dir=paths[2])


@pytest.mark.parametrize("mutation", ["database", "claim", "path", "predicate", "symlink"])
def test_serializer_rejects_unbound_spatial_inputs(tmp_path: Path, mutation: str) -> None:
    paths = _fixture(tmp_path)
    if mutation == "database":
        with duckdb.connect(str(paths[0])) as connection:
            connection.execute("UPDATE spatial_places SET document='{}' WHERE geoname_id=101")
    elif mutation in {"claim", "path", "predicate"}:
        document = json.loads(paths[1].read_text())
        if mutation == "claim":
            document["candidate"]["publicationClaim"] = True
        else:
            document["candidate"]["geometry"]["geometries"][0][mutation] = "tampered"
        _write_receipt(paths[1], document["candidate"])
    else:
        linked = tmp_path / "linked.db"
        linked.symlink_to(paths[0])
        paths = linked, paths[1], paths[2]
    with pytest.raises(module.SpatialGeoParquetError):
        _serialize(paths)


def test_fixed_batches_bound_memory_and_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(module, "ROW_GROUP_SIZE", 2)
    stream, evidence = _serialize(_fixture(tmp_path, rows=5))
    assert evidence.row_count == 5 and [pq.ParquetFile(stream).metadata.row_group(index).num_rows for index in range(3)] == [2, 2, 1]  # noqa: E501  # fmt: skip
