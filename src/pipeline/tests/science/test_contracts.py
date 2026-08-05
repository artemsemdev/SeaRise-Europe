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
)

REPO_ROOT = Path(__file__).parents[4]
CONTRACT_DIR = REPO_ROOT / "src" / "pipeline" / "science"


def test_contracts_validate_and_geometry_bytes_match() -> None:
    contracts = load_science_contracts(CONTRACT_DIR)

    verify_geometry_assets(contracts, REPO_ROOT)
    assert contracts.source_semantics["verticalCompatibility"]["status"] == "blocked"
    assert contracts.geography_rules["support"]["status"] == "approximation"
    assert contracts.geography_rules["coastal"]["status"] == "approximation"
    assert contracts.geography_rules["predicate"] == "covers"
    assert contracts.vertical_methodology["decision"] == "accepted"
    assert (
        contracts.vertical_methodology["methodId"]
        == "absolute-mean-water-surface-egm2008-interval-v1"
    )


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
    assert methodology["projection"]["quantiles"] == {
        "lower": 0.17,
        "central": 0.5,
        "upper": 0.83,
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
    assert methodology["review"]["status"] == "pending"


def test_projection_mapping_is_keyed_by_exact_source_version() -> None:
    contracts = load_science_contracts(CONTRACT_DIR)

    mapping = projection_mapping(contracts, "ipcc-ar6-sea-level", "20210809")

    assert mapping["variable"] == "sea_level_change"
    assert mapping["dimensions"] == ["quantiles", "years", "locations"]
    assert mapping["units"] == "mm"
    assert mapping["unitToMetres"] == 0.001
    assert mapping["statistic"] == {"confidence": "medium", "quantile": 0.5}


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
    assert "supported-geography-approval" in message
    assert "canonical-coastal-source" in message
