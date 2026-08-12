"""Fail-closed binding between candidate QA routes and validator implementations."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Literal, Mapping, NoReturn

from .qa_matrix import ArtifactSelector, QaRoutingMatrix, load_qa_routing_matrix
from .validator import CandidateContractError

QaStatus = Literal["pass", "fail", "not-measured"]


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


@dataclass(frozen=True)
class QaValidationOutcome:
    """An explicit validator disposition; successful return alone is never a pass."""

    status: QaStatus
    code: str
    message: str


ArtifactValidator = Callable[[QaValidationRequest], QaValidationOutcome]


def _fail(code: str, message: str) -> NoReturn:
    raise CandidateContractError(code, message)


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
