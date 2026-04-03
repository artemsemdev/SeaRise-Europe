"""Tests for pipeline.config — constants and env helpers."""

import os

import pytest

from pipeline.config import (
    EUROPE_BBOX,
    HORIZONS,
    LEGEND_COLORMAP,
    SCENARIOS,
    get_env,
)


def test_europe_bbox_is_valid_wgs84():
    lon_min, lat_min, lon_max, lat_max = EUROPE_BBOX
    assert -180 <= lon_min < lon_max <= 180
    assert -90 <= lat_min < lat_max <= 90


def test_scenarios_match_adr016():
    assert SCENARIOS == ["ssp1-26", "ssp2-45", "ssp5-85"]


def test_horizons_match_fr015():
    assert HORIZONS == [2030, 2050, 2100]


def test_legend_colormap_has_exposure_stop():
    stops = LEGEND_COLORMAP["colorStops"]
    assert len(stops) == 1
    assert stops[0]["value"] == 1
    assert stops[0]["color"] == "#E85D04"


def test_get_env_returns_value(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("TEST_VAR_ABC", "hello")
    assert get_env("TEST_VAR_ABC") == "hello"


def test_get_env_returns_default():
    assert get_env("NONEXISTENT_VAR_XYZ", "fallback") == "fallback"


def test_get_env_raises_when_missing():
    with pytest.raises(EnvironmentError):
        get_env("NONEXISTENT_VAR_XYZ")
