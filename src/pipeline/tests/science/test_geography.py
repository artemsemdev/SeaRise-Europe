"""Tests for deterministic approximation rebuilds and geometry QA."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import geopandas as gpd
from shapely.geometry import box

from searise_pipeline.science import (
    canonical_geojson_bytes,
    inspect_geometry_assets,
    load_science_contracts,
    rebuild_approximation,
)

REPO_ROOT = Path(__file__).parents[4]
CONTRACT_DIR = REPO_ROOT / "src" / "pipeline" / "science"


def test_checked_in_geometry_passes_all_named_controls() -> None:
    rules = load_science_contracts(CONTRACT_DIR).geography_rules

    report = inspect_geometry_assets(
        REPO_ROOT,
        rules,
        CONTRACT_DIR / "geography-controls.json",
    )

    assert report["support"]["valid"] is True
    assert report["coastal"]["valid"] is True
    assert report["controls"]["passed"] == report["controls"]["count"] == 19
    assert report["topology"]["boundaryControl"]["covers"] is True
    assert report["topology"]["boundaryControl"]["contains"] is False


def test_rebuild_and_serialization_are_deterministic(tmp_path: Path) -> None:
    admin_path = tmp_path / "admin.geojson"
    ocean_path = tmp_path / "ocean.geojson"
    gpd.GeoDataFrame(
        {
            "CONTINENT": ["Europe", "Asia"],
            "NAME": ["Example", "Other"],
            "geometry": [box(0, 0, 1, 1), box(2, 2, 3, 3)],
        },
        crs=4326,
    ).to_file(admin_path, driver="GeoJSON")
    gpd.GeoDataFrame(
        {"geometry": [box(-1, -1, 0.2, 2)]},
        crs=4326,
    ).to_file(ocean_path, driver="GeoJSON")
    rules = deepcopy(load_science_contracts(CONTRACT_DIR).geography_rules)
    rules["support"]["recipe"].update(
        {"selectedFeatureCount": 1, "clipBoundsWgs84": [-2, -2, 2, 2]}
    )
    rules["coastal"]["recipe"]["oceanClipBoundsWgs84"] = [-2, -2, 2, 2]

    first = rebuild_approximation(admin_path, ocean_path, rules)
    second = rebuild_approximation(admin_path, ocean_path, rules)
    properties = {"status": "approximation", "version": "test"}

    assert canonical_geojson_bytes("support", first.support, properties) == (
        canonical_geojson_bytes("support", second.support, properties)
    )
    assert canonical_geojson_bytes("coastal", first.coastal, properties) == (
        canonical_geojson_bytes("coastal", second.coastal, properties)
    )
