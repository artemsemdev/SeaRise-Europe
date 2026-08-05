"""Test the deterministic analytical GeoParquet parity artifact."""

from __future__ import annotations

import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from searise_pipeline.release import (
    load_source_fixture,
    validate_geoparquet,
    write_geoparquet,
)
from searise_pipeline.science import ScienceContractError

from .test_source_fixture import FIXTURE_DIR, contract


def _real_source():
    receipt = json.loads((FIXTURE_DIR / "source-fixture-receipt.json").read_text(encoding="utf-8"))
    return load_source_fixture(
        FIXTURE_DIR / "source-fixture.json.gz",
        receipt=receipt,
        release_contract=contract(),
    )


@pytest.fixture(scope="module")
def geoparquet_case(tmp_path_factory: pytest.TempPathFactory):
    source = _real_source()
    path = tmp_path_factory.mktemp("geoparquet") / "baseline.parquet"
    write_geoparquet(source, path, contract=contract())
    return source, pq.read_table(path)


def test_geoparquet_is_byte_deterministic_and_exact(tmp_path: Path) -> None:
    source = _real_source()
    first = tmp_path / "first.parquet"
    second = tmp_path / "second.parquet"

    first_evidence = write_geoparquet(source, first, contract=contract())
    second_evidence = write_geoparquet(source, second, contract=contract())
    validate_geoparquet(first, source, contract=contract())

    assert first.read_bytes() == second.read_bytes()
    assert first_evidence.sha256 == second_evidence.sha256
    assert first_evidence.row_count == 27489
    assert first_evidence.byte_size <= contract()["budgets"]["geoparquetBytes"]
    assert first_evidence.valid_rows_by_layer == {
        "ssp1-26/2030": 3055,
        "ssp1-26/2050": 3055,
        "ssp1-26/2100": 3055,
        "ssp2-45/2030": 3054,
        "ssp2-45/2050": 3054,
        "ssp2-45/2100": 3054,
        "ssp5-85/2030": 3054,
        "ssp5-85/2050": 3054,
        "ssp5-85/2100": 3054,
    }


@pytest.mark.parametrize(
    ("tamper", "message"),
    [
        ("schema", "Arrow field types"),
        ("column-order", "column order"),
        ("crs", "geometry or index metadata"),
        ("bbox", "geometry or index metadata"),
        ("row-group", "row-group sizes"),
        ("compression", "ZSTD compression"),
        ("value", "median_mm values"),
        ("geometry", "geometry differs"),
        ("scientific-disposition", "release metadata"),
    ],
)
def test_geoparquet_rejects_semantic_tampering(
    tmp_path: Path,
    geoparquet_case,
    tamper: str,
    message: str,
) -> None:
    source, baseline = geoparquet_case
    release = contract()
    specification = release["artifacts"]["geoparquet"]
    table = baseline
    compression = specification["compression"]
    row_group_size = specification["rowGroupSize"]

    if tamper == "schema":
        table = table.set_column(
            table.schema.get_field_index("horizon"),
            "horizon",
            pa.array(table["horizon"].to_pylist(), type=pa.int32()),
        )
    elif tamper == "column-order":
        names = table.column_names
        names[0], names[1] = names[1], names[0]
        table = table.select(names)
    elif tamper in {"crs", "bbox", "scientific-disposition"}:
        metadata = dict(table.schema.metadata or {})
        if tamper in {"crs", "bbox"}:
            geo = json.loads(metadata[b"geo"])
            if tamper == "crs":
                geo["columns"]["geometry"]["crs"]["id"] = {
                    "authority": "EPSG",
                    "code": 3857,
                }
            else:
                geo["columns"]["geometry"]["bbox"] = [0, 0, 0, 0]
            metadata[b"geo"] = json.dumps(geo, sort_keys=True).encode()
        else:
            metadata[b"searise:scientific_disposition"] = b"flood-risk"
        table = table.replace_schema_metadata(metadata)
    elif tamper == "row-group":
        row_group_size -= 1
    elif tamper == "compression":
        compression = "NONE"
    elif tamper == "value":
        values = table["median_mm"].to_pylist()
        values[0] += 1
        table = table.set_column(
            table.schema.get_field_index("median_mm"),
            "median_mm",
            pa.array(values, type=pa.int16()),
        )
    else:
        geometry = table["geometry"].to_pylist()
        replacement = next(item for item in geometry if item != geometry[0])
        geometry[0] = replacement
        table = table.set_column(
            table.schema.get_field_index("geometry"),
            "geometry",
            pa.array(geometry, type=pa.binary()),
        )

    path = tmp_path / f"tampered-{tamper}.parquet"
    pq.write_table(
        table,
        path,
        compression=compression,
        row_group_size=row_group_size,
        use_dictionary=["scenario"],
    )

    with pytest.raises(ScienceContractError, match=message):
        validate_geoparquet(path, source, contract=release)
