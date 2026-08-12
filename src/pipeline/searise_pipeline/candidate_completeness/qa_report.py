"""Deterministic candidate-wide gate report construction."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path, PurePosixPath
from typing import Any, NoReturn

from jsonschema import Draft202012Validator

from searise_pipeline.gate_report import (
    render_gate_report_markdown,
    validate_gate_report_semantics,
)

from .validator import CandidateContractError

REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
GATE_SCHEMA_PATH = REPOSITORY_ROOT / "contracts/release-gates/v1/gate-report.schema.json"
GATE_SCHEMA_URL = (
    "https://artemsemdev.github.io/SeaRise-Europe/contracts/"
    "release-gates/v1/gate-report.schema.json"
)


def _fail(code: str, message: str) -> NoReturn:
    raise CandidateContractError(code, message)


def canonical_json(document: Mapping[str, Any]) -> bytes:
    """Encode one report with the repository's canonical JSON byte policy."""
    try:
        return (
            json.dumps(
                document,
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
                sort_keys=True,
            )
            + "\n"
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise CandidateContractError("qa-report-json", "report is not canonical JSON") from exc


def _evidence(path: str, sha256: str) -> dict[str, str]:
    logical = PurePosixPath(path)
    if (
        logical.is_absolute()
        or logical.as_posix() != path
        or any(part in {"", ".", ".."} for part in logical.parts)
    ):
        _fail("qa-report-evidence", f"evidence path is unsafe: {path}")
    if len(sha256) != 64 or any(character not in "0123456789abcdef" for character in sha256):
        _fail("qa-report-evidence", f"evidence SHA-256 is invalid: {path}")
    return {"path": path, "sha256": sha256}


def _artifact_evidence(
    artifacts: Mapping[str, Mapping[str, Any]], artifact_id: str
) -> list[dict[str, str]]:
    artifact = artifacts.get(artifact_id)
    if artifact is None:
        _fail("qa-report-evidence", f"evidence artifact is absent: {artifact_id}")
    return [_evidence(str(artifact["path"]), str(artifact["sha256"]))]


def build_synthetic_fixture_gate_report(
    candidate: Mapping[str, Any],
    *,
    generated_at: str = "2026-08-11T00:00:00Z",
) -> tuple[bytes, bytes]:
    """Build the explicit non-releasable report for the complete synthetic fixture.

    The fixture proves assembly, identity, rights plumbing, and parity wiring. It
    deliberately does not claim production format/scientific validation, owner
    approval, or protected supply-chain evidence.
    """
    raw_artifacts = candidate.get("artifacts")
    if not isinstance(raw_artifacts, Sequence) or isinstance(raw_artifacts, (str, bytes)):
        _fail("qa-report-candidate", "candidate artifacts are unavailable")
    artifacts = {
        str(item.get("artifactId")): item
        for item in raw_artifacts
        if isinstance(item, Mapping) and item.get("artifactId")
    }
    checks: list[dict[str, Any]] = [
        {
            "checkId": "artifact-integrity",
            "label": "Artifact integrity mismatches",
            "status": "pass",
            "nonWaivable": True,
            "unit": "count",
            "target": {"operator": "exactly", "value": 0},
            "measuredValue": 0,
            "evidence": _artifact_evidence(artifacts, "build-receipt"),
        },
        {
            "checkId": "cross-runtime-parity",
            "label": "Cross-runtime parity mismatches",
            "status": "pass",
            "nonWaivable": True,
            "unit": "count",
            "target": {"operator": "exactly", "value": 0},
            "measuredValue": 0,
            "evidence": _artifact_evidence(artifacts, "quality-summary"),
        },
        {
            "checkId": "format-validation",
            "label": "Production format validation failures",
            "status": "not-measured",
            "nonWaivable": True,
            "unit": "count",
            "target": {"operator": "exactly", "value": 0},
            "measuredValue": None,
            "evidence": _artifact_evidence(artifacts, "methodology"),
            "stopReasonCode": "required-measurement-missing",
        },
        {
            "checkId": "owner-approval",
            "label": "Missing owner approvals",
            "status": "not-measured",
            "nonWaivable": True,
            "unit": "count",
            "target": {"operator": "exactly", "value": 0},
            "measuredValue": None,
            "evidence": _artifact_evidence(artifacts, "architecture-evidence"),
            "stopReasonCode": "owner-approval-missing",
        },
        {
            "checkId": "rights-completeness",
            "label": "Artifacts missing rights records",
            "status": "pass",
            "nonWaivable": True,
            "unit": "count",
            "target": {"operator": "exactly", "value": 0},
            "measuredValue": 0,
            "evidence": _artifact_evidence(artifacts, "source-attribution"),
        },
        {
            "checkId": "scientific-validation",
            "label": "Scientific validation failures",
            "status": "not-measured",
            "nonWaivable": True,
            "unit": "count",
            "target": {"operator": "exactly", "value": 0},
            "measuredValue": None,
            "evidence": _artifact_evidence(artifacts, "quality-summary"),
            "stopReasonCode": "required-measurement-missing",
        },
        {
            "checkId": "supply-chain-validation",
            "label": "Supply-chain validation failures",
            "status": "not-measured",
            "nonWaivable": True,
            "unit": "count",
            "target": {"operator": "exactly", "value": 0},
            "measuredValue": None,
            "evidence": _artifact_evidence(artifacts, "architecture-evidence"),
            "stopReasonCode": "supply-chain-invalid",
        },
    ]
    checks.sort(key=lambda check: str(check["checkId"]))
    report: dict[str, Any] = {
        "$schema": GATE_SCHEMA_URL,
        "schemaVersion": "1.0.0",
        "rendererVersion": "markdown-v1",
        "ordering": "check-id-then-evidence-path-utf8-bytewise",
        "candidateId": candidate.get("candidateId"),
        "dataReleaseId": candidate.get("dataReleaseId"),
        "dataProvenanceClass": candidate.get("dataProvenanceClass"),
        "generatedAt": generated_at,
        "authority": {
            "kind": "automation",
            "automatedValidation": "not-measured",
            "ownerDisposition": "not-recorded",
        },
        "releasable": False,
        "checks": checks,
        "stopReasonCodes": [
            "owner-approval-missing",
            "required-measurement-missing",
            "supply-chain-invalid",
        ],
    }
    schema = json.loads(GATE_SCHEMA_PATH.read_text(encoding="utf-8"))
    errors = sorted(
        Draft202012Validator(schema).iter_errors(report),
        key=lambda error: list(error.path),
    )
    if errors:
        _fail("qa-report-schema", errors[0].message)
    validate_gate_report_semantics(report)
    return canonical_json(report), render_gate_report_markdown(report).encode("utf-8")
