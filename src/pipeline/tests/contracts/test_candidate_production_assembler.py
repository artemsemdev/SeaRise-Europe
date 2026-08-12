from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import pytest

from searise_pipeline.candidate_completeness import (
    CandidateAssemblyError,
    assemble_candidate_fixture,
    validate_candidate_root,
)
from searise_pipeline.candidate_completeness.production_assembler import (
    ProductionCandidateMetadata,
    assemble_production_candidate,
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
METADATA = ProductionCandidateMetadata(
    candidate_id="candidate-phase-1-real-source-20260812-0123456789ab",
    data_release_id="searise-europe-v1.0.0-20260812-0123456789ab",
    generated_at="2026-08-12T00:00:00Z",
)


def _registry(validator: ArtifactValidator) -> dict[str, ArtifactValidator]:
    return {route.validator_id: validator for route in load_qa_routing_matrix().routes}


def _pass(_: QaValidationRequest) -> QaValidationOutcome:
    return QaValidationOutcome("pass", "fixture-pass", "fixture validator passed")


def _input_root(tmp_path: Path) -> Path:
    fixture = tmp_path / "fixture"
    assemble_candidate_fixture(RECEIPT, fixture)
    manifest = json.loads((fixture / "manifest.json").read_text(encoding="utf-8"))
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    for artifact in manifest["artifacts"][:51]:
        source = fixture / artifact["path"]
        target = inputs / artifact["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    return inputs


def _make_writable(root: Path) -> None:
    for directory, _, files in os.walk(root):
        Path(directory).chmod(0o700)
        for name in files:
            (Path(directory) / name).chmod(0o600)


def test_assembles_real_source_candidate_with_manifest_written_last(tmp_path: Path) -> None:
    inputs = _input_root(tmp_path)
    output = tmp_path / "real-candidate"
    summary = assemble_production_candidate(
        inputs, output, METADATA, QaValidatorDispatcher(_registry(_pass))
    )

    assert summary.candidate_id == METADATA.candidate_id
    assert summary.artifact_count == 54
    gated = validate_candidate_root(output)
    assert summary.manifest_sha256 == gated.manifest_sha256
    assert summary.artifact_bytes == gated.artifact_bytes
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["dataProvenanceClass"] == "real-source"
    assert {item["dataProvenanceClass"] for item in manifest["artifacts"]} == {
        "real-source"
    }
    report = json.loads((output / "evidence/gate-report.json").read_text())
    assert report["authority"]["automatedValidation"] == "pass"
    assert report["releasable"] is False
    assert (output / "checksums.txt").read_text().count("\n") == 53
    _make_writable(output)


def test_production_assembly_is_byte_deterministic(tmp_path: Path) -> None:
    inputs = _input_root(tmp_path)
    dispatcher = QaValidatorDispatcher(_registry(_pass))
    first = tmp_path / "first"
    second = tmp_path / "second"
    one = assemble_production_candidate(inputs, first, METADATA, dispatcher)
    two = assemble_production_candidate(inputs, second, METADATA, dispatcher)
    assert one.manifest_sha256 == two.manifest_sha256
    left = {
        path.relative_to(first): path.read_bytes()
        for path in first.rglob("*")
        if path.is_file()
    }
    right = {
        path.relative_to(second): path.read_bytes()
        for path in second.rglob("*")
        if path.is_file()
    }
    assert left == right
    _make_writable(first)
    _make_writable(second)


def test_nonpass_pre_gate_blocks_manifest_and_publication(tmp_path: Path) -> None:
    inputs = _input_root(tmp_path)

    def fail_scenario(request: QaValidationRequest) -> QaValidationOutcome:
        if request.artifact_id == "scenario-config":
            return QaValidationOutcome("fail", "fixture-fail", "fixture validation failed")
        return _pass(request)

    output = tmp_path / "blocked"
    with pytest.raises(CandidateAssemblyError, match="pre-terminal candidate QA"):
        assemble_production_candidate(
            inputs,
            output,
            METADATA,
            QaValidatorDispatcher(_registry(fail_scenario)),
        )
    assert not output.exists()


def test_input_inventory_and_metadata_fail_closed(tmp_path: Path) -> None:
    inputs = _input_root(tmp_path)
    (inputs / "unexpected.txt").write_text("unexpected", encoding="utf-8")
    dispatcher = QaValidatorDispatcher(_registry(_pass))
    with pytest.raises(CandidateAssemblyError) as caught:
        assemble_production_candidate(inputs, tmp_path / "extra", METADATA, dispatcher)
    assert caught.value.code == "assembly-input-inventory"

    (inputs / "unexpected.txt").unlink()
    invalid = ProductionCandidateMetadata(
        candidate_id="invalid",
        data_release_id=METADATA.data_release_id,
        generated_at=METADATA.generated_at,
    )
    with pytest.raises(CandidateAssemblyError):
        assemble_production_candidate(inputs, tmp_path / "invalid", invalid, dispatcher)
    assert not (tmp_path / "invalid").exists()
