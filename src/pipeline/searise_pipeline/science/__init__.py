"""Fail-closed scientific contracts for the offline pipeline."""

from .ar6 import (
    Ar6GridSlice,
    Ar6ProjectionInterval,
    bilinear_sample,
    extract_projection_grid,
    extract_projection_interval,
    validate_ar6_schema,
)
from .baseline import BaselineSurface, MonthlySlaField, reconstruct_baseline_surface
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
from .geoid import (
    GeoidCorrection,
    GeoidEnginePolicy,
    GeoidEvaluation,
    GeoidModelRequest,
    build_geoid_requests,
    evaluate_geoid_correction,
    reconcile_baseline_to_egm2008,
)

__all__ = [
    "Ar6GridSlice",
    "Ar6ProjectionInterval",
    "BaselineSurface",
    "CandidateGeometries",
    "GeoidCorrection",
    "GeoidEnginePolicy",
    "GeoidEvaluation",
    "GeoidModelRequest",
    "ScienceContractError",
    "ScienceContracts",
    "MonthlySlaField",
    "assert_publication_ready",
    "bilinear_sample",
    "build_geoid_requests",
    "compare_dem_samples",
    "canonical_geojson_bytes",
    "connectivity_comparison",
    "extract_projection_grid",
    "extract_projection_interval",
    "evaluate_geoid_correction",
    "load_science_contracts",
    "ocean_connected_cells",
    "inspect_dem_sample",
    "inspect_geometry_assets",
    "projection_mapping",
    "reconstruct_baseline_surface",
    "reconcile_baseline_to_egm2008",
    "rebuild_approximation",
    "verify_geometry_assets",
    "validate_ar6_schema",
]
