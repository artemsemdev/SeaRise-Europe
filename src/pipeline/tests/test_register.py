"""Tests for pipeline.register — seed data constants and layer registration logic."""

from pipeline.register import (
    _GEOGRAPHY_BOUNDARIES,
    _HORIZONS,
    _METHODOLOGY_V1,
    _SCENARIOS,
)


def test_scenarios_match_adr016():
    """Seed data should include exactly the 3 ADR-016 scenarios."""
    ids = [s[0] for s in _SCENARIOS]
    assert ids == ["ssp1-26", "ssp2-45", "ssp5-85"]


def test_ssp245_is_default():
    """ssp2-45 should be marked as default per ADR-017."""
    for sid, _, _, _, is_default in _SCENARIOS:
        if sid == "ssp2-45":
            assert is_default is True
            return
    pytest.fail("ssp2-45 not found in _SCENARIOS")


def test_horizons_match_fr015():
    """Seed data should include horizons 2030, 2050, 2100."""
    years = [h[0] for h in _HORIZONS]
    assert years == [2030, 2050, 2100]


def test_horizon_2050_is_default():
    """2050 should be marked as default per ADR-017."""
    for year, _, is_default, _ in _HORIZONS:
        if year == 2050:
            assert is_default is True
            return
    pytest.fail("2050 not found in _HORIZONS")


def test_methodology_v1_version():
    """Methodology v1.0 should be the initial version."""
    assert _METHODOLOGY_V1["version"] == "v1.0"


def test_methodology_v1_has_five_limitations():
    """Methodology v1.0 should list 5 known limitations."""
    import json
    limitations = json.loads(_METHODOLOGY_V1["limitations"])
    assert len(limitations) == 5


def test_geography_boundaries_has_required_entries():
    """geography_boundaries should have europe and coastal_analysis_zone."""
    names = [b["name"] for b in _GEOGRAPHY_BOUNDARIES]
    assert "europe" in names
    assert "coastal_analysis_zone" in names


import pytest
