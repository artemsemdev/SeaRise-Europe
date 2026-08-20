"""Prove the committed browser range fixture is a valid, deterministic later-chunk COG."""

from __future__ import annotations

import hashlib
import json
import runpy
import struct
from pathlib import Path

import geopandas as gpd
import pyarrow.parquet as pq
import pytest
from shapely.geometry import Point, Polygon, shape

import searise_pipeline.release as release_api
import searise_pipeline.release.boundary_geoparquet as boundary_module
from searise_pipeline.release.boundary_geoparquet import (
    _browser_fixture_arrow_schemas,
    _write_browser_fixture_boundary_geoparquet,
)
from searise_pipeline.science import ScienceContractError

ROOT = Path(__file__).parents[4]
RELEASE_ID = "searise-europe-v1.0.0-20260810-c096aeab4e09"
SOURCE = ROOT / "contracts/release/v1/fixtures/release" / RELEASE_ID / "analysis/ssp2-45/2050.tif"
OVERLAY_ROOT = ROOT / "contracts/release/v2/fixtures/browser-release" / RELEASE_ID
COMMITTED = OVERLAY_ROOT / "analysis/ssp2-45/2050.tif"
BUILDER = runpy.run_path(str(ROOT / "scripts/release/build-browser-integrity-fixture.py"))
CONTROL = ROOT / "src/pipeline/fixtures/browser-release/adr-024-nodata-control-v1.json"
ARROW_SCHEMAS = ROOT / "src/pipeline/fixtures/browser-release/boundary-arrow-schemas-v1.json"
SOURCES = {
    "support-boundary": ROOT / "data/geometry/europe.geojson",
    "coastal-boundary": ROOT / "data/geometry/coastal_analysis_zone.geojson",
}
COMMITTED_BOUNDARIES = {
    "support-boundary": OVERLAY_ROOT / "boundaries/europe.parquet",
    "coastal-boundary": OVERLAY_ROOT / "boundaries/coastal-analysis-zone.parquet",
}


def test_browser_fixture_writer_is_not_public_release_api() -> None:
    assert not hasattr(release_api, "write_browser_fixture_boundary_geoparquet")
    assert not hasattr(release_api, "_write_browser_fixture_boundary_geoparquet")


@pytest.mark.parametrize("role", sorted(SOURCES))
def test_browser_only_nodata_boundary_is_deterministic_and_explicit(
    tmp_path: Path,
    role: str,
) -> None:
    rebuilt = tmp_path / f"{role}.parquet"
    evidence = _write_browser_fixture_boundary_geoparquet(
        SOURCES[role],
        rebuilt,
        role=role,
        control_path=CONTROL,
        arrow_schema_path=ARROW_SCHEMAS,
    )
    committed = COMMITTED_BOUNDARIES[role]
    assert rebuilt.read_bytes() == committed.read_bytes()
    assert evidence.sha256 == hashlib.sha256(committed.read_bytes()).hexdigest()
    control = json.loads(CONTROL.read_text(encoding="utf-8"))
    control_polygon = Polygon(control["boundaryControl"]["ring"])
    audited_document = json.loads(SOURCES[role].read_text(encoding="utf-8"))
    audited_geometry = shape(audited_document["features"][0]["geometry"])
    assert audited_geometry.disjoint(control_polygon)

    geometry = gpd.read_parquet(committed).geometry.iloc[0]
    assert geometry.is_valid
    assert geometry.covers(Point(44, 62))
    metadata = pq.ParquetFile(committed).metadata.metadata or {}
    assert metadata[b"ARROW:schema"] == _browser_fixture_arrow_schemas(ARROW_SCHEMAS)[role]
    boundary = json.loads(metadata[b"searise:boundary"])
    assert boundary["browserFixtureControl"] == {
        "controlId": "browser-only-source-nodata-62n-44e",
        "dataProvenanceClass": "synthetic-fixture",
        "fixtureOnly": True,
        "path": "src/pipeline/fixtures/browser-release/adr-024-nodata-control-v1.json",
        "sha256": "55a3811d7c56879b5ac5cff6e0a868cd22a8a545305ddb718a9697244c431d2e",
    }


@pytest.mark.parametrize("mutation", ["payload", "decoded-length"])
def test_browser_fixture_arrow_schema_rejects_corruption(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    document = json.loads(ARROW_SCHEMAS.read_text(encoding="utf-8"))
    record = document["schemas"]["support-boundary"]
    if mutation == "payload":
        record["payload"] = f"!{record['payload'][1:]}"
        message = "payload is corrupt"
    else:
        record["decodedLength"] += 1
        message = "payload differs from the pin"
    mutated = tmp_path / "mutated-arrow-schemas.json"
    mutated.write_text(json.dumps(document), encoding="utf-8")
    monkeypatch.setattr(
        boundary_module,
        "_BROWSER_FIXTURE_ARROW_SCHEMAS_SHA256",
        hashlib.sha256(mutated.read_bytes()).hexdigest(),
    )

    with pytest.raises(ScienceContractError, match=message):
        _browser_fixture_arrow_schemas(mutated)


def test_browser_nodata_control_binds_all_twenty_seven_cog_values() -> None:
    manifest = json.loads(
        (ROOT / "contracts/release/v1/fixtures/release" / RELEASE_ID / "manifest.json").read_text(
            encoding="utf-8"
        )
    )
    cogs = [item for item in manifest["artifacts"] if item["role"] == "projection-analysis-cog"]
    control = json.loads(CONTROL.read_text(encoding="utf-8"))

    BUILDER["_validate_nodata_control"](control, cogs)


def test_committed_browser_cog_is_deterministic_and_moves_real_tiles_later(
    tmp_path: Path,
) -> None:
    rebuilt = tmp_path / "later-chunk.tif"
    BUILDER["_write_later_chunk_cog"](SOURCE, rebuilt)
    assert rebuilt.read_bytes() == COMMITTED.read_bytes()

    payload = COMMITTED.read_bytes()
    positions = BUILDER["_classic_tiff_tile_offset_positions"](payload)
    tile_offsets = [struct.unpack_from("<I", payload, position)[0] for position in positions]
    assert min(tile_offsets) >= 3 * 65_536
    assert max(tile_offsets) < len(payload)

    range_index = json.loads(
        (OVERLAY_ROOT / "analysis/cog-range-integrity.json").read_text(encoding="utf-8")
    )
    identity = next(
        item
        for item in range_index["artifacts"]
        if item["artifactId"] == "projection-ssp2-45-2050-cog"
    )
    assert identity["byteSize"] == len(payload)
    assert len(identity["chunks"]) == 4
    assert identity["chunks"][-1]["start"] == 3 * 65_536
