"""Validate one offline synthetic candidate/evidence pair without signing claims."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, NoReturn

from searise_pipeline.candidate_completeness import (
    CandidateContractError,
    ProvenanceContractError,
    validate_candidate_document,
    validate_provenance_statement,
)

from .build_plane_sbom import validate_build_plane_sbom
from .contracts import REPOSITORY_ROOT, SupplyChainContractError, validate_evidence_files
from .nuget_sbom import validate_nuget_sbom
from .python_sbom import validate_python_sbom
from .sbom import validate_npm_sbom

_MANIFEST = PurePosixPath("manifest.json")
_ENVELOPE = PurePosixPath("evidence-envelope.json")
_PROVENANCE = PurePosixPath("provenance.intoto.jsonl")
_POLICY = Path("contracts/supply-chain/v1/identity-policy.json")


@dataclass(frozen=True)
class _SbomAuthority:
    logical_path: str
    ecosystem: str
    authority_path: str
    target: str = ""


_SBOMS = (
    _SbomAuthority(
        "sbom/build-plane.cdx.json",
        "build-plane",
        "contracts/supply-chain/v1/dependency-inventory.json",
    ),
    _SbomAuthority(
        "sbom/frontend-npm.cdx.json",
        "npm",
        "src/frontend/package-lock.json",
        "src/frontend/package-lock.json",
    ),
    *(
        _SbomAuthority(
            f"sbom/nuget/searise-{name.lower()}-net8.0.cdx.json",
            "nuget",
            f"src/api/SeaRise.{name}/SeaRise.{name}.csproj",
            f"src/api/SeaRise.{name}/packages.lock.json",
        )
        for name in ("Api", "Application", "Domain", "Infrastructure")
    ),
    *(
        _SbomAuthority(
            f"sbom/python-{graph}-{target}.cdx.json",
            "python",
            f"contracts/supply-chain/v1/python-graphs/{annotation}.json",
            target,
        )
        for graph, annotation in (
            ("release", "release-runtime"),
            ("settlement-spatial", "settlement-spatial-runtime"),
        )
        for target in ("linux-x86-64-cp311", "macos-arm64-cp311")
    ),
)
_SBOM_PATHS = tuple(sorted(item.logical_path for item in _SBOMS))


@dataclass(frozen=True)
class CandidateEvidenceSummary:
    """Stable nonclaim result for one validated synthetic pair."""

    candidate_id: str
    data_release_id: str
    data_provenance_class: str
    manifest_sha256: str
    provenance_sha256: str
    sbom_count: int
    cryptographic_verification: bool = False
    production: bool = False
    publication: bool = False


def _fail(message: str) -> NoReturn:
    raise SupplyChainContractError(message)


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate object key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> NoReturn:
    raise ValueError(f"non-standard JSON constant: {value}")


def _strict_json(raw: bytes, label: str) -> dict[str, Any]:
    try:
        document = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_strict_object,
            parse_constant=_reject_constant,
        )
    except (UnicodeDecodeError, ValueError, json.JSONDecodeError) as exc:
        _fail(f"{label} must be one strict UTF-8 JSON object: {exc}")
    if not isinstance(document, dict):
        _fail(f"{label} JSON root must be an object")
    return document


def _open_root(path: Path, label: str) -> tuple[Path, int]:
    if ".." in path.parts:
        _fail(f"{label} root must not contain parent traversal")
    absolute = path.absolute()
    flags = os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(absolute.anchor, flags)
        for part in absolute.parts[1:]:
            child = os.open(part, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
    except OSError as exc:
        if "descriptor" in locals():
            os.close(descriptor)
        raise SupplyChainContractError(
            f"{label} root must be an existing directory without symlinks: {path}"
        ) from exc
    return absolute, descriptor


def _same_file(left: os.stat_result, right: os.stat_result) -> bool:
    fields = ("st_dev", "st_ino", "st_mode", "st_size", "st_mtime_ns", "st_ctime_ns")
    return all(getattr(left, field) == getattr(right, field) for field in fields)


def _read_root_file(root: int, logical: PurePosixPath, label: str) -> bytes:
    directory = os.dup(root)
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        for part in logical.parts[:-1]:
            child = os.open(part, flags | os.O_DIRECTORY, dir_fd=directory)
            os.close(directory)
            directory = child
        descriptor = os.open(
            logical.name,
            flags | getattr(os, "O_NONBLOCK", 0),
            dir_fd=directory,
        )
        try:
            before = os.fstat(descriptor)
            if not stat.S_ISREG(before.st_mode):
                _fail(f"{label} must be a regular file")
            chunks: list[bytes] = []
            while chunk := os.read(descriptor, 1024 * 1024):
                chunks.append(chunk)
            after = os.fstat(descriptor)
            linked = os.stat(logical.name, dir_fd=directory, follow_symlinks=False)
            raw = b"".join(chunks)
            if (
                not _same_file(before, after)
                or not _same_file(after, linked)
                or len(raw) != after.st_size
            ):
                _fail(f"{label} changed while it was read")
            return raw
        finally:
            os.close(descriptor)
    except OSError as exc:
        raise SupplyChainContractError(
            f"{label} must be an existing regular file without symlinks"
        ) from exc
    finally:
        os.close(directory)


def _snapshot(root: Path, logical: PurePosixPath, raw: bytes) -> Path:
    target = root.joinpath(*logical.parts)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(raw)
    return target


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _build_receipt_path(candidate: Mapping[str, Any]) -> PurePosixPath:
    paths = [
        item.get("path") for item in candidate["artifacts"] if item.get("role") == "build-receipt"
    ]
    if len(paths) != 1 or paths[0] != "receipts/build.json":
        _fail("candidate must declare the exact build receipt path")
    return PurePosixPath(paths[0])


def _validate_sbom_authority(spec: _SbomAuthority, path: Path, repository_root: Path) -> None:
    authority = repository_root / spec.authority_path
    if spec.ecosystem == "build-plane":
        validate_build_plane_sbom(path, authority, repository_root=repository_root)
    elif spec.ecosystem == "npm":
        validate_npm_sbom(
            path,
            authority,
            repository_root=repository_root,
            logical_path=spec.target,
        )
    elif spec.ecosystem == "nuget":
        validate_nuget_sbom(
            path,
            authority,
            repository_root / spec.target,
            repository_root=repository_root,
            target_framework="net8.0",
        )
    else:
        validate_python_sbom(
            path,
            authority,
            repository_root=repository_root,
            target_id=spec.target,
        )


def validate_candidate_evidence_pair(
    candidate_root: Path,
    evidence_root: Path,
    *,
    repository_root: Path = REPOSITORY_ROOT,
    trusted_invocation_uri: str,
) -> CandidateEvidenceSummary:
    """Validate exact offline pair bytes while preserving the pending signing gate."""
    _, candidate_descriptor = _open_root(candidate_root, "candidate")
    try:
        _, evidence_descriptor = _open_root(evidence_root, "evidence")
    except Exception:
        os.close(candidate_descriptor)
        raise
    try:
        manifest_raw = _read_root_file(candidate_descriptor, _MANIFEST, "candidate manifest")
        candidate = _strict_json(manifest_raw, "candidate manifest")
        try:
            validate_candidate_document(candidate)
        except CandidateContractError as exc:
            raise SupplyChainContractError(str(exc)) from exc
        receipt_logical = _build_receipt_path(candidate)
        receipt_raw = _read_root_file(candidate_descriptor, receipt_logical, "build receipt")
        _strict_json(receipt_raw, "build receipt")
        source_raw = {
            PurePosixPath(item["path"]): _read_root_file(
                candidate_descriptor, PurePosixPath(item["path"]), "source receipt"
            )
            for item in candidate["artifacts"]
            if item["role"] == "source-receipt"
        }
        for raw in source_raw.values():
            _strict_json(raw, "source receipt")

        envelope_raw = _read_root_file(evidence_descriptor, _ENVELOPE, "evidence envelope")
        envelope = _strict_json(envelope_raw, "evidence envelope")
        descriptors = envelope.get("softwareBillsOfMaterials")
        if not isinstance(descriptors, list) or not all(
            isinstance(item, dict) for item in descriptors
        ):
            _fail("evidence envelope SBOM descriptors must be objects")
        descriptor_paths = [item.get("path") for item in descriptors]
        if tuple(descriptor_paths) != _SBOM_PATHS:
            _fail("evidence envelope must declare the exact sorted ten canonical SBOM paths")

        provenance_raw = _read_root_file(evidence_descriptor, _PROVENANCE, "provenance")
        provenance = _strict_json(provenance_raw, "provenance")
        sbom_raw = {
            spec.logical_path: _read_root_file(
                evidence_descriptor,
                PurePosixPath(spec.logical_path),
                f"SBOM {spec.logical_path}",
            )
            for spec in _SBOMS
        }
        for logical_path, raw in sbom_raw.items():
            _strict_json(raw, f"SBOM {logical_path}")
    finally:
        os.close(candidate_descriptor)
        os.close(evidence_descriptor)

    policy_path = repository_root.absolute() / _POLICY
    try:
        policy_raw = policy_path.read_bytes()
    except OSError as exc:
        raise SupplyChainContractError(f"cannot read identity policy: {policy_path}") from exc
    _strict_json(policy_raw, "identity policy")
    manifest_sha256 = _sha256(manifest_raw)
    provenance_sha256 = _sha256(provenance_raw)

    with tempfile.TemporaryDirectory(
        prefix="searise-pair-", dir=Path(tempfile.gettempdir()).resolve()
    ) as temporary:
        snapshot_root = Path(temporary)
        manifest_path = _snapshot(snapshot_root / "candidate", _MANIFEST, manifest_raw)
        receipt_path = _snapshot(snapshot_root / "candidate", receipt_logical, receipt_raw)
        for source_logical, raw in source_raw.items():
            _snapshot(snapshot_root / "candidate", source_logical, raw)
        envelope_path = _snapshot(snapshot_root / "evidence", _ENVELOPE, envelope_raw)
        provenance_path = _snapshot(snapshot_root / "evidence", _PROVENANCE, provenance_raw)
        policy_snapshot = _snapshot(
            snapshot_root, PurePosixPath("identity-policy.json"), policy_raw
        )
        sbom_paths = {
            logical_path: _snapshot(snapshot_root / "evidence", PurePosixPath(logical_path), raw)
            for logical_path, raw in sbom_raw.items()
        }
        try:
            validate_provenance_statement(
                provenance_path,
                manifest_path,
                receipt_path,
                trusted_invocation_uri=trusted_invocation_uri,
            )
        except ProvenanceContractError as exc:
            raise SupplyChainContractError(str(exc)) from exc
        validated_envelope = validate_evidence_files(envelope_path, policy_snapshot, sbom_paths)
        identities = ("candidateId", "dataReleaseId", "dataProvenanceClass")
        external = provenance["predicate"]["buildDefinition"]["externalParameters"]
        for field in identities:
            if candidate[field] != validated_envelope[field] or candidate[field] != external[field]:
                _fail(f"candidate, evidence, and provenance identity differ: {field}")
        if validated_envelope["candidateManifest"]["sha256"] != manifest_sha256:
            _fail("evidence envelope does not bind the actual candidate manifest bytes")
        if validated_envelope["provenance"]["sha256"] != provenance_sha256:
            _fail("evidence envelope does not bind the actual provenance bytes")
        if external["actualManifestSha256"] != manifest_sha256:
            _fail("provenance does not bind the actual candidate manifest bytes")
        signatures = validated_envelope["signatures"]
        if len(signatures) != 2:
            _fail("evidence envelope must declare exactly two signature descriptors")
        verification = validated_envelope["verification"]
        claims = provenance["predicate"]["buildDefinition"]["internalParameters"]["claims"]
        if any(
            (
                verification["verified"],
                verification["policySatisfied"],
                verification["productionClaim"],
                claims["cryptographicVerification"],
                claims["production"],
                claims["publication"],
            )
        ):
            _fail("offline pair validation must not claim signing, production, or publication")
        for spec in _SBOMS:
            _validate_sbom_authority(
                spec, sbom_paths[spec.logical_path], repository_root.absolute()
            )

    return CandidateEvidenceSummary(
        candidate_id=str(candidate["candidateId"]),
        data_release_id=str(candidate["dataReleaseId"]),
        data_provenance_class=str(candidate["dataProvenanceClass"]),
        manifest_sha256=manifest_sha256,
        provenance_sha256=provenance_sha256,
        sbom_count=len(_SBOMS),
    )
