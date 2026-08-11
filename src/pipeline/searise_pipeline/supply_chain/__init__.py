"""Fail-closed validation for versioned supply-chain contracts."""

from .contracts import (
    SupplyChainContractError,
    discover_dependency_inputs,
    load_json,
    parse_timestamp,
    validate_dependency_exception,
    validate_dependency_inventory,
    validate_evidence_files,
)
from .sbom import canonical_sbom_bytes, generate_npm_sbom

__all__ = [
    "SupplyChainContractError",
    "canonical_sbom_bytes",
    "discover_dependency_inputs",
    "generate_npm_sbom",
    "load_json",
    "parse_timestamp",
    "validate_dependency_exception",
    "validate_dependency_inventory",
    "validate_evidence_files",
]
