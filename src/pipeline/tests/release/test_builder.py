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
        "tippecanoe_source_archive_path": Path(os.environ["SEARISE_TIPPECANOE_SOURCE"]),
        "tippecanoe_build_receipt_path": Path(
            os.environ["SEARISE_TIPPECANOE_BUILD_RECEIPT"]
        ),
        "pmtiles_distribution_asset_path": Path(os.environ["SEARISE_PMTILES_ASSET"]),
        "pmtiles_distribution_platform": os.environ["SEARISE_VECTOR_PLATFORM"],
        "python_lock_path": Path(os.environ["SEARISE_PYTHON_LOCK"]),
    }


EXTERNAL_TOOLS_AVAILABLE = all(
    os.environ.get(name)
    for name in (
        "SEARISE_TIPPECANOE",
        "SEARISE_TIPPECANOE_DECODE",
        "SEARISE_PMTILES",
        "SEARISE_TIPPECANOE_SOURCE",
        "SEARISE_TIPPECANOE_BUILD_RECEIPT",
        "SEARISE_PMTILES_ASSET",
        "SEARISE_VECTOR_PLATFORM",
        "SEARISE_PYTHON_LOCK",
    )
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
        build_environment_id="isolated-build-a",
        source_revision="a" * 40,
        **_tool_paths(),
    )
    second_result = build_regional_release(
        source,
        second,
        release_id="ar6-europe-fixture-v1",
        contract=contract(),
        lookup_goldens_path=GOLDENS_PATH,
        build_environment_id="isolated-build-b",
        source_revision="a" * 40,
        **_tool_paths(),
    )
    assert len(list(first.glob("analysis/*/*.tif"))) == 9
    assert len(list(first.glob("layers/*/*.pmtiles"))) == 9
    assert (first / "analysis/projections.parquet").is_file()
    assert len(first_result.manifest["artifacts"]) == 31
    assert first_result.manifest == second_result.manifest
    with pytest.raises(ScienceContractError, match="genuinely independent"):
        compare_release_candidates(first, second, contract=contract())
    assert first_result.gate["automatedValidation"] == "failed"
    assert first_result.gate["releaseDisposition"] == "blocked"
    assert first_result.gate["blockers"] == [
        "sourceArchiveAndMembersVerified",
        "crossEnvironmentReproducibility",
        "deliveryMeasurements",
        "projectOwnerReleaseDecision",
        "finalIntegrationMergedToMaster",
    ]
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
            tippecanoe_source_archive_path=Path("missing"),
            tippecanoe_build_receipt_path=Path("missing"),
            pmtiles_distribution_asset_path=Path("missing"),
            pmtiles_distribution_platform="darwin-arm64",
            python_lock_path=Path("missing"),
            build_environment_id="test-existing-path",
            source_revision="a" * 40,
        )


def test_builder_rejects_post_verification_array_mutation_before_tools(
    tmp_path: Path,
) -> None:
    source = _source()
    layer = source.layers[0]
    layer.central_mm.flags.writeable = True
    layer.central_mm[0, 0] = layer.central_mm[0, 0] + 1
    output = tmp_path / "candidate"

    with pytest.raises(ScienceContractError, match="changed after verification"):
        build_regional_release(
            source,
            output,
            release_id="ar6-europe-fixture-v1",
            contract=contract(),
            lookup_goldens_path=GOLDENS_PATH,
            tippecanoe_path=Path("missing"),
            decode_path=Path("missing"),
            pmtiles_path=Path("missing"),
            tippecanoe_source_archive_path=Path("missing"),
            tippecanoe_build_receipt_path=Path("missing"),
            pmtiles_distribution_asset_path=Path("missing"),
            pmtiles_distribution_platform="darwin-arm64",
            python_lock_path=Path("missing"),
            build_environment_id="test-mutated-source",
            source_revision="a" * 40,
        )

    assert not output.exists()


@pytest.mark.parametrize("release_id", ["../escape", "/absolute", "UPPER", "name/child"])
def test_builder_rejects_unsafe_release_ids(tmp_path: Path, release_id: str) -> None:
    with pytest.raises(ScienceContractError, match="Release ID"):
        build_regional_release(
            _source(),
            tmp_path / "candidate",
            release_id=release_id,
            contract=contract(),
            lookup_goldens_path=GOLDENS_PATH,
            tippecanoe_path=Path("missing"),
            decode_path=Path("missing"),
            pmtiles_path=Path("missing"),
            tippecanoe_source_archive_path=Path("missing"),
            tippecanoe_build_receipt_path=Path("missing"),
            pmtiles_distribution_asset_path=Path("missing"),
            pmtiles_distribution_platform="darwin-arm64",
            python_lock_path=Path("missing"),
            build_environment_id="test-unsafe-id",
            source_revision="a" * 40,
        )
