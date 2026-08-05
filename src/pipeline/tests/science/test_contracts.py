"""Characterize the fail-closed Phase 0.2 scientific contracts."""

from __future__ import annotations

import json
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
