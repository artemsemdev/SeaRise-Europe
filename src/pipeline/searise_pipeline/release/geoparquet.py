"""Exact analytical GeoParquet parity artifact for AR6 regional values."""

from __future__ import annotations

import base64
import hashlib
import json
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import numpy as np

from searise_pipeline.science.contracts import ScienceContractError

from .model import RegionalReleaseSource

_ARROW_SCHEMA_KEY = b"ARROW:schema"
_CANONICAL_ARROW_SCHEMA_SHA256 = (
    "66ca08a3ca8b5a6ca52f71d3b4980eb56f72261ed82c811500729769eb2db51c"
)
_CANONICAL_ARROW_SCHEMA = zlib.decompress(
    base64.b64decode(
        b"eNq9WVt7osoS/UH7IVxksn3YD6CCGMFRkdubQJRLg87xgvDrT1V3o8ZJcnIm37d9iEJ3162rVq3uPD3BR1AdVVXn"
        b"Kvu8qGpP1baqrqpbdbCl7zTtzXiN36Pr+Kx+Yc8wEYfGNayFEVgR0Nc1LB/ScSYORQ0Oz+enp9X1WaO/wqGdWZ7V"
        b"hN68njl2HkgjYeboRZCbgp3rxM6TzG63TVDCmFP07DZow6HV2Lklz4ywDL1VO3OKemZYTZCrim2sFItZnuCfWHLT"
        b"uCRt6OzbSHabQHI3gT/J1waRQrffro1RYzsBTi2eITTm1T51gX8CT0mjMRHWnp1GA7GGtftkXOCQ+yg/9MQ0qhb7"
        b"QOw3kXQh1L8ZCL108YOo0HhpML4ngbzYR1LvGEnK4XWuvj7KCyRCUF5YktyXFvtY1s6xhLb0TxDPHdo7vdlL1we+"
        b"KU09V4zLfh0uRYhrAjoUtB1+X0jg22TqBxeYGj3ou477kn0GvU3g2YIvkUL9mcPO/U2DxHZtR3cedOzWHsTDcDEg"
        b"4YO8U+jpTeiDDNkmkeHmiUHOESbE0KlpqGsub7obwq9nsySn0HB7VP/YPUaVlc0yLfKX9dYs+TvS30flgrwabmvm"
        b"u60nCgdzMMkh3mLkKeydfMiiUj+GS/MHjEEc3RPuW9SYOLdce+4h1PunwBMJzjcrOw9hn8Hus5mBrkpLQUcai33h"
        b"1df4HPcEOXAOjVU2HahZVLnHeEw2yZjUnZ5kDDrKmI17rhB4izQxRujDKfEuhw348dpMbnrL9Aw6f0AO0DWwzxCn"
        b"xebO9l0kT/avZf/0oV0Qs2Q4kuh4qYiRrym+vFBisHOWqdnaUwTLCb5uU2WfE6gPqI1DJNkp3TOIeTj4MHafza+h"
        b"fgrIqfs47aNqLtlsHGwQ61f30Z9AYP6IJDEAC/xFimMQ80M0hv0ev9nfQyQnJCb9Y7T8wMbyck4kt/El8fivxRFs"
        b"Dw2SRp/a9ducj+J1sbPP4tXZ/aV4ifFY+zxelVvHxr8dr4REEtg/nihMZrgHPCp8xC6PyQwl94yy4qqgcmNDB7zQ"
        b"23u9gME14PNHNXoOSsTd+cd2uQxP4tKF9/0GbQM7D4BzDWCIwuKjKfC7iWRW60npNoDL5yhDHSbsVe8yzdUMfbyL"
        b"nRT6kxaxm8rIzZPV9BqzEhC1KZ6yvbfgdys8PfUDbc7xcVToFB8rrVlDj4krsgmk/gFy4fR+7N7g5/ObceYPiUrE"
        b"MsDbhsbFX0LFoS+BPGnZHLOIJXuHPY1jlZCMtXaW/X2Ox5PzOlMAu+JzNydu+pI16MlTmfa2X7HUP00BV9eGewyW"
        b"Cn1muXTbqwXsZyhP0thI94FgL1cMn285ARavGrVnD9TdXJw4s+F8z/yDPQP/fMB16DfHoLwQ7tf9WrDvUpgj9H0B"
        b"dUFyU7eVWF6QaKleZs5WMI279bx+Im9CYt53/m95g3QVl/oJe/TLctKfDjD2t/x1JeAFxnxL/TZc6OPWdiWTFvrn"
        b"0RyOFPBv+zKKZatV95AXj3XrQy84hANtHHr9IvSBZzSa8wr9NfSErYXcCOK0aLey1RTZb/X1NfvHljMSrcF31gey"
        b"/a31sWRl31ifj9rZEtazOoZ+etnHY/u89ua8Fu72Q0gcc7hlvaYCjuKRTeTpvyDOwBHTfYy1MQxa4J8Xq40PDItD"
        b"yA/kSOEBcBZir9CeD/IasOFk5SvZys0WOGVL67/U8wB5p2cr17pnvQ975A/c48CHXACsWfsLNqdw5yuBYQvUeUH3"
        b"H+yw8rC/6biQPCkAYwGj3E3c5RCrgTbxJnc4DT3AIDXU3x6w8sDyXO+t/XdyvLiLrXE5R2UCXNdF/WhvGpQT4HPh"
        b"HvxG3kpj6Bi8rkvgpyXneBQHJ8gleWyBO/lzhs+GW8E88k5+3+c1xvYLunXhA90niI+wZnEWo5IILBYLAnhDQqhN"
        b"36f5Adyw3/WGWSTPt2tJAa7Q4z4Bf/VG97XL30+ySN6yfKL8Z7HzpQtyHyHxFjSWUziT0N4guW2iIzdSKthfMWTY"
        b"d7ScLR2Pyn6TGOkmAl/uxhVrgHqAS8vAByHGoXSTjWtZHpCC73mKNiBXxN5HYyMkw64XcJkZx9Bsw3yvIN5HiHfT"
        b"8Qma7/ohWxl95BwZ491XX6OpY9XQ1w7msPuei+w7hm8t4XIf+tzoZC17NbcF4qkLkWzyWrzsgwrwvyqu/b3r6Sxv"
        b"aK1d9xvlTPMR2k+PUvR8BWvg1IGPAp5Ff+FvYzumh1B4/gt7q6UavMniZ4mH3YGK72ImBJqsju9VfvbV6Hl1BdNw"
        b"norzuw99Nm79lL2lp0YBp9F+bbcKnJfU6/NPi/Vv8D9m/fbZH9z6K/z+4QPXT8aLOm53Z9ZDd5jD1VTmPdS3zkmu"
        b"nuymj+euX2vIuyhTIH9TwK3RiT6TOpvqdUb5jltnM3j+rceKbA6tOz7nioODdLgiFvQREpvZJX6vz6Ktr+LD+i/0"
        b"NcBJPB9ncA7ksrtea8dmvo/+ROaLjmdUpQVs2YNdBx8xFXybVUeQr4tQV3i+El67WLias+D+U1zF9/noYlNcvcCe"
        b"MCzk+/HFfhu31jVepOjic4/pXJ6+0u0xtzNHnMX3tN9WYn86RpuxN7kYj/ir/W42jNsXl/m09ha4Fv24wwPC5NGe"
        b"knA7ERNQz+5iOasW6/aP4j+KcX39Tf3Cd/TbeSx8U7/4Lf1t0HxTv/QN/Y3lWMq39LeqsvHFBNfDeeuw9rU2km55"
        b"/B5O8BzGet7DGTFdQw/zJeQUWMs7CbhSD+ySmU0K7Qeh2y+xx4H9J3hX0dzPi940N0W7NRurXUmWLKDcNJBsEXh0"
        b"3tWtlfXqP6/vjjcxv9/jTZ2vsey+wc77eATehceu8/N3zLrfq/uezW1/4DAK35fLFbfhPAb90ab3exwzKIfi6ymP"
        b"4e+L0EtgLuxh9XvuvLWj4xUd7uoZ9FySlITf1bA1yKW4nmLtT/jdJLexhLNeBRznUzvEhMYYznyRrHUY+oZTdXHA"
        b"s/VbjFW4bcg10i6H8b5WWAN3unJB9C8TgBuhnoQ8ciOUOXVGPTre2XzHy3B85qiHa1ylO47LekHPGgv/M8+QWz3i"
        b"OPxmvRPWQT1nmznjG3N3snTE+Efop3hWoLxodndPw/jDFnkIu1+/Xqrz++Ir39Ab6PvytEr+EzA6svpYPj3j0EnH"
        b"n3hLPPwL+QiIHIwe5Hf64eXtXojdnx/wXwXq9SZcLfizpjKr49t9MP1M8A/0L6gv/YR3R/Q++icsYuqoVK97npv0"
        b"eXy7v77jV7f7OibZeWL2qxo12myf3vgzmL/1R0M+pl3v+yFHcl5zGzgHAj8bXuXRlVb+IE99iA+6ql3vYvl+mfh+"
        b"cJ0z6oxY4ThwvzH/v8n8FqSR/r58Gv/bPXXdjXdL//nnvxvGnRI="
    )
)

