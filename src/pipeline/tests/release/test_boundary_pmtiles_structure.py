"""Visual-only PMTiles derived from exact boundary GeoParquet artifacts."""

from __future__ import annotations

import copy
from dataclasses import replace
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
import shapely

import searise_pipeline.release.boundary_pmtiles as boundary_pmtiles
from searise_pipeline.release import (
    VectorToolchainEvidence,
    write_boundary_geoparquet,
)
from searise_pipeline.science import ScienceContractError

REPO_ROOT = Path(__file__).resolve().parents[4]
GEOJSON = {
    "support-boundary": REPO_ROOT / "data/geometry/europe.geojson",
    "coastal-boundary": REPO_ROOT / "data/geometry/coastal_analysis_zone.geojson",
}


def _source(tmp_path: Path, role: str = "support-boundary") -> Path:
    source = tmp_path / f"{role}.parquet"
    write_boundary_geoparquet(GEOJSON[role], source, role=role)
    return source


def _tool_evidence() -> VectorToolchainEvidence:
    return VectorToolchainEvidence(
        tippecanoe_version="2.79.0",
        tippecanoe_source_sha256="a" * 64,
        tippecanoe_binary_sha256="b" * 64,
        pmtiles_version="1.31.2",
        pmtiles_commit="a3e4951ea6a0477b784c27c1dcbfd9c130878c5a",
        pmtiles_binary_sha256="c" * 64,
        pmtiles_distribution_platform="darwin-arm64",
        pmtiles_distribution_sha256="d" * 64,
        decode_binary_sha256="e" * 64,
    )


def _header(source: object, *, byte_size: int = 1000) -> dict[str, object]:
    return {
        "spec_version": 3,
        "root_dir_offset": 127,
        "root_dir_bytes": 100,
        "json_metadata_offset": 227,
        "json_metadata_bytes": 200,
        "leaf_dirs_offset": 427,
        "leaf_dirs_bytes": 50,
        "tile_data_offset": 477,
        "tile_data_bytes": byte_size - 477,
        "addressed_tiles_count": 5,
        "tile_entries_count": 4,
        "tile_contents_count": 3,
        "clustered": True,
        "internal_compression": "gzip",
        "tile_compression": "gzip",
        "tile_type": "mvt",
        "minzoom": 0,
        "maxzoom": 6,
        "bounds": list(source.specification.header_bounds),
        "center": list(source.specification.header_center),
    }


def _reported_header(header: dict[str, object]) -> dict[str, object]:
    return {
        key: header[key]
        for key in ("tile_compression", "tile_type", "minzoom", "maxzoom", "bounds", "center")
    }


