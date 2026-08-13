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
    validate_visual_pmtiles,
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
    release, tools = _pinned_toolchain(tmp_path, embedded_pmtiles=b"unrelated-pmtiles-binary")
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
                        "features": [{"id": 1, "properties": {"source_location_id": 1}}],
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


@pytest.mark.parametrize(
    ("tamper", "message"),
    [
        ("string-id", "exact integer"),
        ("float-median", "properties or types"),
        ("numeric-scenario", "properties or types"),
    ],
)
def test_decoder_rejects_coerced_feature_types(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    tamper: str,
    message: str,
) -> None:
    feature = {
        "id": 1,
        "properties": {
            "horizon": 2050,
            "lower_mm": 100,
            "median_mm": 200,
            "scenario": "ssp2-45",
            "source_location_id": 1,
            "upper_mm": 300,
        },
    }
    if tamper == "string-id":
        feature["id"] = "1"
    elif tamper == "float-median":
        feature["properties"]["median_mm"] = 200.0
    else:
        feature["properties"]["scenario"] = 245
    decoded = {
        "features": [
            {
                "features": [
                    {
                        "properties": {"layer": "projection"},
                        "features": [feature],
                    }
                ]
            }
        ]
    }
    monkeypatch.setattr(pmtiles_module, "_run", lambda _command: json.dumps(decoded))

    with pytest.raises(ScienceContractError, match=message):
        pmtiles_module._decode_properties(
            tmp_path / "decode",
            tmp_path / "archive.pmtiles",
            6,
            "projection",
        )


