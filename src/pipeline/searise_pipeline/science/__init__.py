"""Fail-closed scientific contracts for the offline pipeline."""

from .ar6 import (
    Ar6GridSlice,
    Ar6ProjectionInterval,
    bilinear_sample,
    extract_projection_grid,
    extract_projection_interval,
    validate_ar6_schema,
)
from .connectivity import connectivity_comparison, ocean_connected_cells
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
    "Ar6ProjectionInterval",
    "CandidateGeometries",
    "ScienceContractError",
    "ScienceContracts",
    "assert_publication_ready",
    "bilinear_sample",
    "compare_dem_samples",
    "canonical_geojson_bytes",
    "connectivity_comparison",
    "extract_projection_grid",
    "extract_projection_interval",
    "load_science_contracts",
    "ocean_connected_cells",
    "inspect_dem_sample",
    "inspect_geometry_assets",
    "projection_mapping",
    "rebuild_approximation",
    "verify_geometry_assets",
    "validate_ar6_schema",
]
