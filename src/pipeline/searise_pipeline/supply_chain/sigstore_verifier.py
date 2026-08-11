from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, NoReturn

from searise_pipeline.candidate_completeness import (
    CandidateContractError,
    validate_candidate_document,
)

from .candidate_evidence import (
    _SBOM_PATHS,
    _SIGNATURE_PATHS,
    _open_root,
    _read_root_file,
    _strict_json,
    _validate_candidate_evidence_pair,
)
from .contracts import REPOSITORY_ROOT, SupplyChainContractError, _validate_schema
from .cosign_tool import parse_cosign_tool_lock
from .sbom import write_new_sbom

_IDENTITY = (
    "https://github.com/artemsemdev/SeaRise-Europe/.github/workflows/"
    "phase-1-release-sign.yml@refs/heads/master"
)
_ISSUER = "https://token.actions.githubusercontent.com"
_POLICY = PurePosixPath("contracts/supply-chain/v1/identity-policy.json")
_MANIFEST = PurePosixPath("manifest.json")
_BUILD_RECEIPT = PurePosixPath("receipts/build.json")
_ENVELOPE = PurePosixPath("evidence-envelope.json")
_PROVENANCE = PurePosixPath("provenance.intoto.jsonl")
_DEPENDENCY_INVENTORY = PurePosixPath("contracts/supply-chain/v1/dependency-inventory.json")
_RUN_ID = re.compile(r"[1-9][0-9]*")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_TEMP_ROOT = Path(tempfile.gettempdir()).resolve()


@dataclass(frozen=True)
class _CryptographicVerification:
    receipt: Mapping[str, Any]
    receipt_bytes: bytes


def _fail(message: str) -> NoReturn:
    raise SupplyChainContractError(message)


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _logical(value: object, label: str) -> PurePosixPath:
    if not isinstance(value, str):
        _fail(f"{label} path must be a string")
    logical = PurePosixPath(value)
    if (
        logical.is_absolute()
        or logical.as_posix() != value
        or any(part in {"", ".", ".."} for part in logical.parts)
    ):
        _fail(f"{label} path is unsafe")
    return logical


def _canonical(document: Mapping[str, Any]) -> bytes:
    try:
        return (
            json.dumps(document, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n"
        ).encode("utf-8")
    except (RecursionError, UnicodeEncodeError, ValueError) as exc:
        raise SupplyChainContractError(
            f"verification receipt is not canonical JSON: {exc}"
        ) from exc


def _read(path: Path, label: str) -> bytes:
    root = _open_root(path.parent, f"{label} parent")
    try:
        return _read_root_file(root, PurePosixPath(path.name), label)
    finally:
        os.close(root)


def _snapshot(path: Path, raw: bytes, *, executable: bool = False) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0),
        0o500 if executable else 0o400,
    )
    try:
        remaining = memoryview(raw)
        while remaining:
            count = os.write(descriptor, remaining)
            if count <= 0:
                raise OSError("snapshot write made no progress")
            remaining = remaining[count:]
        os.fsync(descriptor)
    except OSError as exc:
        raise SupplyChainContractError("could not create an exact private snapshot") from exc
    finally:
        os.close(descriptor)
    return path


def _require_root_generation(path: Path, expected: os.stat_result, label: str) -> None:
    current = _open_root(path, label)
    try:
        if not os.path.samestat(os.fstat(current), expected):
            _fail(f"{label} root generation changed during verification")
    finally:
        os.close(current)


def _executable_bytes(path: Path) -> bytes:
    if not path.is_absolute() or ".." in path.parts:
        _fail("Cosign executable path must be absolute and canonical")
    parent = _open_root(path.parent, "Cosign executable parent")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path.name, flags | getattr(os, "O_NONBLOCK", 0), dir_fd=parent)
        try:
            before = os.fstat(descriptor)
            linked = os.stat(path.name, dir_fd=parent, follow_symlinks=False)
            identity = (before.st_dev, before.st_ino, before.st_mode, before.st_size)
            linked_identity = (linked.st_dev, linked.st_ino, linked.st_mode, linked.st_size)
            if (
                not stat.S_ISREG(before.st_mode)
                or before.st_mode & 0o111 == 0
                or identity != linked_identity
            ):
                _fail("Cosign executable must be one executable regular file without symlinks")
            chunks: list[bytes] = []
            while chunk := os.read(descriptor, 1024 * 1024):
                chunks.append(chunk)
            after = os.fstat(descriptor)
            linked = os.stat(path.name, dir_fd=parent, follow_symlinks=False)
            raw = b"".join(chunks)
            after_identity = (after.st_dev, after.st_ino, after.st_mode, after.st_size)
            linked_identity = (linked.st_dev, linked.st_ino, linked.st_mode, linked.st_size)
            if (
                identity != after_identity
                or after_identity != linked_identity
                or len(raw) != after.st_size
            ):
                _fail("Cosign executable changed while it was read")
            return raw
        finally:
            os.close(descriptor)
    except OSError as exc:
        raise SupplyChainContractError(
            "Cosign executable must be one executable regular file without symlinks"
        ) from exc
    finally:
        os.close(parent)


