"""Contract tests for the direct Natural Earth settlement coastline."""

from __future__ import annotations

import hashlib
import importlib
import json
import os
import zipfile
from copy import deepcopy
from pathlib import Path

import geopandas as gpd
import pytest
from shapely.geometry import LineString, shape

from searise_pipeline.settlements import coastline as coastline_module
from searise_pipeline.settlements.coastline import (
    build_coastline,
    build_coastline_evidence,
    inspect_coastline_artifact,
)
from searise_pipeline.settlements.coastline_contract import (
    CoastlineContractError,
    load_coastline_policy,
)

REPO_ROOT = Path(__file__).parents[4]
POLICY_PATH = REPO_ROOT / "src/pipeline/settlements/shoreline-distance-policy-v1.json"
POLICY_SCHEMA_PATH = REPO_ROOT / "src/pipeline/settlements/shoreline-distance-policy-v1.schema.json"
SOURCE_LOCK_PATH = REPO_ROOT / "src/pipeline/sources/source-lock.phase-1-settlement-coastline.json"


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, document: dict) -> None:
    path.write_text(json.dumps(document, sort_keys=True), encoding="utf-8")


def _member_inventory(archive_path: Path) -> list[dict]:
    with zipfile.ZipFile(archive_path) as archive:
        return [
            {
                "id": info.filename.rsplit(".", maxsplit=1)[-1].lower(),
                "path": info.filename,
                "role": "settlement-coastline-source-member",
                "nativeVersion": "unused-by-test-helper",
                "byteSize": info.file_size,
                "compressedByteSize": info.compress_size,
                "crc32": f"{info.CRC:08x}",
                "sha256": hashlib.sha256(archive.read(info.filename)).hexdigest(),
            }
            for info in archive.infolist()
        ]


def _write_shape_archive(
    root: Path,
    stem: str,
    geometries: list[LineString],
    native_version: str,
) -> Path:
    shape_root = root / stem
    shape_root.mkdir()
    gpd.GeoDataFrame(
        {
            "featurecla": ["Coastline"] * len(geometries),
            "scalerank": [0] * len(geometries),
            "min_zoom": [0.0] * len(geometries),
            "geometry": geometries,
        },
        crs=4326,
    ).to_file(shape_root / f"{stem}.shp")
    (shape_root / f"{stem}.VERSION.txt").write_bytes((native_version + "\r\n").encode("ascii"))
    (shape_root / f"{stem}.README.html").write_text("fixture", encoding="ascii")
    archive_path = root / f"{stem}.zip"
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(shape_root.iterdir()):
            archive.write(path, arcname=path.name)
    return archive_path


