"""Test fail-closed pins and optional real PMTiles integration."""

from __future__ import annotations

import hashlib
import json
import os
import zipfile
from copy import deepcopy
from pathlib import Path

import pytest

import searise_pipeline.release.pmtiles as pmtiles_module
from searise_pipeline.release import (
    load_source_fixture,
    validate_vector_toolchain,
    write_visual_pmtiles,
)
from searise_pipeline.science import ScienceContractError

from .test_source_fixture import FIXTURE_DIR, contract


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_executable(path: Path, content: bytes) -> None:
    path.write_bytes(content)
    path.chmod(0o755)


def _pinned_toolchain(
    tmp_path: Path,
    *,
    embedded_pmtiles: bytes = b"pmtiles-binary",
) -> tuple[dict[str, object], dict[str, Path | str]]:
    release = deepcopy(contract())
    platform = "test-platform"
    tippecanoe = tmp_path / "tippecanoe"
    decode = tmp_path / "tippecanoe-decode"
    pmtiles = tmp_path / "pmtiles"
    source = tmp_path / "tippecanoe-source.tar.gz"
    receipt = tmp_path / "tippecanoe-build-receipt.json"
    build_recipe = tmp_path / "Dockerfile.tippecanoe-test"
    asset = tmp_path / "go-pmtiles-test.zip"
    _write_executable(tippecanoe, b"tippecanoe-binary")
    _write_executable(decode, b"decode-binary")
    _write_executable(pmtiles, b"pmtiles-binary")
    source.write_bytes(b"tippecanoe-source")
    build_recipe.write_bytes(b"FROM pinned-base@sha256:test\n")
    with zipfile.ZipFile(asset, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr("pmtiles", embedded_pmtiles)

    tippecanoe_pin = release["toolchain"]["tippecanoe"]
    tippecanoe_pin["sourceByteSize"] = source.stat().st_size
    tippecanoe_pin["sourceSha256"] = _sha256(source)
    reference = {
        "tippecanoeBinarySha256": _sha256(tippecanoe),
        "decodeBinarySha256": _sha256(decode),
        "buildEnvironment": {
            "buildRecipePath": f"src/pipeline/toolchain/{build_recipe.name}",
            "buildRecipeSha256": _sha256(build_recipe),
        },
    }
    tippecanoe_pin["referenceBuilds"] = {platform: reference}
    receipt.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "version": tippecanoe_pin["version"],
                "commit": tippecanoe_pin["commit"],
                "sourceSha256": tippecanoe_pin["sourceSha256"],
                "buildCommand": tippecanoe_pin["buildCommand"],
                "platform": platform,
                **reference,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    release["toolchain"]["pmtiles"]["assets"] = {
        platform: {
            "fileName": asset.name,
            "byteSize": asset.stat().st_size,
            "sha256": _sha256(asset),
        }
    }
    return release, {
        "tippecanoe_path": tippecanoe,
        "decode_path": decode,
        "pmtiles_path": pmtiles,
        "tippecanoe_source_archive_path": source,
        "tippecanoe_build_receipt_path": receipt,
        "pmtiles_distribution_asset_path": asset,
        "pmtiles_distribution_platform": platform,
    }


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
            tippecanoe_source_archive_path=missing,
            tippecanoe_build_receipt_path=missing,
            pmtiles_distribution_asset_path=missing,
            pmtiles_distribution_platform="darwin-arm64",
            contract=contract(),
        )


def test_vector_toolchain_rejects_tampered_tippecanoe_source(
    tmp_path: Path,
) -> None:
    release, tools = _pinned_toolchain(tmp_path)
    Path(tools["tippecanoe_source_archive_path"]).write_bytes(b"tampered")

    with pytest.raises(ScienceContractError, match="source archive differs"):
        validate_vector_toolchain(contract=release, **tools)


