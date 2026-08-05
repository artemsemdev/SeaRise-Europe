"""Characterize the fail-closed Phase 0.2 scientific contracts."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from searise_pipeline.science import (
    ScienceContractError,
    assert_publication_ready,
    load_science_contracts,
    projection_mapping,
    verify_geometry_assets,
    verify_terrain_source_bindings,
)

REPO_ROOT = Path(__file__).parents[4]
CONTRACT_DIR = REPO_ROOT / "src" / "pipeline" / "science"
SOURCE_LOCK_PATH = REPO_ROOT / "src" / "pipeline" / "sources" / "source-lock.json"


def test_contracts_validate_and_geometry_bytes_match() -> None:
    contracts = load_science_contracts(CONTRACT_DIR)

    verify_geometry_assets(contracts, REPO_ROOT)
    assert contracts.source_semantics["verticalCompatibility"]["status"] == "blocked"
    assert contracts.geography_rules["support"]["status"] == "selected-scope-approximation"
    assert contracts.geography_rules["coastal"]["status"] == "selected-scope-approximation"
    assert contracts.geography_rules["predicate"] == "covers"
    assert contracts.vertical_methodology["decision"] == "accepted"
    assert (
        contracts.vertical_methodology["methodId"]
        == "absolute-mean-water-surface-egm2008-interval-v1"
    )
    assert contracts.terrain_decision["decision"]["selectedInstance"] == "GLO-30"
    assert contracts.terrain_decision["review"]["status"] == "pending-external"
    assert contracts.final_gate["decision"] == "blocked"
    assert contracts.final_gate["phase1"]["unlocked"] is False


def test_vertical_methodology_binds_reference_epoch_and_uncertainty() -> None:
    methodology = load_science_contracts(CONTRACT_DIR).vertical_methodology

    assert methodology["targetReference"] == {
        "surface": "EGM2008 geoid",
        "verticalCrs": "EPSG:3855",
        "units": "m",
        "tideSystem": "tide_free",
    }
    assert methodology["baseline"]["referencePeriod"] == {
        "startInclusive": "1995-01-01",
        "endExclusive": "2015-01-01",
        "aggregation": "duration-weighted mean over complete source intervals",
        "missingIntervals": "nodata",
    }
    assert methodology["baseline"]["sourceProductId"] == "SEALEVEL_EUR_PHY_L4_MY_008_068"
    assert methodology["baseline"]["sourceVariable"] == "sla"
    assert methodology["baseline"]["derivedVariable"] == "adt"
    assert methodology["baseline"]["supportingMdtProductId"] == (
        "SEALEVEL_EUR_PHY_MDT_L4_STATIC_008_070"
    )
    assert methodology["baseline"]["equation"] == (
        "B_EGM2008 = mean_1995_2014(ADT_GOCO06S) + "
        "N_GOCO06S_tide_free - N_EGM2008_tide_free"
    )
    assert methodology["projection"]["quantiles"] == {
        "lower": 0.167,
        "central": 0.5,
        "upper": 0.833,
    }
    assert methodology["uncertainty"]["classification"] == {
        "verticalEligible": "C_low >= 0",
        "exposed": "C_low >= 0 and approved connectivity passes",
        "notExposed": "C_high < 0 or (C_low >= 0 and approved connectivity rejects)",
        "ambiguous": "C_low < 0 and C_high >= 0",
        "ambiguousState": "DataUnavailable",
        "ambiguousReason": "uncertain-threshold",
        "missingConnectivityState": "DataUnavailable",
    }
    assert methodology["physicalScope"]["connectivity"] == (
        "ocean-seeded eight-neighbour candidate selected for external review; "
        "rejected connectivity is NoModeledExposureDetected and unknown "
        "connectivity is DataUnavailable"
    )
    assert methodology["review"]["status"] == "pending"


def test_terrain_decision_fails_closed_on_unbounded_error_terms() -> None:
    terrain = load_science_contracts(CONTRACT_DIR).terrain_decision

    assert terrain["uncertainty"]["systematicError"]["state"] == "not-bounded"
    assert terrain["uncertainty"]["dsmRepresentationBias"]["state"] == "not-bounded"
    assert terrain["uncertainty"]["composition"] == (
        "U_Z=U_random+U_systematic+U_edit+U_DSM+U_resolution; absent terms do not default to zero"
    )
    assert terrain["publicationGate"]["status"] == "blocked"
    assert "systematic-error-bound" in terrain["publicationGate"]["blockingDecisions"]


def test_coastal_uncertainty_budget_recommends_rejecting_binary_publication() -> None:
    budget = load_science_contracts(CONTRACT_DIR).uncertainty_budget
    terms = {term["id"]: term for term in budget["terms"]}

    assert budget["decision"]["authority"] == "automated-methodology-analysis"
    assert budget["decision"]["recommendedDisposition"] == "rejected"
    assert budget["confidenceFramework"]["projectionTreatment"] == (
        "AR6 q0.167/q0.833 remains a separate projection interval"
    )
    assert terms["sla-l4-mapping"]["numeric"]["value"] == pytest.approx(0.0981413)
    assert terms["mdt-formal-mapping"]["numeric"]["equation"].startswith(
        "U_mdt = 1.645 * err_mdt"
    )
    assert terms["dem-absolute-systematic-envelope"]["numeric"]["value"] == 4.0
    assert terms["coastal-sla-representativeness"]["status"] == "unbounded"
    assert terms["dsm-to-bare-earth-representation"]["status"] == "unbounded"
    assert budget["maximumTotalUncertaintyMetres"] is None
    assert budget["review"]["status"] == "pending-independent"
    assert budget["review"]["authoritativeDisposition"] == "pending"
    assert budget["publicationGate"]["status"] == "blocked"
    assert all(
        context["result"] in {
            "DataUnavailable",
            "defensible-only-with-complete-bounds",
        }
        for context in budget["sensitivity"]["contexts"]
    )


CANONICAL_UNCERTAINTY_TERM_IDS = [
    "sla-l4-mapping",
    "mdt-formal-mapping",
    "temporal-weighting",
    "reference-period-completeness",
    "horizontal-interpolation",
    "coastal-sla-representativeness",
    "geoid-evaluator-disagreement",
    "dem-random-error",
    "dem-absolute-systematic-envelope",
    "dem-edit-fill",
    "dsm-to-bare-earth-representation",
    "water-mask",
    "terrain-void",
    "coastline-representation",
    "effective-resolution",
]


def _mutated_contract_dir(tmp_path: Path) -> tuple[Path, dict]:
    for path in CONTRACT_DIR.glob("*.json"):
        shutil.copy2(path, tmp_path / path.name)
    budget_path = tmp_path / "coastal-uncertainty-budget.json"
    return budget_path, json.loads(budget_path.read_text(encoding="utf-8"))


def _write_budget(path: Path, budget: dict) -> None:
    path.write_text(json.dumps(budget), encoding="utf-8")


@pytest.mark.parametrize("claim", ["reviewed-rejection", "publication-rejection"])
def test_pending_review_cannot_claim_authoritative_rejection(
    tmp_path: Path,
    claim: str,
) -> None:
    budget_path, budget = _mutated_contract_dir(tmp_path)
    if claim == "reviewed-rejection":
        budget["review"]["authoritativeDisposition"] = "rejected"
    else:
        budget["publicationGate"]["status"] = "rejected"
    _write_budget(budget_path, budget)

    with pytest.raises(ScienceContractError, match="coastal-uncertainty"):
        load_science_contracts(tmp_path)


@pytest.mark.parametrize("term_id", CANONICAL_UNCERTAINTY_TERM_IDS)
def test_removing_any_canonical_uncertainty_term_fails_contract(
    tmp_path: Path,
    term_id: str,
) -> None:
    budget_path, budget = _mutated_contract_dir(tmp_path)
    budget["terms"] = [term for term in budget["terms"] if term["id"] != term_id]
    _write_budget(budget_path, budget)

    with pytest.raises(ScienceContractError, match="uncertainty budget|coastal-uncertainty"):
        load_science_contracts(tmp_path)


@pytest.mark.parametrize(
    ("term_id", "status", "kind", "value"),
    [
        ("sla-l4-mapping", "bounded-conditionally", "constant", 0.0),
        ("dem-absolute-systematic-envelope", "bounded-conditionally", "constant", float("inf")),
        ("mdt-formal-mapping", "inapplicable", "exact-zero", 0.0),
        ("dem-random-error", "bounded-conditionally", "constant", 1.0),
        ("temporal-weighting", "bounded", "constant", 1.0),
        ("water-mask", "unbounded", "unbounded", None),
        ("coastal-sla-representativeness", "inapplicable", "exact-zero", 0.0),
        ("dsm-to-bare-earth-representation", "bounded", "constant", 1.0),
    ],
)
def test_zeroing_or_weakening_canonical_uncertainty_semantics_fails_contract(
    tmp_path: Path,
    term_id: str,
    status: str,
    kind: str,
    value: float | None,
) -> None:
    budget_path, budget = _mutated_contract_dir(tmp_path)
    term = next(term for term in budget["terms"] if term["id"] == term_id)
    term["status"] = status
    term["numeric"] = {
        "kind": kind,
        "value": value,
        "equation": "mutated uncertainty semantics",
    }
    _write_budget(budget_path, budget)

    with pytest.raises(ScienceContractError, match="uncertainty budget|coastal-uncertainty"):
        load_science_contracts(tmp_path)


@pytest.mark.parametrize(
    "term_id",
    ["sla-l4-mapping", "temporal-weighting", "dsm-to-bare-earth-representation"],
)
def test_unsupported_terms_cannot_be_weakened_across_classes(
    tmp_path: Path,
    term_id: str,
) -> None:
    budget_path, budget = _mutated_contract_dir(tmp_path)
    term = next(term for term in budget["terms"] if term["id"] == term_id)
    term["unsupportedOutcome"] = "not-applicable"
    _write_budget(budget_path, budget)

    with pytest.raises(ScienceContractError, match="must fail closed"):
        load_science_contracts(tmp_path)


@pytest.mark.parametrize(
    ("field", "mutation"),
    [
        ("requiredBoundTermIds", "remove"),
        ("requiredBoundTermIds", "add-inapplicable"),
        ("unboundedTermIds", "remove"),
        ("unboundedTermIds", "add-bounded"),
    ],
)
def test_eligibility_term_sets_are_canonical(
    tmp_path: Path,
    field: str,
    mutation: str,
) -> None:
    budget_path, budget = _mutated_contract_dir(tmp_path)
    term_ids = budget["eligibility"][field]
    if mutation == "remove":
        term_ids.pop()
    elif field == "requiredBoundTermIds":
        term_ids.append("water-mask")
    else:
        term_ids.append("sla-l4-mapping")
    _write_budget(budget_path, budget)

    with pytest.raises(ScienceContractError, match="uncertainty budget"):
        load_science_contracts(tmp_path)


def test_terrain_decision_binds_exact_locked_control_manifests(
    tmp_path: Path,
) -> None:
    contracts = load_science_contracts(CONTRACT_DIR)

    verify_terrain_source_bindings(contracts, SOURCE_LOCK_PATH)

    source_lock = json.loads(SOURCE_LOCK_PATH.read_text(encoding="utf-8"))
    glo30 = next(
        source for source in source_lock["sources"] if source["id"] == "copernicus-dem-glo30"
    )
    glo30["assets"][0]["objectSet"]["manifestSha256"] = "0" * 64
    changed_path = tmp_path / "source-lock.json"
    changed_path.write_text(json.dumps(source_lock), encoding="utf-8")
    with pytest.raises(ScienceContractError, match="manifest identity"):
        verify_terrain_source_bindings(contracts, changed_path)


def test_projection_mapping_is_keyed_by_exact_source_version() -> None:
    contracts = load_science_contracts(CONTRACT_DIR)

    mapping = projection_mapping(contracts, "ipcc-ar6-sea-level", "20210809")

    assert mapping["variable"] == "sea_level_change"
    assert mapping["dimensions"] == ["quantiles", "years", "locations"]
    assert mapping["units"] == "mm"
    assert mapping["unitToMetres"] == 0.001
    assert mapping["statistic"] == {"confidence": "medium", "quantile": 0.5}
    assert mapping["intervalStatistics"] == {
        "confidence": "medium",
        "lowerQuantile": 0.167,
        "centralQuantile": 0.5,
        "upperQuantile": 0.833,
    }


def test_vertical_input_identities_are_locked_without_open_ended_fallbacks() -> None:
    source = load_science_contracts(CONTRACT_DIR).source_semantics

    assert source["projection"]["archive"]["sha256LockStatus"] == "locked"
    assert source["verticalInputs"]["baseline"] == {
        "reconstructionId": "monthly-sla-plus-static-mdt-v202411",
        "slaSourceId": "copernicus-marine-eur-sla-monthly",
        "mdtSourceId": "copernicus-marine-eur-mdt",
        "sourceVersion": "202411",
        "referencePeriod": {
            "startInclusive": "1995-01-01",
            "endExclusive": "2015-01-01",
        },
        "monthlyObjectCount": 240,
        "calendarDayWeight": 7305,
        "slaVariable": "sla",
        "mdtVariable": "mdt",
        "mdtErrorVariable": "err_mdt",
        "equation": ("mean_1995_2014(ADT_GOCO06S) = day_weighted_mean(monthly_SLA) + MDT_GOCO06S"),
        "missingPeriodRule": "nodata",
    }
    assert source["verticalInputs"]["sourceGeoid"]["nativeTideSystem"] == "zero_tide"
    assert source["verticalInputs"]["targetGeoid"]["nativeTideSystem"] == "tide_free"


@pytest.mark.parametrize(
    ("source_id", "version"),
    [
        ("ipcc-ar6-sea-level", "latest"),
        ("other-source", "20210809"),
    ],
)
def test_unknown_projection_mapping_fails_closed(source_id: str, version: str) -> None:
    contracts = load_science_contracts(CONTRACT_DIR)

    with pytest.raises(ScienceContractError, match="No projection mapping"):
        projection_mapping(contracts, source_id, version)


def test_unexpected_contract_property_fails_closed(tmp_path: Path) -> None:
    for path in CONTRACT_DIR.glob("*.json"):
        (tmp_path / path.name).write_bytes(path.read_bytes())
    document_path = tmp_path / "source-semantics.json"
    document = json.loads(document_path.read_text(encoding="utf-8"))
    document["projection"]["mapping"]["guessedFallback"] = True
    document_path.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(ScienceContractError, match="guessedFallback"):
        load_science_contracts(tmp_path)


def test_publication_gate_reports_every_visible_blocker() -> None:
    contracts = load_science_contracts(CONTRACT_DIR)

    with pytest.raises(ScienceContractError) as exc_info:
        assert_publication_ready(contracts)

    message = str(exc_info.value)
    assert "vertical-datum-reconciliation" in message
    assert "vertical-methodology-review" in message
    assert "product-owner-geography-approval" in message
    assert "independent-connectivity-review" in message
    assert "systematic-error-bound" in message
    assert "egm2008-evaluator-conventions" in message
    assert "dsm-representation-bias-bound" in message
