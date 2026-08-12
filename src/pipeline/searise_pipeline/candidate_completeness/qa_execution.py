"""Candidate-wide execution of the version-selected Phase 1 QA matrix."""

from __future__ import annotations

import hashlib
import os
import stat
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Sequence

from .byte_gate import CandidateByteSummary, validate_candidate_root
from .qa_dispatch import (
    CandidateQaContext,
    QaValidationOutcome,
    QaValidationRequest,
    QaValidatorDispatcher,
)
from .qa_matrix import ArtifactSelector
from .validator import CandidateContractError, load_candidate_bytes, validate_candidate_document


@dataclass(frozen=True)
class CandidateQaArtifactResult:
    """One exact manifest artifact and its explicit authoritative disposition."""

    artifact_id: str
    artifact_path: str
    declared_sha256: str
    validator_id: str
    outcome: QaValidationOutcome


@dataclass(frozen=True)
class CandidateQaExecution:
    """Complete, byte-bound QA dispositions in manifest order."""

    candidate: CandidateByteSummary
    results: tuple[CandidateQaArtifactResult, ...]

    @property
    def releasable(self) -> bool:
        """True only when every selected artifact has an explicit pass."""
        return bool(self.results) and all(
            result.outcome.status == "pass" for result in self.results
        )


@dataclass(frozen=True)
class PreGateQaExecution:
    """QA dispositions for the 51 inputs validated before terminal sealing."""

    candidate: CandidateQaContext
    results: tuple[CandidateQaArtifactResult, ...]

    @property
    def releasable(self) -> bool:
        return len(self.results) == self.candidate.artifact_count and all(
            result.outcome.status == "pass" for result in self.results
        )


def _stable_sha256(path: Path, *, expected_size: int) -> str:
    """Hash one single-link regular file through a no-follow descriptor."""
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = -1
    try:
        descriptor = os.open(path, flags)
        before = os.fstat(descriptor)
        identity = (
            before.st_dev,
            before.st_ino,
            before.st_mode,
            before.st_nlink,
            before.st_size,
            before.st_mtime_ns,
            before.st_ctime_ns,
        )
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or before.st_size != expected_size
        ):
            raise CandidateContractError(
                "qa-input-bytes", "pre-gate input is not the declared regular file"
            )
        digest = hashlib.sha256()
        remaining = expected_size
        while remaining:
            chunk = os.read(descriptor, min(1024 * 1024, remaining))
            if not chunk:
                raise CandidateContractError(
                    "qa-input-bytes", "pre-gate input ended while it was hashed"
                )
            digest.update(chunk)
            remaining -= len(chunk)
        after = os.fstat(descriptor)
        after_identity = (
            after.st_dev,
            after.st_ino,
            after.st_mode,
            after.st_nlink,
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        )
        if os.read(descriptor, 1) or after_identity != identity:
            raise CandidateContractError(
                "qa-input-changed", "pre-gate input changed while it was hashed"
            )
        return digest.hexdigest()
    except CandidateContractError:
        raise
    except OSError as exc:
        raise CandidateContractError(
            "qa-input-bytes", "pre-gate input cannot be opened safely"
        ) from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def execute_pre_gate_qa(
    candidate_root: Path,
    artifacts: Sequence[Mapping[str, Any]],
    dispatcher: QaValidatorDispatcher,
    *,
    candidate_id: str,
    data_release_id: str,
    data_provenance_class: str,
) -> PreGateQaExecution:
    """Validate the exact 51 non-terminal bytes before reports and manifest exist."""
    matrix = dispatcher.matrix
    inventory = load_candidate_bytes(matrix.candidate_inventory.read_bytes())
    expected = inventory.get("requiredArtifacts")
    if not isinstance(expected, list):
        raise CandidateContractError("qa-inventory", "candidate inventory is malformed")
    pre_gate = expected[:-3]
    if len(pre_gate) != 51 or len(artifacts) != len(pre_gate):
        raise CandidateContractError(
            "qa-inventory", "pre-gate QA requires the exact 51-artifact v2 inventory"
        )
    expected_identity = [
        (item["artifactId"], item["path"], item["role"], item["mediaType"], item["contentEncoding"])
        for item in pre_gate
    ]
    observed_identity = [
        (
            item.get("artifactId"),
            item.get("path"),
            item.get("role"),
            item.get("mediaType"),
            item.get("contentEncoding"),
        )
        for item in artifacts
    ]
    if observed_identity != expected_identity:
        raise CandidateContractError(
            "qa-inventory", "pre-gate artifact identities or order differ"
        )
    context = CandidateQaContext(
        candidate_root=candidate_root,
        candidate_id=candidate_id,
        data_release_id=data_release_id,
        data_provenance_class=data_provenance_class,
        manifest_sha256=None,
        artifact_count=51,
    )
    results: list[CandidateQaArtifactResult] = []
    before: list[tuple[Path, int, str]] = []
    for artifact in artifacts:
        relative = PurePosixPath(str(artifact["path"]))
        if relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
            raise CandidateContractError(
                "qa-input-path", "pre-gate artifact path is unsafe"
            )
        path = candidate_root.joinpath(*relative.parts)
        byte_size = artifact.get("byteSize")
        declared = artifact.get("sha256")
        if not isinstance(byte_size, int) or byte_size < 1 or not isinstance(declared, str):
            raise CandidateContractError(
                "qa-input-bytes", "pre-gate byte identity is incomplete"
            )
        observed = _stable_sha256(path, expected_size=byte_size)
        if observed != declared:
            raise CandidateContractError(
                "qa-input-bytes", f"pre-gate SHA-256 differs: {artifact['artifactId']}"
            )
        before.append((path, byte_size, observed))
        selector = ArtifactSelector(
            str(artifact["role"]),
            str(artifact["mediaType"]),
            str(artifact["contentEncoding"]),
        )
        validator_id = dispatcher.validator_id_for(selector)
        request = QaValidationRequest(
            artifact_id=str(artifact["artifactId"]),
            artifact_path=path,
            selector=selector,
            declared_sha256=declared,
            candidate=context,
        )
        results.append(
            CandidateQaArtifactResult(
                artifact_id=request.artifact_id,
                artifact_path=str(artifact["path"]),
                declared_sha256=declared,
                validator_id=validator_id,
                outcome=dispatcher.dispatch(request),
            )
        )
    for path, byte_size, declared in before:
        if _stable_sha256(path, expected_size=byte_size) != declared:
            raise CandidateContractError(
                "qa-input-changed", "pre-gate candidate changed during QA execution"
            )
    return PreGateQaExecution(context, tuple(results))


