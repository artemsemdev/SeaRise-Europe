"""Test the deterministic analytical GeoParquet parity artifact."""

from __future__ import annotations

import json
from pathlib import Path

from searise_pipeline.release import (
    load_source_fixture,
    validate_geoparquet,
    write_geoparquet,
)

from .test_source_fixture import FIXTURE_DIR, contract


def _real_source():
    receipt = json.loads((FIXTURE_DIR / "source-fixture-receipt.json").read_text(encoding="utf-8"))
    return load_source_fixture(
        FIXTURE_DIR / "source-fixture.json.gz",
        receipt=receipt,
        release_contract=contract(),
    )


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
