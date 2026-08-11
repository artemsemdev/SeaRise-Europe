"""Fail-closed validation for versioned supply-chain contracts."""

from .candidate_evidence import CandidateEvidenceSummary, validate_candidate_evidence_pair
from .contracts import (
    SupplyChainContractError,
    discover_dependency_inputs,
    load_json,
    parse_timestamp,
    validate_dependency_exception,
    validate_dependency_inventory,
    validate_evidence_files,
)
from .nuget_sbom import generate_nuget_sbom, publish_nuget_sbom, validate_nuget_sbom
from .python_graph import validate_python_lock_graph
from .python_sbom import generate_python_sbom, publish_python_sbom, validate_python_sbom
from .sbom import (
    canonical_sbom_bytes,
    generate_npm_sbom,
    publish_npm_sbom,
    validate_npm_sbom,
    write_new_sbom,
)
from .sigstore_verifier import (
    verify_candidate_evidence_cryptographically,
)

__all__ = [
    "CandidateEvidenceSummary",
    "SupplyChainContractError",
    "canonical_sbom_bytes",
    "discover_dependency_inputs",
    "generate_npm_sbom",
    "generate_nuget_sbom",
    "generate_python_sbom",
    "load_json",
    "parse_timestamp",
    "publish_npm_sbom",
    "publish_nuget_sbom",
    "publish_python_sbom",
    "validate_dependency_exception",
    "validate_dependency_inventory",
    "validate_candidate_evidence_pair",
    "validate_evidence_files",
    "validate_npm_sbom",
    "validate_nuget_sbom",
    "validate_python_lock_graph",
    "validate_python_sbom",
    "verify_candidate_evidence_cryptographically",
    "write_new_sbom",
]