if hashlib.sha256(_CANONICAL_ARROW_SCHEMA).hexdigest() != _CANONICAL_ARROW_SCHEMA_SHA256:
    raise RuntimeError("Canonical Arrow schema payload is corrupt")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _replace_arrow_schema_payload(path: Path, generated: bytes) -> None:
    """Replace Arrow's architecture-specific schema with the pinned payload."""
    if len(generated) != len(_CANONICAL_ARROW_SCHEMA):
        raise ScienceContractError("Generated Arrow schema length differs from the pin")
    payload = path.read_bytes()
    if payload.count(_ARROW_SCHEMA_KEY) != 1 or payload.count(generated) != 1:
        raise ScienceContractError("GeoParquet Arrow schema payload is not unique")
    if generated != _CANONICAL_ARROW_SCHEMA:
        path.write_bytes(payload.replace(generated, _CANONICAL_ARROW_SCHEMA, 1))


def _canonicalize_arrow_schema(path: Path, *, parquet: Any) -> None:
    metadata = parquet.ParquetFile(path).metadata.metadata or {}
    try:
        generated = metadata[_ARROW_SCHEMA_KEY]
    except KeyError as exc:
        raise ScienceContractError("GeoParquet Arrow schema is missing") from exc
    _replace_arrow_schema_payload(path, generated)
    canonical = parquet.ParquetFile(path).metadata.metadata or {}
    if canonical.get(_ARROW_SCHEMA_KEY) != _CANONICAL_ARROW_SCHEMA:
        raise ScienceContractError("GeoParquet Arrow schema canonicalization failed")


