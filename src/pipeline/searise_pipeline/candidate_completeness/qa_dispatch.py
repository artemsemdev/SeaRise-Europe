"""Fail-closed binding between candidate QA routes and validator implementations."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Literal, Mapping, NoReturn

from jsonschema import Draft202012Validator

from searise_pipeline.gate_report import render_gate_report_markdown, validate_gate_report_semantics

from .qa_matrix import ArtifactSelector, QaRoutingMatrix, load_qa_routing_matrix
from .validator import CandidateContractError

QaStatus = Literal["pass", "fail", "not-measured"]


@dataclass(frozen=True)
class CandidateQaContext:
    """Immutable candidate identity and peer-artifact root available to validators."""

    candidate_root: Path
    candidate_id: str
    data_release_id: str
    data_provenance_class: str
    manifest_sha256: str | None
    artifact_count: int


@dataclass(frozen=True)
class QaValidationRequest:
    """One declared artifact routed to an authoritative validator.

    This routing primitive does not establish byte identity. The candidate-wide
    gate must first bind ``artifact_path`` to ``declared_sha256`` through the
    descriptor-safe byte gate and retain that binding in its final report.
    """

    artifact_id: str
    artifact_path: Path
    selector: ArtifactSelector
    declared_sha256: str
    candidate: CandidateQaContext


@dataclass(frozen=True)
class QaValidationOutcome:
    """An explicit validator disposition; successful return alone is never a pass."""

    status: QaStatus
    code: str
    message: str


ArtifactValidator = Callable[[QaValidationRequest], QaValidationOutcome]


def _fail(code: str, message: str) -> NoReturn:
    raise CandidateContractError(code, message)


def _strict_json(path: Path) -> Mapping[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CandidateContractError("qa-json", "artifact is not readable strict JSON") from exc
    if not isinstance(value, dict):
        _fail("qa-json", "artifact JSON root must be an object")
    return value


def _gate_report_json(request: QaValidationRequest) -> QaValidationOutcome:
    report = _strict_json(request.artifact_path)
    schema_path = (
        Path(__file__).resolve().parents[4]
        / "contracts/release-gates/v1/gate-report.schema.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    errors = sorted(
        Draft202012Validator(schema).iter_errors(report), key=lambda error: list(error.path)
    )
    if errors:
        return QaValidationOutcome("fail", "gate-report-schema", errors[0].message)
    try:
        validate_gate_report_semantics(report)
    except ValueError as exc:
        return QaValidationOutcome("fail", "gate-report-semantics", str(exc))
    context = request.candidate
    if (
        report.get("candidateId") != context.candidate_id
        or report.get("dataReleaseId") != context.data_release_id
        or report.get("dataProvenanceClass") != context.data_provenance_class
    ):
        return QaValidationOutcome(
            "fail", "gate-report-binding", "gate report candidate binding differs"
        )
    return QaValidationOutcome("pass", "gate-report-valid", "gate report is valid and bound")


def _gate_report_markdown(request: QaValidationRequest) -> QaValidationOutcome:
    report_path = request.candidate.candidate_root / "evidence/gate-report.json"
    report = _strict_json(report_path)
    expected = render_gate_report_markdown(report).encode("utf-8")
    try:
        observed = request.artifact_path.read_bytes()
    except OSError as exc:
        raise CandidateContractError("qa-markdown", "gate report Markdown is unreadable") from exc
    if observed != expected:
        return QaValidationOutcome(
            "fail", "gate-report-markdown", "Markdown differs from deterministic renderer"
        )
    return QaValidationOutcome(
        "pass", "gate-report-markdown", "Markdown matches deterministic renderer"
    )


def _checksums(request: QaValidationRequest) -> QaValidationOutcome:
    manifest = _strict_json(request.candidate.candidate_root / "manifest.json")
    expected = "".join(
        f"{item['sha256']}  {item['path']}\n"
        for item in manifest.get("checksumInventory", {}).get("subjects", [])  # type: ignore[union-attr]
    ).encode("utf-8")
    try:
        observed = request.artifact_path.read_bytes()
    except OSError as exc:
        raise CandidateContractError("qa-checksums", "checksums artifact is unreadable") from exc
    if observed != expected or hashlib.sha256(observed).hexdigest() != request.declared_sha256:
        return QaValidationOutcome(
            "fail", "checksums-invalid", "checksums differ from the manifest inventory"
        )
    return QaValidationOutcome("pass", "checksums-valid", "checksums cover exact subjects")


def terminal_validator_registry() -> dict[str, ArtifactValidator]:
    """Return authoritative validators for the three post-gate terminal roles."""
    return {
        "candidate.byte-gate.checksums": _checksums,
        "candidate.qa-report-json": _gate_report_json,
        "candidate.qa-report-markdown": _gate_report_markdown,
    }


def with_terminal_validators(
    validators: Mapping[str, ArtifactValidator],
) -> dict[str, ArtifactValidator]:
    """Add sealed-candidate validators without allowing caller replacement."""
    terminal = terminal_validator_registry()
    overlap = sorted(set(validators) & set(terminal))
    if overlap:
        _fail("qa-validator-registry", f"terminal validators cannot be replaced: {overlap}")
    return {**validators, **terminal}


class QaValidatorDispatcher:
    """Resolve every matrix route to exactly one callable validator."""

    def __init__(
        self,
        validators: Mapping[str, ArtifactValidator],
        *,
        matrix: QaRoutingMatrix | None = None,
    ) -> None:
        self._matrix = matrix or load_qa_routing_matrix()
        expected = {route.validator_id for route in self._matrix.routes}
        observed = set(validators)
        missing = sorted(expected - observed)
        unknown = sorted(observed - expected)
        if missing or unknown:
            _fail(
                "qa-validator-registry",
                f"missing validators={missing}; unknown validators={unknown}",
            )
        noncallable = sorted(key for key, value in validators.items() if not callable(value))
        if noncallable:
            _fail("qa-validator-registry", f"validators are not callable: {noncallable}")
        self._validators = dict(validators)
        self._routes: dict[ArtifactSelector, str] = {
            route.selector: str(route.validator_id) for route in self._matrix.routes
        }

    @property
    def validator_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._validators))

    @property
    def matrix(self) -> QaRoutingMatrix:
        """Expose the exact immutable routing authority selected by the dispatcher."""
        return self._matrix

    def validator_id_for(self, selector: ArtifactSelector) -> str:
        validator_id = self._routes.get(selector)
        if validator_id is None:
            _fail("qa-validator-route", f"no validator route for artifact selector: {selector}")
        return validator_id

    def dispatch(self, request: QaValidationRequest) -> QaValidationOutcome:
        """Run the selected validator and require an explicit, well-formed outcome."""
        validator_id = self.validator_id_for(request.selector)
        try:
            outcome = self._validators[validator_id](request)
        except CandidateContractError:
            raise
        except Exception as exc:
            raise CandidateContractError(
                "qa-validator-execution",
                f"{validator_id} raised while validating {request.artifact_id}",
            ) from exc
        if not isinstance(outcome, QaValidationOutcome):
            _fail(
                "qa-validator-outcome",
                f"{validator_id} did not return an explicit QA outcome",
            )
        if outcome.status not in ("pass", "fail", "not-measured"):
            _fail("qa-validator-outcome", f"{validator_id} returned an unknown status")
        if not outcome.code or not outcome.message:
            _fail("qa-validator-outcome", f"{validator_id} returned incomplete evidence")
        return outcome
