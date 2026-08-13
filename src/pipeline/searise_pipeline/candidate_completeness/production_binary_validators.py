"""Authoritative candidate-bound validators for production binary artifacts."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from searise_pipeline.release import (
    BoundaryVectorToolPaths,
    RegionalLayer,
    RegionalReleaseSource,
    validate_analysis_cog,
    validate_boundary_geoparquet,
    validate_boundary_pmtiles,
    validate_geoparquet,
    validate_visual_pmtiles,
)
from searise_pipeline.science import ScienceContractError
from searise_pipeline.settlements.spatial_geoparquet import (
    SpatialGeoParquetError,
    validate_retained_spatial_geoparquet,
    validate_spatial_geoparquet,
)

from .qa_dispatch import ArtifactValidator, QaValidationOutcome, QaValidationRequest


@dataclass(frozen=True)
class ProjectionQaAuthority:
    source: RegionalReleaseSource
    contract: Mapping[str, Any]
    tippecanoe: Path
    decode: Path
    pmtiles: Path
    tippecanoe_source: Path
    tippecanoe_build_receipt: Path
    pmtiles_distribution_asset: Path
    platform: str
    retained_pmtiles: RetainedPmtilesAuthority | None = None


@dataclass(frozen=True)
class BoundaryQaAuthority:
    contract: Mapping[str, Any]
    support_geojson: Path
    coastal_geojson: Path
    tools: BoundaryVectorToolPaths
    retained_pmtiles: RetainedPmtilesAuthority | None = None


@dataclass(frozen=True)
class RetainedPmtilesAuthority:
    """A prior exact-byte PMTiles validation retained on the same machine."""

    candidate_root: Path
    checksums: Path
    validation_report: Path
    required_check: str
    checksum_prefix: str = ""


@dataclass(frozen=True)
class SettlementQaAuthority:
    spatial_receipt: Path
    work_directory: Path
    spatial_database: Path | None = None
    artifact_receipt: Path | None = None


@dataclass(frozen=True)
class ProductionBinaryQaAuthorities:
    projection: ProjectionQaAuthority
    boundary: BoundaryQaAuthority
    settlement: SettlementQaAuthority


def _pass(code: str, message: str) -> QaValidationOutcome:
    return QaValidationOutcome("pass", code, message)


def _fail(code: str, error: Exception) -> QaValidationOutcome:
    return QaValidationOutcome("fail", code, str(error))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _retained_pmtiles(
    request: QaValidationRequest, authority: RetainedPmtilesAuthority
) -> None:
    report = json.loads(authority.validation_report.read_text(encoding="utf-8"))
    if not isinstance(report, dict):
        raise ScienceContractError("retained PMTiles report is not an object")
    checks = report.get("checks")
    if not isinstance(checks, dict) or checks.get(authority.required_check) not in {
        True,
        "passed",
    }:
        raise ScienceContractError("retained PMTiles validation did not pass")
    relative = request.artifact_path.relative_to(request.candidate.candidate_root)
    retained = authority.candidate_root / relative
    expected = _sha256(request.artifact_path)
    if not retained.is_file() or _sha256(retained) != expected:
        raise ScienceContractError("PMTiles bytes differ from the retained candidate")
    checksum_lines = authority.checksums.read_text(encoding="utf-8").splitlines()
    checksum_paths = {
        line.split(maxsplit=1)[1].removeprefix("*").removeprefix("./"): line.split(
            maxsplit=1
        )[0]
        for line in checksum_lines
        if len(line.split(maxsplit=1)) == 2
    }
    checksum_path = f"{authority.checksum_prefix}{relative.as_posix()}"
    if checksum_paths.get(checksum_path) != expected:
        raise ScienceContractError("retained PMTiles checksum authority differs")


def _projection_layer(
    request: QaValidationRequest, source: RegionalReleaseSource
) -> RegionalLayer:
    relative = request.artifact_path.relative_to(request.candidate.candidate_root)
    parts = relative.parts
    if len(parts) != 3 or parts[0] not in {"analysis", "layers"}:
        raise ScienceContractError("Projection artifact path differs from the matrix")
    scenario = parts[1]
    try:
        horizon = int(Path(parts[2]).stem)
    except ValueError as exc:
        raise ScienceContractError("Projection horizon path is invalid") from exc
    matches = [
        layer
        for layer in source.layers
        if layer.scenario == scenario and layer.horizon == horizon
    ]
    if len(matches) != 1:
        raise ScienceContractError("Projection path has no unique source layer")
    return matches[0]


def _analysis_cog(authority: ProjectionQaAuthority) -> ArtifactValidator:
    def validate(request: QaValidationRequest) -> QaValidationOutcome:
        try:
            layer = _projection_layer(request, authority.source)
            validate_analysis_cog(
                request.artifact_path, layer, contract=authority.contract
            )
        except (OSError, ScienceContractError) as exc:
            return _fail("analysis-cog-invalid", exc)
        return _pass("analysis-cog-valid", "COG bytes equal the verified AR6 layer")

    return validate


def _projection_geoparquet(authority: ProjectionQaAuthority) -> ArtifactValidator:
    def validate(request: QaValidationRequest) -> QaValidationOutcome:
        try:
            validate_geoparquet(
                request.artifact_path, authority.source, contract=authority.contract
            )
        except (OSError, ScienceContractError) as exc:
            return _fail("projection-geoparquet-invalid", exc)
        return _pass(
            "projection-geoparquet-valid",
            "GeoParquet values equal the complete verified AR6 matrix",
        )

    return validate


def _projection_pmtiles(authority: ProjectionQaAuthority) -> ArtifactValidator:
    def validate(request: QaValidationRequest) -> QaValidationOutcome:
        try:
            if authority.retained_pmtiles is not None:
                _retained_pmtiles(request, authority.retained_pmtiles)
                return _pass(
                    "projection-pmtiles-valid",
                    "PMTiles bytes equal the retained, tool-validated AR6 candidate",
                )
            layer = _projection_layer(request, authority.source)
            validate_visual_pmtiles(
                authority.source,
                layer,
                request.artifact_path,
                contract=authority.contract,
                tippecanoe_path=authority.tippecanoe,
                decode_path=authority.decode,
                pmtiles_path=authority.pmtiles,
                tippecanoe_source_archive_path=authority.tippecanoe_source,
                tippecanoe_build_receipt_path=authority.tippecanoe_build_receipt,
                pmtiles_distribution_asset_path=authority.pmtiles_distribution_asset,
                pmtiles_distribution_platform=authority.platform,
            )
        except (OSError, ScienceContractError) as exc:
            return _fail("projection-pmtiles-invalid", exc)
        return _pass(
            "projection-pmtiles-valid",
            "PMTiles structure and decoded properties equal the verified AR6 layer",
        )

    return validate


def _boundary_geoparquet(
    authority: BoundaryQaAuthority, *, role: str
) -> ArtifactValidator:
    source = (
        authority.support_geojson
        if role == "support-boundary"
        else authority.coastal_geojson
    )

    def validate(request: QaValidationRequest) -> QaValidationOutcome:
        try:
            validate_boundary_geoparquet(request.artifact_path, source, role=role)
        except (OSError, ScienceContractError) as exc:
            return _fail("boundary-geoparquet-invalid", exc)
        return _pass(
            "boundary-geoparquet-valid",
            f"{role} boundary equals the checksum-pinned GeoJSON authority",
        )

    return validate


def _boundary_pmtiles(
    authority: BoundaryQaAuthority, *, role: str
) -> ArtifactValidator:
    source_geojson = (
        authority.support_geojson
        if role == "support-boundary"
        else authority.coastal_geojson
    )
    source_name = (
        "europe.parquet"
        if role == "support-boundary"
        else "coastal-analysis-zone.parquet"
    )

    def validate(request: QaValidationRequest) -> QaValidationOutcome:
        source_geoparquet = request.candidate.candidate_root / "boundaries" / source_name
        try:
            if authority.retained_pmtiles is not None:
                _retained_pmtiles(request, authority.retained_pmtiles)
                return _pass(
                    "boundary-pmtiles-valid",
                    f"{role} PMTiles equals the retained, tool-validated candidate",
                )
            validate_boundary_pmtiles(
                request.artifact_path,
                source_geoparquet,
                source_geojson,
                role=role,
                contract=authority.contract,
                tools=authority.tools,
            )
        except (OSError, ScienceContractError) as exc:
            return _fail("boundary-pmtiles-invalid", exc)
        return _pass(
            "boundary-pmtiles-valid",
            f"{role} PMTiles has exact decoded parity with its boundary GeoParquet",
        )

    return validate


def _settlement_geoparquet(authority: SettlementQaAuthority) -> ArtifactValidator:
    def validate(request: QaValidationRequest) -> QaValidationOutcome:
        try:
            with request.artifact_path.open("rb") as stream:
                if authority.spatial_database is not None and authority.artifact_receipt is None:
                    validate_spatial_geoparquet(
                        stream,
                        authority.spatial_database,
                        authority.spatial_receipt,
                        work_dir=authority.work_directory,
                    )
                elif authority.artifact_receipt is not None and authority.spatial_database is None:
                    validate_retained_spatial_geoparquet(
                        stream,
                        authority.spatial_receipt,
                        authority.artifact_receipt,
                        work_dir=authority.work_directory,
                    )
                else:
                    raise SpatialGeoParquetError(
                        "settlement QA requires exactly one full-replay or retained authority"
                    )
        except (OSError, SpatialGeoParquetError) as exc:
            return _fail("settlement-geoparquet-invalid", exc)
        return _pass(
            "settlement-geoparquet-valid",
            "Settlement GeoParquet equals the descriptor-bound spatial stage",
        )

    return validate


def production_binary_validator_registry(
    authorities: ProductionBinaryQaAuthorities,
) -> dict[str, ArtifactValidator]:
    """Return exact-source validators for every unencoded production binary role."""
    return {
        "release.analysis-cog": _analysis_cog(authorities.projection),
        "release.projection-geoparquet": _projection_geoparquet(authorities.projection),
        "release.projection-pmtiles": _projection_pmtiles(authorities.projection),
        "release.boundary-geoparquet.support": _boundary_geoparquet(
            authorities.boundary, role="support-boundary"
        ),
        "release.boundary-geoparquet.coastal": _boundary_geoparquet(
            authorities.boundary, role="coastal-boundary"
        ),
        "release.boundary-pmtiles.support": _boundary_pmtiles(
            authorities.boundary, role="support-boundary"
        ),
        "release.boundary-pmtiles.coastal": _boundary_pmtiles(
            authorities.boundary, role="coastal-boundary"
        ),
        "settlements.geoparquet": _settlement_geoparquet(authorities.settlement),
    }
