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
from .cosign_tool import CosignToolSummary, validate_cosign_tool_lock
from .evidence_retention import (
    ReleaseEvidenceRetention,
    retain_release_evidence,
    validate_release_evidence_retention,
)
from .nuget_sbom import generate_nuget_sbom, publish_nuget_sbom, validate_nuget_sbom
from .protected_workflow_artifacts import (
    CandidateArtifactAuthority,
    ProtectedWorkflowArtifactError,
    extract_protected_candidate,
    extract_protected_evidence,
    load_candidate_artifact_authority,
    validate_candidate_artifact_authority,
    write_candidate_artifact_authority,
)
from .public_readback import PublicReadbackVerification, verify_public_signed_subjects
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
from .static_profile import validate_static_target_profile

__all__ = [
    "CandidateEvidenceSummary",
    "CandidateArtifactAuthority",
    "CosignToolSummary",
    "ProtectedWorkflowArtifactError",
    "PublicReadbackVerification",
    "ReleaseEvidenceRetention",
    "SupplyChainContractError",
    "canonical_sbom_bytes",
    "discover_dependency_inputs",
    "extract_protected_candidate",
    "extract_protected_evidence",
    "generate_npm_sbom",
    "generate_nuget_sbom",
    "generate_python_sbom",
    "load_json",
    "load_candidate_artifact_authority",
    "parse_timestamp",
    "publish_npm_sbom",
    "publish_nuget_sbom",
    "publish_python_sbom",
    "retain_release_evidence",
    "validate_release_evidence_retention",
    "validate_dependency_exception",
    "validate_dependency_inventory",
    "validate_candidate_evidence_pair",
    "validate_candidate_artifact_authority",
    "validate_cosign_tool_lock",
    "validate_evidence_files",
    "validate_npm_sbom",
    "validate_nuget_sbom",
    "validate_python_lock_graph",
    "validate_python_sbom",
    "validate_static_target_profile",
    "verify_candidate_evidence_cryptographically",
    "verify_public_signed_subjects",
    "write_new_sbom",
    "write_candidate_artifact_authority",
]
