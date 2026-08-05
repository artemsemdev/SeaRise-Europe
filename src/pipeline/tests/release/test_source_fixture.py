"""Test deterministic source fixtures against independent AR6 goldens."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pytest

from searise_pipeline.release import (
    RegionalLayer,
    RegionalReleaseSource,
    load_release_contract,
    load_source_fixture,
    write_source_fixture,
)
from searise_pipeline.science import ScienceContractError

REPO_ROOT = Path(__file__).parents[4]
CONTRACT_PATH = REPO_ROOT / "src/pipeline/science/ar6-regional-release.json"
SOURCE_LOCK_PATH = REPO_ROOT / "src/pipeline/sources/source-lock.json"
FIXTURE_DIR = REPO_ROOT / "src/pipeline/fixtures/ar6-regional-release"
GOLDENS_PATH = REPO_ROOT / "src/pipeline/science/evidence/ar6-lookup-goldens.json"


def contract() -> dict[str, object]:
    return dict(load_release_contract(CONTRACT_PATH))


def synthetic_source() -> RegionalReleaseSource:
    release_contract = contract()
    source_lock = json.loads(SOURCE_LOCK_PATH.read_text(encoding="utf-8"))
    archive = next(
        asset
        for source in source_lock["sources"]
        if source["id"] == "ipcc-ar6-sea-level"
        for asset in source["assets"]
        if asset["id"] == "regional-confidence-archive"
    )
    hashes = {
        {"ssp126": "ssp1-26", "ssp245": "ssp2-45", "ssp585": "ssp5-85"}[member["scenario"]]: member[
            "sha256"
        ]
        for member in archive["members"]
    }
    shape = (
        release_contract["grid"]["height"],
        release_contract["grid"]["width"],
    )
    location_ids = np.arange(np.prod(shape), dtype=np.int64).reshape(shape) + 1000000000
    layers = []
    for scenario_index, scenario in enumerate(release_contract["matrix"]["scenarios"]):
        for horizon in release_contract["matrix"]["horizons"]:
            central = np.full(shape, 100 + scenario_index * 10 + horizon - 2030, dtype=np.int16)
            lower = central - 10
            upper = central + 10
            lower[0, 0] = central[0, 0] = upper[0, 0] = -32768
            layers.append(
                RegionalLayer(
                    scenario=scenario,
                    horizon=horizon,
                    member_sha256=hashes[scenario],
                    lower_mm=lower,
                    central_mm=central,
                    upper_mm=upper,
                )
            )
    return RegionalReleaseSource(
        source_mode="verified-archive",
        archive_sha256=release_contract["source"]["archiveSha256"],
        contract_sha256=hashlib.sha256(CONTRACT_PATH.read_bytes()).hexdigest(),
        latitudes=np.arange(30, 76, dtype=np.float64),
        longitudes=np.arange(-30, 46, dtype=np.float64),
        location_ids=location_ids,
        layers=tuple(layers),
    )


def test_offline_source_fixture_is_byte_deterministic_and_verified(tmp_path: Path) -> None:
    source = synthetic_source()
    first = tmp_path / "first.json.gz"
    second = tmp_path / "second.json.gz"

    receipt = write_source_fixture(source, first)
    second_receipt = write_source_fixture(source, second)
    restored = load_source_fixture(first, receipt=receipt, release_contract=contract())

    assert first.read_bytes() == second.read_bytes()
    assert receipt == second_receipt
    assert restored.source_mode == "offline-real-source-fixture"
    assert restored.archive_sha256 == source.archive_sha256
    assert np.array_equal(restored.location_ids, source.location_ids)
    for expected, actual in zip(source.layers, restored.layers):
        assert (actual.scenario, actual.horizon, actual.member_sha256) == (
            expected.scenario,
            expected.horizon,
            expected.member_sha256,
        )
        assert np.array_equal(actual.lower_mm, expected.lower_mm)
        assert np.array_equal(actual.central_mm, expected.central_mm)
        assert np.array_equal(actual.upper_mm, expected.upper_mm)


def test_offline_source_fixture_fails_closed_on_tamper(tmp_path: Path) -> None:
    path = tmp_path / "fixture.json.gz"
    receipt = write_source_fixture(synthetic_source(), path)
    path.write_bytes(path.read_bytes()[:-1] + b"x")

    with pytest.raises(ScienceContractError, match="integrity mismatch"):
        load_source_fixture(path, receipt=receipt, release_contract=contract())


def test_checked_in_fixture_matches_independent_ar6_goldens() -> None:
    receipt = json.loads((FIXTURE_DIR / "source-fixture-receipt.json").read_text(encoding="utf-8"))
    source = load_source_fixture(
        FIXTURE_DIR / "source-fixture.json.gz",
        receipt=receipt,
        release_contract=contract(),
    )
    goldens = json.loads(GOLDENS_PATH.read_text(encoding="utf-8"))
    layers = {(layer.scenario, layer.horizon): layer for layer in source.layers}

    assert [int(layer.valid.sum()) for layer in source.layers] == [
        3055,
        3055,
        3055,
        3054,
        3054,
        3054,
        3054,
        3054,
        3054,
    ]
    for result in goldens["results"]:
        if result["state"] != "ProjectionAvailable":
            continue
        positions = np.argwhere(source.location_ids == result["source"]["locationId"])
        assert positions.shape == (1, 2)
        row, column = positions[0]
        for projection in result["projections"]:
            layer = layers[(projection["scenario"], projection["horizon"])]
            assert (
                int(layer.lower_mm[row, column]),
                int(layer.central_mm[row, column]),
                int(layer.upper_mm[row, column]),
            ) == (
                projection["lowerMillimetres"],
                projection["centralMillimetres"],
                projection["upperMillimetres"],
            )
