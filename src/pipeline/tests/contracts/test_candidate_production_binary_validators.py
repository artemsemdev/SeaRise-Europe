from __future__ import annotations

from pathlib import Path

import pytest

import searise_pipeline.candidate_completeness.production_binary_validators as subject
from searise_pipeline.candidate_completeness.production_binary_validators import (
    BoundaryQaAuthority,
    ProductionBinaryQaAuthorities,
    ProjectionQaAuthority,
    SettlementQaAuthority,
    production_binary_validator_registry,
)
from searise_pipeline.candidate_completeness.qa_dispatch import (
    CandidateQaContext,
    QaValidationRequest,
)
from searise_pipeline.candidate_completeness.qa_matrix import ArtifactSelector
from searise_pipeline.science import ScienceContractError


class _Layer:
    scenario = "ssp2-45"
    horizon = 2050


class _Source:
    layers = (_Layer(),)


def _authorities(tmp_path: Path) -> ProductionBinaryQaAuthorities:
    projection = ProjectionQaAuthority(
        source=_Source(),  # type: ignore[arg-type]
        contract={},
        tippecanoe=tmp_path / "tippecanoe",
        decode=tmp_path / "decode",
        pmtiles=tmp_path / "pmtiles",
        tippecanoe_source=tmp_path / "tippecanoe-source",
        tippecanoe_build_receipt=tmp_path / "tippecanoe-receipt",
        pmtiles_distribution_asset=tmp_path / "pmtiles-asset",
        platform="test-platform",
    )
    boundary = BoundaryQaAuthority(
        contract={},
        support_geojson=tmp_path / "europe.geojson",
        coastal_geojson=tmp_path / "coastal.geojson",
        tools=object(),  # type: ignore[arg-type]
    )
    settlement = SettlementQaAuthority(
        spatial_database=tmp_path / "spatial.duckdb",
        spatial_receipt=tmp_path / "spatial.receipt.json",
        work_directory=tmp_path / "work",
    )
    return ProductionBinaryQaAuthorities(projection, boundary, settlement)


def _request(root: Path, relative: str, role: str, media_type: str) -> QaValidationRequest:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"candidate bytes")
    return QaValidationRequest(
        artifact_id=path.stem,
        artifact_path=path,
        selector=ArtifactSelector(role, media_type, "identity"),
        declared_sha256="0" * 64,
        candidate=CandidateQaContext(
            candidate_root=root,
            candidate_id="candidate-phase-1-real-source-20260812-0123456789ab",
            data_release_id="searise-europe-v1.0.0-20260812-0123456789ab",
            data_provenance_class="real-source",
            manifest_sha256=None,
            artifact_count=51,
        ),
    )


def test_binary_registry_has_exact_non_json_routes(tmp_path: Path) -> None:
    registry = production_binary_validator_registry(_authorities(tmp_path))
    assert set(registry) == {
        "release.analysis-cog",
        "release.projection-geoparquet",
        "release.projection-pmtiles",
        "release.boundary-geoparquet.support",
        "release.boundary-geoparquet.coastal",
        "release.boundary-pmtiles.support",
        "release.boundary-pmtiles.coastal",
        "settlements.geoparquet",
    }


def test_projection_route_selects_exact_layer_and_reports_validation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    observed = []
    monkeypatch.setattr(
        subject,
        "validate_analysis_cog",
        lambda path, layer, *, contract: observed.append((path, layer, contract)),
    )
    registry = production_binary_validator_registry(_authorities(tmp_path))
    request = _request(
        tmp_path,
        "analysis/ssp2-45/2050.tif",
        "projection-analysis-cog",
        "image/tiff; application=geotiff; profile=cloud-optimized",
    )
    outcome = registry["release.analysis-cog"](request)
    assert outcome.status == "pass"
    assert observed[0][1] is _Source.layers[0]

    wrong = _request(
        tmp_path,
        "analysis/ssp5-85/2050.tif",
        "projection-analysis-cog",
        "image/tiff; application=geotiff; profile=cloud-optimized",
    )
    assert registry["release.analysis-cog"](wrong).status == "fail"


def test_expected_science_failure_is_an_explicit_failed_outcome(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def reject(*_args, **_kwargs):
        raise ScienceContractError("decoded properties differ")

    monkeypatch.setattr(subject, "validate_visual_pmtiles", reject)
    registry = production_binary_validator_registry(_authorities(tmp_path))
    request = _request(
        tmp_path,
        "layers/ssp2-45/2050.pmtiles",
        "projection-visual-pmtiles",
        "application/vnd.pmtiles",
    )
    outcome = registry["release.projection-pmtiles"](request)
    assert outcome.status == "fail"
    assert outcome.code == "projection-pmtiles-invalid"


def test_boundary_routes_use_authoritative_boundary_role_ids(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    roles = []
    monkeypatch.setattr(
        subject,
        "validate_boundary_geoparquet",
        lambda path, source, *, role: roles.append(role),
    )
    registry = production_binary_validator_registry(_authorities(tmp_path))
    support = _request(
        tmp_path,
        "boundaries/europe.parquet",
        "support-boundary",
        "application/vnd.apache.parquet",
    )
    coastal = _request(
        tmp_path,
        "boundaries/coastal-analysis-zone.parquet",
        "coastal-boundary",
        "application/vnd.apache.parquet",
    )
    assert registry["release.boundary-geoparquet.support"](support).status == "pass"
    assert registry["release.boundary-geoparquet.coastal"](coastal).status == "pass"
    assert roles == ["support-boundary", "coastal-boundary"]
