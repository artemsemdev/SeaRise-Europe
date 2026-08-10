"""Immutable evidence package for exact-pinned boundary PMTiles builds."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import Any, Mapping

from searise_pipeline.science.contracts import ScienceContractError

from .boundary_geoparquet import write_boundary_geoparquet
from .boundary_pmtiles import BoundaryVectorToolPaths, write_boundary_pmtiles
from .evidence import sha256, write_new_json_record
from .toolchain import validate_python_toolchain

_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_BUILD_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_ROLES = {
    "support-boundary": {
        "source": "data/geometry/europe.geojson",
        "geoparquet": "boundaries/europe.parquet",
        "pmtiles": "boundaries/europe.pmtiles",
    },
    "coastal-boundary": {
        "source": "data/geometry/coastal_analysis_zone.geojson",
        "geoparquet": "boundaries/coastal-analysis-zone.parquet",
        "pmtiles": "boundaries/coastal-analysis-zone.pmtiles",
    },
}


def _json_sha256(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _input_record(repository: Path, relative: str) -> Mapping[str, object]:
    path = repository / relative
    if not path.is_file() or path.is_symlink():
        raise ScienceContractError(f"Boundary evidence input is absent or unsafe: {relative}")
    return {
        "path": relative,
        "byteSize": path.stat().st_size,
        "sha256": sha256(path),
    }


def _build_once(
    output: Path,
    *,
    repository: Path,
    contract: Mapping[str, Any],
    tools: BoundaryVectorToolPaths,
) -> list[dict[str, Any]]:
    artifacts: list[dict[str, Any]] = []
    for role in sorted(_ROLES):
        paths = _ROLES[role]
        source_path = repository / paths["source"]
        geoparquet_path = output / paths["geoparquet"]
        pmtiles_path = output / paths["pmtiles"]
        geoparquet = write_boundary_geoparquet(
            source_path,
            geoparquet_path,
            role=role,
        )
        pmtiles = write_boundary_pmtiles(
            geoparquet_path,
            source_path,
            pmtiles_path,
            role=role,
            contract=contract,
            tools=tools,
        )
        artifacts.append(
            {
                "role": role,
                "sourceGeoJson": _input_record(repository, paths["source"]),
                "geoParquet": {
                    "path": geoparquet.path,
                    "byteSize": geoparquet.byte_size,
                    "sha256": geoparquet.sha256,
                    "rowCount": geoparquet.row_count,
                    "sourceSha256": geoparquet.source_sha256,
                },
                "pmtiles": {
                    "path": pmtiles.path,
                    "byteSize": pmtiles.byte_size,
                    "sha256": pmtiles.sha256,
                    "sourceGeoParquetByteSize": pmtiles.source_geoparquet_byte_size,
                    "sourceGeoParquetSha256": pmtiles.source_geoparquet_sha256,
                },
                "inspection": {
                    "decodedFragmentCount": pmtiles.decoded_fragment_count,
                    "decodedZoom": 6,
                    "geometryParity": (
                        "symmetric-hausdorff-plus-per-axis-envelope"
                    ),
                    "header": pmtiles.header,
                    "metadataSha256": _json_sha256(pmtiles.metadata),
                    "officialPmtilesVerify": "passed",
                    "safeMetadata": "passed",
                },
            }
        )
    return artifacts


def _candidate_files(candidate: Path) -> list[Path]:
    return sorted(path for path in candidate.rglob("*") if path.is_file())


def _compare_attempts(first: Path, second: Path) -> None:
    first_paths = [path.relative_to(first) for path in _candidate_files(first)]
    second_paths = [path.relative_to(second) for path in _candidate_files(second)]
    if first_paths != second_paths:
        raise ScienceContractError("Boundary rebuild artifact inventories differ")
    for relative in first_paths:
        if sha256(first / relative) != sha256(second / relative):
            raise ScienceContractError(
                f"Boundary rebuild bytes differ: {relative.as_posix()}"
            )


def build_boundary_evidence_package(
    output: Path,
    *,
    repository: Path,
    source_revision: str,
    build_run_id: str,
    release_contract_path: Path,
    python_lock_path: Path,
    tools: BoundaryVectorToolPaths,
) -> Path:
    """Build both boundaries twice and atomically publish their evidence package."""
    if _HEX40.fullmatch(source_revision) is None:
        raise ScienceContractError("Boundary evidence requires an exact source revision")
    if _BUILD_RUN_ID.fullmatch(build_run_id) is None:
        raise ScienceContractError("Boundary evidence build-run identity is invalid")
    output = output.resolve(strict=False)
    if output.exists() or output.is_symlink():
        raise ScienceContractError("Immutable boundary evidence output already exists")
    try:
        contract = json.loads(release_contract_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ScienceContractError(f"Cannot read boundary release contract: {exc}") from exc
    if not isinstance(contract, dict):
        raise ScienceContractError("Boundary release contract must be a JSON object")

    python_evidence = validate_python_toolchain(python_lock_path, contract=contract)
    vector_evidence = tools.validate(contract)
    candidate_id = (
        f"phase-1-boundaries-{source_revision[:12]}-{tools.platform}"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary_root = Path(
        tempfile.mkdtemp(prefix=f".{output.name}.", dir=output.parent)
    )
    try:
        package = temporary_root / "package"
        candidate = package / "candidate"
        rebuild = temporary_root / "rebuild"
        candidate.mkdir(parents=True)
        rebuild.mkdir(parents=True)
        artifacts = _build_once(
            candidate,
            repository=repository,
            contract=contract,
            tools=tools,
        )
        rebuilt_artifacts = _build_once(
            rebuild,
            repository=repository,
            contract=contract,
            tools=tools,
        )
        _compare_attempts(candidate, rebuild)
        if artifacts != rebuilt_artifacts:
            raise ScienceContractError("Boundary rebuild inspection evidence differs")

        output_records = [
            {
                "path": path.relative_to(candidate).as_posix(),
                "byteSize": path.stat().st_size,
                "sha256": sha256(path),
            }
            for path in _candidate_files(candidate)
        ]
        build_receipt = {
            "schemaVersion": 1,
            "issue": 51,
            "candidateId": candidate_id,
            "sourceRevision": source_revision,
            "buildRunId": build_run_id,
            "releaseContract": _input_record(
                repository,
                release_contract_path.relative_to(repository).as_posix(),
            ),
            "inputs": [
                _input_record(repository, paths["source"])
                for paths in _ROLES.values()
            ],
            "environment": {
                "python": asdict(python_evidence),
                "vector": asdict(vector_evidence),
            },
            "toolReceipts": [
                {
                    "path": tools.tippecanoe_build_receipt.relative_to(
                        repository
                    ).as_posix(),
                    "sha256": sha256(tools.tippecanoe_build_receipt),
                }
            ],
            "outputs": output_records,
            "reproducibility": {
                "independentBuildAttempts": 2,
                "artifactInventoryIdentical": True,
                "artifactBytesIdentical": True,
                "inspectionEvidenceIdentical": True,
            },
        }
        validation_report = {
            "schemaVersion": 1,
            "issue": 51,
            "candidate": {
                "candidateId": candidate_id,
                "sourceRevision": source_revision,
                "platform": tools.platform,
                "artifacts": output_records,
            },
            "status": "passed",
            "blockingChecks": [],
            "checks": {
                "exactPinnedPython": "passed",
                "exactPinnedVectorTools": "passed",
                "officialPmtilesIntegrity": "passed",
                "decodedIdentityPropertiesGeometryParity": "passed",
                "byteDeterministicRebuild": "passed",
            },
            "artifacts": artifacts,
            "limitation": {
                "status": "selected-scope-approximation",
                "purpose": "product-eligibility-only",
                "engineeringUse": "engineering-only",
                "publicationEligible": False,
                "canonical": False,
                "production": False,
                "hazardExtentClaim": False,
            },
        }
        write_new_json_record(package / "build-receipt.json", build_receipt)
        write_new_json_record(
            package / "validation-report.json", validation_report
        )
        checksum_paths = [
            *[path.relative_to(package) for path in _candidate_files(candidate)],
            Path("build-receipt.json"),
            Path("validation-report.json"),
        ]
        (package / "checksums.txt").write_text(
            "".join(
                f"{sha256(package / relative)}  {relative.as_posix()}\n"
                for relative in sorted(checksum_paths)
            ),
            encoding="utf-8",
        )
        os.replace(package, output)
    finally:
        shutil.rmtree(temporary_root, ignore_errors=True)
    return output
