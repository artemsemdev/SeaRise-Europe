from __future__ import annotations

import base64
import binascii
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
_RECEIPT = PurePosixPath("receipts/build.json")
_ENVELOPE = PurePosixPath("evidence-envelope.json")
_PROVENANCE = PurePosixPath("provenance.intoto.jsonl")
_POLICY = PurePosixPath("contracts/supply-chain/v1/identity-policy.json")
_TEMP_ROOT = Path(tempfile.gettempdir()).resolve()
_PYTHON_TARGETS = ("linux-x86-64-cp311", "macos-arm64-cp311")
_SIGNATURE_PATHS = ("manifest.sigstore.json", "provenance.sigstore.json")
_TLOG_FIELDS = "canonicalizedBody inclusionPromise integratedTime kindVersion logId logIndex"
_SBOM_PATHS = (
    "sbom/build-plane.cdx.json",
    "sbom/frontend-npm.cdx.json",
    *(
        f"sbom/nuget/searise-{name}-net8.0.cdx.json"
        for name in ("api", "application", "domain", "infrastructure")
    ),
    *(
        f"sbom/python-{graph}-{target}.cdx.json"
        for graph in ("release", "settlement-spatial")
        for target in _PYTHON_TARGETS
    ),
)


@dataclass(frozen=True)
class CandidateEvidenceSummary:
    candidate_id: str
    data_provenance_class: str
    sbom_count: int
    cryptographic_verification: bool = False
    production: bool = False
    publication: bool = False


def _fail(message: str) -> NoReturn:
    raise SupplyChainContractError(message)


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = dict(pairs)
    if len(result) != len(pairs):
        raise ValueError("duplicate object key")
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
        json.dumps(document, ensure_ascii=False).encode("utf-8")
    except (RecursionError, UnicodeDecodeError, UnicodeEncodeError, ValueError) as exc:
        _fail(f"{label} must be one strict UTF-8 JSON object: {exc}")
    if not isinstance(document, dict):
        _fail(f"{label} JSON root must be an object")
    return document


def _open_root(path: Path, label: str) -> int:
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
    return descriptor


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
            linked = os.stat(logical.name, dir_fd=directory, follow_symlinks=False)
            if not stat.S_ISREG(before.st_mode) or not _same_file(before, linked):
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


def _decoded(value: object, label: str) -> bytes:
    try:
        if not isinstance(value, str) or not value:
            raise ValueError("empty or non-string value")
        decoded = base64.b64decode(value, validate=True)
        if not decoded:
            raise ValueError("empty decoded value")
        return decoded
    except (binascii.Error, ValueError) as exc:
        raise SupplyChainContractError(f"{label} must be nonempty base64") from exc


def _exact(value: object, keys: str) -> bool:
    return isinstance(value, dict) and set(value) == set(keys.split())


def _claimed(document: Mapping[str, Any], keys: str) -> bool:
    return any(document[key] for key in keys.split())


def _descriptor_paths(value: object, label: str) -> tuple[object, ...]:
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        _fail(f"evidence envelope {label} descriptors must be objects")
    return tuple(item.get("path") for item in value)


def _read_files(root: int, paths: tuple[str, ...], label: str) -> dict[str, bytes]:
    return {path: _read_root_file(root, PurePosixPath(path), f"{label} {path}") for path in paths}


def _validate_bundle(bundle: Mapping[str, Any], subject: bytes, label: str) -> None:
    try:
        material = bundle["verificationMaterial"]
        signature = bundle["messageSignature"]
        entries = material["tlogEntries"]
        if (
            not _exact(bundle, "mediaType verificationMaterial messageSignature")
            or bundle["mediaType"] != "application/vnd.dev.sigstore.bundle.v0.3+json"
            or not _exact(material, "certificate tlogEntries")
            or not _exact(material["certificate"], "rawBytes")
            or not _exact(signature, "messageDigest signature")
            or not _exact(signature["messageDigest"], "algorithm digest")
            or signature["messageDigest"]["algorithm"] != "SHA2_256"
            or not isinstance(entries, list)
            or not entries
        ):
            _fail(f"{label} is not the exact supported Sigstore sign-blob subset")
        _decoded(material["certificate"]["rawBytes"], f"{label} certificate")
        _decoded(signature["signature"], f"{label} signature")
        for entry in entries:
            times = (entry["integratedTime"], entry["logIndex"])
            if (
                not _exact(entry, _TLOG_FIELDS)
                or not _exact(entry["inclusionPromise"], "signedEntryTimestamp")
                or entry["kindVersion"] != {"kind": "hashedrekord", "version": "0.0.1"}
                or not _exact(entry["logId"], "keyId")
                or not all(type(value) is int and value >= 0 for value in times)
            ):
                _fail(f"{label} transparency-log entry is not the exact hashedrekord subset")
            _decoded(entry["canonicalizedBody"], f"{label} log body")
            _decoded(entry["inclusionPromise"]["signedEntryTimestamp"], f"{label} log promise")
            _decoded(entry["logId"]["keyId"], f"{label} log ID")
        digest = _decoded(signature["messageDigest"]["digest"], f"{label} message digest")
    except (KeyError, TypeError) as exc:
        raise SupplyChainContractError(f"{label} structure is malformed") from exc
    if digest != hashlib.sha256(subject).digest():
        _fail(f"{label} message digest does not bind its exact declared subject bytes")


