"""Fail-closed scientific contracts for the offline pipeline."""

from .ar6 import (
    Ar6GridSlice,
    Ar6MemberIdentity,
    Ar6ProjectionInterval,
    bilinear_sample,
    extract_projection_grid,
    extract_projection_interval,
    projection_member_identity,
    validate_ar6_schema,
)
from .baseline import BaselineSurface, MonthlySlaField, reconstruct_baseline_surface
from .connectivity import (
    connectivity_comparison,
    evaluate_connectivity_controls,
    ocean_connected_cells,
)
from .contracts import (
    ScienceContractError,
    ScienceContracts,
    assert_publication_ready,
    load_science_contracts,
    projection_mapping,
    verify_geometry_assets,
    verify_terrain_source_bindings,
)
from .dem import (
    compare_dem_samples,
    compare_dem_windows,
    inspect_dem_sample,
    inspect_dem_window,
)
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
from .receipt import (
    assert_vertical_receipt_publishable,
    canonical_vertical_receipt_bytes,
    load_vertical_receipt,
    validate_vertical_receipt,
    vertical_receipt_sha256,
)
from .uncertainty import (
    UncertaintyAggregate,
    UncertaintyTerm,
    aggregate_absolute_bounds,
)
from .vertical import (
    NODATA_CLASS,
    REASON_LABELS,
    ClassificationReason,
    VerticalResult,
    reconcile_vertical_interval,
)

__all__ = [
    "Ar6GridSlice",
    "Ar6MemberIdentity",
    "Ar6ProjectionInterval",
    "BaselineSurface",
    "CandidateGeometries",
    "ClassificationReason",
    "GeoidCorrection",
    "GeoidEnginePolicy",
    "GeoidEvaluation",
    "GeoidModelRequest",
    "NODATA_CLASS",
    "REASON_LABELS",
    "ScienceContractError",
    "ScienceContracts",
    "UncertaintyAggregate",
    "UncertaintyTerm",
    "VerticalResult",
    "MonthlySlaField",
    "assert_publication_ready",
    "aggregate_absolute_bounds",
    "bilinear_sample",
    "build_geoid_requests",
    "compare_dem_samples",
    "compare_dem_windows",
    "canonical_geojson_bytes",
    "connectivity_comparison",
    "evaluate_connectivity_controls",
    "extract_projection_grid",
    "extract_projection_interval",
    "evaluate_geoid_correction",
    "load_science_contracts",
    "ocean_connected_cells",
    "inspect_dem_sample",
    "inspect_dem_window",
    "inspect_geometry_assets",
    "projection_mapping",
    "projection_member_identity",
    "reconstruct_baseline_surface",
    "reconcile_baseline_to_egm2008",
    "assert_vertical_receipt_publishable",
    "canonical_vertical_receipt_bytes",
    "load_vertical_receipt",
    "validate_vertical_receipt",
    "vertical_receipt_sha256",
    "reconcile_vertical_interval",
    "rebuild_approximation",
    "verify_geometry_assets",
    "verify_terrain_source_bindings",
    "validate_ar6_schema",
]
