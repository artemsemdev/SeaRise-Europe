"""Tests for the explicit Phase 0.3 stop/go decision."""

from __future__ import annotations

from copy import deepcopy

import pytest

from searise_pipeline.regional_fixture.gate import (
    HORIZONS,
    SCENARIOS,
    MethodologyGateBlocked,
    assert_scientific_release_allowed,
    evaluate_methodology_gate,
)
from searise_pipeline.science.contracts import ScienceContracts, load_science_contracts


def test_current_contracts_end_in_explicit_blocked_state() -> None:
    gate = evaluate_methodology_gate(load_science_contracts())

    assert gate.state == "blocked"
    assert gate.unlocks_phase_1 is False
    assert gate.generated_scientific_artifacts == ()
    assert "vertical-compatibility" in gate.blockers
    assert "projection-archive-sha256" in gate.blockers
    assert "canonical-coastal-source" in gate.blockers
    assert "vertical-methodology-review" in gate.blockers
    assert gate.missing_evidence


def test_all_nine_layers_record_lineage_without_claiming_completion() -> None:
    gate = evaluate_methodology_gate(load_science_contracts())

    assert len(gate.layers) == len(SCENARIOS) * len(HORIZONS) == 9
    assert {(item.scenario, item.horizon) for item in gate.layers} == {
        (scenario, horizon) for scenario in SCENARIOS for horizon in HORIZONS
    }
    assert all(item.status == "blocked" for item in gate.layers)
    assert all(item.source_lineage["variable"] == "sea_level_change" for item in gate.layers)
    assert all(item.source_lineage["quantile"] == 0.5 for item in gate.layers)
    assert all(
        item.source_lineage["verticalMethodology"]
        == "absolute-mean-water-surface-egm2008-interval-v1"
        for item in gate.layers
    )


def test_release_guard_prevents_scientific_artifacts_and_phase_1() -> None:
    gate = evaluate_methodology_gate(load_science_contracts())

    with pytest.raises(MethodologyGateBlocked, match="vertical-datum-reconciliation"):
        assert_scientific_release_allowed(gate)


def test_gate_receipt_is_json_serializable() -> None:
    gate = evaluate_methodology_gate(load_science_contracts())
    receipt = gate.to_dict()

    assert receipt["state"] == "blocked"
    assert receipt["generatedScientificArtifacts"] == []
    assert len(receipt["layers"]) == 9


def test_no_go_is_not_implicitly_promoted_after_contract_edits() -> None:
    contracts = load_science_contracts()
    source = deepcopy(contracts.source_semantics)
    geography = deepcopy(contracts.geography_rules)
    vertical_methodology = deepcopy(contracts.vertical_methodology)
    source["publicationGate"]["status"] = "approved"
    source["publicationGate"]["blockingDecisions"] = []
    geography["publicationGate"]["status"] = "approved"
    geography["publicationGate"]["blockingDecisions"] = []
    source["verticalCompatibility"]["status"] = "approved"
    for review in (
        source["projection"]["review"],
        geography["support"]["review"],
        geography["coastal"]["review"],
        geography["connectivity"]["review"],
    ):
        review["status"] = "approved"

    gate = evaluate_methodology_gate(
        ScienceContracts(source, geography, vertical_methodology)
    )

    assert gate.state == "blocked"
    assert gate.unlocks_phase_1 is False
    assert "vertical-methodology-review" in gate.blockers
    assert all(item.status == "blocked" for item in gate.layers)
