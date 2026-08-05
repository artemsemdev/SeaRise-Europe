"""Cryptographic bindings for immutable issue #110 release candidates."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from searise_pipeline.science.contracts import ScienceContractError


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
    if candidate.is_absolute() or not relative or ".." in candidate.parts:
        raise ScienceContractError("Release manifest contains an unsafe artifact path")
    resolved_root = root.resolve()
    resolved = (root / candidate).resolve()
    if resolved == resolved_root or resolved_root not in resolved.parents:
        raise ScienceContractError("Release artifact escapes its immutable candidate")
    return resolved


def candidate_binding(root: Path) -> Mapping[str, Any]:
    """Hash every declared artifact and the receipts before accepting evidence."""
    manifest_path = root / "manifest.json"
    receipt_path = root / "build-receipt.json"
    build_evidence_path = root / "build-evidence.json"
    source_receipt_path = root / "source-receipt.json"
    manifest = load_json(manifest_path)
    receipt = load_json(receipt_path)
    load_json(build_evidence_path)
    load_json(source_receipt_path)
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise ScienceContractError("Release manifest has no artifacts")
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
    if receipt.get("releaseId") != manifest.get("releaseId"):
        raise ScienceContractError("Build receipt and manifest release IDs differ")
    checksum_path = root / "checksums.txt"
    try:
        checksum_lines = checksum_path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ScienceContractError(f"Cannot read candidate checksums: {exc}") from exc
    declared_checksums: dict[str, str] = {}
    for line in checksum_lines:
        parts = line.split("  ", 1)
        if len(parts) != 2 or parts[1] in declared_checksums:
            raise ScienceContractError("Candidate checksum inventory is malformed")
        declared_checksums[parts[1]] = parts[0]
    actual_files = {
        path.relative_to(root).as_posix(): sha256(path)
        for path in sorted(item for item in root.rglob("*") if item.is_file())
        if path.name != "checksums.txt"
    }
    if declared_checksums != actual_files:
        raise ScienceContractError("Candidate checksum inventory differs from actual files")
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
    }