def _verify_cosign(
    executable: Path,
    subject: Path,
    bundle: Path,
    *,
    home: Path,
) -> None:
    command = [
        str(executable),
        "verify-blob",
        "--bundle",
        str(bundle),
        "--certificate-identity",
        _IDENTITY,
        "--certificate-oidc-issuer",
        _ISSUER,
        str(subject),
    ]
    try:
        completed = subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=180,
            env={
                "HOME": str(home),
                "XDG_CACHE_HOME": str(home / "cache"),
                "LANG": "C",
                "LC_ALL": "C",
                "NO_COLOR": "1",
            },
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise SupplyChainContractError("Cosign verification could not complete") from exc
    if completed.returncode != 0:
        _fail("Cosign rejected the signed subject")
    if completed.stdout != b"Verified OK\n":
        _fail("Cosign returned an unexpected success output")


def verify_candidate_evidence_cryptographically(
    candidate_root: Path,
    evidence_root: Path,
    *,
    repository_root: Path = REPOSITORY_ROOT,
    controlled_build_run_id: str,
    cosign_executable: Path,
    cosign_tool_lock: Path,
    trusted_cosign_tool_lock_sha256: str,
    receipt_path: Path | None = None,
) -> _CryptographicVerification:
    if _RUN_ID.fullmatch(controlled_build_run_id) is None:
        _fail("controlled build run ID must be one canonical positive integer")
    if _SHA256.fullmatch(trusted_cosign_tool_lock_sha256) is None:
        _fail("trusted Cosign tool-lock SHA-256 must be one lowercase digest")
    invocation_uri = (
        "https://github.com/artemsemdev/SeaRise-Europe/actions/runs/"
        f"{controlled_build_run_id}/attempts/1"
    )
    candidate = _open_root(candidate_root, "candidate")
    try:
        evidence = _open_root(evidence_root, "evidence")
        repository = _open_root(repository_root, "repository")
    except Exception:
        os.close(candidate)
        if "evidence" in locals():
            os.close(evidence)
        raise
    generations = tuple(os.fstat(item) for item in (candidate, evidence, repository))
    try:
        manifest_raw = _read_root_file(candidate, _MANIFEST, "candidate manifest")
        manifest_document = _strict_json(manifest_raw, "candidate manifest")
        try:
            validate_candidate_document(manifest_document)
        except CandidateContractError as exc:
            raise SupplyChainContractError(str(exc)) from exc
        build_raw = _read_root_file(candidate, _BUILD_RECEIPT, "build receipt")
        envelope_raw = _read_root_file(evidence, _ENVELOPE, "evidence envelope")
        provenance_raw = _read_root_file(evidence, _PROVENANCE, "provenance")
        envelope = _strict_json(envelope_raw, "evidence envelope")
        provenance_document = _strict_json(provenance_raw, "provenance")
        source_receipts = {
            _logical(item["path"], "source receipt"): _read_root_file(
                candidate, _logical(item["path"], "source receipt"), "source receipt"
            )
            for item in manifest_document["artifacts"]
            if item["role"] == "source-receipt"
        }
        evidence_files = {
            PurePosixPath(path): _read_root_file(evidence, PurePosixPath(path), path)
            for path in (*_SIGNATURE_PATHS, *_SBOM_PATHS)
        }
        policy_raw = _read_root_file(repository, _POLICY, "identity policy")
        inventory_raw = _read_root_file(repository, _DEPENDENCY_INVENTORY, "dependency inventory")
        inventory = _strict_json(inventory_raw, "dependency inventory")
        try:
            dependency_paths = {
                _logical(item["path"], "dependency input")
                for component in inventory["components"]
                for item in component["inputs"]
            }
        except (KeyError, TypeError) as exc:
            raise SupplyChainContractError("dependency input inventory is malformed") from exc
        repository_files = {
            path: _read_root_file(repository, path, "dependency input") for path in dependency_paths
        }
        repository_files.update({_POLICY: policy_raw, _DEPENDENCY_INVENTORY: inventory_raw})

        with tempfile.TemporaryDirectory(prefix="searise-cosign-", dir=_TEMP_ROOT) as temporary:
            root = Path(temporary)
            candidate_snapshot, evidence_snapshot, repository_snapshot = (
                root / "candidate",
                root / "evidence",
                root / "repository",
            )
            manifest = _snapshot(candidate_snapshot / _MANIFEST, manifest_raw)
            _snapshot(candidate_snapshot / _BUILD_RECEIPT, build_raw)
            for logical, raw in source_receipts.items():
                _snapshot(candidate_snapshot / logical, raw)
            _snapshot(evidence_snapshot / _ENVELOPE, envelope_raw)
            provenance = _snapshot(evidence_snapshot / _PROVENANCE, provenance_raw)
            for logical, raw in evidence_files.items():
                _snapshot(evidence_snapshot / logical, raw)
            for logical, raw in repository_files.items():
                _snapshot(repository_snapshot / logical, raw)
            summary = _validate_candidate_evidence_pair(
                candidate_snapshot,
                evidence_snapshot,
                repository_root=repository_snapshot,
                trusted_invocation_uri=invocation_uri,
                allow_production_envelope=True,
            )
            identities = (
                manifest_document["candidateId"],
                manifest_document["dataReleaseId"],
                manifest_document["dataProvenanceClass"],
            )
            external = provenance_document["predicate"]["buildDefinition"]["externalParameters"]
            if identities != (
                summary.candidate_id,
                external["dataReleaseId"],
                summary.data_provenance_class,
            ):
                _fail("receipt identity differs from its exact snapshotted subjects")
            policy = _strict_json(policy_raw, "identity policy")
            expected_policy = {
                "$schema": "https://artemsemdev.github.io/SeaRise-Europe/contracts/supply-chain/v1/identity-policy.schema.json",
                "schemaVersion": "1.0.0",
                "contractId": "phase-1-production-signing-identity-v1",
                "repository": "artemsemdev/SeaRise-Europe",
                "workflowPath": ".github/workflows/phase-1-release-sign.yml",
                "workflowRef": "refs/heads/master",
                "certificateIdentity": _IDENTITY,
                "oidcIssuer": _ISSUER,
                "protectedEnvironment": "phase-1-production-signing",
                "bundleMediaType": "application/vnd.dev.sigstore.bundle+json;version=0.3",
            }
            if policy != expected_policy or envelope["identityPolicy"]["sha256"] != _sha256(
                policy_raw
            ):
                _fail("identity policy does not match the exact production signing identity")
            lock_raw = _read(cosign_tool_lock, "Cosign tool lock")
            if _sha256(lock_raw) != trusted_cosign_tool_lock_sha256:
                _fail("Cosign tool lock does not match the independently reviewed SHA-256")
            lock = parse_cosign_tool_lock(lock_raw)
            executable_raw = _executable_bytes(cosign_executable)
            executable = lock["executable"]
            if executable["sha256"] != _sha256(executable_raw) or executable["byteSize"] != len(
                executable_raw
            ):
                _fail("Cosign executable does not match the reviewed tool lock")
            tool = _snapshot(root / "bin/cosign", executable_raw, executable=True)
            subjects = {
                "manifest.json": (manifest_raw, manifest),
                "provenance.intoto.jsonl": (provenance_raw, provenance),
            }
            receipt_subjects = []
            for subject_path, (subject_raw, subject) in subjects.items():
                descriptor = next(
                    item for item in envelope["signatures"] if item["subjectPath"] == subject_path
                )
                bundle_path = str(descriptor["path"])
                bundle_raw = evidence_files[PurePosixPath(bundle_path)]
                _verify_cosign(tool, subject, evidence_snapshot / bundle_path, home=root / "home")
                receipt_subjects.append(
                    {
                        "path": subject_path,
                        "sha256": _sha256(subject_raw),
                        "bundlePath": bundle_path,
                        "bundleSha256": _sha256(bundle_raw),
                        "verified": True,
                    }
                )

        for path, generation, label in zip(
            (candidate_root, evidence_root, repository_root),
            generations,
            ("candidate", "evidence", "repository"),
        ):
            _require_root_generation(path, generation, label)
    finally:
        os.close(candidate)
        os.close(evidence)
        os.close(repository)

    receipt: Mapping[str, Any] = {
        "$schema": "https://artemsemdev.github.io/SeaRise-Europe/contracts/supply-chain/v1/cryptographic-verification-receipt.schema.json",
        "schemaVersion": "1.0.0",
        "receiptType": "phase-1-sigstore-cryptographic-verification-v1",
        "candidateId": summary.candidate_id,
        "dataReleaseId": str(manifest_document["dataReleaseId"]),
        "dataProvenanceClass": summary.data_provenance_class,
        "controlledBuildRunId": controlled_build_run_id,
        "trustedInvocationUri": invocation_uri,
        "identityPolicy": {
            "sha256": _sha256(policy_raw),
            "certificateIdentity": _IDENTITY,
            "oidcIssuer": _ISSUER,
        },
        "cosign": {
            "toolLockSha256": _sha256(lock_raw),
            "executableSha256": _sha256(executable_raw),
        },
        "subjects": receipt_subjects,
        "claims": {
            "certificateWorkflowIdentityVerified": True,
            "oidcIssuerVerified": True,
            "protectedEnvironmentVerified": False,
            "subjectDigestsVerified": True,
            "productionClaim": False,
            "publicationClaim": False,
            "scientificApproval": False,
        },
    }
    receipt_bytes = _canonical(receipt)
    _validate_schema(receipt, "cryptographic-verification-receipt.schema.json")
    if receipt_path is not None:
        write_new_sbom(receipt_path, receipt_bytes)
    return _CryptographicVerification(receipt=receipt, receipt_bytes=receipt_bytes)
