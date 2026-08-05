"""Atomic construction of the complete nine-layer AR6 regional release."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping

import numpy as np

from searise_pipeline.science.contracts import ScienceContractError

from .cog import CogEvidence, write_analysis_cog
from .geoparquet import GeoParquetEvidence, write_geoparquet
from .model import RegionalLayer, RegionalReleaseSource, assert_source_integrity
from .pmtiles import (
    PmtilesEvidence,
    validate_vector_toolchain,
    write_visual_pmtiles,
)
from .source_grid import SourceGridEvidence, write_source_grid
from .toolchain import validate_python_toolchain

_RELEASE_ID = re.compile(r"^[a-z0-9]+(?:[.-][a-z0-9]+)*$")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, document: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    path.write_text(encoded, encoding="utf-8")


@dataclass(frozen=True)
class ReleaseBuildResult:
    """Completed candidate location and its machine disposition."""

    output_directory: Path
    manifest: Mapping[str, Any]
    gate: Mapping[str, Any]
    build_duration_seconds: float


def _layer_statistics(layer: RegionalLayer) -> Mapping[str, Any]:
    valid = layer.valid
    statistics: dict[str, Any] = {
        "scenario": layer.scenario,
        "horizon": layer.horizon,
        "validCellCount": int(valid.sum()),
        "nodataCellCount": int(valid.size - valid.sum()),
        "quantiles": {},
    }
    for name, values in (
        ("lower", layer.lower_mm),
        ("central", layer.central_mm),
        ("upper", layer.upper_mm),
    ):
        selected = values[valid].astype(np.int64)
        statistics["quantiles"][name] = {
            "minimumMillimetres": int(selected.min()),
            "maximumMillimetres": int(selected.max()),
            "meanMillimetres": round(float(selected.mean()), 6),
        }
    return statistics


def _artifact_record(
    evidence: CogEvidence | GeoParquetEvidence | PmtilesEvidence | SourceGridEvidence,
    *,
    source: RegionalReleaseSource,
    contract: Mapping[str, Any],
    media_type: str,
    role: str,
    scenario: str | None = None,
    horizon: int | None = None,
) -> Mapping[str, Any]:
    record: dict[str, Any] = {
        "path": evidence.path,
        "mediaType": media_type,
        "role": role,
        "byteSize": evidence.byte_size,
        "sha256": evidence.sha256,
        "source": {
            "sourceId": contract["source"]["sourceId"],
            "release": contract["source"]["version"],
            "archiveSha256": source.archive_sha256,
        },
        "method": {
            "methodVersion": "ar6-regional-projection-v1",
            "scientificResampling": "none",
        },
        "rights": {
            "licence": contract["source"]["licence"],
            "attribution": contract["source"]["attribution"],
            "notice": "NOTICE.md",
        },
        "valueSemantics": {
            "baseline": contract["values"]["baseline"],
            "confidence": contract["values"]["confidence"],
            "quantiles": contract["matrix"]["quantiles"],
            "storageUnits": contract["values"]["storageUnits"],
            "publishedUnits": contract["values"]["publishedUnits"],
            "scaleToMetres": contract["values"]["scaleToMetres"],
            "scientificDisposition": contract["scientificDisposition"],
        },
    }
    if scenario is not None:
        record["scenario"] = scenario
    if horizon is not None:
        record["horizon"] = horizon
    if scenario is not None:
        member = next(
            layer.member_sha256
            for layer in source.layers
            if layer.scenario == scenario
        )
        record["source"] = {**record["source"], "memberSha256": member}
    else:
        record["source"] = {
            **record["source"],
            "memberSha256": {
                layer.scenario: layer.member_sha256
                for layer in source.layers
                if layer.horizon == 2030
            },
        }
    return record


def _attach_lineage(
    record: Mapping[str, Any],
    *,
    source: RegionalReleaseSource,
    contract: Mapping[str, Any],
) -> Mapping[str, Any]:
    scenario = record.get("scenario")
    source_lineage: dict[str, Any] = {
        "sourceId": contract["source"]["sourceId"],
        "release": contract["source"]["version"],
        "archiveSha256": source.archive_sha256,
    }
    if scenario:
        source_lineage["memberSha256"] = next(
            layer.member_sha256 for layer in source.layers if layer.scenario == scenario
        )
    else:
        source_lineage["memberSha256"] = {
            layer.scenario: layer.member_sha256
            for layer in source.layers
            if layer.horizon == 2030
        }
    return {
        **record,
        "source": source_lineage,
        "method": {
            "methodVersion": "ar6-regional-projection-v1",
            "scientificResampling": "none",
        },
        "rights": {
            "licence": contract["source"]["licence"],
            "attribution": contract["source"]["attribution"],
            "notice": "NOTICE.md",
        },
        "valueSemantics": {
            "baseline": contract["values"]["baseline"],
            "confidence": contract["values"]["confidence"],
            "quantiles": contract["matrix"]["quantiles"],
            "storageUnits": contract["values"]["storageUnits"],
            "publishedUnits": contract["values"]["publishedUnits"],
            "scaleToMetres": contract["values"]["scaleToMetres"],
            "scientificDisposition": contract["scientificDisposition"],
        },
    }


def _validate_lookup_goldens(
    source: RegionalReleaseSource,
    goldens_path: Path,
) -> Mapping[str, Any]:
    try:
        goldens = json.loads(goldens_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ScienceContractError(f"Cannot read AR6 lookup goldens: {exc}") from exc
    if goldens["provenance"]["archiveSha256"] != source.archive_sha256:
        raise ScienceContractError("Lookup goldens belong to another AR6 archive")
    expected_members = {
        layer.scenario: layer.member_sha256 for layer in source.layers if layer.horizon == 2030
    }
    golden_members = {
        {"ssp126": "ssp1-26", "ssp245": "ssp2-45", "ssp585": "ssp5-85"}[scenario]: digest
        for scenario, digest in goldens["provenance"]["memberSha256"].items()
    }
    if golden_members != expected_members:
        raise ScienceContractError("Lookup goldens belong to other AR6 members")
    layers = {(layer.scenario, layer.horizon): layer for layer in source.layers}
    available_count = 0
    declared_states = set()
    for result in goldens["results"]:
        declared_states.add(result["state"])
        if result["state"] != "ProjectionAvailable":
            continue
        available_count += 1
        positions = np.argwhere(source.location_ids == result["source"]["locationId"])
        if positions.shape != (1, 2):
            raise ScienceContractError("Golden source location is absent from regional grid")
        row, column = positions[0]
        for projection in result["projections"]:
            layer = layers[(projection["scenario"], projection["horizon"])]
            actual = (
                int(layer.lower_mm[row, column]),
                int(layer.central_mm[row, column]),
                int(layer.upper_mm[row, column]),
            )
            expected = (
                projection["lowerMillimetres"],
                projection["centralMillimetres"],
                projection["upperMillimetres"],
            )
            if actual != expected:
                raise ScienceContractError("Regional values differ from independent goldens")
    validation_binding = goldens["validationContract"]
    validation_path = goldens_path.parents[4] / validation_binding["path"]
    if _sha256(validation_path) != validation_binding["sha256"]:
        raise ScienceContractError("Lookup validation contract binding changed")
    validation = json.loads(validation_path.read_text(encoding="utf-8"))
    controls = {item["expectedState"] for item in validation["validation"]["algorithmicControls"]}
    required_states = {
        "ProjectionAvailable",
        "DataUnavailable",
        "OutOfScope",
        "UnsupportedGeography",
    }
    if declared_states | controls != required_states:
        raise ScienceContractError("Lookup goldens do not cover all four product states")
    return {
        "path": f"src/pipeline/science/evidence/{goldens_path.name}",
        "sha256": _sha256(goldens_path),
        "availableControlCount": available_count,
        "coveredStates": sorted(required_states),
        "numericToleranceMillimetres": 0,
    }


def _checksums(root: Path) -> None:
    entries = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        if path.name == "checksums.txt":
            continue
        entries.append(f"{_sha256(path)}  {path.relative_to(root).as_posix()}")
    (root / "checksums.txt").write_text("\n".join(entries) + "\n", encoding="utf-8")


def _write_notice(root: Path, contract: Mapping[str, Any]) -> Mapping[str, Any]:
    source = contract["source"]
    lines = [
        "# Third-party notice",
        "",
        source["attribution"],
        "",
        f"Canonical record: {source['canonicalRecord']}",
        f"Licence: {source['licence']} ({source['licenceUrl']})",
        "",
        "Required acknowledgements:",
        "",
        *[f"- {item}" for item in source["requiredAcknowledgements"]],
        "",
    ]
    path = root / "NOTICE.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return {
        "path": "NOTICE.md",
        "mediaType": "text/markdown",
        "role": "licence-notice",
        "byteSize": path.stat().st_size,
        "sha256": _sha256(path),
    }


def _write_stac(
    root: Path,
    artifacts: list[Mapping[str, Any]],
    *,
    release_id: str,
    source: RegionalReleaseSource,
    contract: Mapping[str, Any],
) -> list[Mapping[str, Any]]:
    """Write a deterministic STAC Collection and one Item per projection layer."""
    by_path = {item["path"]: item for item in artifacts}
    item_records: list[Mapping[str, Any]] = []
    item_links: list[Mapping[str, Any]] = []
    for scenario in contract["matrix"]["scenarios"]:
        for horizon in contract["matrix"]["horizons"]:
            item_id = f"{scenario}-{horizon}"
            item_path = root / f"stac/items/{item_id}.json"
            item_path.parent.mkdir(parents=True, exist_ok=True)
            cog_path = f"analysis/{scenario}/{horizon}.tif"
            pmtiles_path = f"layers/{scenario}/{horizon}.pmtiles"
            assets = {}
            for key, relative in (
                ("analysis", cog_path),
                ("visual", pmtiles_path),
                ("table", "analysis/projections.parquet"),
                ("source-grid", "analysis/source-grid.json.gz"),
            ):
                record = by_path[relative]
                assets[key] = {
                    "href": f"../../{relative}",
                    "type": record["mediaType"],
                    "roles": [record["role"]],
                    "file:size": record["byteSize"],
                    "checksum:multihash": f"1220{record['sha256']}",
                }
            document = {
                "stac_version": "1.0.0",
                "stac_extensions": [
                    "https://stac-extensions.github.io/file/v2.1.0/schema.json",
                    "https://stac-extensions.github.io/checksum/v1.0.0/schema.json",
                ],
                "type": "Feature",
                "id": item_id,
                "bbox": contract["grid"]["bounds"],
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[
                        [-30.5, 29.5], [45.5, 29.5], [45.5, 75.5],
                        [-30.5, 75.5], [-30.5, 29.5]
                    ]],
                },
                "properties": {
                    "datetime": f"{horizon}-01-01T00:00:00Z",
                    "scenario": scenario,
                    "baseline": contract["values"]["baseline"],
                    "confidence": contract["values"]["confidence"],
                    "scientific_disposition": contract["scientificDisposition"],
                    "attribution": contract["source"]["attribution"],
                    "source_release": contract["source"]["version"],
                    "source_archive_sha256": contract["source"]["archiveSha256"],
                    "source_member_sha256": by_path[cog_path]["source"]["memberSha256"],
                    "method_version": "ar6-regional-projection-v1",
                    "quantiles": contract["matrix"]["quantiles"],
                    "storage_units": contract["values"]["storageUnits"],
                    "published_units": contract["values"]["publishedUnits"],
                    "scale_to_metres": contract["values"]["scaleToMetres"],
                },
                "collection": release_id,
                "links": [
                    {"rel": "collection", "href": "../collection.json", "type": "application/json"},
                    {"rel": "license", "href": contract["source"]["licenceUrl"]},
                    {"rel": "cite-as", "href": contract["source"]["canonicalRecord"]},
                ],
                "assets": assets,
            }
            _write_json(item_path, document)
            record = {
                "path": f"stac/items/{item_id}.json",
                "mediaType": "application/geo+json",
                "role": "stac-item",
                "scenario": scenario,
                "horizon": horizon,
                "byteSize": item_path.stat().st_size,
                "sha256": _sha256(item_path),
            }
            item_records.append(record)
            item_links.append(
                {"rel": "item", "href": f"items/{item_id}.json", "type": "application/geo+json"}
            )
    collection_path = root / "stac/collection.json"
    horizons = contract["matrix"]["horizons"]
    collection = {
        "stac_version": "1.0.0",
        "type": "Collection",
        "id": release_id,
        "description": "Projection-only IPCC AR6 regional relative sea-level change.",
        "license": contract["source"]["licence"],
        "providers": [
            {
                "name": "IPCC AR6 projection authors via Zenodo",
                "roles": ["producer", "licensor"],
                "url": contract["source"]["canonicalRecord"],
            }
        ],
        "summaries": {
            "source_release": [contract["source"]["version"]],
            "source_archive_sha256": [contract["source"]["archiveSha256"]],
            "method_version": ["ar6-regional-projection-v1"],
            "baseline": [contract["values"]["baseline"]],
            "confidence": [contract["values"]["confidence"]],
        },
        "extent": {
            "spatial": {"bbox": [contract["grid"]["bounds"]]},
            "temporal": {
                "interval": [[
                    f"{min(horizons)}-01-01T00:00:00Z",
                    f"{max(horizons)}-01-01T00:00:00Z",
                ]]
            },
        },
        "links": [
            {"rel": "license", "href": contract["source"]["licenceUrl"]},
            {"rel": "cite-as", "href": contract["source"]["canonicalRecord"]},
            *item_links,
        ],
    }
    _write_json(collection_path, collection)
    records = [
        {
            "path": "stac/collection.json",
            "mediaType": "application/json",
            "role": "stac-collection",
            "byteSize": collection_path.stat().st_size,
            "sha256": _sha256(collection_path),
        },
        *item_records,
    ]
    _validate_stac(
        root,
        artifacts,
        release_id=release_id,
        source=source,
        contract=contract,
    )
    return records


def _validate_stac(
    root: Path,
    artifacts: list[Mapping[str, Any]],
    *,
    release_id: str,
    source: RegionalReleaseSource,
    contract: Mapping[str, Any],
) -> None:
    """Offline validation of collection, 3x3 Items, links, and bound assets."""
    collection = json.loads((root / "stac/collection.json").read_text(encoding="utf-8"))
    ordered_matrix = [
        (scenario, horizon)
        for scenario in contract["matrix"]["scenarios"]
        for horizon in contract["matrix"]["horizons"]
    ]
    expected_matrix = set(ordered_matrix)
    item_links = [
        {
            "rel": "item",
            "href": f"items/{scenario}-{horizon}.json",
            "type": "application/geo+json",
        }
        for scenario, horizon in ordered_matrix
    ]
    horizons = contract["matrix"]["horizons"]
    expected_collection = {
        "stac_version": "1.0.0",
        "type": "Collection",
        "id": release_id,
        "description": "Projection-only IPCC AR6 regional relative sea-level change.",
        "license": contract["source"]["licence"],
        "providers": [
            {
                "name": "IPCC AR6 projection authors via Zenodo",
                "roles": ["producer", "licensor"],
                "url": contract["source"]["canonicalRecord"],
            }
        ],
        "summaries": {
            "source_release": [contract["source"]["version"]],
            "source_archive_sha256": [contract["source"]["archiveSha256"]],
            "method_version": ["ar6-regional-projection-v1"],
            "baseline": [contract["values"]["baseline"]],
            "confidence": [contract["values"]["confidence"]],
        },
        "extent": {
            "spatial": {"bbox": [contract["grid"]["bounds"]]},
            "temporal": {
                "interval": [[
                    f"{min(horizons)}-01-01T00:00:00Z",
                    f"{max(horizons)}-01-01T00:00:00Z",
                ]]
            },
        },
        "links": [
            {"rel": "license", "href": contract["source"]["licenceUrl"]},
            {"rel": "cite-as", "href": contract["source"]["canonicalRecord"]},
            *item_links,
        ],
    }
    if collection != expected_collection:
        raise ScienceContractError(
            "STAC Collection envelope differs from the exact release contract"
        )
    expected_item_links = {
        f"items/{scenario}-{horizon}.json": (scenario, horizon)
        for scenario, horizon in expected_matrix
    }
    by_path = {item["path"]: item for item in artifacts}
    observed: set[tuple[str, int]] = set()
    for link in item_links:
        layer = expected_item_links.get(link.get("href"))
        if link.get("type") != "application/geo+json" or layer is None:
            raise ScienceContractError("STAC Collection Item links differ from the matrix")
        scenario, horizon = layer
        item_path = (root / "stac" / link["href"]).resolve()
        if (root / "stac/items").resolve() not in item_path.parents:
            raise ScienceContractError("STAC item link escapes the candidate")
        item = json.loads(item_path.read_text(encoding="utf-8"))
        observed.add((scenario, horizon))
        source_layer = next(
            (
                item
                for item in source.layers
                if item.scenario == scenario and item.horizon == horizon
            ),
            None,
        )
        if source_layer is None:
            raise ScienceContractError("STAC Item has no matching verified source layer")
        west, south, east, north = contract["grid"]["bounds"]
        expected_geometry = {
            "type": "Polygon",
            "coordinates": [[
                [west, south],
                [east, south],
                [east, north],
                [west, north],
                [west, south],
            ]],
        }
        if (
            item.get("stac_version") != "1.0.0"
            or item.get("stac_extensions")
            != [
                "https://stac-extensions.github.io/file/v2.1.0/schema.json",
                "https://stac-extensions.github.io/checksum/v1.0.0/schema.json",
            ]
            or item.get("type") != "Feature"
            or item.get("id") != f"{scenario}-{horizon}"
            or item.get("collection") != release_id
            or item.get("bbox") != contract["grid"]["bounds"]
            or item.get("geometry") != expected_geometry
        ):
            raise ScienceContractError("STAC Item identity or geometry differs from the matrix")
        expected_properties = {
            "datetime": f"{horizon}-01-01T00:00:00Z",
            "scenario": scenario,
            "baseline": contract["values"]["baseline"],
            "confidence": contract["values"]["confidence"],
            "scientific_disposition": contract["scientificDisposition"],
            "source_release": contract["source"]["version"],
            "source_archive_sha256": contract["source"]["archiveSha256"],
            "source_member_sha256": source_layer.member_sha256,
            "method_version": "ar6-regional-projection-v1",
            "quantiles": contract["matrix"]["quantiles"],
            "storage_units": contract["values"]["storageUnits"],
            "published_units": contract["values"]["publishedUnits"],
            "scale_to_metres": contract["values"]["scaleToMetres"],
            "attribution": contract["source"]["attribution"],
        }
        if item.get("properties") != expected_properties:
            raise ScienceContractError("STAC Item lineage differs from its artifacts")
        expected_links = {
            "collection": {
                "rel": "collection",
                "href": "../collection.json",
                "type": "application/json",
            },
            "license": {
                "rel": "license",
                "href": contract["source"]["licenceUrl"],
            },
            "cite-as": {
                "rel": "cite-as",
                "href": contract["source"]["canonicalRecord"],
            },
        }
        actual_links = item.get("links")
        if (
            not isinstance(actual_links, list)
            or len(actual_links) != len(expected_links)
            or not all(isinstance(item_link, Mapping) for item_link in actual_links)
            or {item_link.get("rel"): item_link for item_link in actual_links}
            != expected_links
        ):
            raise ScienceContractError("STAC Item rights links differ from the contract")
        expected_asset_paths = {
            "analysis": f"analysis/{scenario}/{horizon}.tif",
            "visual": f"layers/{scenario}/{horizon}.pmtiles",
            "table": "analysis/projections.parquet",
            "source-grid": "analysis/source-grid.json.gz",
        }
        expected_assets = {}
        for key, relative in expected_asset_paths.items():
            record = by_path.get(relative)
            if record is None:
                raise ScienceContractError("STAC Item source artifacts are incomplete")
            expected_assets[key] = {
                "href": f"../../{relative}",
                "type": record["mediaType"],
                "roles": [record["role"]],
                "file:size": record["byteSize"],
                "checksum:multihash": f"1220{record['sha256']}",
            }
        if item.get("assets") != expected_assets:
            raise ScienceContractError("STAC Item asset inventory differs from sealed artifacts")
        for asset in expected_assets.values():
            target = (item_path.parent / asset["href"]).resolve()
            if root.resolve() not in target.parents or not target.is_file():
                raise ScienceContractError("STAC asset target is missing or unsafe")
            relative = target.relative_to(root.resolve()).as_posix()
            record = by_path.get(relative)
            if (
                record is None
                or asset.get("file:size") != record["byteSize"]
                or asset.get("checksum:multihash") != f"1220{record['sha256']}"
                or asset.get("roles") != [record["role"]]
                or _sha256(target) != record["sha256"]
            ):
                raise ScienceContractError("STAC asset is not bound to manifest bytes")
    if observed != expected_matrix:
        raise ScienceContractError("STAC Items differ from the exact 3 x 3 matrix")


def build_regional_release(
    source: RegionalReleaseSource,
    output_directory: Path,
    *,
    release_id: str,
    contract: Mapping[str, Any],
    tippecanoe_path: Path,
    decode_path: Path,
    pmtiles_path: Path,
    tippecanoe_source_archive_path: Path,
    tippecanoe_build_receipt_path: Path,
    pmtiles_distribution_asset_path: Path,
    pmtiles_distribution_platform: str,
    python_lock_path: Path,
    lookup_goldens_path: Path,
    build_environment_id: str,
    source_revision: str,
    workflow_started_monotonic: float | None = None,
) -> ReleaseBuildResult:
    """Build an immutable candidate; external evidence is finalized separately."""
    started = workflow_started_monotonic or time.perf_counter()
    if started > time.perf_counter():
        raise ScienceContractError("Workflow start timestamp cannot be in the future")
    if not _RELEASE_ID.fullmatch(release_id):
        raise ScienceContractError("Release ID contains unsafe or non-canonical characters")
    if not build_environment_id.strip():
        raise ScienceContractError("A non-empty clean build environment ID is required")
    if not re.fullmatch(r"[0-9a-f]{40}", source_revision):
        raise ScienceContractError("Source revision must be one exact Git commit SHA")
    if output_directory.exists():
        raise ScienceContractError(f"Immutable release path already exists: {output_directory}")
    assert_source_integrity(source, contract, require_verified_archive=False)
    if source.archive_and_members_verified_this_build and workflow_started_monotonic is None:
        raise ScienceContractError(
            "Verified-archive builds must time the workflow from before source verification"
        )
    output_directory.parent.mkdir(parents=True, exist_ok=True)
    python_toolchain = validate_python_toolchain(python_lock_path, contract=contract)
    toolchain = validate_vector_toolchain(
        tippecanoe_path=tippecanoe_path,
        decode_path=decode_path,
        pmtiles_path=pmtiles_path,
        tippecanoe_source_archive_path=tippecanoe_source_archive_path,
        tippecanoe_build_receipt_path=tippecanoe_build_receipt_path,
        pmtiles_distribution_asset_path=pmtiles_distribution_asset_path,
        pmtiles_distribution_platform=pmtiles_distribution_platform,
        contract=contract,
    )
    lookup_evidence = _validate_lookup_goldens(source, lookup_goldens_path)
    with tempfile.TemporaryDirectory(
        prefix="searise-release-", dir=output_directory.parent
    ) as temporary:
        temporary_root = Path(temporary).resolve()
        root = temporary_root / release_id
        if root.resolve().parent != temporary_root:
            raise ScienceContractError("Release ID escapes the private staging directory")
        root.mkdir()
        cogs: list[CogEvidence] = []
        pmtiles: list[PmtilesEvidence] = []
        for layer in source.layers:
            cog_path = root / f"analysis/{layer.scenario}/{layer.horizon}.tif"
            cogs.append(write_analysis_cog(layer, cog_path, contract=contract))
        geoparquet = write_geoparquet(
            source,
            root / "analysis/projections.parquet",
            contract=contract,
        )
        source_grid = write_source_grid(
            source,
            root / "analysis/source-grid.json.gz",
            contract=contract,
        )
        for layer in source.layers:
            archive_path = root / f"layers/{layer.scenario}/{layer.horizon}.pmtiles"
            pmtiles.append(
                write_visual_pmtiles(
                    source,
                    layer,
                    archive_path,
                    contract=contract,
                    tippecanoe_path=tippecanoe_path,
                    decode_path=decode_path,
                    pmtiles_path=pmtiles_path,
                    tippecanoe_source_archive_path=tippecanoe_source_archive_path,
                    tippecanoe_build_receipt_path=tippecanoe_build_receipt_path,
                    pmtiles_distribution_asset_path=pmtiles_distribution_asset_path,
                    pmtiles_distribution_platform=pmtiles_distribution_platform,
                )
            )
        statistics = {
            "schemaVersion": 1,
            "releaseId": release_id,
            "storageUnits": "mm",
            "nodata": contract["values"]["nodata"],
            "layers": [_layer_statistics(layer) for layer in source.layers],
        }
        _write_json(root / "statistics.json", statistics)

        artifacts: list[Mapping[str, Any]] = []
        by_layer = {(layer.scenario, layer.horizon): layer for layer in source.layers}
        for evidence in cogs:
            parts = Path(evidence.path).parts
            artifacts.append(
                _artifact_record(
                    evidence,
                    source=source,
                    contract=contract,
                    media_type="image/tiff; application=geotiff; profile=cloud-optimized",
                    role="exact-browser-lookup",
                    scenario=parts[1],
                    horizon=int(Path(parts[2]).stem),
                )
            )
        artifacts.append(
            _artifact_record(
                geoparquet,
                source=source,
                contract=contract,
                media_type="application/vnd.apache.parquet",
                role="analytical-parity",
            )
        )
        for evidence in pmtiles:
            parts = Path(evidence.path).parts
            layer = by_layer[(parts[1], int(Path(parts[2]).stem))]
            artifacts.append(
                _artifact_record(
                    evidence,
                    source=source,
                    contract=contract,
                    media_type="application/vnd.pmtiles",
                    role="visual-only",
                    scenario=layer.scenario,
                    horizon=layer.horizon,
                )
            )
        artifacts.append(
            _artifact_record(
                source_grid,
                source=source,
                contract=contract,
                media_type="application/gzip",
                role="source-grid-identity",
            )
        )
        notice = _write_notice(root, contract)
        stac = _write_stac(
            root,
            artifacts,
            release_id=release_id,
            source=source,
            contract=contract,
        )
        artifacts.extend(
            [
                _attach_lineage(notice, source=source, contract=contract),
                *[
                    _attach_lineage(record, source=source, contract=contract)
                    for record in stac
                ],
            ]
        )
        totals = {
            "cogBytes": sum(item.byte_size for item in cogs),
            "pmtilesBytes": sum(item.byte_size for item in pmtiles),
            "geoparquetBytes": geoparquet.byte_size,
        }
        totals["coreArtifactBytes"] = sum(totals.values())
        budgets = contract["budgets"]
        budget_passed = (
            totals["cogBytes"] <= budgets["cogTotalBytes"]
            and totals["pmtilesBytes"] <= budgets["pmtilesTotalBytes"]
            and totals["geoparquetBytes"] <= budgets["geoparquetBytes"]
            and totals["coreArtifactBytes"] <= budgets["coreArtifactsTotalBytes"]
        )
        build_evidence = {
            "schemaVersion": 1,
            "releaseId": release_id,
            "checks": {
                "sourceArchiveAndMembersVerified": (
                    source.archive_and_members_verified_this_build
                ),
                "completeScenarioHorizonMatrix": len(source.layers) == 9,
                "sourceContentSeal": True,
                "nonAllNodataLayers": len(cogs) == 9
                and all(item.valid_cells > 0 for item in cogs),
                "cogStructureAndValues": len(cogs) == 9,
                "sourceGridIdentity": source_grid.cell_count
                == contract["grid"]["width"] * contract["grid"]["height"],
                "geoparquetSchemaAndValues": geoparquet.row_count
                == sum(item.source_feature_count for item in pmtiles),
                "pmtilesStructureAndProperties": len(pmtiles) == 9,
                "crossArtifactSemanticParity": all(
                    cog.valid_cells == tile.source_feature_count for cog, tile in zip(cogs, pmtiles)
                ),
                "lookupGoldenParity": True,
                "licenceAndAttribution": contract["source"]["licence"]
                == "CC-BY-4.0"
                and len(contract["source"]["requiredAcknowledgements"]) == 2
                and notice["sha256"] == _sha256(root / "NOTICE.md"),
                "artifactBudgets": budget_passed,
            },
            "lookupGoldenEvidence": lookup_evidence,
            "totals": totals,
        }
        source_receipt = {
            "schemaVersion": 1,
            "sourceMode": source.source_mode,
            "archiveSha256": source.archive_sha256,
            "archiveAndMembersVerifiedThisBuild": (
                source.archive_and_members_verified_this_build
            ),
            "memberSha256": {
                layer.scenario: layer.member_sha256
                for layer in source.layers
                if layer.horizon == 2030
            },
            "releaseContractSha256": source.contract_sha256,
            "licence": contract["source"]["licence"],
            "attribution": contract["source"]["attribution"],
            "canonicalRecord": contract["source"]["canonicalRecord"],
            "requiredAcknowledgements": contract["source"]["requiredAcknowledgements"],
            "notice": notice,
            "sourceContentSha256": source.content_sha256,
        }
        build_receipt = {
            "schemaVersion": 1,
            "releaseId": release_id,
            "sourceRevision": source_revision,
            "toolchainPins": contract["toolchain"],
            "environmentIdentity": {
                "buildRunId": build_environment_id,
                "python": asdict(python_toolchain),
                "vector": asdict(toolchain),
            },
            "normalizedParameters": {
                "nativeResolutionDegrees": 1,
                "pmtilesMaximumZoom": contract["artifacts"]["pmtiles"]["maximumZoom"],
                "scientificResampling": "none",
                "pmtilesCanonicalMetadata": True,
            },
        }
        manifest = {
            "schemaVersion": 1,
            "releaseId": release_id,
            "releaseContractId": contract["releaseContractId"],
            "scientificDisposition": contract["scientificDisposition"],
            "publicationStatus": "pending-owner",
            "modeledQuantity": "regional-relative-sea-level-change",
            "baseline": contract["values"]["baseline"],
            "confidence": contract["values"]["confidence"],
            "storageUnits": "mm",
            "scaleToMetres": contract["values"]["scaleToMetres"],
            "nativeResolutionDegrees": contract["grid"]["nativeResolutionDegrees"],
            "grid": contract["grid"],
            "matrix": contract["matrix"],
            "source": source_receipt,
            "artifacts": artifacts,
            "totals": totals,
            "limitations": [
                "projection-only-not-flood-inundation-terrain-or-property-risk",
                "pmtiles-visual-only",
                "geoparquet-nearest-selection-prohibited",
                "cog-is-the-only-exact-browser-lookup-artifact",
            ],
        }
        _write_json(root / "source-receipt.json", source_receipt)
        _write_json(root / "build-receipt.json", build_receipt)
        _write_json(root / "build-evidence.json", build_evidence)
        _write_json(root / "manifest.json", manifest)
        from .gate import evaluate_recovery_gate

        gate = evaluate_recovery_gate(
            build_evidence,
            contract=contract,
            reproducibility_report=None,
            delivery_report=None,
        )
        _write_json(root / "gate.json", gate)
        _checksums(root)
        os.replace(root, output_directory)
    duration = round(time.perf_counter() - started, 6)
    return ReleaseBuildResult(
        output_directory=output_directory,
        manifest=manifest,
        gate=gate,
        build_duration_seconds=duration,
    )