def test_vector_toolchain_rejects_tampered_build_receipt(tmp_path: Path) -> None:
    release, tools = _pinned_toolchain(tmp_path)
    Path(tools["tippecanoe_build_receipt_path"]).write_text(
        '{"schemaVersion": 1}\n', encoding="utf-8"
    )

    with pytest.raises(ScienceContractError, match="build receipt"):
        validate_vector_toolchain(contract=release, **tools)


def test_vector_toolchain_rejects_tampered_tippecanoe_binary(tmp_path: Path) -> None:
    release, tools = _pinned_toolchain(tmp_path)
    _write_executable(Path(tools["tippecanoe_path"]), b"tampered")

    with pytest.raises(ScienceContractError, match="contract hashes"):
        validate_vector_toolchain(contract=release, **tools)


def test_vector_toolchain_rejects_tampered_build_recipe(tmp_path: Path) -> None:
    release, tools = _pinned_toolchain(tmp_path)
    (tmp_path / "Dockerfile.tippecanoe-test").write_bytes(b"FROM unpinned-base\n")

    with pytest.raises(ScienceContractError, match="build recipe"):
        validate_vector_toolchain(contract=release, **tools)


def test_vector_toolchain_rejects_tampered_pmtiles_asset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    release, tools = _pinned_toolchain(tmp_path)
    monkeypatch.setattr(pmtiles_module, "_run", lambda _command: "tippecanoe v2.79.0")
    asset = Path(tools["pmtiles_distribution_asset_path"])
    asset.write_bytes(asset.read_bytes() + b"tampered")

    with pytest.raises(ScienceContractError, match="asset differs"):
        validate_vector_toolchain(contract=release, **tools)


def test_vector_toolchain_rejects_unrelated_embedded_pmtiles_binary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    release, tools = _pinned_toolchain(
        tmp_path, embedded_pmtiles=b"unrelated-pmtiles-binary"
    )
    monkeypatch.setattr(pmtiles_module, "_run", lambda _command: "tippecanoe v2.79.0")

    with pytest.raises(ScienceContractError, match="official distribution"):
        validate_vector_toolchain(contract=release, **tools)


def test_decoder_rejects_an_unexpected_mvt_layer_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    decoded = {
        "features": [
            {
                "features": [
                    {
                        "properties": {"layer": "not-projection"},
                        "features": [
                            {"id": 1, "properties": {"source_location_id": 1}}
                        ],
                    }
                ]
            }
        ]
    }
    monkeypatch.setattr(pmtiles_module, "_run", lambda _command: json.dumps(decoded))

    with pytest.raises(ScienceContractError, match="layer ID differs"):
        pmtiles_module._decode_properties(
            tmp_path / "decode",
            tmp_path / "archive.pmtiles",
            6,
            "projection",
        )


TOOL_ENVIRONMENT = (
    "SEARISE_TIPPECANOE",
    "SEARISE_TIPPECANOE_DECODE",
    "SEARISE_PMTILES",
    "SEARISE_TIPPECANOE_SOURCE",
    "SEARISE_TIPPECANOE_BUILD_RECEIPT",
    "SEARISE_PMTILES_ASSET",
    "SEARISE_VECTOR_PLATFORM",
)


@pytest.mark.skipif(
    not all(
        os.environ.get(name)
        for name in TOOL_ENVIRONMENT
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
    }

    first_evidence = write_visual_pmtiles(source, layer, first, contract=contract(), **tools)
    second_evidence = write_visual_pmtiles(source, layer, second, contract=contract(), **tools)

    assert first.read_bytes() == second.read_bytes()
    assert first_evidence.sha256 == second_evidence.sha256
    assert first_evidence.source_feature_count == 3054
    assert first_evidence.decoded_fragment_count >= first_evidence.source_feature_count
    assert first_evidence.metadata["searise"]["method_version"] == (
        "ar6-regional-projection-v1"
    )
    assert "generator_options" not in first_evidence.metadata
    assert first_evidence.byte_size <= contract()["budgets"]["pmtilesTotalBytes"] / 9
