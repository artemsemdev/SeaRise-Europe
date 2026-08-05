"""Exercise the complete candidate builder with pinned external tools."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sys
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

REPO_ROOT = Path(__file__).parents[4]


def _load_release_cli():
    script_path = REPO_ROOT / "scripts/science/build_ar6_regional_release.py"
    spec = importlib.util.spec_from_file_location("searise_ar6_release_cli", script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load release CLI from {script_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


release_cli = _load_release_cli()


def _source():
    receipt = json.loads((FIXTURE_DIR / "source-fixture-receipt.json").read_text(encoding="utf-8"))
    return load_source_fixture(
        FIXTURE_DIR / "source-fixture.json.gz",
        receipt=receipt,
        release_contract=contract(),
    )


def _tool_paths() -> dict[str, Path | str]:
    return {
        "tippecanoe_path": Path(os.environ["SEARISE_TIPPECANOE"]),
        "decode_path": Path(os.environ["SEARISE_TIPPECANOE_DECODE"]),
        "pmtiles_path": Path(os.environ["SEARISE_PMTILES"]),
        "tippecanoe_source_archive_path": Path(
            os.environ["SEARISE_TIPPECANOE_SOURCE"]
        ),
        "tippecanoe_build_receipt_path": Path(
            os.environ["SEARISE_TIPPECANOE_BUILD_RECEIPT"]
        ),
        "pmtiles_distribution_asset_path": Path(
            os.environ["SEARISE_PMTILES_ASSET"]
        ),
        "pmtiles_distribution_platform": os.environ["SEARISE_VECTOR_PLATFORM"],
        "python_lock_path": Path(os.environ["SEARISE_PYTHON_LOCK"]),
    }


def _missing_tool_paths() -> dict[str, Path | str]:
    missing = Path("missing")
    return {
        "tippecanoe_path": missing,
        "decode_path": missing,
        "pmtiles_path": missing,
        "tippecanoe_source_archive_path": missing,
        "tippecanoe_build_receipt_path": missing,
        "pmtiles_distribution_asset_path": missing,
        "pmtiles_distribution_platform": "darwin-arm64",
        "python_lock_path": missing,
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
            **_missing_tool_paths(),
        )


def test_builder_rejects_source_mutation_before_artifact_generation(
    tmp_path: Path,
) -> None:
    source = _source()
    layer = source.layers[0]
    layer.central_mm.flags.writeable = True
    layer.central_mm[0, 0] = layer.central_mm[0, 0] + 1

    with pytest.raises(ScienceContractError, match="changed after verification"):
        build_regional_release(
            source,
            tmp_path / "candidate",
            release_id="ar6-europe-fixture-v1",
            contract=contract(),
            lookup_goldens_path=GOLDENS_PATH,
            **_missing_tool_paths(),
        )

    assert not (tmp_path / "candidate").exists()


def test_builder_rejects_unbound_python_environment_before_vector_tools(
    tmp_path: Path,
) -> None:
    output = tmp_path / "candidate"

    with pytest.raises(ScienceContractError, match="release lock differs"):
        build_regional_release(
            _source(),
            output,
            release_id="ar6-europe-fixture-v1",
            contract=contract(),
            lookup_goldens_path=GOLDENS_PATH,
            **_missing_tool_paths(),
        )

    assert not output.exists()


def test_cli_wires_required_vector_trust_inputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    missing = tmp_path / "missing"
    output = tmp_path / "candidate"
    failure = tmp_path / "failure.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "build_ar6_regional_release.py",
            "--fixture",
            str(FIXTURE_DIR / "source-fixture.json.gz"),
            "--fixture-receipt",
            str(FIXTURE_DIR / "source-fixture-receipt.json"),
            "--source-lock",
            str(REPO_ROOT / "src/pipeline/sources/source-lock.json"),
            "--source-semantics",
            str(REPO_ROOT / "src/pipeline/science/source-semantics.json"),
            "--release-contract",
            str(REPO_ROOT / "src/pipeline/science/ar6-regional-release.json"),
            "--lookup-goldens",
            str(GOLDENS_PATH),
            "--tippecanoe",
            str(missing),
            "--tippecanoe-decode",
            str(missing),
            "--pmtiles",
            str(missing),
            "--tippecanoe-source-archive",
            str(missing),
            "--tippecanoe-build-receipt",
            str(missing),
            "--pmtiles-distribution-asset",
            str(missing),
            "--pmtiles-distribution-platform",
            "darwin-arm64",
            "--python-lock",
            str(REPO_ROOT / "src/pipeline/requirements-release-macos-arm64.lock"),
            "--release-id",
            "ar6-europe-fixture-v1",
            "--output",
            str(output),
            "--failure-gate",
            str(failure),
        ],
    )

    with pytest.raises(SystemExit):
        release_cli.main()

    blocked = json.loads(failure.read_text(encoding="utf-8"))
    assert blocked["failure"]["type"] == "ScienceContractError"
    assert not output.exists()
