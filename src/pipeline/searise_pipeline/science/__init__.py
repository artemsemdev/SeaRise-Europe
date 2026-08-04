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

__all__ = [
    "Ar6GridSlice",
    "ScienceContractError",
    "ScienceContracts",
    "assert_publication_ready",
    "bilinear_sample",
    "extract_projection_grid",
    "load_science_contracts",
    "projection_mapping",
    "verify_geometry_assets",
    "validate_ar6_schema",
]
