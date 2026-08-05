"""Atomic construction of the complete nine-layer AR6 regional release."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping

import numpy as np

from searise_pipeline.science.contracts import ScienceContractError

from .cog import CogEvidence, write_analysis_cog
from .gate import evaluate_recovery_gate
from .geoparquet import GeoParquetEvidence, write_geoparquet
from .model import RegionalLayer, RegionalReleaseSource, assert_source_integrity
from .pmtiles import (
    PmtilesEvidence,
    validate_vector_toolchain,
    write_visual_pmtiles,
)
from .toolchain import validate_python_toolchain


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, document: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    path.write_text(encoded, encoding="utf-8")


@dataclass(frozen=True)
class ReleaseBuildResult:
    """Completed candidate location and its machine disposition."""

    output_directory: Path
    manifest: Mapping[str, Any]
    gate: Mapping[str, Any]
    build_duration_seconds: float


def _layer_statistics(layer: RegionalLayer) -> Mapping[str, Any]:
    valid = layer.valid
    statistics: dict[str, Any] = {
        "scenario": layer.scenario,
        "horizon": layer.horizon,
        "validCellCount": int(valid.sum()),
        "nodataCellCount": int(valid.size - valid.sum()),
        "quantiles": {},
    }
    for name, values in (
        ("lower", layer.lower_mm),
        ("central", layer.central_mm),
        ("upper", layer.upper_mm),
    ):
        selected = values[valid].astype(np.int64)
        statistics["quantiles"][name] = {
            "minimumMillimetres": int(selected.min()),
            "maximumMillimetres": int(selected.max()),
            "meanMillimetres": round(float(selected.mean()), 6),
        }
    return statistics


def _artifact_record(
    evidence: CogEvidence | GeoParquetEvidence | PmtilesEvidence,
    *,
    media_type: str,
    role: str,
    scenario: str | None = None,
    horizon: int | None = None,
) -> Mapping[str, Any]:
    record: dict[str, Any] = {
        "path": evidence.path,
        "mediaType": media_type,
        "role": role,
        "byteSize": evidence.byte_size,
        "sha256": evidence.sha256,
    }
    if scenario is not None:
        record["scenario"] = scenario
    if horizon is not None:
        record["horizon"] = horizon
    return record


def _validate_lookup_goldens(
    source: RegionalReleaseSource,
    goldens_path: Path,
) -> Mapping[str, Any]:
    try:
        goldens = json.loads(goldens_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ScienceContractError(f"Cannot read AR6 lookup goldens: {exc}") from exc
    if goldens["provenance"]["archiveSha256"] != source.archive_sha256:
        raise ScienceContractError("Lookup goldens belong to another AR6 archive")
    expected_members = {
        layer.scenario: layer.member_sha256 for layer in source.layers if layer.horizon == 2030
    }
    golden_members = {
        {"ssp126": "ssp1-26", "ssp245": "ssp2-45", "ssp585": "ssp5-85"}[scenario]: digest
        for scenario, digest in goldens["provenance"]["memberSha256"].items()
    }
    if golden_members != expected_members:
        raise ScienceContractError("Lookup goldens belong to other AR6 members")
    layers = {(layer.scenario, layer.horizon): layer for layer in source.layers}
    available_count = 0
    declared_states = set()
    for result in goldens["results"]:
        declared_states.add(result["state"])
        if result["state"] != "ProjectionAvailable":
            continue
        available_count += 1
        positions = np.argwhere(source.location_ids == result["source"]["locationId"])
        if positions.shape != (1, 2):
            raise ScienceContractError("Golden source location is absent from regional grid")
        row, column = positions[0]
        for projection in result["projections"]:
            layer = layers[(projection["scenario"], projection["horizon"])]
            actual = (
                int(layer.lower_mm[row, column]),
                int(layer.central_mm[row, column]),
                int(layer.upper_mm[row, column]),
            )
            expected = (
                projection["lowerMillimetres"],
                projection["centralMillimetres"],
                projection["upperMillimetres"],
            )
            if actual != expected:
                raise ScienceContractError("Regional values differ from independent goldens")
    validation_binding = goldens["validationContract"]
    validation_path = goldens_path.parents[4] / validation_binding["path"]
    if _sha256(validation_path) != validation_binding["sha256"]:
        raise ScienceContractError("Lookup validation contract binding changed")
    validation = json.loads(validation_path.read_text(encoding="utf-8"))
    controls = {item["expectedState"] for item in validation["validation"]["algorithmicControls"]}
    required_states = {
        "ProjectionAvailable",
        "DataUnavailable",
        "OutOfScope",
        "UnsupportedGeography",
    }
    if declared_states | controls != required_states:
        raise ScienceContractError("Lookup goldens do not cover all four product states")
    return {
        "path": str(goldens_path),
        "sha256": _sha256(goldens_path),
        "availableControlCount": available_count,
        "coveredStates": sorted(required_states),
        "numericToleranceMillimetres": 0,
    }


def _checksums(root: Path) -> None:
    entries = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        if path.name == "checksums.txt":
            continue
        entries.append(f"{_sha256(path)}  {path.relative_to(root).as_posix()}")
    (root / "checksums.txt").write_text("\n".join(entries) + "\n", encoding="utf-8")


def build_regional_release(
    source: RegionalReleaseSource,
    output_directory: Path,
    *,
    release_id: str,
    contract: Mapping[str, Any],
    tippecanoe_path: Path,
    decode_path: Path,
    pmtiles_path: Path,
    python_lock_path: Path,
    lookup_goldens_path: Path,
    reproducibility_report: Mapping[str, Any] | None = None,
    delivery_report: Mapping[str, Any] | None = None,
    owner_decision: str = "pending-owner",
) -> ReleaseBuildResult:
    """Build into a private directory and publish atomically only after validation."""
    if output_directory.exists():
        raise ScienceContractError(f"Immutable release path already exists: {output_directory}")
    assert_source_integrity(source, contract, require_verified_archive=False)
    output_directory.parent.mkdir(parents=True, exist_ok=True)
    python_toolchain = validate_python_toolchain(python_lock_path, contract=contract)
    toolchain = validate_vector_toolchain(
        tippecanoe_path=tippecanoe_path,
        decode_path=decode_path,
        pmtiles_path=pmtiles_path,
        contract=contract,
    )
    lookup_evidence = _validate_lookup_goldens(source, lookup_goldens_path)
    started = time.perf_counter()
    with tempfile.TemporaryDirectory(
        prefix="searise-release-", dir=output_directory.parent
    ) as temporary:
        root = Path(temporary) / release_id
        root.mkdir()
        cogs: list[CogEvidence] = []
        pmtiles: list[PmtilesEvidence] = []
        for layer in source.layers:
            cog_path = root / f"analysis/{layer.scenario}/{layer.horizon}.tif"
            cogs.append(write_analysis_cog(layer, cog_path, contract=contract))
        geoparquet = write_geoparquet(
            source,
            root / "analysis/projections.parquet",
            contract=contract,
        )
        for layer in source.layers:
            archive_path = root / f"layers/{layer.scenario}/{layer.horizon}.pmtiles"
            pmtiles.append(
                write_visual_pmtiles(
                    source,
                    layer,
                    archive_path,
                    contract=contract,
                    tippecanoe_path=tippecanoe_path,
                    decode_path=decode_path,
                    pmtiles_path=pmtiles_path,
                )
            )
        duration = round(time.perf_counter() - started, 6)
        statistics = {
            "schemaVersion": 1,
            "releaseId": release_id,
            "storageUnits": "mm",
            "nodata": contract["values"]["nodata"],
            "layers": [_layer_statistics(layer) for layer in source.layers],
        }
        _write_json(root / "statistics.json", statistics)

        artifacts: list[Mapping[str, Any]] = []
        by_layer = {(layer.scenario, layer.horizon): layer for layer in source.layers}
        for evidence in cogs:
            parts = Path(evidence.path).parts
            artifacts.append(
                _artifact_record(
                    evidence,
                    media_type="image/tiff; application=geotiff; profile=cloud-optimized",
                    role="exact-browser-lookup",
                    scenario=parts[1],
                    horizon=int(Path(parts[2]).stem),
                )
            )
        artifacts.append(
            _artifact_record(
                geoparquet,
                media_type="application/vnd.apache.parquet",
                role="analytical-parity",
            )
        )
        for evidence in pmtiles:
            parts = Path(evidence.path).parts
            layer = by_layer[(parts[1], int(Path(parts[2]).stem))]
            artifacts.append(
                _artifact_record(
                    evidence,
                    media_type="application/vnd.pmtiles",
                    role="visual-only",
                    scenario=layer.scenario,
                    horizon=layer.horizon,
                )
            )
        totals = {
            "cogBytes": sum(item.byte_size for item in cogs),
            "pmtilesBytes": sum(item.byte_size for item in pmtiles),
            "geoparquetBytes": geoparquet.byte_size,
        }
        totals["coreArtifactBytes"] = sum(totals.values())
        budgets = contract["budgets"]
        budget_passed = (
            totals["cogBytes"] <= budgets["cogTotalBytes"]
            and totals["pmtilesBytes"] <= budgets["pmtilesTotalBytes"]
            and totals["geoparquetBytes"] <= budgets["geoparquetBytes"]
            and totals["coreArtifactBytes"] <= budgets["coreArtifactsTotalBytes"]
        )
        build_evidence = {
            "schemaVersion": 1,
            "releaseId": release_id,
            "checks": {
                "sourceArchiveAndMembersVerified": (
                    source.archive_and_members_verified_this_build
                ),
                "completeScenarioHorizonMatrix": len(source.layers) == 9,
                "cogStructureAndValues": len(cogs) == 9,
                "geoparquetSchemaAndValues": geoparquet.row_count
                == sum(item.source_feature_count for item in pmtiles),
                "pmtilesStructureAndProperties": len(pmtiles) == 9,
                "crossArtifactSemanticParity": all(
                    cog.valid_cells == tile.source_feature_count for cog, tile in zip(cogs, pmtiles)
                ),
                "lookupGoldenParity": True,
                "licenceAndAttribution": contract["source"]["licence"] == "CC-BY-4.0"
                and bool(contract["source"]["attribution"]),
                "artifactBudgets": budget_passed,
            },
            "lookupGoldenEvidence": lookup_evidence,
            "totals": totals,
        }
        gate = evaluate_recovery_gate(
            build_evidence,
            contract=contract,
            reproducibility_report=reproducibility_report,
            delivery_report=delivery_report,
            owner_decision=owner_decision,
        )
        source_receipt = {
            "schemaVersion": 1,
            "sourceMode": source.source_mode,
            "archiveSha256": source.archive_sha256,
            "archiveAndMembersVerifiedThisBuild": (
                source.archive_and_members_verified_this_build
            ),
            "memberSha256": {
                layer.scenario: layer.member_sha256
                for layer in source.layers
                if layer.horizon == 2030
            },
            "releaseContractSha256": source.contract_sha256,
            "licence": contract["source"]["licence"],
            "attribution": contract["source"]["attribution"],
        }
        build_receipt = {
            "schemaVersion": 1,
            "releaseId": release_id,
            "toolchainPins": contract["toolchain"],
            "observedPython": asdict(python_toolchain),
            "observedBinaries": asdict(toolchain),
            "normalizedParameters": {
                "nativeResolutionDegrees": 1,
                "pmtilesMaximumZoom": contract["artifacts"]["pmtiles"]["maximumZoom"],
                "scientificResampling": "none",
                "pmtilesCanonicalMetadata": True,
            },
        }
        manifest = {
            "schemaVersion": 1,
            "releaseId": release_id,
            "releaseContractId": contract["releaseContractId"],
            "scientificDisposition": contract["scientificDisposition"],
            "publicationStatus": "approved" if gate["phase1Unlocked"] else "not-approved",
            "modeledQuantity": "regional-relative-sea-level-change",
            "baseline": contract["values"]["baseline"],
            "confidence": contract["values"]["confidence"],
            "storageUnits": "mm",
            "scaleToMetres": contract["values"]["scaleToMetres"],
            "nativeResolutionDegrees": contract["grid"]["nativeResolutionDegrees"],
            "grid": contract["grid"],
            "matrix": contract["matrix"],
            "source": source_receipt,
            "artifacts": artifacts,
            "totals": totals,
            "limitations": [
                "projection-only-not-flood-inundation-terrain-or-property-risk",
                "pmtiles-visual-only",
                "geoparquet-nearest-selection-prohibited",
                "cog-is-the-only-exact-browser-lookup-artifact",
            ],
        }
        _write_json(root / "source-receipt.json", source_receipt)
        _write_json(root / "build-receipt.json", build_receipt)
        _write_json(root / "build-evidence.json", build_evidence)
        _write_json(root / "gate.json", gate)
        _write_json(
            root / "reproducibility.json",
            reproducibility_report
            or {"schemaVersion": 1, "status": "pending", "reason": "second-environment-required"},
        )
        _write_json(
            root / "delivery-measurements.json",
            delivery_report
            or {
                "schemaVersion": 1,
                "status": "pending",
                "buildDurationSeconds": duration,
                "artifactBytes": totals,
                "reason": "browser-profile-measurements-required",
            },
        )
        _write_json(root / "manifest.json", manifest)
        _checksums(root)
        os.replace(root, output_directory)
    return ReleaseBuildResult(
        output_directory=output_directory,
        manifest=manifest,
        gate=gate,
        build_duration_seconds=duration,
    )
