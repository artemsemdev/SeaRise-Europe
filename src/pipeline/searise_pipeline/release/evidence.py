"""Cryptographic bindings for immutable issue #110 release candidates."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping

from searise_pipeline.science.contracts import ScienceContractError

_HEX40 = re.compile(r"^[0-9a-f]{40}$")


def _same_json_value(observed: Any, expected: Any) -> bool:
    if type(observed) is not type(expected):
        return False
    if isinstance(expected, dict):
        return set(observed) == set(expected) and all(
            _same_json_value(observed[key], value)
            for key, value in expected.items()
        )
    if isinstance(expected, list):
        return len(observed) == len(expected) and all(
            _same_json_value(left, right)
            for left, right in zip(observed, expected)
        )
    return observed == expected


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> Mapping[str, Any]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ScienceContractError(f"Cannot read release evidence: {exc}") from exc
    if not isinstance(document, dict):
        raise ScienceContractError("Release evidence must be a JSON object")
    return document


def binding_sha256(binding: Mapping[str, Any]) -> str:
    """Return a canonical digest for a candidate evidence binding."""
    encoded = json.dumps(binding, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256((encoded + "\n").encode("utf-8")).hexdigest()


def safe_candidate_path(root: Path, relative: str) -> Path:
    candidate = Path(relative)
    if (
        candidate.is_absolute()
        or not relative
        or candidate.as_posix() != relative
        or any(part in {"", ".", ".."} for part in candidate.parts)
    ):
        raise ScienceContractError("Release manifest contains an unsafe artifact path")
    resolved_root = root.resolve()
    unresolved = root / candidate
    if any(
        (root / Path(*candidate.parts[:index])).is_symlink()
        for index in range(1, len(candidate.parts) + 1)
    ):
        raise ScienceContractError("Release candidate contains a symlink")
    resolved = unresolved.resolve()
    if resolved == resolved_root or resolved_root not in resolved.parents:
        raise ScienceContractError("Release artifact escapes its immutable candidate")
    return resolved


def _validate_build_receipt(
    receipt: Mapping[str, Any],
    *,
    manifest: Mapping[str, Any],
    contract: Mapping[str, Any],
) -> Mapping[str, str]:
    expected_keys = {
        "schemaVersion",
        "releaseId",
        "sourceRevision",
        "toolchainPins",
        "environmentIdentity",
        "normalizedParameters",
    }
    if type(receipt) is not dict or set(receipt) != expected_keys:
        raise ScienceContractError("Build receipt fields differ from the exact schema")
    release_id = manifest.get("releaseId")
    source_revision = receipt.get("sourceRevision")
    if (
        type(receipt.get("schemaVersion")) is not int
        or receipt["schemaVersion"] != 1
        or not isinstance(release_id, str)
        or type(receipt.get("releaseId")) is not str
        or receipt["releaseId"] != release_id
        or type(source_revision) is not str
        or _HEX40.fullmatch(source_revision) is None
    ):
        raise ScienceContractError("Build receipt identity is invalid")
    if not _same_json_value(receipt["toolchainPins"], contract["toolchain"]):
        raise ScienceContractError("Build receipt toolchain pins differ from the contract")
    expected_parameters = {
        "nativeResolutionDegrees": contract["grid"]["nativeResolutionDegrees"],
        "pmtilesMaximumZoom": contract["artifacts"]["pmtiles"]["maximumZoom"],
        "scientificResampling": "none",
        "pmtilesCanonicalMetadata": True,
    }
    if not _same_json_value(receipt["normalizedParameters"], expected_parameters):
        raise ScienceContractError("Build receipt parameters differ from the contract")

    environment = receipt["environmentIdentity"]
    if type(environment) is not dict or set(environment) != {
        "buildRunId",
        "python",
        "vector",
    }:
        raise ScienceContractError("Build environment fields differ from the exact schema")
    build_run_id = environment["buildRunId"]
    if (
        type(build_run_id) is not str
        or not build_run_id
        or len(build_run_id) > 128
        or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]*", build_run_id) is None
    ):
        raise ScienceContractError("Build run label is invalid")

    python = environment["python"]
    if type(python) is not dict:
        raise ScienceContractError("Python environment evidence must be an exact object")
    python_platform = python.get("platform")
    python_profiles = contract["toolchain"]["python"]["profiles"]
    if type(python_platform) is not str or python_platform not in python_profiles:
        raise ScienceContractError("Python environment is not an allowed pinned profile")
    python_pin = python_profiles[python_platform]
    expected_python = {
        "platform": python_platform,
        "python_version": python_pin["pythonVersion"],
        "lock_path": python_pin["lockPath"],
        "lock_sha256": python_pin["lockSha256"],
        "packages": contract["toolchain"]["python"]["packageVersions"],
        "gdal_version": python_pin["gdal"],
        "rasterio_proj_version": python_pin["rasterioProj"],
        "pyproj_proj_version": python_pin["pyprojProj"],
    }
    if not _same_json_value(python, expected_python):
        raise ScienceContractError("Python environment evidence differs from its pinned profile")

    vector = environment["vector"]
    expected_vector_platform = python_platform.rsplit("-cp", 1)[0].replace(
        "macos-", "darwin-", 1
    )
    tippecanoe = contract["toolchain"]["tippecanoe"]
    pmtiles = contract["toolchain"]["pmtiles"]
    reference_build = tippecanoe["referenceBuilds"].get(expected_vector_platform)
    distribution_asset = pmtiles["assets"].get(expected_vector_platform)
    expected_vector_keys = {
        "tippecanoe_version",
        "tippecanoe_source_sha256",
        "tippecanoe_binary_sha256",
        "pmtiles_version",
        "pmtiles_commit",
        "pmtiles_distribution_platform",
        "pmtiles_distribution_sha256",
        "decode_binary_sha256",
    }
    if (
        type(vector) is not dict
        or set(vector) != expected_vector_keys
        or reference_build is None
        or distribution_asset is None
    ):
        raise ScienceContractError("Vector environment is not an allowed pinned profile")
    expected_vector = {
        "tippecanoe_version": tippecanoe["version"],
        "tippecanoe_source_sha256": tippecanoe["sourceSha256"],
        "tippecanoe_binary_sha256": reference_build["tippecanoeBinarySha256"],
        "pmtiles_version": pmtiles["version"],
        "pmtiles_commit": pmtiles["commit"],
        "pmtiles_distribution_platform": expected_vector_platform,
        "pmtiles_distribution_sha256": distribution_asset["sha256"],
        "decode_binary_sha256": reference_build["decodeBinarySha256"],
    }
    if any(
        not _same_json_value(vector[key], value)
        for key, value in expected_vector.items()
    ):
        raise ScienceContractError("Vector environment evidence differs from its pinned profile")
    return {
        "pythonPlatform": python_platform,
        "pythonLockSha256": python_pin["lockSha256"],
        "vectorPlatform": expected_vector_platform,
        "tippecanoeBinarySha256": reference_build["tippecanoeBinarySha256"],
    }


def candidate_binding(
    root: Path,
    *,
    contract: Mapping[str, Any],
) -> Mapping[str, Any]:
    """Hash every declared artifact and the receipts before accepting evidence."""
    try:
        candidate_entries = list(root.rglob("*"))
    except OSError as exc:
        raise ScienceContractError(f"Cannot inventory release candidate: {exc}") from exc
    if root.is_symlink() or any(path.is_symlink() for path in candidate_entries):
        raise ScienceContractError("Release candidate contains a symlink")

    manifest_path = root / "manifest.json"
    receipt_path = root / "build-receipt.json"
    build_evidence_path = root / "build-evidence.json"
    source_receipt_path = root / "source-receipt.json"
    statistics_path = root / "statistics.json"
    gate_path = root / "gate.json"
    manifest = load_json(manifest_path)
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list) or len(artifacts) != 31:
        raise ScienceContractError("Release manifest must contain exactly 31 artifacts")
    hashes: dict[str, str] = {}
    for record in artifacts:
        if not isinstance(record, dict):
            raise ScienceContractError("Release artifact record must be an object")
        relative = record.get("path")
        if not isinstance(relative, str) or relative in hashes:
            raise ScienceContractError("Release artifact paths must be unique strings")
        path = safe_candidate_path(root, relative)
        if (
            not path.is_file()
            or path.stat().st_size != record.get("byteSize")
            or sha256(path) != record.get("sha256")
        ):
            raise ScienceContractError(f"Release artifact bytes differ from manifest: {relative}")
        hashes[relative] = record["sha256"]

    evidence_paths = {
        "manifest.json",
        "build-receipt.json",
        "build-evidence.json",
        "source-receipt.json",
        "statistics.json",
        "gate.json",
    }
    if set(hashes) & evidence_paths:
        raise ScienceContractError("Manifest artifacts overlap candidate evidence files")
    expected_files = set(hashes) | evidence_paths
    checksum_path = root / "checksums.txt"
    actual_files = {
        path.relative_to(root).as_posix(): sha256(path)
        for path in sorted(candidate_entries)
        if path.is_file() and path != checksum_path
    }
    if set(actual_files) != expected_files:
        raise ScienceContractError("Candidate file inventory differs from the exact release set")

    try:
        checksum_lines = checksum_path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ScienceContractError(f"Cannot read candidate checksums: {exc}") from exc
    declared_checksums: dict[str, str] = {}
    for line in checksum_lines:
        parts = line.split("  ", 1)
        relative = Path(parts[1]) if len(parts) == 2 else None
        if (
            relative is None
            or not parts[1]
            or relative.is_absolute()
            or relative.as_posix() != parts[1]
            or any(part in {"", ".", ".."} for part in relative.parts)
            or parts[1] in declared_checksums
        ):
            raise ScienceContractError("Candidate checksum inventory is malformed")
        declared_checksums[parts[1]] = parts[0]
    if declared_checksums != actual_files:
        raise ScienceContractError("Candidate checksum inventory differs from actual files")

    receipt = load_json(receipt_path)
    load_json(build_evidence_path)
    load_json(source_receipt_path)
    load_json(statistics_path)
    load_json(gate_path)
    validated_profile = _validate_build_receipt(
        receipt,
        manifest=manifest,
        contract=contract,
    )
    candidate_files = {
        **actual_files,
        "checksums.txt": sha256(checksum_path),
    }
    return {
        "releaseId": manifest["releaseId"],
        "releaseContractId": manifest["releaseContractId"],
        "manifestSha256": sha256(manifest_path),
        "buildReceiptSha256": sha256(receipt_path),
        "buildEvidenceSha256": sha256(build_evidence_path),
        "sourceReceiptSha256": sha256(source_receipt_path),
        "artifactHashes": hashes,
        "candidateFileHashes": candidate_files,
        "sourceRevision": receipt["sourceRevision"],
        "environmentIdentity": receipt["environmentIdentity"],
        "validatedEnvironmentProfile": validated_profile,
    }
