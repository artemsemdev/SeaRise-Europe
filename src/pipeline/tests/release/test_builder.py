"""Exercise the complete candidate builder with pinned external tools."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest

from searise_pipeline.release import (
    build_regional_release,
    compare_release_candidates,
    load_source_fixture,
)
from searise_pipeline.science import ScienceContractError

from .test_recovery_gate import DELIVERY, REPRODUCIBILITY
from .test_source_fixture import FIXTURE_DIR, GOLDENS_PATH, contract


def _source():
    receipt = json.loads((FIXTURE_DIR / "source-fixture-receipt.json").read_text(encoding="utf-8"))
    return load_source_fixture(
        FIXTURE_DIR / "source-fixture.json.gz",
        receipt=receipt,
        release_contract=contract(),
    )


def _tool_paths() -> dict[str, Path]:
    return {
        "tippecanoe_path": Path(os.environ["SEARISE_TIPPECANOE"]),
        "decode_path": Path(os.environ["SEARISE_TIPPECANOE_DECODE"]),
        "pmtiles_path": Path(os.environ["SEARISE_PMTILES"]),
    }


EXTERNAL_TOOLS_AVAILABLE = all(
    os.environ.get(name)
    for name in ("SEARISE_TIPPECANOE", "SEARISE_TIPPECANOE_DECODE", "SEARISE_PMTILES")
)


@pytest.mark.skipif(
    not EXTERNAL_TOOLS_AVAILABLE,
    reason="set the three pinned vector-tool paths for the complete release integration",
)
def test_complete_fixture_release_is_deterministic_but_cannot_approve_source(
    tmp_path: Path,
) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    source = _source()

    first_result = build_regional_release(
        source,
        first,
        release_id="ar6-europe-fixture-v1",
        contract=contract(),
        lookup_goldens_path=GOLDENS_PATH,
        reproducibility_report=REPRODUCIBILITY,
        delivery_report=DELIVERY,
        owner_decision="approved",
        **_tool_paths(),
    )
    second_result = build_regional_release(
        source,
        second,
        release_id="ar6-europe-fixture-v1",
        contract=contract(),
        lookup_goldens_path=GOLDENS_PATH,
        reproducibility_report=REPRODUCIBILITY,
        delivery_report=DELIVERY,
        owner_decision="approved",
        **_tool_paths(),
    )
    comparison = compare_release_candidates(
        first,
        second,
        first_environment="isolated-build-a",
        second_environment="isolated-build-b",
        contract=contract(),
    )

    assert len(list(first.glob("analysis/*/*.tif"))) == 9
    assert len(list(first.glob("layers/*/*.pmtiles"))) == 9
    assert (first / "analysis/projections.parquet").is_file()
    assert len(first_result.manifest["artifacts"]) == 19
    assert first_result.manifest == second_result.manifest
    assert comparison["status"] == "passed"
    assert comparison["comparedArtifactCount"] == 19
    assert first_result.gate["disposition"] == "blocked"
    assert first_result.gate["blockingChecks"] == ["sourceArchiveAndMembersVerified"]
    assert first_result.gate["phase1Unlocked"] is False

    for line in (first / "checksums.txt").read_text(encoding="utf-8").splitlines():
        expected, relative_path = line.split("  ", 1)
        actual = hashlib.sha256((first / relative_path).read_bytes()).hexdigest()
        assert actual == expected


def test_builder_refuses_to_overwrite_immutable_release(tmp_path: Path) -> None:
    output = tmp_path / "existing"
    output.mkdir()

    with pytest.raises(ScienceContractError, match="already exists"):
        build_regional_release(
            _source(),
            output,
            release_id="ar6-europe-fixture-v1",
            contract=contract(),
            lookup_goldens_path=GOLDENS_PATH,
            tippecanoe_path=Path("missing"),
            decode_path=Path("missing"),
            pmtiles_path=Path("missing"),
        )
