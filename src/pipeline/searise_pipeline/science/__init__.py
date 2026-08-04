"""Fail-closed scientific contracts for the offline pipeline."""

from .ar6 import Ar6GridSlice, bilinear_sample, extract_projection_grid, validate_ar6_schema
from .contracts import (
    ScienceContractError,
    ScienceContracts,
    assert_publication_ready,
    load_science_contracts,
    projection_mapping,
    verify_geometry_assets,
)
from .dem import compare_dem_samples, inspect_dem_sample
from .geography import (
    CandidateGeometries,
    canonical_geojson_bytes,
    inspect_geometry_assets,
    rebuild_approximation,
)

__all__ = [
    "Ar6GridSlice",
    "CandidateGeometries",
    "ScienceContractError",
    "ScienceContracts",
    "assert_publication_ready",
    "bilinear_sample",
    "compare_dem_samples",
    "canonical_geojson_bytes",
    "extract_projection_grid",
    "load_science_contracts",
    "inspect_dem_sample",
    "inspect_geometry_assets",
    "projection_mapping",
    "rebuild_approximation",
    "verify_geometry_assets",
    "validate_ar6_schema",
]
