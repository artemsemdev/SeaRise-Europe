#!/usr/bin/env python3
"""Build deterministic real-source Baltic and Black Sea control evidence."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

import geopandas as gpd  # type: ignore[import-untyped]
import numpy as np
import xarray as xr
from jsonschema import Draft202012Validator, FormatChecker
from searise_pipeline.science import inspect_dem_window
from searise_pipeline.sources import load_registry
from shapely.geometry import Point

LAYERS = ("DEM", "EDM", "FLM", "HEM", "WBM")
BUILDER_VERSION = "1.0.0"
EVIDENCE_RELATIVE_PATH = Path(
    "src/pipeline/science/evidence/phase-0-12-basin-controls.json"
)
EVIDENCE_SCHEMA_RELATIVE_PATH = Path(
    "src/pipeline/science/evidence/phase-0-12-basin-controls.schema.json"
)


class EvidenceBuildError(RuntimeError):
    """An input is missing, changed, or scientifically unsupported."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _canonical_bytes(document: Mapping[str, Any]) -> bytes:
    return (json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _validate_document(
    document: Mapping[str, Any], schema: Mapping[str, Any], label: str
) -> None:
    errors = sorted(
        Draft202012Validator(
            schema, format_checker=FormatChecker()
        ).iter_errors(document),
        key=lambda item: list(item.path),
    )
    if errors:
        first = errors[0]
        location = ".".join(str(part) for part in first.path) or "<root>"
        raise EvidenceBuildError(f"Invalid {label} at {location}: {first.message}")


def _load_contract(repo_root: Path) -> dict[str, Any]:
    contract_dir = repo_root / "src/pipeline/science"
    contract = json.loads((contract_dir / "basin-controls.json").read_text(encoding="utf-8"))
    schema = json.loads(
        (contract_dir / "basin-controls.schema.json").read_text(encoding="utf-8")
    )
    _validate_document(contract, schema, "basin control contract")
    return contract


def _dem_filename(tile: str, layer: str) -> str:
    return f"Copernicus_DSM_COG_10_{tile}_{layer}.tif"


def _dem_key(tile: str, layer: str) -> str:
    prefix = f"Copernicus_DSM_COG_10_{tile}_DEM"
    filename = _dem_filename(tile, layer)
    return f"{prefix}/{prefix}.tif" if layer == "DEM" else f"{prefix}/AUXFILES/{filename}"


def build_dem_manifest(contract: Mapping[str, Any], dem_dir: Path) -> bytes:
    """Return a deterministic gzip manifest for the four five-layer DEM controls."""
    terrain = contract["sourceBindings"]["terrain"]
    rows: list[dict[str, Any]] = []
    regions: list[str] = []
    for window in contract["windows"]:
        region, tile = window["id"], window["tile"]
        regions.append(region)
        for layer in LAYERS:
            path = dem_dir / _dem_filename(tile, layer)
            if not path.is_file():
                raise EvidenceBuildError(f"Missing DEM control asset: {path}")
            key = _dem_key(tile, layer)
            rows.append(
                {
                    "byteSize": path.stat().st_size,
                    "key": key,
                    "region": region,
                    "role": layer,
                    "sha256": _sha256(path),
                    "tile": tile,
                    "type": "object",
                    "url": f"{terrain['resolvedUrl']}/{key}",
                }
            )
    header = {
        "datasetVersion": terrain["resolvedVersion"],
        "objectCount": len(rows),
        "productId": terrain["nativeVersion"],
        "regions": regions,
        "resolution": "GLO-30",
        "roles": list(LAYERS),
        "schemaVersion": 1,
        "totalByteSize": sum(row["byteSize"] for row in rows),
        "type": "manifest",
    }
    payload = b"".join(_canonical_bytes(item) for item in (header, *rows))
    return gzip.compress(payload, mtime=0)


def _manifest_records(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]], bytes]:
    compressed = path.read_bytes()
    try:
        payload = gzip.decompress(compressed)
        records = [json.loads(line) for line in payload.decode("utf-8").splitlines()]
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EvidenceBuildError(f"Invalid manifest: {path}") from exc
    if not records or records[0].get("type") != "manifest":
        raise EvidenceBuildError(f"Manifest header is missing: {path}")
    return records[0], records[1:], payload


