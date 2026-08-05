"""Test deterministic source fixtures against independent AR6 goldens."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from searise_pipeline.release import (
    load_release_contract,
    load_source_fixture,
    write_source_fixture,
)
from searise_pipeline.release.model import assert_source_integrity
from searise_pipeline.science import ScienceContractError

REPO_ROOT = Path(__file__).parents[4]
CONTRACT_PATH = REPO_ROOT / "src/pipeline/science/ar6-regional-release.json"
FIXTURE_DIR = REPO_ROOT / "src/pipeline/fixtures/ar6-regional-release"
GOLDENS_PATH = REPO_ROOT / "src/pipeline/science/evidence/ar6-lookup-goldens.json"


def contract() -> dict[str, object]:
    return dict(load_release_contract(CONTRACT_PATH))


def fixture_source():
    receipt = json.loads(
        (FIXTURE_DIR / "source-fixture-receipt.json").read_text(encoding="utf-8")
    )
    return load_source_fixture(
        FIXTURE_DIR / "source-fixture.json.gz",
        receipt=receipt,
        release_contract=contract(),
    )


def test_offline_source_fixture_is_byte_deterministic_and_verified(tmp_path: Path) -> None:
    source = fixture_source()
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
    receipt = write_source_fixture(fixture_source(), path)
    path.write_bytes(path.read_bytes()[:-1] + b"x")

    with pytest.raises(ScienceContractError, match="integrity mismatch"):
        load_source_fixture(path, receipt=receipt, release_contract=contract())


def test_checked_in_fixture_matches_independent_ar6_goldens() -> None:
    source = fixture_source()
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


def test_source_content_seal_rejects_post_verification_array_mutation() -> None:
    source = fixture_source()
    layer = source.layers[0]
    layer.central_mm.flags.writeable = True
    layer.central_mm[0, 0] = layer.central_mm[0, 0] + 1

    with pytest.raises(ScienceContractError, match="changed after verification"):
        assert_source_integrity(source, contract(), require_verified_archive=False)


def test_fixture_writer_rejects_post_verification_array_mutation(
    tmp_path: Path,
) -> None:
    source = fixture_source()
    layer = source.layers[0]
    layer.central_mm.flags.writeable = True
    layer.central_mm[0, 0] = layer.central_mm[0, 0] + 1
    output = tmp_path / "mutated.json.gz"

    with pytest.raises(ScienceContractError, match="changed after verification"):
        write_source_fixture(source, output)

    assert not output.exists()
