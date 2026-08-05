"""Test fail-closed pins and optional real PMTiles integration."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from searise_pipeline.release import (
    load_source_fixture,
    validate_vector_toolchain,
    write_visual_pmtiles,
)
from searise_pipeline.science import ScienceContractError

from .test_source_fixture import FIXTURE_DIR, contract


def _real_source():
    receipt = json.loads((FIXTURE_DIR / "source-fixture-receipt.json").read_text(encoding="utf-8"))
    return load_source_fixture(
        FIXTURE_DIR / "source-fixture.json.gz",
        receipt=receipt,
        release_contract=contract(),
    )


def test_vector_toolchain_fails_closed_when_binary_is_absent(tmp_path: Path) -> None:
    missing = tmp_path / "absent"

    with pytest.raises(ScienceContractError, match="executable is absent"):
        validate_vector_toolchain(
            tippecanoe_path=missing,
            decode_path=missing,
            pmtiles_path=missing,
            contract=contract(),
        )


@pytest.mark.skipif(
    not all(
        os.environ.get(name)
        for name in ("SEARISE_TIPPECANOE", "SEARISE_TIPPECANOE_DECODE", "SEARISE_PMTILES")
    ),
    reason="set the three pinned vector-tool paths for the external integration",
)
def test_visual_pmtiles_is_byte_deterministic_and_property_exact(tmp_path: Path) -> None:
    source = _real_source()
    layer = next(
        item for item in source.layers if item.scenario == "ssp2-45" and item.horizon == 2050
    )
    first = tmp_path / "first.pmtiles"
    second = tmp_path / "second.pmtiles"
    tools = {
        "tippecanoe_path": Path(os.environ["SEARISE_TIPPECANOE"]),
        "decode_path": Path(os.environ["SEARISE_TIPPECANOE_DECODE"]),
        "pmtiles_path": Path(os.environ["SEARISE_PMTILES"]),
    }

    first_evidence = write_visual_pmtiles(source, layer, first, contract=contract(), **tools)
    second_evidence = write_visual_pmtiles(source, layer, second, contract=contract(), **tools)

    assert first.read_bytes() == second.read_bytes()
    assert first_evidence.sha256 == second_evidence.sha256
    assert first_evidence.source_feature_count == 3054
    assert first_evidence.decoded_fragment_count >= first_evidence.source_feature_count
    assert first_evidence.byte_size <= contract()["budgets"]["pmtilesTotalBytes"] / 9
