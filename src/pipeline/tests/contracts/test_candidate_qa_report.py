from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from searise_pipeline.candidate_completeness.assembler import _load_inputs
from searise_pipeline.candidate_completeness.qa_dispatch import (
    CandidateQaContext,
    QaValidationOutcome,
)
from searise_pipeline.candidate_completeness.qa_execution import (
    CandidateQaArtifactResult,
    PreGateQaExecution,
)
from searise_pipeline.candidate_completeness.qa_matrix import (
    ArtifactSelector,
    load_qa_routing_matrix,
)
from searise_pipeline.candidate_completeness.qa_report import (
    GATE_SCHEMA_PATH,
    build_pre_gate_report,
    build_synthetic_fixture_gate_report,
    canonical_json,
)
from searise_pipeline.candidate_completeness.validator import CandidateContractError
from searise_pipeline.gate_report import render_gate_report_markdown

ROOT = Path(__file__).resolve().parents[4]
RECEIPT = ROOT / "contracts/candidate-completeness/v2/fixtures/assembly/complete-synthetic.json"


def _report() -> tuple[dict[str, Any], bytes]:
    candidate, _, _, payloads = _load_inputs(RECEIPT)
    for artifact in candidate["artifacts"][:51]:
        raw = payloads[artifact["artifactId"]]
        artifact["byteSize"] = len(raw)
        import hashlib

        artifact["sha256"] = hashlib.sha256(raw).hexdigest()
    json_raw, markdown_raw = build_synthetic_fixture_gate_report(candidate)
    return json.loads(json_raw), markdown_raw


def test_synthetic_report_is_schema_valid_semantic_and_byte_stable() -> None:
    report, markdown = _report()
    schema = json.loads(GATE_SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator(schema).validate(report)
    assert canonical_json(report) == canonical_json(json.loads(canonical_json(report)))
    assert markdown == render_gate_report_markdown(report).encode("utf-8")
    assert build_synthetic_fixture_gate_report(_candidate_with_hashes()) == (
        canonical_json(report),
        markdown,
    )


def _candidate_with_hashes() -> dict[str, Any]:
    candidate, _, _, payloads = _load_inputs(RECEIPT)
    import hashlib

    for artifact in candidate["artifacts"][:51]:
        raw = payloads[artifact["artifactId"]]
        artifact.update(byteSize=len(raw), sha256=hashlib.sha256(raw).hexdigest())
    return candidate


def test_report_distinguishes_pass_and_not_measured_without_release_claim() -> None:
    report, _ = _report()
    statuses = {check["checkId"]: check["status"] for check in report["checks"]}
    assert statuses == {
        "artifact-integrity": "pass",
        "cross-runtime-parity": "pass",
        "format-validation": "not-measured",
        "owner-approval": "not-measured",
        "rights-completeness": "pass",
        "scientific-validation": "not-measured",
        "supply-chain-validation": "not-measured",
    }
    assert report["authority"]["automatedValidation"] == "not-measured"
    assert report["releasable"] is False
    assert report["stopReasonCodes"] == [
        "owner-approval-missing",
        "required-measurement-missing",
        "supply-chain-invalid",
    ]


def test_every_report_evidence_is_candidate_bound_and_release_relative() -> None:
    candidate = _candidate_with_hashes()
    report = json.loads(build_synthetic_fixture_gate_report(candidate)[0])
    artifacts = {item["path"]: item["sha256"] for item in candidate["artifacts"][:51]}
    for check in report["checks"]:
        paths = [item["path"] for item in check["evidence"]]
        assert paths == sorted(set(paths))
        for evidence in check["evidence"]:
            assert artifacts[evidence["path"]] == evidence["sha256"]


def _pre_gate_execution(
    overrides: dict[str, str] | None = None,
) -> PreGateQaExecution:
    candidate = _candidate_with_hashes()
    routes = {
        route.selector: route.validator_id for route in load_qa_routing_matrix().routes
    }
    context = CandidateQaContext(
        candidate_root=Path("candidate"),
        candidate_id=candidate["candidateId"],
        data_release_id=candidate["dataReleaseId"],
        data_provenance_class=candidate["dataProvenanceClass"],
        manifest_sha256=None,
        artifact_count=51,
    )
    results = []
    for artifact in candidate["artifacts"][:51]:
        selector = ArtifactSelector(
            artifact["role"], artifact["mediaType"], artifact["contentEncoding"]
        )
        validator_id = routes[selector]
        status = (overrides or {}).get(validator_id, "pass")
        results.append(
            CandidateQaArtifactResult(
                artifact_id=artifact["artifactId"],
                artifact_path=artifact["path"],
                declared_sha256=artifact["sha256"],
                validator_id=validator_id,
                outcome=QaValidationOutcome(  # type: ignore[arg-type]
                    status, f"fixture-{status}", f"fixture is {status}"
                ),
            )
        )
    return PreGateQaExecution(context, tuple(results))


def test_pre_gate_report_is_deterministic_and_keeps_automation_non_promoting() -> None:
    execution = _pre_gate_execution()
    first = build_pre_gate_report(execution, generated_at="2026-08-12T00:00:00Z")
    second = build_pre_gate_report(execution, generated_at="2026-08-12T00:00:00Z")
    assert first == second
    report = json.loads(first[0])
    Draft202012Validator(json.loads(GATE_SCHEMA_PATH.read_text())).validate(report)
    assert len(report["checks"]) == 20
    assert {check["status"] for check in report["checks"]} == {"pass"}
    assert report["authority"] == {
        "kind": "automation",
        "automatedValidation": "pass",
        "ownerDisposition": "not-recorded",
    }
    assert report["releasable"] is False
    assert report["stopReasonCodes"] == []
    assert first[1] == render_gate_report_markdown(report).encode()


def test_pre_gate_report_distinguishes_fail_and_not_measured() -> None:
    execution = _pre_gate_execution(
        {
            "release.analysis-cog": "fail",
            "settlements.browser-search-shard": "not-measured",
        }
    )
    report = json.loads(
        build_pre_gate_report(execution, generated_at="2026-08-12T00:00:00Z")[0]
    )
    statuses = {check["checkId"]: check for check in report["checks"]}
    assert statuses["release-analysis-cog"]["status"] == "fail"
    assert statuses["release-analysis-cog"]["measuredValue"] == 9
    assert statuses["settlements-browser-search-shard"]["status"] == "not-measured"
    assert statuses["settlements-browser-search-shard"]["measuredValue"] is None
    assert report["authority"]["automatedValidation"] == "fail"
    assert report["stopReasonCodes"] == [
        "cross-runtime-parity-failed",
        "scientific-parity-failed",
    ]


def test_pre_gate_report_rejects_unmapped_validator() -> None:
    execution = _pre_gate_execution()
    changed = list(execution.results)
    changed[0] = replace(changed[0], validator_id="unknown.validator")
    with pytest.raises(CandidateContractError, match="mapping is missing"):
        build_pre_gate_report(
            PreGateQaExecution(execution.candidate, tuple(changed)),
            generated_at="2026-08-12T00:00:00Z",
        )