def _synthetic_contract(tmp_path: Path) -> tuple[Path, Path, dict[str, Path]]:
    policy = deepcopy(_json(POLICY_PATH))
    assets = {
        "coastline": _write_shape_archive(
            tmp_path,
            "ne_10m_coastline",
            [LineString([(-35, 52), (0, 52), (50, 52)])],
            "5.0.0-pre9",
        ),
        "minor-islands-coastline": _write_shape_archive(
            tmp_path,
            "ne_10m_minor_islands_coastline",
            [LineString([(10, 40), (10.5, 40.5)])],
            "4.1.0",
        ),
    }
    lock = deepcopy(_json(SOURCE_LOCK_PATH))
    locked_assets = {item["id"]: item for item in lock["sources"][0]["assets"]}
    policy_assets = {item["assetId"]: item for item in policy["source"]["assets"]}
    for asset_id, archive_path in assets.items():
        locked = locked_assets[asset_id]
        locked["byteSize"] = archive_path.stat().st_size
        locked["sha256"] = _sha256(archive_path)
        locked["members"] = _member_inventory(archive_path)
        for member in locked["members"]:
            member["nativeVersion"] = locked["nativeVersion"]
        bound = policy_assets[asset_id]
        bound["archiveByteSize"] = locked["byteSize"]
        bound["archiveSha256"] = locked["sha256"]
        bound["memberInventorySha256"] = hashlib.sha256(
            json.dumps(locked["members"], sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        bound["memberPaths"] = [member["path"] for member in locked["members"]]
    lock_path = tmp_path / "source-lock.phase-1-settlement-coastline.json"
    _write_json(lock_path, lock)
    policy["sourceLock"]["sha256"] = _sha256(lock_path)
    policy_path = tmp_path / "shoreline-distance-policy-v1.json"
    _write_json(policy_path, policy)
    return lock_path, policy_path, assets


def test_checked_in_linework_is_valid_direct_and_passes_named_controls() -> None:
    policy = load_coastline_policy(POLICY_PATH, POLICY_SCHEMA_PATH)

    report = inspect_coastline_artifact(REPO_ROOT, policy)

    assert report["valid"] is True
    assert report["geometryTypes"] == ["LineString"]
    assert report["featureCount"] == policy["output"]["featureCount"] == 1218
    assert report["coordinateCount"] == policy["output"]["coordinateCount"] == 87246
    assert report["bySourceAsset"] == {
        "coastline": 537,
        "minor-islands-coastline": 681,
    }
    assert report["boundsWgs84"] == policy["output"]["boundsWgs84"]
    assert report["controls"] == {"count": 4, "passed": 4}
    assert report["featuresTruncated"] == 0
    assert policy["distanceMethod"] == {
        "coordinateOrder": "longitude-latitude-xy",
        "distanceExpression": "ST_Distance(place_3035, shoreline_3035)",
        "distanceUnit": "meter",
        "engine": "duckdb-spatial",
        "engineVersion": "1.5.4",
        "hybridNearestDegreesAllowed": False,
        "inputCrs": "EPSG:4326",
        "metricCrs": "EPSG:3035",
        "spheroidDistanceAllowed": False,
        "transformExpression": ("ST_Transform(geometry, 'EPSG:4326', 'EPSG:3035', true)"),
    }
    assert policy["distanceMethodVersion"] == ("epsg3035-planar-whole-meter-half-even-v1")
    assert policy["distancePersistence"] == {
        "expression": "CAST(ST_Distance(place_3035, shoreline_3035) AS BIGINT)",
        "field": "distance_to_coast_m",
        "inputType": "DOUBLE",
        "outputType": "BIGINT",
        "roundingMode": "nearest-half-to-even",
        "subMeterPrecisionClaim": False,
        "unit": "whole-meter",
    }
    assert [item["persistedDistanceMeters"] for item in report["controlResults"]] == [
        169,
        549,
        2916,
        390855,
    ]
    for control, result in zip(policy["controls"], report["controlResults"]):
        assert "distanceMeters" not in result
        assert set(result) == {
            "expectedNearestAssetId",
            "id",
            "maximumDistanceMeters",
            "minimumDistanceMeters",
            "nearestAssetId",
            "passed",
            "persistedDistanceMeters",
        }
        assert result["minimumDistanceMeters"] == control["minimumDistanceMeters"]
        assert result["maximumDistanceMeters"] == control["maximumDistanceMeters"]
        assert result["expectedNearestAssetId"] == control["expectedNearestAssetId"]
    assert policy["coastalClassification"] == {
        "derivedFromShorelineDistance": False,
        "geometryVersion": "natural-earth-5.1.1-25km-scope-v2",
        "predicate": "ST_Covers",
    }
    expected_evidence = (
        json.dumps(
            build_coastline_evidence(REPO_ROOT, POLICY_PATH),
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        + b"\n"
    )
    assert (REPO_ROOT / policy["evidencePath"]).read_bytes() == expected_evidence


def test_exact_verified_archives_rebuild_checked_in_bytes_twice() -> None:
    main = os.environ.get("SEARISE_NE_COASTLINE_ARCHIVE")
    minor = os.environ.get("SEARISE_NE_MINOR_ISLANDS_COASTLINE_ARCHIVE")
    if not main or not minor:
        if os.environ.get("SEARISE_REQUIRE_EXACT_COASTLINE_REBUILD") == "1":
            pytest.fail("mandatory exact Natural Earth shoreline archives were not supplied")
        pytest.skip("exact ignored Natural Earth archives were not supplied")
    archives = {"coastline": Path(main), "minor-islands-coastline": Path(minor)}

    first = build_coastline(SOURCE_LOCK_PATH, POLICY_PATH, archives)
    second = build_coastline(SOURCE_LOCK_PATH, POLICY_PATH, archives)
    output = REPO_ROOT / load_coastline_policy(POLICY_PATH)["output"]["path"]

    assert first == second == output.read_bytes()


def test_pinned_duckdb_double_to_bigint_cast_is_half_even() -> None:
    try:
        duckdb = importlib.import_module("duckdb")
    except ModuleNotFoundError:
        if os.environ.get("SEARISE_REQUIRE_DUCKDB_NUMERIC_SEMANTICS") == "1":
            pytest.fail("mandatory pinned DuckDB numeric-semantics check could not execute")
        pytest.skip("pinned DuckDB build plane is not installed")

    assert duckdb.__version__ == "1.5.4"
    observed = duckdb.sql(
        """
        SELECT CAST(value AS BIGINT)
        FROM (VALUES (0.5::DOUBLE), (1.5::DOUBLE), (2.5::DOUBLE), (3.5::DOUBLE))
             AS controls(value)
        """
    ).fetchall()
    assert observed == [(0,), (2,), (2,), (4,)]


def test_synthetic_rebuild_selects_whole_lines_without_created_endpoints(tmp_path: Path) -> None:
    lock_path, policy_path, archives = _synthetic_contract(tmp_path)

    first = build_coastline(lock_path, policy_path, archives)
    second = build_coastline(lock_path, policy_path, archives)
    document = json.loads(first)
    lines = [shape(feature["geometry"]) for feature in document["features"]]

    assert first == second
    original = LineString([(-35, 52), (0, 52), (50, 52)])
    rebuilt = next(line for line in lines if line.equals(original))
    assert rebuilt.equals_exact(original, tolerance=0)
    assert set(rebuilt.coords) == {(-35.0, 52.0), (0.0, 52.0), (50.0, 52.0)}
    assert not any(coordinate[0] in {-30.0, 45.0} for coordinate in rebuilt.coords)


def test_named_control_mutation_fails_closed(tmp_path: Path) -> None:
    policy = deepcopy(_json(POLICY_PATH))
    policy["controls"][0]["maximumDistanceMeters"] = 2000
    policy_path = tmp_path / POLICY_PATH.name
    _write_json(policy_path, policy)

    with pytest.raises(CoastlineContractError, match="named controls"):
        inspect_coastline_artifact(
            REPO_ROOT,
            load_coastline_policy(policy_path, POLICY_SCHEMA_PATH),
        )


@pytest.mark.parametrize(
    ("attribute", "value"),
    [("__version__", "0.11.0"), ("__gdal_version_string__", "3.10.2")],
)
def test_io_toolchain_mutation_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    attribute: str,
    value: str,
) -> None:
    monkeypatch.setattr(coastline_module.pyogrio, attribute, value)

    with pytest.raises(CoastlineContractError, match="toolchain"):
        inspect_coastline_artifact(
            REPO_ROOT,
            load_coastline_policy(POLICY_PATH, POLICY_SCHEMA_PATH),
        )


def test_artifact_hash_mutation_fails_closed(tmp_path: Path) -> None:
    policy = deepcopy(_json(POLICY_PATH))
    policy["output"]["sha256"] = "0" * 64
    policy_path = tmp_path / POLICY_PATH.name
    _write_json(policy_path, policy)

    with pytest.raises(CoastlineContractError, match="checksum"):
        inspect_coastline_artifact(
            REPO_ROOT,
            load_coastline_policy(policy_path, POLICY_SCHEMA_PATH),
        )