def test_ndjson_rejects_common_mode_property_tampering(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _real_source()
    layer = source.layers[4]
    original = pmtiles_module._feature

    def tampered_feature(source, layer, row, column):
        feature = deepcopy(original(source, layer, row, column))
        feature["properties"]["median_mm"] += 1
        return feature

    monkeypatch.setattr(pmtiles_module, "_feature", tampered_feature)

    with pytest.raises(ScienceContractError, match="properties differ"):
        pmtiles_module._write_ndjson(tmp_path / "tampered.ndjson", source, layer)


def test_ndjson_rejects_a_shrunken_interior_source_cell(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _real_source()
    layer = source.layers[4]
    target_row, target_column = next(
        (int(row), int(column))
        for row, column in zip(*layer.valid.nonzero())
        if 0 < row < layer.valid.shape[0] - 1 and 0 < column < layer.valid.shape[1] - 1
    )
    original = pmtiles_module._feature

    def tampered_feature(source, layer, row, column):
        feature = deepcopy(original(source, layer, row, column))
        if (row, column) == (target_row, target_column):
            longitude = float(source.longitudes[column])
            latitude = float(source.latitudes[row])
            feature["geometry"]["coordinates"] = [
                [
                    [longitude - 0.1, latitude - 0.1],
                    [longitude + 0.1, latitude - 0.1],
                    [longitude + 0.1, latitude + 0.1],
                    [longitude - 0.1, latitude + 0.1],
                    [longitude - 0.1, latitude - 0.1],
                ]
            ]
        return feature

    monkeypatch.setattr(pmtiles_module, "_feature", tampered_feature)

    with pytest.raises(ScienceContractError, match="geometry differs"):
        pmtiles_module._write_ndjson(tmp_path / "tampered.ndjson", source, layer)


def test_pmtiles_rejects_common_mode_metadata_tampering(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _real_source()
    layer = source.layers[4]
    release = contract()
    original = pmtiles_module._canonical_metadata
    edited_metadata: dict[str, object] = {}

    def tampered_metadata(source, layer, contract):
        metadata = deepcopy(original(source, layer, contract))
        metadata["searise"]["baseline"] = "wrong-baseline"
        return metadata

    def fake_run(command: list[str]) -> str:
        output = next(
            (argument for argument in command if argument.startswith("--output=")),
            None,
        )
        if output is not None:
            Path(output.removeprefix("--output=")).write_bytes(b"pmtiles")
        metadata_argument = next(
            (argument for argument in command if argument.startswith("--metadata=")),
            None,
        )
        if metadata_argument is not None:
            metadata_path = Path(metadata_argument.removeprefix("--metadata="))
            edited_metadata.update(json.loads(metadata_path.read_text(encoding="utf-8")))
        if "show" in command and "--metadata" in command:
            return json.dumps(edited_metadata)
        return ""

    monkeypatch.setattr(pmtiles_module, "_canonical_metadata", tampered_metadata)
    monkeypatch.setattr(
        pmtiles_module,
        "_canonicalize_tippecanoe_gzip_headers",
        lambda _path: None,
    )
    monkeypatch.setattr(pmtiles_module, "validate_vector_toolchain", lambda **_kwargs: None)
    monkeypatch.setattr(pmtiles_module, "_run", fake_run)

    dummy = tmp_path / "unused"
    with pytest.raises(ScienceContractError, match="metadata differs"):
        write_visual_pmtiles(
            source,
            layer,
            tmp_path / "tampered.pmtiles",
            contract=release,
            tippecanoe_path=dummy,
            decode_path=dummy,
            pmtiles_path=dummy,
            tippecanoe_source_archive_path=dummy,
            tippecanoe_build_receipt_path=dummy,
            pmtiles_distribution_asset_path=dummy,
            pmtiles_distribution_platform="test-platform",
        )


def test_existing_visual_pmtiles_is_revalidated_against_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _real_source()
    layer = source.layers[4]
    release = contract()
    archive = tmp_path / "existing.pmtiles"
    archive.write_bytes(b"existing archive")
    metadata = pmtiles_module._expected_metadata(source, layer, release)
    specification = release["artifacts"]["pmtiles"]
    header = {
        "tile_compression": specification["tileCompression"],
        "tile_type": specification["tileType"],
        "minzoom": specification["minimumZoom"],
        "maxzoom": specification["maximumZoom"],
        "bounds": release["grid"]["bounds"],
    }
    expected_properties = pmtiles_module._expected_properties(source, layer)

    def fake_run(command: list[str]) -> str:
        if "--metadata" in command:
            return json.dumps(metadata)
        if "--header-json" in command:
            return json.dumps(header)
        return ""

    monkeypatch.setattr(pmtiles_module, "validate_vector_toolchain", lambda **_kwargs: None)
    monkeypatch.setattr(pmtiles_module, "_run", fake_run)
    monkeypatch.setattr(
        pmtiles_module,
        "_decode_properties",
        lambda *_args: (expected_properties, len(expected_properties)),
    )
    dummy = tmp_path / "unused"
    evidence = validate_visual_pmtiles(
        source,
        layer,
        archive,
        contract=release,
        tippecanoe_path=dummy,
        decode_path=dummy,
        pmtiles_path=dummy,
        tippecanoe_source_archive_path=dummy,
        tippecanoe_build_receipt_path=dummy,
        pmtiles_distribution_asset_path=dummy,
        pmtiles_distribution_platform="test-platform",
    )

    assert evidence.source_feature_count == len(expected_properties)
    assert evidence.sha256 == _sha256(archive)


def test_tippecanoe_gzip_headers_are_cross_platform_canonical(tmp_path: Path) -> None:
    prefix = b"\x1f\x8b\x08\x00\x00\x00\x00\x00\x00"
    linux = tmp_path / "linux.pmtiles"
    macos = tmp_path / "macos.pmtiles"
    linux.write_bytes(b"header" + prefix + b"\x03payload" + prefix + b"\x03tail")
    macos.write_bytes(b"header" + prefix + b"\x13payload" + prefix + b"\x13tail")

    assert pmtiles_module._canonicalize_tippecanoe_gzip_headers(linux) == 2
    assert pmtiles_module._canonicalize_tippecanoe_gzip_headers(macos) == 2

    assert linux.read_bytes() == macos.read_bytes()
    assert linux.read_bytes().count(prefix + b"\xff") == 2


def test_tippecanoe_gzip_header_canonicalization_fails_closed_without_tiles(
    tmp_path: Path,
) -> None:
    archive = tmp_path / "empty.pmtiles"
    archive.write_bytes(b"not-a-tile-archive")

    with pytest.raises(ScienceContractError, match="gzip members are absent"):
        pmtiles_module._canonicalize_tippecanoe_gzip_headers(archive)


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
    not all(os.environ.get(name) for name in TOOL_ENVIRONMENT),
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
        "tippecanoe_source_archive_path": Path(os.environ["SEARISE_TIPPECANOE_SOURCE"]),
        "tippecanoe_build_receipt_path": Path(os.environ["SEARISE_TIPPECANOE_BUILD_RECEIPT"]),
        "pmtiles_distribution_asset_path": Path(os.environ["SEARISE_PMTILES_ASSET"]),
        "pmtiles_distribution_platform": os.environ["SEARISE_VECTOR_PLATFORM"],
    }

    first_evidence = write_visual_pmtiles(source, layer, first, contract=contract(), **tools)
    second_evidence = write_visual_pmtiles(source, layer, second, contract=contract(), **tools)

    assert first.read_bytes() == second.read_bytes()
    assert first_evidence.sha256 == second_evidence.sha256
    assert first_evidence.source_feature_count == 3054
    assert first_evidence.decoded_fragment_count >= first_evidence.source_feature_count
    assert first_evidence.metadata["searise"]["method_version"] == ("ar6-regional-projection-v1")
    assert "generator_options" not in first_evidence.metadata
    assert first_evidence.byte_size <= contract()["budgets"]["pmtilesTotalBytes"] / 9
