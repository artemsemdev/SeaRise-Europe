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
from searise_pipeline.release.builder import _validate_stac, _write_stac
from searise_pipeline.science import ScienceContractError

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


def _write_json(path: Path, document: object) -> None:
    path.write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _stac_candidate(root: Path) -> list[dict[str, object]]:
    artifacts: list[dict[str, object]] = []

    def add_artifact(
        relative: str,
        *,
        media_type: str,
        role: str,
        member_sha256: str | None = None,
    ) -> None:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((relative + "\n").encode())
        record: dict[str, object] = {
            "path": relative,
            "mediaType": media_type,
            "role": role,
            "byteSize": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
        if member_sha256 is not None:
            record["source"] = {"memberSha256": member_sha256}
        artifacts.append(record)

    release = contract()
    for scenario in release["matrix"]["scenarios"]:
        member_sha256 = hashlib.sha256(scenario.encode()).hexdigest()
        for horizon in release["matrix"]["horizons"]:
            add_artifact(
                f"analysis/{scenario}/{horizon}.tif",
                media_type=(
                    "image/tiff; application=geotiff; profile=cloud-optimized"
                ),
                role="exact-browser-lookup",
                member_sha256=member_sha256,
            )
            add_artifact(
                f"layers/{scenario}/{horizon}.pmtiles",
                media_type="application/vnd.pmtiles",
                role="visual-only",
            )
    add_artifact(
        "analysis/projections.parquet",
        media_type="application/vnd.apache.parquet",
        role="analytical-parity",
    )
    add_artifact(
        "analysis/source-grid.json.gz",
        media_type="application/gzip",
        role="source-grid-identity",
    )
    _write_stac(
        root,
        artifacts,
        release_id="ar6-europe-fixture-v1",
        contract=release,
    )
    return artifacts


def _first_stac_item(root: Path) -> tuple[Path, dict[str, object]]:
    release = contract()
    scenario = release["matrix"]["scenarios"][0]
    horizon = release["matrix"]["horizons"][0]
    path = root / f"stac/items/{scenario}-{horizon}.json"
    return path, json.loads(path.read_text(encoding="utf-8"))


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


@pytest.mark.parametrize("mutation", ["empty", "missing", "extra", "swapped"])
def test_stac_validator_rejects_mutated_asset_inventory(
    tmp_path: Path,
    mutation: str,
) -> None:
    artifacts = _stac_candidate(tmp_path)
    item_path, item = _first_stac_item(tmp_path)
    assets = item["assets"]
    if mutation == "empty":
        item["assets"] = {}
    elif mutation == "missing":
        assets.pop("visual")
    elif mutation == "extra":
        assets["unexpected"] = dict(assets["analysis"])
    else:
        assets["analysis"], assets["visual"] = assets["visual"], assets["analysis"]
    _write_json(item_path, item)

    with pytest.raises(ScienceContractError, match="asset inventory"):
        _validate_stac(
            tmp_path,
            artifacts,
            release_id="ar6-europe-fixture-v1",
            contract=contract(),
        )


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("id", "identity or geometry"),
        ("collection", "identity or geometry"),
        ("bbox", "identity or geometry"),
        ("geometry", "identity or geometry"),
        ("properties", "lineage"),
    ],
)
def test_stac_validator_rejects_mutated_item_contract(
    tmp_path: Path,
    mutation: str,
    message: str,
) -> None:
    artifacts = _stac_candidate(tmp_path)
    item_path, item = _first_stac_item(tmp_path)
    if mutation == "properties":
        item["properties"]["unexpected"] = True
    else:
        item[mutation] = {} if mutation in {"bbox", "geometry"} else "wrong"
    _write_json(item_path, item)

    with pytest.raises(ScienceContractError, match=message):
        _validate_stac(
            tmp_path,
            artifacts,
            release_id="ar6-europe-fixture-v1",
            contract=contract(),
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
    assert (first / "analysis/source-grid.json.gz").is_file()
    assert (first / "NOTICE.md").is_file()
    assert (first / "stac/collection.json").is_file()
    assert len(list(first.glob("stac/items/*.json"))) == 9
    assert len(first_result.manifest["artifacts"]) == 31
    source_grid = next(
        artifact
        for artifact in first_result.manifest["artifacts"]
        if artifact["role"] == "source-grid-identity"
    )
    assert source_grid["path"] == "analysis/source-grid.json.gz"
    assert first_result.manifest == second_result.manifest
    assert comparison["status"] == "passed"
    assert comparison["comparedArtifactCount"] == 31
    assert first_result.gate["disposition"] == "blocked"
    assert first_result.gate["blockingChecks"] == [
        "sourceArchiveAndMembersVerified",
        "crossEnvironmentReproducibility",
        "deliveryMeasurements",
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
            build_environment_id="test-existing-path",
            source_revision="a" * 40,
            **_missing_tool_paths(),
        )


@pytest.mark.parametrize("release_id", ["../escape", "a/b", "UPPER", "absolute"])
def test_builder_rejects_unsafe_release_ids(tmp_path: Path, release_id: str) -> None:
    unsafe_id = str(tmp_path / "absolute") if release_id == "absolute" else release_id
    output = tmp_path / "candidate"

    with pytest.raises(ScienceContractError, match="Release ID"):
        build_regional_release(
            _source(),
            output,
            release_id=unsafe_id,
            contract=contract(),
            lookup_goldens_path=GOLDENS_PATH,
            build_environment_id="test-unsafe-id",
            source_revision="a" * 40,
            **_missing_tool_paths(),
        )

    assert not output.exists()
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    ("build_environment_id", "source_revision", "message"),
    [
        ("", "a" * 40, "build environment"),
        ("test-build", "branch-name", "Source revision"),
    ],
)
def test_builder_rejects_unbound_build_identity(
    tmp_path: Path,
    build_environment_id: str,
    source_revision: str,
    message: str,
) -> None:
    with pytest.raises(ScienceContractError, match=message):
        build_regional_release(
            _source(),
            tmp_path / "candidate",
            release_id="ar6-europe-fixture-v1",
            contract=contract(),
            lookup_goldens_path=GOLDENS_PATH,
            build_environment_id=build_environment_id,
            source_revision=source_revision,
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
            build_environment_id="test-mutated-source",
            source_revision="a" * 40,
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
            build_environment_id="test-unbound-python",
            source_revision="a" * 40,
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
            "--build-environment-id",
            "test-cli",
            "--release-id",
            "ar6-europe-fixture-v1",
            "--output",
            str(output),
            "--failure-gate",
            str(failure),
        ],
    )
    captured: dict[str, object] = {}

    def fake_git(repository: Path, *arguments: str) -> str:
        assert repository == REPO_ROOT
        if arguments == ("status", "--porcelain"):
            return ""
        assert arguments == ("rev-parse", "HEAD")
        return "a" * 40

    def fake_build_regional_release(*args, **kwargs):
        captured.update(kwargs)
        raise ScienceContractError("stop after CLI wiring")

    monkeypatch.setattr(release_cli, "_git", fake_git)
    monkeypatch.setattr(
        release_cli,
        "build_regional_release",
        fake_build_regional_release,
    )

    with pytest.raises(SystemExit):
        release_cli.main()

    blocked = json.loads(failure.read_text(encoding="utf-8"))
    assert blocked["failure"]["type"] == "ScienceContractError"
    assert captured["build_environment_id"] == "test-cli"
    assert captured["source_revision"] == "a" * 40
    assert isinstance(captured["workflow_started_monotonic"], float)
    assert captured["tippecanoe_source_archive_path"] == missing
    assert captured["tippecanoe_build_receipt_path"] == missing
    assert captured["pmtiles_distribution_asset_path"] == missing
    assert captured["pmtiles_distribution_platform"] == "darwin-arm64"
    assert not output.exists()
