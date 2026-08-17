from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import pytest

from searise_pipeline.candidate_completeness.qa_dispatch import (
    ArtifactValidator,
    CandidateQaContext,
    QaValidationOutcome,
    QaValidationRequest,
    QaValidatorDispatcher,
    terminal_validator_registry,
    with_terminal_validators,
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
    context = CandidateQaContext(
        candidate_root=Path("candidate"),
        candidate_id="candidate-phase-1-fixture-20260811-0123456789ab",
        data_release_id="searise-europe-v1.0.0-20260811-0123456789ab",
        data_provenance_class="synthetic-fixture",
        manifest_sha256="b" * 64,
        artifact_count=54,
    )
    return QaValidationRequest(
        artifact_id="scenario-config",
        artifact_path=Path("candidate/config/scenarios.json"),
        selector=selector
        or ArtifactSelector("scenario-config", "application/json", "identity"),
        declared_sha256="a" * 64,
        candidate=context,
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


def test_dispatcher_copies_and_freezes_the_validated_registry() -> None:
    registry = _registry()
    dispatcher = QaValidatorDispatcher(registry)
    validator_id = dispatcher.validator_id_for(_request().selector)
    registry.pop(validator_id)

    assert dispatcher.dispatch(_request()).status == "pass"

    with pytest.raises(TypeError):
        dispatcher._validators[validator_id] = _pass  # type: ignore[index]


@pytest.mark.parametrize("attribute", ["_validators", "_routes", "_matrix"])
def test_dispatcher_authority_cannot_be_rebound_or_deleted(attribute: str) -> None:
    injected_called = False

    def injected(_: QaValidationRequest) -> QaValidationOutcome:
        nonlocal injected_called
        injected_called = True
        return _pass(_request())

    dispatcher = QaValidatorDispatcher(_registry())
    selected = dispatcher.validator_id_for(_request().selector)
    replacement = {selected: injected}

    with pytest.raises(AttributeError, match="immutable after construction"):
        setattr(dispatcher, attribute, replacement)
    with pytest.raises(AttributeError, match="immutable after construction"):
        delattr(dispatcher, attribute)

    assert dispatcher.dispatch(_request()).status == "pass"
    assert not injected_called


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


def test_terminal_validators_cannot_be_replaced() -> None:
    terminal = terminal_validator_registry()
    assert set(terminal) == {
        "candidate.byte-gate.checksums",
        "candidate.qa-report-json",
        "candidate.qa-report-markdown",
    }
    with pytest.raises(CandidateContractError, match="cannot be replaced"):
        with_terminal_validators({"candidate.qa-report-json": _pass})
