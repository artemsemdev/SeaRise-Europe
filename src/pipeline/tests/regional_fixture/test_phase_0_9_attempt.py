"""Reproducibility checks for the nine-layer Phase 0.9 blocked attempt."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from searise_pipeline.regional_fixture.phase_0_9_attempt import (
    BLOCKER_IDS,
    HORIZONS,
    SCENARIOS,
    build_blocked_phase_0_9_attempt,
    canonical_phase_0_9_attempt_bytes,
)

REPO_ROOT = Path(__file__).parents[4]
EVIDENCE_PATH = (
    REPO_ROOT / "src/pipeline/science/evidence/phase-0-9-regional-attempt.json"
)


def _evidence() -> dict:  # type: ignore[type-arg]
    return json.loads(EVIDENCE_PATH.read_text(encoding="utf-8"))


def test_checked_in_blocked_attempt_rebuilds_byte_for_byte() -> None:
    rebuilt = build_blocked_phase_0_9_attempt(REPO_ROOT)

    assert canonical_phase_0_9_attempt_bytes(rebuilt) == EVIDENCE_PATH.read_bytes()


def test_all_nine_combinations_bind_the_exact_ar6_member_and_year() -> None:
    attempts = _evidence()["attempts"]
    assert len(attempts) == 9
    assert {(item["scenario"], item["horizon"]) for item in attempts} == {
        (scenario, horizon) for scenario in SCENARIOS for horizon in HORIZONS
    }
    expected_members = {
        "ssp1-26": (
            "ssp126",
            "ssp126-medium-total",
            "28ca163c13470047aefb75ae8f4a8bc6e06c3e44b824ff37e8743ca8d3a1b716",
        ),
        "ssp2-45": (
            "ssp245",
            "ssp245-medium-total",
            "3f31aadb53b7962a729a839cd58e841f171e72575f9e2b802399be6656aa8cb8",
        ),
        "ssp5-85": (
            "ssp585",
            "ssp585-medium-total",
            "b3bcf98c6a17b43fbb24d0e60ede382886f3487883022aa88b513ea582a607e0",
        ),
    }
    for attempt in attempts:
        source_scenario, member_id, member_sha = expected_members[attempt["scenario"]]
        assert attempt["sourceScenario"] == source_scenario
        assert attempt["projectionMember"] == {"id": member_id, "sha256": member_sha}
        assert attempt["projectionQuantiles"] == [0.167, 0.5, 0.833]


def test_every_combination_stops_before_arrays_classes_or_artifacts() -> None:
    evidence = _evidence()

    assert evidence["syntheticScientificInputsUsed"] is False
    assert evidence["outputs"] == []
    assert [item["id"] for item in evidence["blockers"]] == list(BLOCKER_IDS)
    for attempt in evidence["attempts"]:
        assert attempt["status"] == "blocked-before-array"
        assert attempt["failureStage"] == "scientific-preflight"
        assert attempt["failureReasons"] == list(BLOCKER_IDS)
        assert attempt["emittedScientificClassValues"] == []
        assert attempt["artifacts"] == []
        assert attempt["statistics"] is None


def test_common_lineage_records_every_unavailable_numerical_control() -> None:
    evidence = _evidence()
    lineage = evidence["lineage"]

    assert lineage["baseline"]["monthlyObjectCount"] == 240
    assert lineage["baseline"]["calendarDayWeight"] == 7305
    assert lineage["baseline"]["sourceVariable"] == "sla"
    assert lineage["baseline"]["derivedVariable"] == "adt"
    assert lineage["baseline"]["equation"] == (
        "mean_1995_2014(ADT_GOCO06S) = "
        "day_weighted_mean(monthly_SLA) + MDT_GOCO06S"
    )
    assert lineage["geoid"]["status"] == "blocked"
    assert lineage["geoid"]["target"]["earthGravityConstant"] is None
    assert lineage["terrain"]["requiredLayers"] == ["DEM", "EDM", "FLM", "HEM", "WBM"]
    assert lineage["terrain"]["regionalShape"] is None
    assert lineage["terrain"]["regionalAffine"] is None
    assert lineage["uncertainty"]["numericBoundsStatus"] == "blocked"
    assert lineage["uncertainty"]["maximumTotalUncertaintyMetres"] is None
    assert lineage["connectivity"]["reviewStatus"] == "pending-external"
    assert lineage["software"]["externalGeoidEngine"]["status"] == "pending"


def test_historical_phase_0_3_evidence_is_only_checksum_referenced() -> None:
    binding = _evidence()["historicalEvidence"]
    historical_path = REPO_ROOT / binding["path"]

    assert binding["path"] == "docs/evidence/phase-0-regional-fixture.md"
    assert hashlib.sha256(historical_path.read_bytes()).hexdigest() == binding["sha256"]
