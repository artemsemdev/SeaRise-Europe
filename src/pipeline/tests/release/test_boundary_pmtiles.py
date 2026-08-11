"""Atomic writer integration for visual-only boundary PMTiles."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

import searise_pipeline.release.boundary_pmtiles as boundary_pmtiles
from searise_pipeline.release import (
    BoundaryVectorToolPaths,
    VectorToolchainEvidence,
    write_boundary_pmtiles,
)
from searise_pipeline.science import ScienceContractError

from .test_boundary_pmtiles_structure import GEOJSON, _source
from .test_source_fixture import contract

TOOL_ENVIRONMENT = """SEARISE_TIPPECANOE SEARISE_TIPPECANOE_DECODE SEARISE_PMTILES
SEARISE_TIPPECANOE_SOURCE SEARISE_TIPPECANOE_BUILD_RECEIPT SEARISE_PMTILES_ASSET
SEARISE_VECTOR_PLATFORM""".split()


def _tools(tmp_path: Path) -> BoundaryVectorToolPaths:
    missing = tmp_path / "missing"
    return BoundaryVectorToolPaths(
        tippecanoe=missing,
        decode=missing,
        pmtiles=missing,
        tippecanoe_source=missing,
        tippecanoe_build_receipt=missing,
        pmtiles_distribution_asset=missing,
        platform="darwin-arm64",
    )


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


def test_boundary_pmtiles_fails_closed_without_pinned_tools(tmp_path: Path) -> None:
    with pytest.raises(ScienceContractError, match="executable is absent"):
        write_boundary_pmtiles(
            _source(tmp_path),
            GEOJSON["support-boundary"],
            tmp_path / "boundary.pmtiles",
            role="support-boundary",
            contract=contract(),
            tools=_tools(tmp_path),
        )


def test_generation_metadata_binds_every_material_writer_step(tmp_path: Path) -> None:
    source = boundary_pmtiles._load_source(
        _source(tmp_path, "coastal-boundary"),
        GEOJSON["coastal-boundary"],
        role="coastal-boundary",
    )
    metadata = boundary_pmtiles._expected_metadata(
        source, _tool_evidence(), build_receipt_sha256="f" * 64
    )
    assert metadata["searise"]["generation"] == {
        "angular_error_model": {
            "comparison": (
                "symmetric-vertex-to-boundary-discrete-distance-"
                "plus-per-axis-envelope"
            ),
            "coordinate_error_degrees": 360 / 2**23,
            "geometry_tolerance_degrees": 2**0.5 * 360 / 2**23,
            "maximum_rounding_stages": 2,
            "model": "web-mercator-mvt-quantization-plus-tile-clipping",
            "per_stage_coordinate_error_degrees": 180 / 2**23,
            "quantization_step_degrees": 360 / 2**23,
        },
        "gzip_canonicalization": {
            "method": "tippecanoe-tile-member-os-byte-rewrite",
            "operating_system_byte": 255,
        },
        "pmtiles_metadata_edit": "canonical-json-replacement",
        "visual_intermediary": {
            "canonical_source_modified": False,
            "coordinate_space": "EPSG:4326-degrees",
            "maximum_segment_length_degrees": 0.10,
            "method": "shapely-segmentize",
            "purpose": "bound-nonlinear-web-mercator-chord-error",
            "source": "boundaries/coastal-analysis-zone.parquet",
            "topology_required": "identical-polygon-and-interior-ring-counts",
        },
        "tippecanoe_options": [
            "--force",
            "--layer=coastal_boundary",
            "--projection=EPSG:4326",
            "--minimum-zoom=0",
            "--maximum-zoom=6",
            "--full-detail=17",
            "--buffer=0",
            "--no-feature-limit",
            "--no-tile-size-limit",
            "--no-line-simplification",
            "--no-tiny-polygon-reduction",
            "--no-tiny-polygon-reduction-at-maximum-zoom",
            "--preserve-input-order",
        ],
    }


def test_boundary_pmtiles_rejects_corruption_reported_by_pinned_tool(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _source(tmp_path)
    archive = tmp_path / "corrupt.pmtiles"
    archive.write_bytes(b"corrupt")
    (tmp_path / "missing").write_bytes(b"validated receipt fixture")
    monkeypatch.setattr(
        boundary_pmtiles, "validate_vector_toolchain", lambda **_kwargs: _tool_evidence()
    )

    def failed_verify(_command: list[str]) -> str:
        raise ScienceContractError("Pinned vector tool failed: corrupt archive")

    monkeypatch.setattr(boundary_pmtiles, "_run", failed_verify)
    with pytest.raises(ScienceContractError, match="corrupt archive"):
        boundary_pmtiles.validate_boundary_pmtiles(
            archive,
            source,
            GEOJSON["support-boundary"],
            role="support-boundary",
            contract=contract(),
            tools=_tools(tmp_path),
        )


@pytest.mark.skipif(
    not all(os.environ.get(name) for name in TOOL_ENVIRONMENT),
    reason="exact pinned vector binaries and official assets are required",
)
@pytest.mark.parametrize("role", sorted(GEOJSON))
def test_boundary_pmtiles_real_build_is_byte_deterministic(tmp_path: Path, role: str) -> None:
    source = _source(tmp_path, role)
    tools = BoundaryVectorToolPaths(
        tippecanoe=Path(os.environ["SEARISE_TIPPECANOE"]),
        decode=Path(os.environ["SEARISE_TIPPECANOE_DECODE"]),
        pmtiles=Path(os.environ["SEARISE_PMTILES"]),
        tippecanoe_source=Path(os.environ["SEARISE_TIPPECANOE_SOURCE"]),
        tippecanoe_build_receipt=Path(os.environ["SEARISE_TIPPECANOE_BUILD_RECEIPT"]),
        pmtiles_distribution_asset=Path(os.environ["SEARISE_PMTILES_ASSET"]),
        platform=os.environ["SEARISE_VECTOR_PLATFORM"],
    )
    first = tmp_path / "first.pmtiles"
    second = tmp_path / "second.pmtiles"
    first_evidence = write_boundary_pmtiles(
        source, GEOJSON[role], first, role=role, contract=contract(), tools=tools
    )
    second_evidence = write_boundary_pmtiles(
        source, GEOJSON[role], second, role=role, contract=contract(), tools=tools
    )
    assert first.read_bytes() == second.read_bytes()
    assert first_evidence.sha256 == second_evidence.sha256
