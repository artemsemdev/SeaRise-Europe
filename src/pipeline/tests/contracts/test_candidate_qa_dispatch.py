from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import pytest

from searise_pipeline.candidate_completeness.qa_dispatch import (
    ArtifactValidator,
    QaValidationOutcome,
    QaValidationRequest,
    QaValidatorDispatcher,
)
from searise_pipeline.candidate_completeness.qa_matrix import (
    ArtifactSelector,
    CandidateContractError,
    load_qa_routing_matrix,
)


def _pass(_: QaValidationRequest) -> QaValidationOutcome:
    return QaValidationOutcome("pass", "fixture-pass", "fixture validator passed")


def _registry() -> dict[str, ArtifactValidator]:
    return {route.validator_id: _pass for route in load_qa_routing_matrix().routes}


def _request(selector: ArtifactSelector | None = None) -> QaValidationRequest:
    return QaValidationRequest(
        artifact_id="scenario-config",
        artifact_path=Path("candidate/config/scenarios.json"),
        selector=selector
        or ArtifactSelector("scenario-config", "application/json", "identity"),
        declared_sha256="a" * 64,
    )


def test_dispatcher_binds_every_route_and_requires_explicit_pass() -> None:
    dispatcher = QaValidatorDispatcher(_registry())
    assert dispatcher.validator_ids == tuple(sorted(_registry()))
    assert dispatcher.dispatch(_request()) == QaValidationOutcome(
        "pass", "fixture-pass", "fixture validator passed"
    )


@pytest.mark.parametrize("mutation", ["missing", "unknown", "noncallable"])
def test_registry_drift_fails_closed(mutation: str) -> None:
    registry: dict[str, Any] = _registry()
    if mutation == "missing":
        registry.pop(next(iter(registry)))
    elif mutation == "unknown":
        registry["unknown.validator"] = _pass
    else:
        registry[next(iter(registry))] = object()
    with pytest.raises(CandidateContractError) as caught:
        QaValidatorDispatcher(cast(dict[str, ArtifactValidator], registry))
    assert caught.value.code == "qa-validator-registry"


def test_unknown_selector_fails_before_any_validator_runs() -> None:
    dispatcher = QaValidatorDispatcher(_registry())
    unknown = ArtifactSelector("unknown", "application/json", "identity")
    with pytest.raises(CandidateContractError) as caught:
        dispatcher.dispatch(_request(unknown))
    assert caught.value.code == "qa-validator-route"


@pytest.mark.parametrize(
    "outcome",
    [
        None,
        QaValidationOutcome(cast(Any, "unknown"), "bad-status", "invalid"),
        QaValidationOutcome("pass", "", "missing code"),
        QaValidationOutcome("pass", "missing-message", ""),
    ],
)
def test_implicit_or_malformed_outcome_fails_closed(outcome: object) -> None:
    registry = _registry()
    validator_id = "release.public-contract.scenario-config"
    registry[validator_id] = cast(
        ArtifactValidator,
        lambda _: outcome,
    )
    with pytest.raises(CandidateContractError) as caught:
        QaValidatorDispatcher(registry).dispatch(_request())
    assert caught.value.code == "qa-validator-outcome"


def test_unexpected_validator_exception_is_wrapped_with_stable_code() -> None:
    def broken(_: QaValidationRequest) -> QaValidationOutcome:
        raise RuntimeError("unstable implementation detail")

    registry = _registry()
    registry["release.public-contract.scenario-config"] = broken
    with pytest.raises(CandidateContractError) as caught:
        QaValidatorDispatcher(registry).dispatch(_request())
    assert caught.value.code == "qa-validator-execution"