def _file_lineage(repo_root: Path, relative_path: str | Path) -> dict[str, Any]:
    path = Path(relative_path)
    return {"path": path.as_posix(), "sha256": _sha256(repo_root / path)}


def _verify_lineage_file(
    repo_root: Path, descriptor: Mapping[str, Any], label: str
) -> Path:
    path = Path(descriptor["path"])
    if path.is_absolute() or ".." in path.parts:
        raise EvidenceBuildError(f"Unsafe {label} lineage path: {path}")
    resolved = repo_root / path
    if not resolved.is_file() or _sha256(resolved) != descriptor["sha256"]:
        raise EvidenceBuildError(f"{label} lineage identity mismatch: {path}")
    return resolved


def _verify_manifest_lineage(
    repo_root: Path, descriptor: Mapping[str, Any], label: str
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    path = _verify_lineage_file(repo_root, descriptor, label)
    header, rows, payload = _manifest_records(path)
    if header["objectCount"] != len(rows) or descriptor["objectCount"] != len(rows):
        raise EvidenceBuildError(f"{label} object count mismatch")
    if "payloadSha256" in descriptor and (
        hashlib.sha256(payload).hexdigest() != descriptor["payloadSha256"]
    ):
        raise EvidenceBuildError(f"{label} payload identity mismatch")
    if "totalByteSize" in descriptor and (
        header["totalByteSize"] != descriptor["totalByteSize"]
    ):
        raise EvidenceBuildError(f"{label} byte total mismatch")
    return header, rows


def validate_checked_in_evidence(
    repo_root: Path, evidence_path: Path | None = None
) -> dict[str, Any]:
    """Validate the committed receipt, all lineage, and canonical regeneration."""
    repo_root = repo_root.resolve()
    path = evidence_path or repo_root / EVIDENCE_RELATIVE_PATH
    raw = path.read_bytes()
    try:
        evidence = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise EvidenceBuildError(f"Invalid basin evidence JSON: {path}") from exc

    schema_path = repo_root / EVIDENCE_SCHEMA_RELATIVE_PATH
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    _validate_document(evidence, schema, "basin control evidence")
    if raw != _canonical_bytes(evidence):
        raise EvidenceBuildError("Basin evidence is not byte-identical canonical JSON")

    expected_identity = {
        "$schema": "./phase-0-12-basin-controls.schema.json",
        "schemaVersion": 1,
        "evidenceId": "phase-0.12-baltic-black-sea-controls-v1",
        "issue": 96,
        "builderVersion": BUILDER_VERSION,
        "status": "source-pinning-complete-vertical-goldens-blocked",
        "realSourceOnly": True,
    }
    for key, expected in expected_identity.items():
        if evidence[key] != expected:
            raise EvidenceBuildError(f"Unexpected evidence {key}: {evidence[key]!r}")
    if evidence["review"] != {
        "status": "pending-external",
        "requiredRoles": ["independent scientific/data reviewer", "product owner"],
        "executableGoldens": "blocked-by-issues-94-and-95",
    }:
        raise EvidenceBuildError("Basin review disposition is not fail-closed")
    if evidence["publicationGate"] != {
        "status": "blocked",
        "europeWideClaimAllowed": False,
        "blockingIssues": [94, 95, 97],
    }:
        raise EvidenceBuildError("Basin publication gate is not fail-closed")

    lineage = evidence["lineage"]
    expected_paths = {
        "recipe": "scripts/science/build_basin_control_evidence.py",
        "contract": "src/pipeline/science/basin-controls.json",
        "contractSchema": "src/pipeline/science/basin-controls.schema.json",
        "evidenceSchema": EVIDENCE_SCHEMA_RELATIVE_PATH.as_posix(),
        "sourceLock": "src/pipeline/sources/source-lock.json",
        "sourceLockSchema": "src/pipeline/sources/source-lock.schema.json",
        "supportGeometry": "data/geometry/europe.geojson",
        "coastalGeometry": "data/geometry/coastal_analysis_zone.geojson",
        "connectivityControls": "src/pipeline/science/connectivity-controls.json",
        "slaManifest": (
            "src/pipeline/sources/manifests/"
            "cmems-eur-monthly-sla-1995-2014-v202411.jsonl.gz"
        ),
        "terrainManifest": (
            "src/pipeline/sources/manifests/"
            "cop-dem-glo-30-baltic-black-sea-controls-v2021_1.jsonl.gz"
        ),
        "existingTerrainManifest": (
            "src/pipeline/sources/manifests/"
            "cop-dem-glo-30-regional-controls-v2021_1.jsonl.gz"
        ),
    }
    if set(lineage) != set(expected_paths):
        raise EvidenceBuildError("Basin evidence lineage set is incomplete or unexpected")
    for key, expected_path in expected_paths.items():
        if lineage[key]["path"] != expected_path:
            raise EvidenceBuildError(f"Unexpected {key} lineage path")

    for key in (
        "recipe",
        "contract",
        "contractSchema",
        "evidenceSchema",
        "sourceLock",
        "sourceLockSchema",
        "supportGeometry",
        "coastalGeometry",
        "connectivityControls",
    ):
        _verify_lineage_file(repo_root, lineage[key], key)
    for key in ("slaManifest", "terrainManifest", "existingTerrainManifest"):
        _verify_manifest_lineage(repo_root, lineage[key], key)

    contract = _load_contract(repo_root)
    if (
        contract["contractId"] != evidence["evidenceId"]
        or contract["issue"] != evidence["issue"]
        or contract["status"] != evidence["status"]
    ):
        raise EvidenceBuildError("Basin contract and evidence identity differ")
    bindings = contract["sourceBindings"]
    for lineage_key, contract_binding in (
        ("supportGeometry", bindings["geography"]["support"]),
        ("coastalGeometry", bindings["geography"]["coastal"]),
        ("connectivityControls", bindings["connectivity"]),
    ):
        if dict(lineage[lineage_key]) != dict(contract_binding):
            raise EvidenceBuildError(f"{lineage_key} differs from the basin contract")
    sla = bindings["baseline"]["sla"]
    terrain = bindings["terrain"]
    for actual, expected in (
        (lineage["slaManifest"]["sha256"], sla["manifestSha256"]),
        (lineage["slaManifest"]["payloadSha256"], sla["payloadSha256"]),
        (lineage["slaManifest"]["objectCount"], sla["objectCount"]),
        (lineage["slaManifest"]["totalByteSize"], sla["totalByteSize"]),
        (lineage["terrainManifest"]["sha256"], terrain["manifestSha256"]),
        (lineage["terrainManifest"]["payloadSha256"], terrain["payloadSha256"]),
        (lineage["terrainManifest"]["objectCount"], terrain["objectCount"]),
        (lineage["terrainManifest"]["totalByteSize"], terrain["totalByteSize"]),
    ):
        if actual != expected:
            raise EvidenceBuildError("Manifest lineage differs from the basin contract")
    load_registry(repo_root / lineage["sourceLock"]["path"])
    return evidence


def _find_source(document: Mapping[str, Any], source_id: str) -> Mapping[str, Any]:
    try:
        return next(source for source in document["sources"] if source["id"] == source_id)
    except StopIteration as exc:
        raise EvidenceBuildError(f"Source binding is absent: {source_id}") from exc


def _find_asset(source: Mapping[str, Any], asset_id: str) -> Mapping[str, Any]:
    try:
        return next(asset for asset in source["assets"] if asset["id"] == asset_id)
    except StopIteration as exc:
        raise EvidenceBuildError(f"Asset binding is absent: {source['id']}:{asset_id}") from exc


def _verify_file(path: Path, expected_size: int, expected_sha256: str) -> None:
    if not path.is_file():
        raise EvidenceBuildError(f"Missing source asset: {path}")
    if path.stat().st_size != expected_size or _sha256(path) != expected_sha256:
        raise EvidenceBuildError(f"Source identity mismatch: {path}")


def _verify_global_bindings(
    contract: Mapping[str, Any], source_lock: Mapping[str, Any]
) -> None:
    bindings = contract["sourceBindings"]
    projection = bindings["projection"]
    source = _find_source(source_lock, projection["sourceId"])
    asset = _find_asset(source, projection["assetId"])
    if source["version"] != projection["version"] or asset["sha256"] != projection["sha256"]:
        raise EvidenceBuildError("Projection archive binding differs from the source lock")
    locked_members = {member["id"]: member["sha256"] for member in asset["members"]}
    if locked_members != {
        member["id"]: member["sha256"] for member in projection["members"]
    }:
        raise EvidenceBuildError("Projection member bindings differ from the source lock")

    baseline = bindings["baseline"]
    for key in ("sla", "mdt"):
        item = baseline[key]
        source = _find_source(source_lock, item["sourceId"])
        asset = _find_asset(source, item["assetId"])
        if source["version"] != item["version"]:
            raise EvidenceBuildError(f"Baseline {key} version differs from the source lock")
        if key == "sla":
            locked = asset["objectSet"]
            for field in (
                "manifestSha256",
                "payloadSha256",
                "objectCount",
                "totalByteSize",
            ):
                if locked[field] != item[field]:
                    raise EvidenceBuildError(f"Baseline SLA {field} differs from source lock")
        elif asset["sha256"] != item["sha256"] or asset["byteSize"] != item["byteSize"]:
            raise EvidenceBuildError("MDT identity differs from the source lock")

    for geoid_key in ("source", "target"):
        item = bindings["geoid"][geoid_key]
        source = _find_source(source_lock, item["sourceId"])
        asset = _find_asset(source, item["assetId"])
        member = next(
            (candidate for candidate in asset["members"] if candidate["id"] == item["memberId"]),
            None,
        )
        if (
            source["version"] != item["version"]
            or member is None
            or member["sha256"] != item["memberSha256"]
        ):
            raise EvidenceBuildError(f"{geoid_key} geoid binding differs from source lock")


def _verify_bound_files(repo_root: Path, contract: Mapping[str, Any]) -> None:
    bindings = contract["sourceBindings"]
    for item in (
        bindings["geography"]["support"],
        bindings["geography"]["coastal"],
        bindings["connectivity"],
    ):
        path = repo_root / item["path"]
        if not path.is_file() or _sha256(path) != item["sha256"]:
            raise EvidenceBuildError(f"Bound contract file identity mismatch: {path}")


def _verify_monthly_inputs(
    repo_root: Path,
    contract: Mapping[str, Any],
    monthly_dir: Path,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    binding = contract["sourceBindings"]["baseline"]["sla"]
    manifest_path = repo_root / binding["manifestPath"]
    compressed = manifest_path.read_bytes()
    header, rows, payload = _manifest_records(manifest_path)
    if (
        len(compressed) != manifest_path.stat().st_size
        or hashlib.sha256(compressed).hexdigest() != binding["manifestSha256"]
        or hashlib.sha256(payload).hexdigest() != binding["payloadSha256"]
        or len(rows) != binding["objectCount"]
        or header["totalByteSize"] != binding["totalByteSize"]
    ):
        raise EvidenceBuildError("Monthly SLA manifest differs from the basin contract")
    expected_names = {Path(row["key"]).name for row in rows}
    actual_names = {path.name for path in monthly_dir.glob("*.nc")}
    if actual_names != expected_names:
        raise EvidenceBuildError("Monthly SLA directory is not the exact 240-object set")
    for row in rows:
        _verify_file(monthly_dir / Path(row["key"]).name, row["byteSize"], row["sha256"])
    return rows, header


def _source_grid(array: xr.DataArray) -> dict[str, Any]:
    longitudes = np.asarray(array.longitude.values)
    latitudes = np.asarray(array.latitude.values)
    return {
        "shape": [int(array.sizes["latitude"]), int(array.sizes["longitude"])],
        "longitude": {
            "minimum": float(longitudes.min()),
            "maximum": float(longitudes.max()),
            "spacingDegrees": float(np.diff(longitudes).min()),
        },
        "latitude": {
            "minimum": float(latitudes.min()),
            "maximum": float(latitudes.max()),
            "spacingDegrees": float(np.diff(latitudes).min()),
        },
    }


def _window_array(array: xr.DataArray, bounds: Iterable[float]) -> xr.DataArray:
    west, south, east, north = bounds
    return array.sel(longitude=slice(west, east), latitude=slice(south, north))


def _coordinate_index(values: np.ndarray, expected: float, label: str) -> int:
    matches = np.flatnonzero(np.isclose(values, expected, rtol=0, atol=1e-8))
    if matches.size != 1:
        raise EvidenceBuildError(f"{label} is not an exact source-cell coordinate: {expected}")
    return int(matches[0])


def _inspect_baseline(
    contract: Mapping[str, Any],
    rows: list[dict[str, Any]],
    monthly_dir: Path,
    mdt_path: Path,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    mdt_binding = contract["sourceBindings"]["baseline"]["mdt"]
    _verify_file(mdt_path, mdt_binding["byteSize"], mdt_binding["sha256"])
    with xr.open_dataset(mdt_path) as dataset:
        if "mdt" not in dataset or dataset["mdt"].attrs.get("units") != "m":
            raise EvidenceBuildError("MDT variable contract is missing")
        mdt = dataset["mdt"].squeeze(drop=True).load()

    windows = {item["id"]: item for item in contract["windows"]}
    valid_months: dict[str, np.ndarray] = {}
    source_grid: dict[str, Any] | None = None
    source_coordinates: tuple[np.ndarray, np.ndarray] | None = None
    for row in rows:
        path = monthly_dir / Path(row["key"]).name
        with xr.open_dataset(path) as dataset:
            if "sla" not in dataset or dataset["sla"].attrs.get("units") != "m":
                raise EvidenceBuildError(f"SLA variable contract is missing: {path.name}")
            sla = dataset["sla"].squeeze(drop=True)
            grid = _source_grid(sla)
            coordinates = (
                np.asarray(sla.longitude.values),
                np.asarray(sla.latitude.values),
            )
            if source_grid is None:
                source_grid = grid
                source_coordinates = (coordinates[0].copy(), coordinates[1].copy())
            elif grid != source_grid or any(
                not np.array_equal(expected, actual)
                for expected, actual in zip(source_coordinates or (), coordinates)
            ):
                raise EvidenceBuildError("Monthly SLA source grid changed within the lock")
            for window_id, window in windows.items():
                values = _window_array(sla, window["boundsWgs84"]).values
                count = valid_months.setdefault(
                    window_id, np.zeros(values.shape, dtype=np.uint16)
                )
                if count.shape != values.shape:
                    raise EvidenceBuildError(f"SLA window shape changed: {window_id}")
                count += np.isfinite(values)
    if source_grid is None or source_coordinates is None:
        raise EvidenceBuildError("No monthly SLA inputs were inspected")

    results: dict[str, dict[str, Any]] = {}
    anchor_lookup: dict[str, dict[str, Any]] = {}
    for window_id, window in windows.items():
        counts = valid_months[window_id]
        mdt_window = _window_array(mdt, window["boundsWgs84"])
        mdt_valid = np.isfinite(mdt_window.values)
        if counts.shape != mdt_valid.shape:
            raise EvidenceBuildError(f"SLA and MDT native grids differ: {window_id}")
        all_months = counts == len(rows)
        never = counts == 0
        partial = ~(all_months | never)
        baseline_ready = all_months & mdt_valid
        results[window_id] = {
            "sourceCellShape": list(counts.shape),
            "sourceCellCount": int(counts.size),
            "slaValidAllMonths": int(all_months.sum()),
            "slaValidNoMonths": int(never.sum()),
            "slaPartiallyValidMonths": int(partial.sum()),
            "mdtValid": int(mdt_valid.sum()),
            "baselineReady": int(baseline_ready.sum()),
            "baselineUnavailable": int(counts.size - baseline_ready.sum()),
            "slaReadyMdtNodata": int((all_months & ~mdt_valid).sum()),
            "slaNodataMdtValid": int((never & mdt_valid).sum()),
            "extrapolatedCellCount": 0,
            "missingRule": contract["sourcePolicy"]["landAndNodata"],
        }
        longitudes = np.asarray(mdt_window.longitude.values)
        latitudes = np.asarray(mdt_window.latitude.values)
        for anchor in window["marineAnchors"]:
            column = _coordinate_index(longitudes, anchor["longitude"], "longitude")
            row_index = _coordinate_index(latitudes, anchor["latitude"], "latitude")
            months = int(counts[row_index, column])
            has_mdt = bool(mdt_valid[row_index, column])
            actual = "baseline-ready" if months == len(rows) and has_mdt else "source-nodata"
            if actual != anchor["expectedSourceState"]:
                raise EvidenceBuildError(f"Marine anchor changed: {anchor['id']}")
            anchor_lookup[anchor["id"]] = {
                "actualSourceState": actual,
                "slaValidMonthCount": months,
                "mdtValid": has_mdt,
                "passed": True,
            }
    return (
        {
            "sla": {
                "assetCount": len(rows),
                "allAssetsVerified": True,
                "sourceGrid": source_grid,
            },
            "mdt": {
                "sha256": _sha256(mdt_path),
                "sourceGrid": _source_grid(mdt),
            },
            "windows": results,
        },
        anchor_lookup,
    )


def _inspect_dem_controls(
    contract: Mapping[str, Any],
    manifest_rows: list[dict[str, Any]],
    dem_dir: Path,
) -> dict[str, Any]:
    expected = {
        (row["region"], row["role"]): (row["byteSize"], row["sha256"])
        for row in manifest_rows
    }
    reports: dict[str, Any] = {}
    for window in contract["windows"]:
        paths = {
            layer: dem_dir / _dem_filename(window["tile"], layer) for layer in LAYERS
        }
        report = inspect_dem_window(paths)
        for layer, identity in report["assets"].items():
            if (identity["byteSize"], identity["sha256"]) != expected[(window["id"], layer)]:
                raise EvidenceBuildError(f"DEM manifest identity mismatch: {window['id']}:{layer}")
        reports[window["id"]] = report
    return reports


def _inspect_state_expectations(
    repo_root: Path,
    contract: Mapping[str, Any],
    anchors: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    geography = contract["sourceBindings"]["geography"]
    support = gpd.read_file(repo_root / geography["support"]["path"]).geometry.union_all()
    coastal = gpd.read_file(repo_root / geography["coastal"]["path"]).geometry.union_all()
    results: list[dict[str, Any]] = []
    for expected in contract["combinedSuite"]["stateExpectations"]:
        point = Point(expected["longitude"], expected["latitude"])
        in_support = bool(support.covers(point))
        in_coastal = bool(coastal.covers(point)) if in_support else False
        actual: str | None = None
        if not in_support:
            actual = "UnsupportedGeography"
        elif not in_coastal:
            actual = "OutOfScope"
        elif expected["verificationStatus"] == "verified-source-native":
            matching_anchors = [
                anchor
                for window in contract["windows"]
                for anchor in window["marineAnchors"]
                if anchor["longitude"] == expected["longitude"]
                and anchor["latitude"] == expected["latitude"]
            ]
            if len(matching_anchors) != 1:
                raise EvidenceBuildError("Source-native state expectation lacks one exact anchor")
            measured = anchors[matching_anchors[0]["id"]]
            if measured["actualSourceState"] != "source-nodata":
                raise EvidenceBuildError("The source-native DataUnavailable control disappeared")
            actual = "DataUnavailable"
        passed = None if actual is None else actual == expected["expectedState"]
        if passed is False:
            raise EvidenceBuildError(f"Five-state expectation changed: {expected['id']}")
        results.append(
            {
                "id": expected["id"],
                "expectedState": expected["expectedState"],
                "reasonCode": expected["reasonCode"],
                "classificationReasonCode": expected["classificationReasonCode"],
                "verificationStatus": expected["verificationStatus"],
                "inSupportedGeography": in_support,
                "inCoastalScope": in_coastal,
                "actualState": actual,
                "passed": passed,
            }
        )
    return results


def _licence_evidence(source_lock: Mapping[str, Any], source_ids: Iterable[str]) -> list[dict[str, Any]]:
    evidence = []
    for source_id in source_ids:
        source = _find_source(source_lock, source_id)
        licence = source["licence"]
        evidence.append(
            {
                "sourceId": source_id,
                "version": source["version"],
                "name": licence["name"],
                "spdx": licence["spdx"],
                "url": licence["url"],
                "attribution": licence["attribution"],
                "redistributionStatus": licence["redistributionStatus"],
                "requiredAcknowledgements": licence["requiredAcknowledgements"],
            }
        )
    return evidence


def build_evidence(
    repo_root: Path,
    contract: Mapping[str, Any],
    dem_dir: Path,
    monthly_dir: Path,
    mdt_path: Path,
) -> dict[str, Any]:
    source_lock_path = repo_root / "src/pipeline/sources/source-lock.json"
    load_registry(source_lock_path)
    source_lock = json.loads(source_lock_path.read_text(encoding="utf-8"))
    _verify_global_bindings(contract, source_lock)
    _verify_bound_files(repo_root, contract)

    terrain_binding = contract["sourceBindings"]["terrain"]
    manifest_path = repo_root / terrain_binding["manifestPath"]
    header, manifest_rows, payload = _manifest_records(manifest_path)
    compressed = manifest_path.read_bytes()
    if (
        header["objectCount"] != len(manifest_rows)
        or len(manifest_rows) != 20
        or terrain_binding["manifestByteSize"] != len(compressed)
        or terrain_binding["manifestSha256"]
        != hashlib.sha256(compressed).hexdigest()
        or terrain_binding["payloadSha256"] != hashlib.sha256(payload).hexdigest()
        or terrain_binding["objectCount"] != len(manifest_rows)
        or terrain_binding["totalByteSize"] != header["totalByteSize"]
        or any(
            row["url"] != f"{terrain_binding['resolvedUrl']}/{row['key']}"
            for row in manifest_rows
        )
    ):
        raise EvidenceBuildError("Basin DEM manifest differs from its standalone contract")

    monthly_rows, monthly_header = _verify_monthly_inputs(
        repo_root, contract, monthly_dir
    )
    baseline, anchors = _inspect_baseline(
        contract, monthly_rows, monthly_dir, mdt_path
    )
    dem = _inspect_dem_controls(contract, manifest_rows, dem_dir)
    states = _inspect_state_expectations(repo_root, contract, anchors)

    previous_manifest_path = (
        repo_root
        / "src/pipeline/sources/manifests/cop-dem-glo-30-regional-controls-v2021_1.jsonl.gz"
    )
    previous_header, previous_rows, previous_payload = _manifest_records(
        previous_manifest_path
    )
    if previous_header["regions"] != contract["combinedSuite"]["existingWindows"]:
        raise EvidenceBuildError("Existing regional windows differ from the combined suite")

    source_ids = (
        "ipcc-ar6-sea-level",
        "copernicus-marine-eur-sla-monthly",
        "copernicus-marine-eur-mdt",
        "goco06s-gravity-model",
        "egm2008-gravity-model",
        "natural-earth-10m",
    )
    licences = _licence_evidence(source_lock, source_ids)
    licences.append(
        {
            "sourceId": terrain_binding["sourceId"],
            "version": terrain_binding["version"],
            **terrain_binding["licence"],
        }
    )
    return {
        "$schema": "./phase-0-12-basin-controls.schema.json",
        "schemaVersion": 1,
        "evidenceId": "phase-0.12-baltic-black-sea-controls-v1",
        "issue": 96,
        "evidenceDate": contract["evidenceDate"],
        "builderVersion": BUILDER_VERSION,
        "status": contract["status"],
        "realSourceOnly": True,
        "lineage": {
            "recipe": _file_lineage(
                repo_root, "scripts/science/build_basin_control_evidence.py"
            ),
            "contract": _file_lineage(
                repo_root, "src/pipeline/science/basin-controls.json"
            ),
            "contractSchema": _file_lineage(
                repo_root, "src/pipeline/science/basin-controls.schema.json"
            ),
            "evidenceSchema": _file_lineage(
                repo_root, EVIDENCE_SCHEMA_RELATIVE_PATH
            ),
            "sourceLock": _file_lineage(
                repo_root, "src/pipeline/sources/source-lock.json"
            ),
            "sourceLockSchema": _file_lineage(
                repo_root, "src/pipeline/sources/source-lock.schema.json"
            ),
            "supportGeometry": dict(contract["sourceBindings"]["geography"]["support"]),
            "coastalGeometry": dict(contract["sourceBindings"]["geography"]["coastal"]),
            "connectivityControls": dict(contract["sourceBindings"]["connectivity"]),
            "slaManifest": {
                "path": contract["sourceBindings"]["baseline"]["sla"]["manifestPath"],
                "sha256": contract["sourceBindings"]["baseline"]["sla"]["manifestSha256"],
                "payloadSha256": contract["sourceBindings"]["baseline"]["sla"][
                    "payloadSha256"
                ],
                "objectCount": monthly_header["objectCount"],
                "totalByteSize": monthly_header["totalByteSize"],
            },
            "terrainManifest": {
                "path": terrain_binding["manifestPath"],
                "sha256": terrain_binding["manifestSha256"],
                "payloadSha256": terrain_binding["payloadSha256"],
                "objectCount": terrain_binding["objectCount"],
                "totalByteSize": terrain_binding["totalByteSize"],
            },
            "existingTerrainManifest": {
                "path": previous_manifest_path.relative_to(repo_root).as_posix(),
                "sha256": _sha256(previous_manifest_path),
                "payloadSha256": hashlib.sha256(previous_payload).hexdigest(),
                "objectCount": len(previous_rows),
                "totalByteSize": previous_header["totalByteSize"],
            },
        },
        "sourceAndLicence": {
            "rawAssetsCommitted": False,
            "licences": licences,
        },
        "baseline": baseline,
        "marineAnchors": anchors,
        "terrain": {
            "manifestAssetsVerified": len(manifest_rows),
            "windows": dem,
        },
        "combinedSuite": {
            "existingWindowCount": len(previous_header["regions"]),
            "newWindowCount": len(contract["windows"]),
            "totalWindowCount": len(previous_header["regions"]) + len(contract["windows"]),
            "basins": ["Atlantic/North Sea", "Mediterranean/Adriatic", "Baltic Sea", "Black Sea"],
            "requiredContexts": contract["combinedSuite"]["requiredContexts"],
            "stateExpectations": states,
        },
        "connectivityComparison": contract["combinedSuite"]["connectivityComparison"],
        "review": contract["review"],
        "publicationGate": contract["publicationGate"],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--dem-dir", type=Path)
    parser.add_argument("--monthly-sla-dir", type=Path)
    parser.add_argument("--mdt", type=Path)
    parser.add_argument("--write-dem-manifest", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--validate-checked-in", action="store_true")
    args = parser.parse_args()

    repo_root = args.repo_root.resolve()
    action_selected = args.validate_checked_in
    if args.validate_checked_in:
        validate_checked_in_evidence(repo_root)
    if (args.write_dem_manifest or args.output) and args.dem_dir is None:
        parser.error("--write-dem-manifest and --output require --dem-dir")
    contract = _load_contract(repo_root)
    if args.write_dem_manifest:
        action_selected = True
        output = args.write_dem_manifest
        if not output.is_absolute():
            output = repo_root / output
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(build_dem_manifest(contract, args.dem_dir))
    if args.output:
        action_selected = True
        if args.monthly_sla_dir is None or args.mdt is None:
            parser.error("--output requires --monthly-sla-dir and --mdt")
        output = args.output if args.output.is_absolute() else repo_root / args.output
        evidence = build_evidence(
            repo_root,
            contract,
            args.dem_dir,
            args.monthly_sla_dir,
            args.mdt,
        )
        schema = json.loads(
            (repo_root / EVIDENCE_SCHEMA_RELATIVE_PATH).read_text(encoding="utf-8")
        )
        _validate_document(evidence, schema, "basin control evidence")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(_canonical_bytes(evidence))
    if not action_selected:
        parser.error("choose --write-dem-manifest and/or --output")


if __name__ == "__main__":
    main()
