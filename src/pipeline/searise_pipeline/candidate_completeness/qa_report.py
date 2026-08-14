"""Deterministic candidate-wide gate report construction."""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path, PurePosixPath
from typing import Any, NoReturn

from jsonschema import Draft202012Validator

from searise_pipeline.gate_report import (
    render_gate_report_markdown,
    validate_gate_report_semantics,
)

from .qa_execution import PreGateQaExecution
from .validator import CandidateContractError

REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
GATE_SCHEMA_PATH = REPOSITORY_ROOT / "contracts/release-gates/v1/gate-report.schema.json"
GATE_SCHEMA_URL = (
    "https://artemsemdev.github.io/SeaRise-Europe/contracts/"
    "release-gates/v1/gate-report.schema.json"
)

_VALIDATOR_STOP_REASONS = {
    "release.public-contract.architecture-evidence": "owner-approval-missing",
    "release.build-receipt": "supply-chain-invalid",
    "release.boundary-geoparquet.coastal": "scientific-parity-failed",
    "release.boundary-pmtiles.coastal": "scientific-parity-failed",
    "release.public-contract.methodology": "scientific-parity-failed",
    "release.analysis-cog": "scientific-parity-failed",
    "release.projection-geoparquet": "scientific-parity-failed",
    "release.projection-pmtiles": "scientific-parity-failed",
    "release.public-contract.quality-summary": "cross-runtime-parity-failed",
    "release.public-contract.scenario-config": "schema-invalid",
    "settlements.geoparquet": "cross-runtime-parity-failed",
    "settlements.browser-search-shard": "cross-runtime-parity-failed",
    "settlements.browser-search-receipt": "cross-runtime-parity-failed",
    "release.rights": "rights-incomplete",
    "release.public-contract.source-receipt": "rights-incomplete",
    "release.stac.catalog": "schema-invalid",
    "release.stac.collection": "schema-invalid",
    "release.stac.item": "schema-invalid",
    "release.boundary-geoparquet.support": "scientific-parity-failed",
    "release.boundary-pmtiles.support": "scientific-parity-failed",
}


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


def _validate_report(report: Mapping[str, Any]) -> None:
    schema = json.loads(GATE_SCHEMA_PATH.read_text(encoding="utf-8"))
    errors = sorted(
        Draft202012Validator(schema).iter_errors(report),
        key=lambda error: list(error.path),
    )
    if errors:
        _fail("qa-report-schema", errors[0].message)
    validate_gate_report_semantics(report)


def build_pre_gate_report(
    execution: PreGateQaExecution,
    *,
    generated_at: str,
) -> tuple[bytes, bytes]:
    """Render deterministic reports from the exact pre-terminal QA outcomes."""
    if not execution.results or len(execution.results) != execution.candidate.artifact_count:
        _fail("qa-report-execution", "pre-gate execution is incomplete")
    grouped: dict[str, list[Any]] = defaultdict(list)
    for result in execution.results:
        grouped[result.validator_id].append(result)
    unknown = sorted(set(grouped) - set(_VALIDATOR_STOP_REASONS))
    if unknown:
        _fail("qa-report-validator", f"validator report mapping is missing: {unknown}")

    checks: list[dict[str, Any]] = []
    for validator_id in sorted(grouped):
        results = grouped[validator_id]
        statuses = {result.outcome.status for result in results}
        if "fail" in statuses:
            status = "fail"
            measured: int | None = sum(
                result.outcome.status != "pass" for result in results
            )
        elif "not-measured" in statuses:
            status = "not-measured"
            measured = None
        else:
            status = "pass"
            measured = 0
        check: dict[str, Any] = {
            "checkId": validator_id.replace(".", "-"),
            "label": validator_id.replace(".", " ").replace("-", " ").title(),
            "status": status,
            "nonWaivable": True,
            "unit": "count",
            "target": {"operator": "exactly", "value": 0},
            "measuredValue": measured,
            "evidence": sorted(
                (_evidence(result.artifact_path, result.declared_sha256) for result in results),
                key=lambda item: item["path"],
            ),
        }
        if status != "pass":
            check["stopReasonCode"] = _VALIDATOR_STOP_REASONS[validator_id]
        checks.append(check)

    aggregate = (
        "fail"
        if any(check["status"] == "fail" for check in checks)
        else "not-measured"
        if any(check["status"] == "not-measured" for check in checks)
        else "pass"
    )
    report: dict[str, Any] = {
        "$schema": GATE_SCHEMA_URL,
        "schemaVersion": "1.0.0",
        "rendererVersion": "markdown-v1",
        "ordering": "check-id-then-evidence-path-utf8-bytewise",
        "candidateId": execution.candidate.candidate_id,
        "dataReleaseId": execution.candidate.data_release_id,
        "dataProvenanceClass": execution.candidate.data_provenance_class,
        "generatedAt": generated_at,
        "authority": {
            "kind": "automation",
            "automatedValidation": aggregate,
            "ownerDisposition": "not-recorded",
        },
        "releasable": False,
        "checks": checks,
        "stopReasonCodes": sorted(
            {
                str(check["stopReasonCode"])
                for check in checks
                if "stopReasonCode" in check
            }
        ),
    }
    _validate_report(report)
    return canonical_json(report), render_gate_report_markdown(report).encode("utf-8")


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
    _validate_report(report)
    return canonical_json(report), render_gate_report_markdown(report).encode("utf-8")
