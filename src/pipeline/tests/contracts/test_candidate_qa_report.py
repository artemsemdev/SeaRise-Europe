from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from searise_pipeline.candidate_completeness.assembler import _load_inputs
from searise_pipeline.candidate_completeness.qa_report import (
    GATE_SCHEMA_PATH,
    build_synthetic_fixture_gate_report,
    canonical_json,
)
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