def _table_with_canonical_schema(table: Any, *, arrow: Any) -> Any:
    """Bind arrays to the pinned logical and metadata schema before writing."""
    try:
        schema = arrow.ipc.read_schema(
            arrow.BufferReader(base64.b64decode(_CANONICAL_ARROW_SCHEMA))
        )
    except (ValueError, arrow.ArrowInvalid) as exc:
        raise ScienceContractError("Pinned Arrow schema cannot be decoded") from exc
    if table.column_names != schema.names or any(
        column.type != field.type for column, field in zip(table.columns, schema)
    ):
        raise ScienceContractError("GeoParquet staging table differs from the pin")
    return arrow.Table.from_arrays(table.columns, schema=schema)


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
    import pyarrow as pa

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
    table = _table_with_canonical_schema(pq.read_table(path), arrow=pa)
    pq.write_table(
        table,
        path,
        compression=specification["compression"],
        row_group_size=specification["rowGroupSize"],
        use_dictionary=["scenario"],
    )
    _canonicalize_arrow_schema(path, parquet=pq)
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
    if (
        metadata.get(_ARROW_SCHEMA_KEY) != _CANONICAL_ARROW_SCHEMA
        or path.read_bytes().count(_ARROW_SCHEMA_KEY) != 1
    ):
        raise ScienceContractError("GeoParquet must contain one canonical Arrow schema")
