"""Semantic validation and deterministic Markdown for release gate reports."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

CRITICAL_STOP_REASONS = frozenset(
    {
        "artifact-integrity-failed",
        "cross-runtime-parity-failed",
        "owner-approval-missing",
        "reproducibility-failed",
        "required-measurement-missing",
        "rights-incomplete",
        "schema-invalid",
        "scientific-parity-failed",
        "supply-chain-invalid",
    }
)


class GateReportError(ValueError):
    """Raised when a schema-valid gate report contradicts gate semantics."""


def _target_met(check: Mapping[str, Any]) -> bool:
    measured = check["measuredValue"]
    target = check["target"]
    operator = target["operator"]
    if operator == "at-most":
        return measured <= target["value"]
    if operator == "at-least":
        return measured >= target["value"]
    return measured == target["value"]


def _aggregate_status(checks: list[Mapping[str, Any]]) -> str:
    statuses = {check["status"] for check in checks}
    if "fail" in statuses:
        return "fail"
    if "not-measured" in statuses:
        return "not-measured"
    return "pass"


def validate_gate_report_semantics(report: Mapping[str, Any]) -> None:
    """Validate deterministic and derived rules after JSON Schema validation."""

    checks = report["checks"]
    authority = report["authority"]
    check_ids = [check["checkId"] for check in checks]
    if check_ids != sorted(check_ids) or len(check_ids) != len(set(check_ids)):
        raise GateReportError("checks must use unique checkId order")

    blocker_reasons: list[str] = []
    for check in checks:
        evidence_paths = [item["path"] for item in check["evidence"]]
        if evidence_paths != sorted(evidence_paths) or len(evidence_paths) != len(
            set(evidence_paths)
        ):
            raise GateReportError(
                f"{check['checkId']} evidence must use unique path order"
            )

        status = check["status"]
        if status != "not-measured":
            target_met = _target_met(check)
            if (status == "pass") != target_met:
                raise GateReportError(
                    f"{check['checkId']} status contradicts its measurement"
                )
        if status != "pass":
            reason = check["stopReasonCode"]
            blocker_reasons.append(reason)
            if reason in CRITICAL_STOP_REASONS and not check["nonWaivable"]:
                raise GateReportError(
                    f"{check['checkId']} critical stop reason must be non-waivable"
                )
        if not check["nonWaivable"] and (
            status != "fail"
            or check.get("stopReasonCode") != "metric-target-missed"
            or authority["kind"] != "owner"
        ):
            raise GateReportError(
                f"{check['checkId']} waivable metric must be owner-controlled"
            )

    stop_reasons = report["stopReasonCodes"]
    expected_reasons = sorted(set(blocker_reasons))
    if stop_reasons != expected_reasons:
        raise GateReportError(
            "stopReasonCodes must be the sorted unique reasons from blocked checks"
        )

    expected_status = _aggregate_status(checks)
    if authority["automatedValidation"] != expected_status:
        raise GateReportError("automatedValidation contradicts check statuses")

    if report["releasable"]:
        if any(check["status"] != "pass" for check in checks):
            raise GateReportError("a blocked check cannot be releasable in v1")
        if authority["kind"] != "owner" or authority["ownerDisposition"] != "approved":
            raise GateReportError("release requires explicit owner approval")


def _number(value: int | float) -> str:
    return json.dumps(value, allow_nan=False, separators=(",", ":"))


def _target_text(check: Mapping[str, Any]) -> str:
    operators = {"at-most": "<=", "at-least": ">=", "exactly": "="}
    target = check["target"]
    return f"{operators[target['operator']]} {_number(target['value'])} {check['unit']}"


def _measured_text(check: Mapping[str, Any]) -> str:
    if check["measuredValue"] is None:
        return "not measured"
    return f"{_number(check['measuredValue'])} {check['unit']}"


def _evidence_text(check: Mapping[str, Any]) -> str:
    return "<br>".join(
        f"`{item['path']}` (`sha256:{item['sha256']}`)"
        for item in check["evidence"]
    )


def render_gate_report_markdown(report: Mapping[str, Any]) -> str:
    """Render a schema-valid gate report as deterministic Markdown v1."""

    validate_gate_report_semantics(report)
    authority = report["authority"]
    lines = [
        "# Release gate report",
        "",
        f"- Candidate: `{report['candidateId']}`",
        f"- Data release: `{report['dataReleaseId']}`",
        f"- Provenance: `{report['dataProvenanceClass']}`",
        f"- Authority: `{authority['kind']}`",
        f"- Automated validation: `{authority['automatedValidation']}`",
        f"- Owner disposition: `{authority['ownerDisposition']}`",
        f"- Releasable: `{'yes' if report['releasable'] else 'no'}`",
        f"- Generated: `{report['generatedAt']}`",
        "",
        "## Checks",
        "",
        "| Check | Status | Target | Measured | Non-waivable | Evidence |",
        "|---|---|---:|---:|---|---|",
    ]
    for check in report["checks"]:
        lines.append(
            "| "
            f"{check['label']} | `{check['status']}` | {_target_text(check)} | "
            f"{_measured_text(check)} | {'yes' if check['nonWaivable'] else 'no'} | "
            f"{_evidence_text(check)} |"
        )

    lines.extend(["", "## Stop reasons", ""])
    if report["stopReasonCodes"]:
        lines.extend(f"- `{reason}`" for reason in report["stopReasonCodes"])
    else:
        lines.append("None.")
    return "\n".join(lines) + "\n"