def _bind_bytes(descriptor: Mapping[str, Any], raw: bytes, label: str) -> None:
    expected = hashlib.sha256(raw).hexdigest()
    if descriptor.get("sha256") != expected or descriptor.get("byteSize") != len(raw):
        _fail(f"{label} descriptor does not bind its exact bytes")


def _validate_sbom_authority(logical: str, path: Path, root: Path) -> None:
    if logical == _SBOM_PATHS[0]:
        inventory = root / "contracts/supply-chain/v1/dependency-inventory.json"
        validate_build_plane_sbom(path, inventory, repository_root=root)
    elif logical == _SBOM_PATHS[1]:
        lock = root / "src/frontend/package-lock.json"
        validate_npm_sbom(
            path, lock, repository_root=root, logical_path="src/frontend/package-lock.json"
        )
    elif logical.startswith("sbom/nuget/"):
        component = logical.split("searise-", 1)[1].split("-net8.0", 1)[0].title()
        project = root / f"src/api/SeaRise.{component}"
        validate_nuget_sbom(
            path,
            project / f"SeaRise.{component}.csproj",
            project / "packages.lock.json",
            repository_root=root,
            target_framework="net8.0",
        )
    else:
        stem = logical.removeprefix("sbom/python-").removesuffix(".cdx.json")
        target = next(item for item in _PYTHON_TARGETS if stem.endswith(item))
        graph = stem.removesuffix(f"-{target}")
        annotation = root / f"contracts/supply-chain/v1/python-graphs/{graph}-runtime.json"
        validate_python_sbom(path, annotation, repository_root=root, target_id=target)


def validate_candidate_evidence_pair(
    candidate_root: Path,
    evidence_root: Path,
    *,
    repository_root: Path = REPOSITORY_ROOT,
    trusted_invocation_uri: str,
) -> CandidateEvidenceSummary:
    candidate_descriptor = _open_root(candidate_root, "candidate")
    try:
        evidence_descriptor = _open_root(evidence_root, "evidence")
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
        receipt_raw = _read_root_file(candidate_descriptor, _RECEIPT, "build receipt")
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
        if _descriptor_paths(envelope.get("softwareBillsOfMaterials"), "SBOM") != _SBOM_PATHS:
            _fail("evidence envelope must declare the exact sorted ten canonical SBOM paths")

        provenance_raw = _read_root_file(evidence_descriptor, _PROVENANCE, "provenance")
        provenance = _strict_json(provenance_raw, "provenance")
        if _descriptor_paths(envelope.get("signatures"), "signature") != _SIGNATURE_PATHS:
            _fail("evidence envelope must declare the exact two signature bundle paths")
        signature_raw = _read_files(evidence_descriptor, _SIGNATURE_PATHS, "signature")
        sbom_raw = _read_files(evidence_descriptor, _SBOM_PATHS, "SBOM")
        for logical_path, raw in sbom_raw.items():
            _strict_json(raw, f"SBOM {logical_path}")
    finally:
        os.close(candidate_descriptor)
        os.close(evidence_descriptor)

    repository_descriptor = _open_root(repository_root, "repository")
    try:
        policy_raw = _read_root_file(repository_descriptor, _POLICY, "identity policy")
    finally:
        os.close(repository_descriptor)
    _strict_json(policy_raw, "identity policy")
    manifest_sha256 = hashlib.sha256(manifest_raw).hexdigest()

    with tempfile.TemporaryDirectory(prefix="searise-pair-", dir=_TEMP_ROOT) as temporary:
        snapshot_root = Path(temporary)
        manifest_path = _snapshot(snapshot_root / "candidate", _MANIFEST, manifest_raw)
        receipt_path = _snapshot(snapshot_root / "candidate", _RECEIPT, receipt_raw)
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
        _bind_bytes(validated_envelope["candidateManifest"], manifest_raw, "candidate manifest")
        _bind_bytes(validated_envelope["provenance"], provenance_raw, "provenance")
        if external["actualManifestSha256"] != manifest_sha256:
            _fail("provenance does not bind the actual candidate manifest bytes")
        signatures = validated_envelope["signatures"]
        subjects = {"manifest.json": manifest_raw, "provenance.intoto.jsonl": provenance_raw}
        for descriptor in signatures:
            path = descriptor["path"]
            _bind_bytes(descriptor, signature_raw[path], f"signature {path}")
            _validate_bundle(
                _strict_json(signature_raw[path], f"signature {path}"),
                subjects[descriptor["subjectPath"]],
                f"signature {path}",
            )
        verification = validated_envelope["verification"]
        claims = provenance["predicate"]["buildDefinition"]["internalParameters"]["claims"]
        if _claimed(verification, "verified policySatisfied productionClaim") or _claimed(
            claims, "cryptographicVerification production publication"
        ):
            _fail("offline pair validation must not claim signing, production, or publication")
        for logical in _SBOM_PATHS:
            _validate_sbom_authority(logical, sbom_paths[logical], repository_root.absolute())

    return CandidateEvidenceSummary(
        candidate_id=str(candidate["candidateId"]),
        data_provenance_class=str(candidate["dataProvenanceClass"]),
        sbom_count=len(_SBOM_PATHS),
    )