def _manifest_bytes(candidate_root: Path, expected_sha256: str) -> bytes:
    try:
        raw = (candidate_root / "manifest.json").read_bytes()
    except OSError as exc:
        raise CandidateContractError(
            "candidate-manifest", "candidate manifest cannot be read for QA routing"
        ) from exc
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise CandidateContractError(
            "candidate-changed", "candidate manifest changed after the byte gate"
        )
    return raw


def execute_candidate_qa(
    candidate_root: Path,
    dispatcher: QaValidatorDispatcher,
) -> CandidateQaExecution:
    """Run every schema-selected route against one byte-stable candidate.

    Validator failures and required measurements that were not made remain
    explicit results. Registry drift, an unknown route, malformed evidence, or
    any mutation of the candidate raises a contract error.
    """
    before = validate_candidate_root(candidate_root)
    manifest_raw = _manifest_bytes(candidate_root, before.manifest_sha256)
    candidate = load_candidate_bytes(manifest_raw)
    contract = validate_candidate_document(candidate)
    if (
        contract.candidate_id != before.candidate_id
        or contract.data_release_id != before.data_release_id
        or contract.artifact_count != before.artifact_count
    ):
        raise CandidateContractError(
            "candidate-summary", "manifest contract and byte-gate summaries differ"
        )

    results: list[CandidateQaArtifactResult] = []
    context = CandidateQaContext(
        candidate_root=candidate_root,
        candidate_id=before.candidate_id,
        data_release_id=before.data_release_id,
        data_provenance_class=str(candidate["dataProvenanceClass"]),
        manifest_sha256=before.manifest_sha256,
        artifact_count=before.artifact_count,
    )
    for artifact in candidate["artifacts"]:
        selector = ArtifactSelector(
            artifact["role"], artifact["mediaType"], artifact["contentEncoding"]
        )
        validator_id = dispatcher.validator_id_for(selector)
        request = QaValidationRequest(
            artifact_id=artifact["artifactId"],
            artifact_path=candidate_root.joinpath(*PurePosixPath(artifact["path"]).parts),
            selector=selector,
            declared_sha256=artifact["sha256"],
            candidate=context,
        )
        results.append(
            CandidateQaArtifactResult(
                artifact_id=artifact["artifactId"],
                artifact_path=artifact["path"],
                declared_sha256=artifact["sha256"],
                validator_id=validator_id,
                outcome=dispatcher.dispatch(request),
            )
        )

    after = validate_candidate_root(candidate_root)
    if after != before or _manifest_bytes(candidate_root, before.manifest_sha256) != manifest_raw:
        raise CandidateContractError("candidate-changed", "candidate changed during QA execution")
    if len(results) != before.artifact_count:
        raise CandidateContractError(
            "qa-inventory", "QA execution did not cover the exact candidate inventory"
        )
    return CandidateQaExecution(before, tuple(results))
