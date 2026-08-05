"""Exact analytical GeoParquet parity artifact for AR6 regional values."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import numpy as np

from searise_pipeline.science.contracts import ScienceContractError

from .model import RegionalReleaseSource


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
    metadata.update(
        {
            b"searise:release_contract_id": contract["releaseContractId"].encode(),
            b"searise:source_archive_sha256": source.archive_sha256.encode(),
            b"searise:scientific_disposition": contract["scientificDisposition"].encode(),
            b"searise:semantic_role": specification["role"].encode(),
            b"searise:nearest_selection": specification["nearestSelection"].encode(),
        }
    )
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
    specification = contract["artifacts"]["geoparquet"]
    parquet = pq.ParquetFile(path)
    metadata = parquet.metadata.metadata
    required_metadata = {
        b"searise:release_contract_id": contract["releaseContractId"].encode(),
        b"searise:source_archive_sha256": source.archive_sha256.encode(),
        b"searise:semantic_role": b"analytical-parity",
        b"searise:nearest_selection": b"prohibited",
    }
    if any(metadata.get(key) != value for key, value in required_metadata.items()):
        raise ScienceContractError("GeoParquet release metadata differs from the contract")
    actual = gpd.read_parquet(path)
    expected_columns, _ = _records(source)
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
