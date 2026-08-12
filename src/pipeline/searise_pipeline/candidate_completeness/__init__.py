"""Offline validation for the Phase 1 pre-sign candidate contract."""

from .assembler import (
    CandidateAssemblyError,
    CandidateAssemblySummary,
    assemble_candidate_fixture,
)
from .byte_gate import CandidateByteSummary, validate_candidate_root
from .provenance import (
    ProvenanceContractError,
    canonical_provenance_bytes,
    generate_provenance_statement,
    validate_provenance_statement,
)
from .qa_execution import (
    CandidateQaArtifactResult,
    CandidateQaExecution,
    PreGateQaExecution,
    execute_candidate_qa,
    execute_pre_gate_qa,
)
from .qa_report import build_pre_gate_report
from .validator import (
    CandidateContractError,
    CandidateSummary,
    load_candidate,
    load_candidate_bytes,
    validate_candidate,
    validate_candidate_document,
)

__all__ = [
    "CandidateAssemblyError",
    "CandidateAssemblySummary",
    "CandidateContractError",
    "CandidateByteSummary",
    "CandidateQaArtifactResult",
    "CandidateQaExecution",
    "CandidateSummary",
    "ProvenanceContractError",
    "PreGateQaExecution",
    "assemble_candidate_fixture",
    "canonical_provenance_bytes",
    "build_pre_gate_report",
    "execute_candidate_qa",
    "execute_pre_gate_qa",
    "generate_provenance_statement",
    "load_candidate",
    "load_candidate_bytes",
    "validate_candidate",
    "validate_candidate_document",
    "validate_candidate_root",
    "validate_provenance_statement",
]
