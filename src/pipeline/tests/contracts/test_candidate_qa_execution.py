from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from searise_pipeline.candidate_completeness import (
    CandidateContractError,
    assemble_candidate_fixture,
    execute_candidate_qa,
    execute_pre_gate_qa,
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
    observed: list[tuple[str, Path, str, Path, str, int]] = []

    def record(request: QaValidationRequest) -> QaValidationOutcome:
        observed.append(
            (
                request.artifact_id,
                request.artifact_path,
                request.declared_sha256,
                request.candidate.candidate_root,
                request.candidate.manifest_sha256,
                request.candidate.artifact_count,
            )
        )
        return _pass(request)

    execution = execute_candidate_qa(candidate, QaValidatorDispatcher(_registry(record)))

    assert execution.releasable is True
    assert execution.candidate.artifact_count == 54
    assert len(execution.results) == len(observed) == 54
    assert [result.artifact_id for result in execution.results] == [
        artifact_id for artifact_id, _, _, _, _, _ in observed
    ]
    assert all(path.is_relative_to(candidate) for _, path, _, _, _, _ in observed)
    assert all(
        result.declared_sha256 == declared
        for result, (_, _, declared, _, _, _) in zip(execution.results, observed)
    )
    assert {root for _, _, _, root, _, _ in observed} == {candidate}
    assert {digest for _, _, _, _, digest, _ in observed} == {
        execution.candidate.manifest_sha256
    }
    assert {count for _, _, _, _, _, count in observed} == {54}


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


def test_executes_exact_pre_gate_inventory_without_a_manifest_binding(tmp_path: Path) -> None:
    candidate = tmp_path / "candidate"
    assemble_candidate_fixture(RECEIPT, candidate)
    manifest = json.loads((candidate / "manifest.json").read_text(encoding="utf-8"))
    observed: list[QaValidationRequest] = []

    def record(request: QaValidationRequest) -> QaValidationOutcome:
        observed.append(request)
        return _pass(request)

    execution = execute_pre_gate_qa(
        candidate,
        manifest["artifacts"][:51],
        QaValidatorDispatcher(_registry(record)),
        candidate_id=manifest["candidateId"],
        data_release_id=manifest["dataReleaseId"],
        data_provenance_class=manifest["dataProvenanceClass"],
    )

    assert execution.releasable is True
    assert len(observed) == 51
    assert execution.candidate.manifest_sha256 is None
    assert {request.candidate for request in observed} == {execution.candidate}


def test_pre_gate_inventory_and_bytes_fail_closed(tmp_path: Path) -> None:
    candidate = tmp_path / "candidate"
    assemble_candidate_fixture(RECEIPT, candidate)
    manifest = json.loads((candidate / "manifest.json").read_text(encoding="utf-8"))
    dispatcher = QaValidatorDispatcher(_registry(_pass))
    arguments = {
        "candidate_id": manifest["candidateId"],
        "data_release_id": manifest["dataReleaseId"],
        "data_provenance_class": manifest["dataProvenanceClass"],
    }

    with pytest.raises(CandidateContractError, match="exact 51-artifact"):
        execute_pre_gate_qa(candidate, manifest["artifacts"][:50], dispatcher, **arguments)

    changed = [dict(item) for item in manifest["artifacts"][:51]]
    changed[0]["sha256"] = "0" * 64
    with pytest.raises(CandidateContractError) as caught:
        execute_pre_gate_qa(candidate, changed, dispatcher, **arguments)
    assert caught.value.code == "qa-input-bytes"
