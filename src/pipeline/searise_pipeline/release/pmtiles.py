"""Deterministic visual-only PMTiles output for source-native AR6 cells."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tarfile
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import numpy as np

from searise_pipeline.science.contracts import ScienceContractError

from .model import RegionalLayer, RegionalReleaseSource


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _run(command: list[str]) -> str:
    try:
        completed = subprocess.run(command, capture_output=True, check=True, text=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        detail = getattr(exc, "stderr", "") or str(exc)
        raise ScienceContractError(f"Pinned vector tool failed: {detail.strip()}") from exc
    return completed.stdout if completed.stdout else completed.stderr


@dataclass(frozen=True)
class VectorToolchainEvidence:
    """Observed local binaries bound to the official source/asset pins."""

    tippecanoe_version: str
    tippecanoe_source_sha256: str
    tippecanoe_binary_sha256: str
    pmtiles_version: str
    pmtiles_commit: str
    pmtiles_binary_sha256: str
    pmtiles_distribution_platform: str
    pmtiles_distribution_sha256: str
    decode_binary_sha256: str


@dataclass(frozen=True)
class PmtilesEvidence:
    """Identity and decoded-property parity for one visual archive."""

    path: str
    byte_size: int
    sha256: str
    source_feature_count: int
    decoded_fragment_count: int
    header: Mapping[str, Any]
    metadata: Mapping[str, Any]


def validate_vector_toolchain(
    *,
    tippecanoe_path: Path,
    decode_path: Path,
    pmtiles_path: Path,
    tippecanoe_source_archive_path: Path,
    tippecanoe_build_receipt_path: Path,
    pmtiles_distribution_asset_path: Path,
    pmtiles_distribution_platform: str,
    contract: Mapping[str, Any],
) -> VectorToolchainEvidence:
    """Reject absent or version-drifted external tools before generation."""
    for name, path in (
        ("tippecanoe", tippecanoe_path),
        ("tippecanoe-decode", decode_path),
        ("pmtiles", pmtiles_path),
    ):
        if not path.is_file() or not os.access(path, os.X_OK):
            raise ScienceContractError(f"Pinned {name} executable is absent: {path}")
    tippecanoe_pin = contract["toolchain"]["tippecanoe"]
    reference_build = tippecanoe_pin["referenceBuilds"].get(pmtiles_distribution_platform)
    if reference_build is None:
        raise ScienceContractError("Unsupported Tippecanoe reference-build platform")
    if (
        not tippecanoe_source_archive_path.is_file()
        or tippecanoe_source_archive_path.stat().st_size != tippecanoe_pin["sourceByteSize"]
        or _sha256(tippecanoe_source_archive_path) != tippecanoe_pin["sourceSha256"]
    ):
        raise ScienceContractError("Tippecanoe source archive differs from the release contract")
    try:
        tippecanoe_receipt = json.loads(
            tippecanoe_build_receipt_path.read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise ScienceContractError(f"Cannot read Tippecanoe build receipt: {exc}") from exc
    expected_receipt = {
        "schemaVersion": 1,
        "version": tippecanoe_pin["version"],
        "commit": tippecanoe_pin["commit"],
        "sourceSha256": tippecanoe_pin["sourceSha256"],
        "buildCommand": tippecanoe_pin["buildCommand"],
        "platform": pmtiles_distribution_platform,
        "tippecanoeBinarySha256": reference_build["tippecanoeBinarySha256"],
        "decodeBinarySha256": reference_build["decodeBinarySha256"],
    }
    if "buildEnvironment" in reference_build:
        expected_receipt["buildEnvironment"] = reference_build["buildEnvironment"]
    if tippecanoe_receipt != expected_receipt:
        raise ScienceContractError("Tippecanoe binaries differ from their pinned build receipt")
    if (
        _sha256(tippecanoe_path) != reference_build["tippecanoeBinarySha256"]
        or _sha256(decode_path) != reference_build["decodeBinarySha256"]
    ):
        raise ScienceContractError("Tippecanoe binaries differ from the contract hashes")
    tippecanoe_version = _run([str(tippecanoe_path), "--version"]).strip()
    if tippecanoe_version != f"tippecanoe v{tippecanoe_pin['version']}":
        raise ScienceContractError("Tippecanoe version differs from the release contract")
    pmtiles_pin = contract["toolchain"]["pmtiles"]
    asset = pmtiles_pin["assets"].get(pmtiles_distribution_platform)
    if asset is None:
        raise ScienceContractError("Unsupported go-pmtiles distribution platform")
    if (
        not pmtiles_distribution_asset_path.is_file()
        or pmtiles_distribution_asset_path.name != asset["fileName"]
        or pmtiles_distribution_asset_path.stat().st_size != asset["byteSize"]
        or _sha256(pmtiles_distribution_asset_path) != asset["sha256"]
    ):
        raise ScienceContractError("go-pmtiles distribution asset differs from the official pin")
    if zipfile.is_zipfile(pmtiles_distribution_asset_path):
        with zipfile.ZipFile(pmtiles_distribution_asset_path) as archive:
            embedded_binary = archive.read("pmtiles")
    elif tarfile.is_tarfile(pmtiles_distribution_asset_path):
        with tarfile.open(pmtiles_distribution_asset_path, "r:gz") as archive:
            members = [item for item in archive.getmembers() if Path(item.name).name == "pmtiles"]
            if len(members) != 1:
                raise ScienceContractError("go-pmtiles asset does not contain one pmtiles binary")
            stream = archive.extractfile(members[0])
            if stream is None:
                raise ScienceContractError("Cannot read pmtiles binary from official asset")
            embedded_binary = stream.read()
    else:
        raise ScienceContractError("Unsupported go-pmtiles distribution archive")
    if hashlib.sha256(embedded_binary).hexdigest() != _sha256(pmtiles_path):
        raise ScienceContractError("go-pmtiles binary differs from the official distribution")
    pmtiles_version = _run([str(pmtiles_path), "version"]).strip()
    expected_pmtiles = (
        f"pmtiles {pmtiles_pin['version']}, commit {pmtiles_pin['commit']}, built at "
    )
    if not pmtiles_version.startswith(expected_pmtiles):
        raise ScienceContractError("go-pmtiles version or commit differs from the release contract")
    return VectorToolchainEvidence(
        tippecanoe_version=tippecanoe_pin["version"],
        tippecanoe_source_sha256=tippecanoe_pin["sourceSha256"],
        tippecanoe_binary_sha256=_sha256(tippecanoe_path),
        pmtiles_version=pmtiles_pin["version"],
        pmtiles_commit=pmtiles_pin["commit"],
        pmtiles_binary_sha256=_sha256(pmtiles_path),
        pmtiles_distribution_platform=pmtiles_distribution_platform,
        pmtiles_distribution_sha256=asset["sha256"],
        decode_binary_sha256=_sha256(decode_path),
    )


def _feature(
    source: RegionalReleaseSource,
    layer: RegionalLayer,
    row: int,
    column: int,
) -> Mapping[str, Any]:
    longitude = float(source.longitudes[column])
    latitude = float(source.latitudes[row])
    location_id = int(source.location_ids[row, column])
    return {
        "type": "Feature",
        "id": location_id,
        "properties": {
            "horizon": layer.horizon,
            "lower_mm": int(layer.lower_mm[row, column]),
            "median_mm": int(layer.central_mm[row, column]),
            "scenario": layer.scenario,
            "source_location_id": location_id,
            "upper_mm": int(layer.upper_mm[row, column]),
        },
        "geometry": {
            "type": "Polygon",
            "coordinates": [
                [
                    [longitude - 0.5, latitude - 0.5],
                    [longitude + 0.5, latitude - 0.5],
                    [longitude + 0.5, latitude + 0.5],
                    [longitude - 0.5, latitude + 0.5],
                    [longitude - 0.5, latitude - 0.5],
                ]
            ],
        },
    }


def _expected_properties(
    source: RegionalReleaseSource,
    layer: RegionalLayer,
) -> dict[int, Mapping[str, Any]]:
    rows, columns = np.nonzero(layer.valid)
    return {
        int(source.location_ids[row, column]): _feature(source, layer, row, column)["properties"]
        for row, column in zip(rows.tolist(), columns.tolist())
    }


def _write_ndjson(path: Path, source: RegionalReleaseSource, layer: RegionalLayer) -> None:
    rows, columns = np.nonzero(layer.valid)
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for row, column in zip(rows.tolist(), columns.tolist()):
            encoded = json.dumps(
                _feature(source, layer, row, column),
                sort_keys=True,
                separators=(",", ":"),
            )
            stream.write(encoded + "\n")


def _canonical_metadata(
    source: RegionalReleaseSource,
    layer: RegionalLayer,
    contract: Mapping[str, Any],
) -> Mapping[str, Any]:
    pmtiles = contract["artifacts"]["pmtiles"]
    return {
        "attribution": contract["source"]["attribution"],
        "description": (
            f"IPCC AR6 {layer.scenario} {layer.horizon} source-native 1 degree grid; visual only"
        ),
        "format": "pbf",
        "generator": f"tippecanoe v{contract['toolchain']['tippecanoe']['version']}",
        "name": f"SeaRise AR6 {layer.scenario} {layer.horizon}",
        "searise": {
            "baseline": contract["values"]["baseline"],
            "confidence": contract["values"]["confidence"],
            "horizon": layer.horizon,
            "member_sha256": layer.member_sha256,
            "method_version": "ar6-regional-projection-v1",
            "native_resolution_degrees": contract["grid"]["nativeResolutionDegrees"],
            "published_units": contract["values"]["publishedUnits"],
            "quantiles": contract["matrix"]["quantiles"],
            "release_contract_id": contract["releaseContractId"],
            "scenario": layer.scenario,
            "scientific_lookup": "prohibited",
            "scale_to_metres": contract["values"]["scaleToMetres"],
            "source_archive_sha256": source.archive_sha256,
            "source_release": contract["source"]["version"],
            "units": "mm",
            "visual_only": True,
        },
        "type": "overlay",
        "vector_layers": [
            {
                "description": "AR6 source-native cells; visual only",
                "fields": {
                    "horizon": "Number",
                    "lower_mm": "Number",
                    "median_mm": "Number",
                    "scenario": "String",
                    "source_location_id": "Number",
                    "upper_mm": "Number",
                },
                "id": pmtiles["layerId"],
                "maxzoom": pmtiles["maximumZoom"],
                "minzoom": pmtiles["minimumZoom"],
            }
        ],
        "version": "1",
    }


def _decode_properties(
    decode_path: Path,
    archive_path: Path,
    maximum_zoom: int,
) -> tuple[dict[int, Mapping[str, Any]], int]:
    decoded = json.loads(
        _run(
            [
                str(decode_path),
                f"-Z{maximum_zoom}",
                f"-z{maximum_zoom}",
                str(archive_path),
            ]
        )
    )
    properties: dict[int, Mapping[str, Any]] = {}
    fragments = 0
    for tile in decoded["features"]:
        for layer in tile["features"]:
            for feature in layer["features"]:
                fragments += 1
                location_id = int(feature["id"])
                candidate = feature["properties"]
                previous = properties.setdefault(location_id, candidate)
                if previous != candidate:
                    raise ScienceContractError(
                        "PMTiles fragments disagree on one source location's properties"
                    )
    return properties, fragments


def write_visual_pmtiles(
    source: RegionalReleaseSource,
    layer: RegionalLayer,
    path: Path,
    *,
    contract: Mapping[str, Any],
    tippecanoe_path: Path,
    decode_path: Path,
    pmtiles_path: Path,
    tippecanoe_source_archive_path: Path,
    tippecanoe_build_receipt_path: Path,
    pmtiles_distribution_asset_path: Path,
    pmtiles_distribution_platform: str,
) -> PmtilesEvidence:
    """Write, canonicalize, verify, and decode one visual-only PMTiles archive."""
    validate_vector_toolchain(
        tippecanoe_path=tippecanoe_path,
        decode_path=decode_path,
        pmtiles_path=pmtiles_path,
        tippecanoe_source_archive_path=tippecanoe_source_archive_path,
        tippecanoe_build_receipt_path=tippecanoe_build_receipt_path,
        pmtiles_distribution_asset_path=pmtiles_distribution_asset_path,
        pmtiles_distribution_platform=pmtiles_distribution_platform,
        contract=contract,
    )
    specification = contract["artifacts"]["pmtiles"]
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="searise-pmtiles-", dir=path.parent) as temporary:
        staging = Path(temporary)
        ndjson_path = staging / "projection.ndjson"
        archive_path = staging / "projection.pmtiles"
        metadata_path = staging / "metadata.json"
        _write_ndjson(ndjson_path, source, layer)
        metadata_path.write_text(
            json.dumps(
                _canonical_metadata(source, layer, contract),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n",
            encoding="utf-8",
        )
        _run(
            [
                str(tippecanoe_path),
                "--force",
                f"--output={archive_path}",
                f"--layer={specification['layerId']}",
                "--projection=EPSG:4326",
                f"--minimum-zoom={specification['minimumZoom']}",
                f"--maximum-zoom={specification['maximumZoom']}",
                "--no-feature-limit",
                "--no-tile-size-limit",
                "--no-line-simplification",
                "--preserve-input-order",
                str(ndjson_path),
            ]
        )
        _run([str(pmtiles_path), "edit", str(archive_path), f"--metadata={metadata_path}"])
        _run([str(pmtiles_path), "verify", str(archive_path)])
        metadata = json.loads(
            _run([str(pmtiles_path), "show", str(archive_path), "--metadata"])
        )
        expected_metadata = _canonical_metadata(source, layer, contract)
        prohibited = {"generator_options", "tilestats", "timestamp", "hostname", "host"}
        if metadata != expected_metadata or prohibited.intersection(metadata):
            raise ScienceContractError("PMTiles metadata differs from the canonical allow-list")
        header = json.loads(_run([str(pmtiles_path), "show", str(archive_path), "--header-json"]))
        expected_header = {
            "tile_compression": specification["tileCompression"],
            "tile_type": specification["tileType"],
            "minzoom": specification["minimumZoom"],
            "maxzoom": specification["maximumZoom"],
            "bounds": contract["grid"]["bounds"],
        }
        if any(header.get(key) != value for key, value in expected_header.items()):
            raise ScienceContractError("PMTiles header differs from the release contract")
        actual_properties, fragments = _decode_properties(
            decode_path,
            archive_path,
            specification["maximumZoom"],
        )
        expected_properties = _expected_properties(source, layer)
        if actual_properties != expected_properties:
            raise ScienceContractError("PMTiles decoded IDs or properties differ from source")
        os.replace(archive_path, path)
    return PmtilesEvidence(
        path=f"layers/{layer.scenario}/{layer.horizon}.pmtiles",
        byte_size=path.stat().st_size,
        sha256=_sha256(path),
        source_feature_count=len(expected_properties),
        decoded_fragment_count=fragments,
        header=header,
        metadata=metadata,
    )
