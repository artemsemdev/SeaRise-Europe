"""Exact analytical GeoParquet parity artifact for AR6 regional values."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import numpy as np

from searise_pipeline.science.contracts import ScienceContractError

from .model import RegionalReleaseSource

_ARROW_SCHEMA_KEY = b"ARROW:schema"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class GeoParquetEvidence:
    """Identity and row counts for the analytical parity artifact."""

    path: str
    byte_size: int
    sha256: str
    row_count: int
    valid_rows_by_layer: Mapping[str, int]


def _dependencies() -> tuple[Any, Any, Any]:
    try:
        import geopandas as gpd
        import pandas as pd
        import pyarrow.parquet as pq
    except ImportError as exc:
        raise ScienceContractError(
            "GeoParquet output requires the exact pinned geopandas and pyarrow toolchain"
        ) from exc
    return gpd, pd, pq


def _records(source: RegionalReleaseSource) -> tuple[dict[str, list[Any]], dict[str, int]]:
    columns: dict[str, list[Any]] = {
        "scenario": [],
        "horizon": [],
        "source_location_id": [],
        "lower_mm": [],
        "median_mm": [],
        "upper_mm": [],
        "longitude": [],
        "latitude": [],
    }
    counts: dict[str, int] = {}
    for layer in source.layers:
        rows, columns_index = np.nonzero(layer.valid)
        key = f"{layer.scenario}/{layer.horizon}"
        counts[key] = int(rows.size)
        for row, column in zip(rows.tolist(), columns_index.tolist()):
            columns["scenario"].append(layer.scenario)
            columns["horizon"].append(layer.horizon)
            columns["source_location_id"].append(int(source.location_ids[row, column]))
            columns["lower_mm"].append(int(layer.lower_mm[row, column]))
            columns["median_mm"].append(int(layer.central_mm[row, column]))
            columns["upper_mm"].append(int(layer.upper_mm[row, column]))
            columns["longitude"].append(float(source.longitudes[column]))
            columns["latitude"].append(float(source.latitudes[row]))
    return columns, counts


def _expected_records(source: RegionalReleaseSource) -> dict[str, list[Any]]:
    """Derive validation rows directly, independently of the writer oracle."""
    expected: dict[str, list[Any]] = {
        "scenario": [],
        "horizon": [],
        "source_location_id": [],
        "lower_mm": [],
        "median_mm": [],
        "upper_mm": [],
        "longitude": [],
        "latitude": [],
    }
    for layer in source.layers:
        for row in range(layer.valid.shape[0]):
            for column in range(layer.valid.shape[1]):
                if not bool(layer.valid[row, column]):
                    continue
                expected["scenario"].append(str(layer.scenario))
                expected["horizon"].append(int(layer.horizon))
                expected["source_location_id"].append(int(source.location_ids[row, column]))
                expected["lower_mm"].append(int(layer.lower_mm[row, column]))
                expected["median_mm"].append(int(layer.central_mm[row, column]))
                expected["upper_mm"].append(int(layer.upper_mm[row, column]))
                expected["longitude"].append(float(source.longitudes[column]))
                expected["latitude"].append(float(source.latitudes[row]))
    return expected


def write_geoparquet(
    source: RegionalReleaseSource,
    path: Path,
    *,
    contract: Mapping[str, Any],
) -> GeoParquetEvidence:
    """Write valid rows only; this table must never drive nearest selection."""
    gpd, pd, pq = _dependencies()
    specification = contract["artifacts"]["geoparquet"]
    if specification["nearestSelection"] != "prohibited":
        raise ScienceContractError("GeoParquet cannot replace exact COG source-node lookup")
    columns, counts = _records(source)
    frame = pd.DataFrame(columns).astype(
        {
            "scenario": "string",
            "horizon": "int16",
            "source_location_id": "int64",
            "lower_mm": "int16",
            "median_mm": "int16",
            "upper_mm": "int16",
            "longitude": "float64",
            "latitude": "float64",
        }
    )
    frame = frame.sort_values(
        ["scenario", "horizon", "source_location_id"], kind="stable"
    ).reset_index(drop=True)
    geometry = gpd.points_from_xy(
        frame.pop("longitude"),
        frame.pop("latitude"),
        crs=specification["crs"],
    )
    geodata = gpd.GeoDataFrame(frame, geometry=geometry, crs=specification["crs"])
    path.parent.mkdir(parents=True, exist_ok=True)
    geodata.to_parquet(
        path,
        index=False,
        compression=specification["compression"],
        geometry_encoding=specification["geometryEncoding"],
        schema_version=specification["schemaVersion"],
        row_group_size=specification["rowGroupSize"],
    )
    table = pq.read_table(path)
    metadata = dict(table.schema.metadata or {})
    # The Parquet writer owns ARROW:schema. Keeping the schema emitted by the
    # GeoPandas staging write would create a duplicate key beside the writer's
    # fresh copy. Arrow serializes schema metadata in insertion order, so sort
    # every remaining key before the final write to make that copy portable.
    metadata.pop(_ARROW_SCHEMA_KEY, None)
    metadata.update(
        {
            b"searise:release_contract_id": contract["releaseContractId"].encode(),
            b"searise:source_archive_sha256": source.archive_sha256.encode(),
            b"searise:scientific_disposition": contract["scientificDisposition"].encode(),
            b"searise:semantic_role": specification["role"].encode(),
            b"searise:nearest_selection": specification["nearestSelection"].encode(),
        }
    )
    metadata = dict(sorted(metadata.items()))
    pq.write_table(
        table.replace_schema_metadata(metadata),
        path,
        compression=specification["compression"],
        row_group_size=specification["rowGroupSize"],
        use_dictionary=["scenario"],
    )
    validate_geoparquet(path, source, contract=contract)
    return GeoParquetEvidence(
        path="analysis/projections.parquet",
        byte_size=path.stat().st_size,
        sha256=_sha256(path),
        row_count=len(geodata),
        valid_rows_by_layer=counts,
    )


def validate_geoparquet(
    path: Path,
    source: RegionalReleaseSource,
    *,
    contract: Mapping[str, Any],
) -> None:
    """Require exact values, IDs, points, CRS, schema, and GeoParquet metadata."""
    gpd, _, pq = _dependencies()
    import pyarrow as pa

    specification = contract["artifacts"]["geoparquet"]
    parquet = pq.ParquetFile(path)
    metadata = parquet.metadata.metadata or {}
    required_metadata = {
        b"searise:release_contract_id": contract["releaseContractId"].encode(),
        b"searise:source_archive_sha256": source.archive_sha256.encode(),
        b"searise:scientific_disposition": contract["scientificDisposition"].encode(),
        b"searise:semantic_role": b"analytical-parity",
        b"searise:nearest_selection": b"prohibited",
    }
    if any(metadata.get(key) != value for key, value in required_metadata.items()):
        raise ScienceContractError("GeoParquet release metadata differs from the contract")
    if _ARROW_SCHEMA_KEY not in metadata or path.read_bytes().count(_ARROW_SCHEMA_KEY) != 1:
        raise ScienceContractError("GeoParquet must contain one canonical Arrow schema")
    expected_fields = [
        ("scenario", pa.string()),
        ("horizon", pa.int16()),
        ("source_location_id", pa.int64()),
        ("lower_mm", pa.int16()),
        ("median_mm", pa.int16()),
        ("upper_mm", pa.int16()),
        ("geometry", pa.binary()),
    ]
    actual_fields = [(field.name, field.type) for field in parquet.schema_arrow]
    if actual_fields != expected_fields:
        raise ScienceContractError(
            "GeoParquet Arrow field types or column order differ from the contract"
        )
    try:
        geo_metadata = json.loads(metadata[b"geo"])
        pandas_metadata = json.loads(metadata[b"pandas"])
    except (KeyError, json.JSONDecodeError) as exc:
        raise ScienceContractError("GeoParquet metadata is absent or malformed") from exc
    geometry_metadata = geo_metadata.get("columns", {}).get("geometry", {})
    crs_id = geometry_metadata.get("crs", {}).get("id", {})
    valid = np.logical_or.reduce([layer.valid for layer in source.layers])
    rows, columns = np.nonzero(valid)
    expected_bbox = [
        float(source.longitudes[columns].min()),
        float(source.latitudes[rows].min()),
        float(source.longitudes[columns].max()),
        float(source.latitudes[rows].max()),
    ]
    bbox = geometry_metadata.get("bbox")
    if (
        geo_metadata.get("version") != specification["schemaVersion"]
        or geo_metadata.get("primary_column") != "geometry"
        or set(geo_metadata.get("columns", {})) != {"geometry"}
        or set(geometry_metadata) != {"encoding", "geometry_types", "crs", "bbox"}
        or geometry_metadata.get("encoding") != specification["geometryEncoding"]
        or geometry_metadata.get("geometry_types") != [specification["geometryType"]]
        or crs_id != {"authority": "OGC", "code": "CRS84"}
        or not isinstance(bbox, list)
        or len(bbox) != 4
        or any(type(value) not in (int, float) for value in bbox)
        or [float(value) for value in bbox] != expected_bbox
        or pandas_metadata.get("index_columns") != []
    ):
        raise ScienceContractError("GeoParquet 1.1 geometry or index metadata differs")
    expected_row_groups = [specification["rowGroupSize"]] * (
        parquet.metadata.num_rows // specification["rowGroupSize"]
    )
    remainder = parquet.metadata.num_rows % specification["rowGroupSize"]
    if remainder:
        expected_row_groups.append(remainder)
    actual_row_groups = [
        parquet.metadata.row_group(index).num_rows
        for index in range(parquet.metadata.num_row_groups)
    ]
    if actual_row_groups != expected_row_groups:
        raise ScienceContractError("GeoParquet row-group sizes differ from the contract")
    for row_group_index in range(parquet.metadata.num_row_groups):
        row_group = parquet.metadata.row_group(row_group_index)
        if any(
            row_group.column(column).compression != "ZSTD"
            for column in range(row_group.num_columns)
        ):
            raise ScienceContractError("GeoParquet columns must all use ZSTD compression")
    actual = gpd.read_parquet(path)
    expected_columns = _expected_records(source)
    expected = gpd.GeoDataFrame(
        {
            "scenario": expected_columns["scenario"],
            "horizon": np.asarray(expected_columns["horizon"], dtype=np.int16),
            "source_location_id": np.asarray(
                expected_columns["source_location_id"], dtype=np.int64
            ),
            "lower_mm": np.asarray(expected_columns["lower_mm"], dtype=np.int16),
            "median_mm": np.asarray(expected_columns["median_mm"], dtype=np.int16),
            "upper_mm": np.asarray(expected_columns["upper_mm"], dtype=np.int16),
        },
        geometry=gpd.points_from_xy(
            expected_columns["longitude"],
            expected_columns["latitude"],
            crs=specification["crs"],
        ),
        crs=specification["crs"],
    ).sort_values(["scenario", "horizon", "source_location_id"], kind="stable")
    expected = expected.reset_index(drop=True)
    if list(actual.columns) != list(expected.columns) or len(actual) != len(expected):
        raise ScienceContractError("GeoParquet schema or row count differs from source")
    key_columns = ["scenario", "horizon", "source_location_id"]
    actual_keys = list(actual[key_columns].itertuples(index=False, name=None))
    if actual_keys != sorted(actual_keys) or len(actual_keys) != len(set(actual_keys)):
        raise ScienceContractError("GeoParquet keys must be sorted and unique")
    for column in (
        "scenario",
        "horizon",
        "source_location_id",
        "lower_mm",
        "median_mm",
        "upper_mm",
    ):
        if actual[column].tolist() != expected[column].tolist():
            raise ScienceContractError(f"GeoParquet {column} values differ from source")
    if actual.crs is None or actual.crs.to_string() != specification["crs"]:
        raise ScienceContractError("GeoParquet CRS differs from the contract")
    if not actual.geometry.equals(expected.geometry):
        raise ScienceContractError("GeoParquet source-node geometry differs from source")
