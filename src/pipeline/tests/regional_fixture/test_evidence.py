"""Validate the committed real-source mechanics evidence and its limits."""

from __future__ import annotations

import json
from pathlib import Path

import rasterio

from searise_pipeline.regional_fixture.build import ATTRIBUTION, validate_fixture
from searise_pipeline.regional_fixture.lookup import RegionalFixture

FIXTURE_DIR = Path(__file__).parents[2] / "fixtures" / "regional"


def test_committed_real_source_outputs_match_build_receipt() -> None:
    validate_fixture(FIXTURE_DIR)


def test_real_dem_derivative_preserves_lineage_and_licence_notice() -> None:
    receipt = json.loads((FIXTURE_DIR / "build-receipt.json").read_text(encoding="utf-8"))
    with rasterio.open(FIXTURE_DIR / "copernicus-dem-window.cog.tif") as dataset:
        tags = dataset.tags()

        assert (dataset.height, dataset.width) == (256, 256)
        assert dataset.crs.to_epsg() == 4326
        assert dataset.block_shapes == [(128, 128)]
        assert tags["AREA_OR_POINT"] == "Point"
        assert tags["source_sha256"] == receipt["source"]["sha256"]
        assert tags["source_release"] == "2021_1"
        assert tags["derivative_notice"] == ATTRIBUTION
        assert tags["scientific_use"] == "blocked-domain-mechanics-only"

    assert receipt["source"]["byteSize"] == 17_037_271
    assert receipt["source"]["sha256"] == (
        "edb307664fd717ca1805e77e8e16ad3267f1992f2614b2d0127193dfdf6851f1"
    )


def test_every_shared_vector_is_bit_exact_in_python() -> None:
    fixture = RegionalFixture.load(FIXTURE_DIR / "lookup-fixture.json")
    golden = json.loads((FIXTURE_DIR / "golden-vectors.json").read_text(encoding="utf-8"))

    assert golden["classificationStatus"] == "blocked"
    assert golden["review"]["status"] == "pending"
    for vector in golden["vectors"]:
        result = fixture.lookup(
            vector["longitude"],
            vector["latitude"],
            vector["scenario"],
            vector["horizon"],
        )
        cell = (
            None
            if result.cell is None
            else {"row": result.cell.row, "column": result.cell.column}
        )
        assert result.state.value == vector["expectedState"], vector["id"]
        assert cell == vector["expectedCell"], vector["id"]


def test_all_nine_layers_are_blocked_without_scientific_arrays() -> None:
    fixture = RegionalFixture.load(FIXTURE_DIR / "lookup-fixture.json")
    receipt = json.loads((FIXTURE_DIR / "build-receipt.json").read_text(encoding="utf-8"))

    assert len(fixture.layers) == 9
    assert all(
        layer.status == "blocked" and layer.values is None
        for layer in fixture.layers.values()
    )
    assert receipt["methodologyGate"]["state"] == "blocked"
    assert receipt["methodologyGate"]["generatedScientificArtifacts"] == []
    assert receipt["methodologyGate"]["unlocksPhase1"] is False
    assert len(receipt["methodologyGate"]["layerMatrix"]) == 9
    assert not list(FIXTURE_DIR.glob("*.pmtiles"))
    assert not (FIXTURE_DIR / "classes").exists()


def test_checked_in_masks_are_derived_from_nonempty_real_geography() -> None:
    fixture = RegionalFixture.load(FIXTURE_DIR / "lookup-fixture.json")

    assert sum(fixture.support_mask) > 0
    assert sum(fixture.coastal_mask) > 0
    assert all(
        not coastal or support
        for coastal, support in zip(fixture.coastal_mask, fixture.support_mask)
    )


def test_delivery_measurement_is_exact_and_scoped_to_reference_profile() -> None:
    measurement = json.loads(
        (FIXTURE_DIR / "delivery-measurements.json").read_text(encoding="utf-8")
    )
    receipt = json.loads((FIXTURE_DIR / "build-receipt.json").read_text(encoding="utf-8"))
    cog = receipt["outputs"]["copernicus-dem-window.cog.tif"]

    assert measurement["artifacts"]["cogByteSize"] == cog["byteSize"]
    assert measurement["artifacts"]["cogSha256"] == cog["sha256"]
    assert measurement["byteRanges"]["requestCount"] == 3
    assert all(
        item["status"] == 206 and item["exactBytes"]
        for item in measurement["byteRanges"]["measurements"]
    )
    assert measurement["interpretation"]["supportsExactCogRangesOnReferenceProfile"]
    assert not measurement["interpretation"]["supportsProductionNetworkLatencyClaim"]
    assert measurement["artifacts"]["pmtiles"]["status"] == "not-generated"