def test_boundary_pmtiles_requires_exact_geo_parquet_bytes(tmp_path: Path) -> None:
    source = _source(tmp_path)
    payload = bytearray(source.read_bytes())
    payload[len(payload) // 2] ^= 1
    source.write_bytes(payload)

    with pytest.raises(ScienceContractError, match="GeoParquet identity"):
        boundary_pmtiles._load_source(source, GEOJSON["support-boundary"], role="support-boundary")


def test_boundary_pmtiles_fails_closed_on_shapely_version_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(shapely, "__version__", "2.0.8")
    with pytest.raises(ScienceContractError, match="exact Shapely 2.0.7"):
        boundary_pmtiles._require_shapely()


def test_boundary_pmtiles_rejects_unsafe_source_row(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _source(tmp_path)
    table = pq.read_table(source)
    index = table.schema.get_field_index("status")
    table = table.set_column(
        index,
        table.schema.field(index),
        pa.array(["canonical"], type=pa.string()),
    )
    pq.write_table(table, source, compression="zstd", use_dictionary=False)
    specification = boundary_pmtiles._BOUNDARIES["support-boundary"]
    monkeypatch.setitem(
        boundary_pmtiles._BOUNDARIES,
        "support-boundary",
        replace(
            specification,
            source_byte_size=source.stat().st_size,
            source_sha256=boundary_pmtiles._sha256(source),
        ),
    )
    monkeypatch.setattr(boundary_pmtiles, "validate_boundary_geoparquet", lambda *_a, **_k: None)

    with pytest.raises(ScienceContractError, match="safe row values"):
        boundary_pmtiles._load_source(
            source,
            GEOJSON["support-boundary"],
            role="support-boundary",
        )


def test_boundary_pmtiles_metadata_binds_safe_use_lineage_and_tools(tmp_path: Path) -> None:
    source = boundary_pmtiles._load_source(
        _source(tmp_path, "coastal-boundary"),
        GEOJSON["coastal-boundary"],
        role="coastal-boundary",
    )
    metadata = boundary_pmtiles._expected_metadata(
        source,
        _tool_evidence(),
        build_receipt_sha256="f" * 64,
    )

    searise = metadata["searise"]
    assert searise["role"] == "coastal-boundary"
    assert searise["status"] == "selected-scope-approximation"
    assert searise["purpose"] == "product-eligibility-only"
    assert searise["visual_only"] is True
    assert searise["analytical_lookup"] == "prohibited"
    for field in ("publication_eligible", "canonical", "production", "hazard_extent_claim"):
        assert searise[field] is False
    assert searise["source_geoparquet"] == {
        "byte_size": 667750,
        "path": "boundaries/coastal-analysis-zone.parquet",
        "sha256": "3ba4d5eaba24d1202482bc33fd64fde8ce54b7ff1dd1456990d3c8cfece43366",
    }
    assert searise["toolchain"]["platform"] == "darwin-arm64"
    assert searise["toolchain"]["shapely_version"] == "2.0.7"
    assert searise["toolchain"]["tippecanoe_build_receipt_sha256"] == "f" * 64
    assert metadata["attribution"] == "Made with Natural Earth."


def test_boundary_pmtiles_rejects_metadata_and_header_mutations(tmp_path: Path) -> None:
    source = boundary_pmtiles._load_source(
        _source(tmp_path), GEOJSON["support-boundary"], role="support-boundary"
    )
    evidence = _tool_evidence()
    metadata = boundary_pmtiles._expected_metadata(source, evidence, build_receipt_sha256="f" * 64)
    mutated_status = copy.deepcopy(metadata)
    mutated_status["searise"]["publication_eligible"] = True
    mutated_extra = copy.deepcopy(metadata)
    mutated_extra["generator_options"] = "unsafe"
    for mutated in (mutated_status, mutated_extra):
        with pytest.raises(ScienceContractError, match="safe allow-list"):
            boundary_pmtiles._validate_metadata(
                mutated, source, evidence, build_receipt_sha256="f" * 64
            )

    header = _header(source)
    reported = _reported_header(header)
    encoded = boundary_pmtiles._PMTILES_HEADER.pack(
        b"PMTiles",
        3,
        *(127, 100, 227, 200, 427, 50, 477, 523, 5, 4, 3),
        *(1, 2, 2, 1, 0, 6),
        *(round(value * 10_000_000) for value in source.specification.header_bounds),
        *(6, 253_125_000, 387_888_940),
    )
    archive = tmp_path / "header.pmtiles"
    archive.write_bytes(encoded + bytes(1000 - len(encoded)))
    assert boundary_pmtiles._read_pmtiles_header(archive) == header
    boundary_pmtiles._validate_header(header, reported, source, byte_size=1000)
    with pytest.raises(ScienceContractError, match="decoded header disagree"):
        boundary_pmtiles._validate_header(
            header, {**reported, "maxzoom": 5}, source, byte_size=1000
        )
    for field, value, error in (
        ("spec_version", 2, "generation parameters"),
        ("clustered", False, "generation parameters"),
        ("internal_compression", "none", "generation parameters"),
        ("tile_contents_count", 6, "tile counts"),
        ("tile_data_bytes", 522, "canonical and contiguous"),
    ):
        mutated = {**header, field: value}
        with pytest.raises(ScienceContractError, match=error):
            boundary_pmtiles._validate_header(mutated, reported, source, byte_size=1000)
