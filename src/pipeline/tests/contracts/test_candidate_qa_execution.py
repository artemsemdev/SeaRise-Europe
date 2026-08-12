from __future__ import annotations

import os
from pathlib import Path

import pytest

from searise_pipeline.candidate_completeness import (
    CandidateContractError,
    assemble_candidate_fixture,
    execute_candidate_qa,
)
from searise_pipeline.candidate_completeness.qa_dispatch import (
    ArtifactValidator,
    QaValidationOutcome,
    QaValidationRequest,
    QaValidatorDispatcher,
)
from searise_pipeline.candidate_completeness.qa_matrix import load_qa_routing_matrix

ROOT = Path(__file__).resolve().parents[4]
RECEIPT = ROOT / "contracts/candidate-completeness/v2/fixtures/assembly/complete-synthetic.json"


def _registry(
    validator: ArtifactValidator,
) -> dict[str, ArtifactValidator]:
    return {route.validator_id: validator for route in load_qa_routing_matrix().routes}


def _pass(_: QaValidationRequest) -> QaValidationOutcome:
    return QaValidationOutcome("pass", "fixture-pass", "fixture validator passed")


def _make_writable(root: Path) -> None:
    for directory, _, files in os.walk(root):
        Path(directory).chmod(0o700)
        for name in files:
            (Path(directory) / name).chmod(0o600)


def test_executes_all_54_manifest_artifacts_in_order(tmp_path: Path) -> None:
    candidate = tmp_path / "candidate"
    assemble_candidate_fixture(RECEIPT, candidate)
    observed: list[tuple[str, Path, str]] = []

    def record(request: QaValidationRequest) -> QaValidationOutcome:
        observed.append(
            (request.artifact_id, request.artifact_path, request.declared_sha256)
        )
        return _pass(request)

    execution = execute_candidate_qa(candidate, QaValidatorDispatcher(_registry(record)))

    assert execution.releasable is True
    assert execution.candidate.artifact_count == 54
    assert len(execution.results) == len(observed) == 54
    assert [result.artifact_id for result in execution.results] == [
        artifact_id for artifact_id, _, _ in observed
    ]
    assert all(path.is_relative_to(candidate) for _, path, _ in observed)
    assert all(
        result.declared_sha256 == declared
        for result, (_, _, declared) in zip(execution.results, observed)
    )


@pytest.mark.parametrize("status", ["fail", "not-measured"])
def test_nonpassing_dispositions_remain_explicit_and_block_release(
    tmp_path: Path, status: str
) -> None:
    candidate = tmp_path / "candidate"
    assemble_candidate_fixture(RECEIPT, candidate)

    def disposition(_: QaValidationRequest) -> QaValidationOutcome:
        return QaValidationOutcome(status, f"fixture-{status}", f"fixture is {status}")  # type: ignore[arg-type]

    execution = execute_candidate_qa(
        candidate, QaValidatorDispatcher(_registry(disposition))
    )
    assert execution.releasable is False
    assert {result.outcome.status for result in execution.results} == {status}


def test_candidate_mutation_during_validation_fails_closed(tmp_path: Path) -> None:
    candidate = tmp_path / "candidate"
    assemble_candidate_fixture(RECEIPT, candidate)
    changed = False

    def mutate(request: QaValidationRequest) -> QaValidationOutcome:
        nonlocal changed
        if not changed:
            changed = True
            raw = request.artifact_path.read_bytes()
            request.artifact_path.chmod(0o600)
            request.artifact_path.write_bytes(bytes([raw[0] ^ 1]) + raw[1:])
        return _pass(request)

    try:
        with pytest.raises(CandidateContractError) as caught:
            execute_candidate_qa(candidate, QaValidatorDispatcher(_registry(mutate)))
        assert caught.value.code in {"artifact-bytes", "candidate-changed"}
    finally:
        _make_writable(candidate)
