"""Candidate-wide execution of the version-selected Phase 1 QA matrix."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from .byte_gate import CandidateByteSummary, validate_candidate_root
from .qa_dispatch import QaValidationOutcome, QaValidationRequest, QaValidatorDispatcher
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
