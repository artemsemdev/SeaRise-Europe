"""Characterize the regional lookup without making scientific assertions."""

from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path

import pytest

from searise_pipeline.regional_fixture.lookup import (
    DomainState,
    FixtureContractError,
    RegionalFixture,
)


def _encoded(values: bytes) -> dict[str, str]:
    return {
        "encoding": "base64-uint8-row-major",
        "data": base64.b64encode(values).decode("ascii"),
        "sha256": hashlib.sha256(values).hexdigest(),
    }


def _write_fixture(path: Path, *, blocked: bool = False) -> None:
    layer = (
        {"status": "blocked", "blockedBy": ["vertical-datum-reconciliation"]}
        if blocked
        else {"status": "ready", "values": _encoded(bytes([1, 0, 0, 255, 0, 0]))}
    )
    path.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "fixtureId": "contract-test-only",
                "grid": {
                    "width": 3,
                    "height": 2,
                    "west": 4.0,
                    "south": 52.0,
                    "east": 5.0,
                    "north": 53.0,
                    "longitude_convention": "minus-180-to-180",
                    "edge_rule": "west-north-inclusive-east-south-exclusive",
                },
                "supportMask": _encoded(bytes([1, 1, 1, 1, 1, 0])),
                "coastalMask": _encoded(bytes([1, 1, 0, 1, 1, 0])),
                "layers": {"ssp2-45/2050": layer},
            }
        ),
        encoding="utf-8",
    )


def test_lookup_distinguishes_all_five_domain_states(tmp_path: Path) -> None:
    path = tmp_path / "fixture.json"
    _write_fixture(path)
    fixture = RegionalFixture.load(path)

    assert fixture.lookup(4.1, 52.9, "ssp2-45", 2050).state == (
        DomainState.MODELED_EXPOSURE_DETECTED
    )
    assert fixture.lookup(4.4, 52.9, "ssp2-45", 2050).state == (
        DomainState.NO_MODELED_EXPOSURE_DETECTED
    )
    assert fixture.lookup(4.1, 52.4, "ssp2-45", 2050).state == DomainState.DATA_UNAVAILABLE
    assert fixture.lookup(4.8, 52.9, "ssp2-45", 2050).state == DomainState.OUT_OF_SCOPE
    assert fixture.lookup(4.8, 52.4, "ssp2-45", 2050).state == (
        DomainState.UNSUPPORTED_GEOGRAPHY
    )
    assert fixture.lookup(3.9, 52.9, "ssp2-45", 2050).state == (
        DomainState.UNSUPPORTED_GEOGRAPHY
    )
    assert fixture.lookup(4.1, 52.9, "ssp1-26", 2030).state == DomainState.DATA_UNAVAILABLE


def test_lookup_maps_half_open_grid_edges_explicitly(tmp_path: Path) -> None:
    path = tmp_path / "fixture.json"
    _write_fixture(path)
    fixture = RegionalFixture.load(path)

    assert fixture.lookup(4.0, 53.0, "ssp2-45", 2050).cell == (fixture.grid.cell(4.0, 53.0))
    assert fixture.grid.cell(4.0, 53.0) is not None
    assert fixture.grid.cell(4.0, 53.0).row == 0
    assert fixture.grid.cell(4.0, 53.0).column == 0
    assert fixture.grid.cell(5.0, 53.0) is None
    assert fixture.grid.cell(4.0, 52.0) is None


def test_blocked_layer_fails_closed_to_data_unavailable(tmp_path: Path) -> None:
    path = tmp_path / "fixture.json"
    _write_fixture(path, blocked=True)
    fixture = RegionalFixture.load(path)

    result = fixture.lookup(4.1, 52.9, "ssp2-45", 2050)
    assert result.state == DomainState.DATA_UNAVAILABLE


def test_rejects_tampered_array_checksum(tmp_path: Path) -> None:
    path = tmp_path / "fixture.json"
    _write_fixture(path)
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["coastalMask"]["sha256"] = "0" * 64
    path.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(FixtureContractError, match="SHA-256 mismatch"):
        RegionalFixture.load(path)


def test_rejects_coastal_cells_outside_support(tmp_path: Path) -> None:
    path = tmp_path / "fixture.json"
    _write_fixture(path)
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["coastalMask"] = _encoded(bytes([1, 1, 0, 1, 1, 1]))
    path.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(FixtureContractError, match="subset"):
        RegionalFixture.load(path)


def test_rejects_longitude_outside_declared_convention(tmp_path: Path) -> None:
    path = tmp_path / "fixture.json"
    _write_fixture(path)
    fixture = RegionalFixture.load(path)

    with pytest.raises(FixtureContractError, match="longitude"):
        fixture.lookup(364.1, 52.9, "ssp2-45", 2050)
