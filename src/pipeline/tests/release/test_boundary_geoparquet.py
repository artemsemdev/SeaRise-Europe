"""Deterministic engineering-only boundary GeoParquet packaging."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import geopandas as gpd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
import shapely
from shapely import affinity

from searise_pipeline.release import (
    validate_boundary_geoparquet,
    write_boundary_geoparquet,
)
from searise_pipeline.science import ScienceContractError

REPO_ROOT = Path(__file__).resolve().parents[4]
SOURCES = {
    "support-boundary": REPO_ROOT / "data/geometry/europe.geojson",
    "coastal-boundary": REPO_ROOT / "data/geometry/coastal_analysis_zone.geojson",
}
SOURCE_HASHES = {
    "support-boundary": "dd98b938df00fc582bbd220b913d96b1fd19bab812e2e9d95ecc4b409330a385",
    "coastal-boundary": "aa08f31460c80cbe35eefb44c6f8feb22b90727840eda3734241d707d7a910d9",
}
PARITY_PATH = (
    REPO_ROOT
    / "src/pipeline/science/evidence/geography-classifier-parity-v1.json"
)
PARITY_RELEASE_ROOT = (
    REPO_ROOT
    / "contracts/release/v2/fixtures/browser-release"
    / "searise-europe-v1.0.0-20260810-c096aeab4e09"
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_browser_classifier_golden_matches_shapely_covers_on_exact_geoparquet() -> None:
    fixture = json.loads(PARITY_PATH.read_text(encoding="utf-8"))
    support_identity = fixture["release"]["supportArtifact"]
    coastal_identity = fixture["release"]["coastalArtifact"]
    support_path = PARITY_RELEASE_ROOT / support_identity["path"]
    coastal_path = PARITY_RELEASE_ROOT / coastal_identity["path"]
    assert _sha256(support_path) == support_identity["sha256"]
    assert _sha256(coastal_path) == coastal_identity["sha256"]

    support = gpd.read_parquet(support_path).geometry.iloc[0]
    coastal = gpd.read_parquet(coastal_path).geometry.iloc[0]
    assert fixture["semantics"] == {
        "operation": "OGC-covers",
        "boundaryInclusive": True,
        "epsilonDegrees": 0.00001,
        "classificationOrder": ["support", "coastal"],
    }
    assert {case["boundaryRole"] for case in fixture["cases"]} == {
        "support",
        "coastal",
    }
    assert {case["relation"] for case in fixture["cases"]} == {
        "exterior-boundary",
        "hole-boundary",
        "epsilon-inside",
        "epsilon-outside",
    }

    for case in fixture["cases"]:
        coordinates = case["coordinates"]
        point = shapely.Point(coordinates["longitude"], coordinates["latitude"])
        support_covers = support.covers(point)
        coastal_covers = coastal.covers(point)
        classification = (
            "OutsideEurope"
            if not support_covers
            else (
                "InEuropeAndCoastalZone"
                if coastal_covers
                else "InEuropeOutsideCoastalZone"
            )
        )
        assert support_covers is case["expectedSupportCovers"], case["id"]
        assert coastal_covers is case["expectedCoastalCovers"], case["id"]
        assert classification == case["expectedClassification"], case["id"]
        if case["relation"].endswith("boundary"):
            boundary = support.boundary if case["boundaryRole"] == "support" else coastal.boundary
            assert boundary.covers(point), case["id"]


@pytest.mark.parametrize("role", sorted(SOURCES))
def test_boundary_geoparquet_is_exact_and_byte_deterministic(
    tmp_path: Path, role: str
) -> None:
    first = tmp_path / f"{role}-first.parquet"
    second = tmp_path / f"{role}-second.parquet"

    first_evidence = write_boundary_geoparquet(SOURCES[role], first, role=role)
    second_evidence = write_boundary_geoparquet(SOURCES[role], second, role=role)
    validate_boundary_geoparquet(first, SOURCES[role], role=role)

    assert first.read_bytes() == second.read_bytes()
    assert first_evidence == second_evidence
    assert first_evidence.source_sha256 == SOURCE_HASHES[role]
    assert first_evidence.row_count == 1
    assert first_evidence.sha256 == {
        "support-boundary": "531c6042a33cf3be9bc3ea340b0e557cb66bafb34de7954db0d7e47be90d35a9",
        "coastal-boundary": "3ba4d5eaba24d1202482bc33fd64fde8ce54b7ff1dd1456990d3c8cfece43366",
    }[role]
    assert first_evidence.byte_size == {
        "support-boundary": 267676,
        "coastal-boundary": 667750,
    }[role]

    parquet = pq.ParquetFile(first)
    metadata = parquet.metadata.metadata or {}
    boundary = json.loads(metadata[b"searise:boundary"])
    geo = json.loads(metadata[b"geo"])
    assert boundary["schemaVersion"] == "1.0.0"
    assert boundary["role"] == role
    assert boundary["status"] == "selected-scope-approximation"
    assert boundary["purpose"] == "product-eligibility-only"
    assert boundary["engineeringUse"] == "engineering-only"
    assert boundary["publicationEligible"] is False
    assert boundary["canonical"] is False
    assert boundary["production"] is False
    assert boundary["hazardExtentClaim"] is False
    assert boundary["lineage"]["input"]["sha256"] == SOURCE_HASHES[role]
    assert boundary["lineage"]["input"]["path"] == {
        "support-boundary": "data/geometry/europe.geojson",
        "coastal-boundary": "data/geometry/coastal_analysis_zone.geojson",
    }[role]
    assert boundary["lineage"]["contract"] == {
        "path": "src/pipeline/science/geography-rules.json",
        "sha256": "195b7128ba5483a633e8e35187541b0b884ed8644ac40ae8191c9db9935becf5",
    }
    assert boundary["lineage"]["source"] == {
        "assetId": {
            "support-boundary": "admin-0-countries",
            "coastal-boundary": "ocean",
        }[role],
        "sourceId": "natural-earth-10m",
        "version": "5.1.1",
    }
    assert boundary["normalization"] == "crs84-multipolygon-rings-v1"
    assert boundary["rights"] == {
        "attribution": "Made with Natural Earth.",
        "licence": "Natural Earth public domain dedication",
        "spdx": "LicenseRef-Natural-Earth-Public-Domain",
        "url": "https://www.naturalearthdata.com/about/terms-of-use/",
    }
    assert geo["columns"]["geometry"]["crs"]["id"] == {
        "authority": "OGC",
        "code": "CRS84",
    }
    assert geo["columns"]["geometry"]["geometry_types"] == ["MultiPolygon"]
    readback = gpd.read_parquet(first)
    assert readback.crs is not None and readback.crs.to_string() == "OGC:CRS84"
    packaged = readback.geometry.iloc[0]
    assert packaged.is_valid
    assert all(
        value == round(value, 6)
        for polygon in packaged.geoms
        for ring in (polygon.exterior, *polygon.interiors)
        for value in (coordinate for point in ring.coords for coordinate in point)
    )
    for polygon in packaged.geoms:
        assert shapely.is_ccw(polygon.exterior)
        assert tuple(polygon.exterior.coords)[0] == min(tuple(polygon.exterior.coords)[:-1])
        for interior in polygon.interiors:
            assert not shapely.is_ccw(interior)
            assert tuple(interior.coords)[0] == min(tuple(interior.coords)[:-1])


def test_boundary_geoparquet_rejects_mutated_source(tmp_path: Path) -> None:
    source = json.loads(SOURCES["support-boundary"].read_text(encoding="utf-8"))
    source["features"][0]["geometry"]["coordinates"][0][0][0][0] += 0.000001
    mutated = tmp_path / "mutated.geojson"
    mutated.write_text(json.dumps(source), encoding="utf-8")

    with pytest.raises(ScienceContractError, match="input SHA-256"):
        write_boundary_geoparquet(
            mutated,
            tmp_path / "mutated.parquet",
            role="support-boundary",
        )


@pytest.mark.parametrize(
    ("tamper", "message"),
    [
        ("geometry", "geometry"),
        ("status", "row values"),
        ("metadata", "metadata"),
        ("compression", "compression"),
        ("compression-level", "bytes or compression"),
    ],
)
def test_boundary_geoparquet_rejects_artifact_tampering(
    tmp_path: Path, tamper: str, message: str
) -> None:
    source = SOURCES["support-boundary"]
    baseline = tmp_path / "baseline.parquet"
    write_boundary_geoparquet(source, baseline, role="support-boundary")
    table = pq.read_table(baseline)
    metadata = dict(table.schema.metadata or {})
    compression = "zstd"
    compression_level = None

    if tamper == "geometry":
        geometry = shapely.from_wkb(table["geometry"][0].as_py())
        index = table.schema.get_field_index("geometry")
        table = table.set_column(
            index,
            table.schema.field(index),
            pa.array(
                [shapely.to_wkb(affinity.translate(geometry, xoff=0.001), byte_order=1)],
                type=pa.binary(),
            ),
        )
    elif tamper == "status":
        index = table.schema.get_field_index("status")
        table = table.set_column(
            index,
            table.schema.field(index),
            pa.array(["canonical"], type=pa.string()),
        )
    elif tamper == "metadata":
        boundary = json.loads(metadata[b"searise:boundary"])
        boundary["publicationEligible"] = True
        metadata[b"searise:boundary"] = json.dumps(
            boundary, sort_keys=True, separators=(",", ":")
        ).encode()
        table = table.replace_schema_metadata(metadata)
    elif tamper == "compression":
        compression = "NONE"
    else:
        compression_level = 1

    tampered = tmp_path / f"tampered-{tamper}.parquet"
    pq.write_table(
        table,
        tampered,
        compression=compression,
        compression_level=compression_level,
        use_dictionary=False,
    )

    with pytest.raises(ScienceContractError, match=message):
        validate_boundary_geoparquet(
            tampered,
            source,
            role="support-boundary",
        )
