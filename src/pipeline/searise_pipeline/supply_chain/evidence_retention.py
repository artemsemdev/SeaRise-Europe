"""Append-only handoff for release-lifetime supply-chain evidence."""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from searise_pipeline.candidate_completeness import (
    CandidateContractError,
    validate_candidate_root,
)

from .candidate_evidence import (
    _ENVELOPE,
    _MANIFEST,
    _PROVENANCE,
    _SBOM_PATHS,
    _SIGNATURE_PATHS,
    _open_root,
    _strict_json,
    _validate_candidate_evidence_pair,
)
from .contracts import REPOSITORY_ROOT, SupplyChainContractError, _validate_schema
from .production_evidence import (
    _MAX_BUNDLE_BYTES,
    _MAX_MANIFEST_BYTES,
    _MAX_TOTAL_READ_BYTES,
    _close_quietly,
    _new_stage,
    _output_parent,
    _publish,
    _read_bounded,
    _read_external,
    _ReadBudget,
    _require_absent,
    _require_current_path,
    _require_parent_outside_authorities,
    _snapshot_fd,
    _validate_tree,
)
from .sbom import canonical_sbom_bytes

_CRYPTO = PurePosixPath("receipts/cryptographic-verification.json")
_READBACK = PurePosixPath("receipts/public-readback.json")
_RETENTION = PurePosixPath("retention-receipt.json")
_SCHEMA_URI = (
    "https://artemsemdev.github.io/SeaRise-Europe/contracts/supply-chain/v1/"
    "release-evidence-retention-receipt.schema.json"
)
_EVIDENCE_PATHS = (_ENVELOPE, _PROVENANCE) + tuple(
    PurePosixPath(path) for path in (*_SIGNATURE_PATHS, *_SBOM_PATHS)
)
_MAX_RECEIPT_BYTES = 2 * 1024 * 1024


@dataclass(frozen=True)
class ReleaseEvidenceRetention:
    """Identity committed with one complete release-lifetime evidence handoff."""

    candidate_id: str
    data_release_id: str
    output_root: Path
    deterministic_identity: str
    retained_file_count: int


def _fail(message: str) -> None:
    raise SupplyChainContractError(message)


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _canonical(document: Mapping[str, Any]) -> bytes:
    return canonical_sbom_bytes(document)


def _candidate(path: Path) -> Any:
    try:
        return validate_candidate_root(path)
    except CandidateContractError as exc:
        raise SupplyChainContractError(str(exc)) from exc


def _receipt(
    path: Path,
    label: str,
    schema_name: str,
    budget: _ReadBudget,
) -> tuple[bytes, dict[str, Any]]:
    raw = _read_external(path, label, budget)
    if len(raw) > _MAX_RECEIPT_BYTES:
        _fail(f"{label} exceeds its {_MAX_RECEIPT_BYTES}-byte limit")
    document = _strict_json(raw, label)
    if raw != _canonical(document):
        _fail(f"{label} must be canonical JSON")
    _validate_schema(document, schema_name)
    return raw, document


def _descriptor(path: PurePosixPath, raw: bytes) -> dict[str, object]:
    return {"path": path.as_posix(), "byteSize": len(raw), "sha256": _sha256(raw)}


def _subject_map(receipt: Mapping[str, Any], label: str) -> dict[str, Mapping[str, Any]]:
    subjects = receipt.get("subjects")
    if not isinstance(subjects, list) or not all(isinstance(item, Mapping) for item in subjects):
        _fail(f"{label} subjects are invalid")
    result = {str(item.get("path")): item for item in subjects}
    if len(result) != len(subjects):
        _fail(f"{label} subjects are duplicated")
    return result


def _bind_receipts(
    manifest_raw: bytes,
    evidence: Mapping[PurePosixPath, bytes],
    cryptographic_raw: bytes,
    cryptographic: Mapping[str, Any],
    readback: Mapping[str, Any],
    *,
    candidate_id: str,
    data_release_id: str,
    data_provenance_class: str,
) -> str:
    shared = ("candidateId", "dataReleaseId", "controlledBuildRunId")
    if any(cryptographic.get(key) != readback.get(key) for key in shared):
        _fail("verification receipts identify different candidate runs")
    if (
        cryptographic.get("candidateId") != candidate_id
        or cryptographic.get("dataReleaseId") != data_release_id
        or cryptographic.get("dataProvenanceClass") != data_provenance_class
        or readback.get("cryptographicVerificationReceiptSha256") != _sha256(cryptographic_raw)
    ):
        _fail("verification receipts differ from the exact candidate evidence authority")
    crypto_subjects = _subject_map(cryptographic, "cryptographic receipt")
    public_subjects = _subject_map(readback, "public-readback receipt")
    exact_subjects = {
        "manifest.json": manifest_raw,
        "provenance.intoto.jsonl": evidence[_PROVENANCE],
    }
    for logical, raw in exact_subjects.items():
        expected = _sha256(raw)
        crypto = crypto_subjects.get(logical)
        public = public_subjects.get(logical)
        if (
            crypto is None
            or public is None
            or crypto.get("sha256") != expected
            or crypto.get("verified") is not True
            or public.get("sha256") != expected
            or public.get("byteSize") != len(raw)
            or public.get("matchesCryptographicallyVerifiedSubject") is not True
        ):
            _fail(f"verification receipt subject binding differs: {logical}")
    for logical, bundle in zip(("manifest.json", "provenance.intoto.jsonl"), _SIGNATURE_PATHS):
        subject = crypto_subjects[logical]
        if subject.get("bundlePath") != bundle or subject.get("bundleSha256") != _sha256(
            evidence[PurePosixPath(bundle)]
        ):
            _fail(f"cryptographic receipt bundle binding differs: {bundle}")
    run_id = cryptographic.get("controlledBuildRunId")
    if not isinstance(run_id, str):
        _fail("controlled build run ID is invalid")
    return run_id


def _retention_document(
    files: Mapping[PurePosixPath, bytes],
    *,
    candidate_id: str,
    data_release_id: str,
    data_provenance_class: str,
    controlled_build_run_id: str,
) -> tuple[dict[str, Any], bytes]:
    document: dict[str, Any] = {
        "$schema": _SCHEMA_URI,
        "schemaVersion": "1.0.0",
        "receiptType": "phase-1-release-evidence-retention-v1",
        "candidateId": candidate_id,
        "dataReleaseId": data_release_id,
        "dataProvenanceClass": data_provenance_class,
        "controlledBuildRunId": controlled_build_run_id,
        "files": [
            _descriptor(path, files[path])
            for path in sorted(files, key=lambda item: item.as_posix())
        ],
        "retention": {
            "class": "immutable-release-lifetime",
            "coRetainedWithDataRelease": True,
            "overwriteAllowed": False,
            "correctionPolicy": "new-data-release-id",
        },
        "claims": {
            "completeHandoff": True,
            "cryptographicVerificationReceiptRetained": True,
            "publicReadbackReceiptRetained": True,
            "productionClaim": False,
            "publicationApproval": False,
            "scientificApproval": False,
        },
    }
    document["deterministicIdentity"] = _sha256(_canonical(document))
    _validate_schema(document, "release-evidence-retention-receipt.schema.json")
    return document, _canonical(document)


def retain_release_evidence(
    candidate_root: Path,
    evidence_root: Path,
    cryptographic_receipt: Path,
    public_readback_receipt: Path,
    output_root: Path,
    *,
    repository_root: Path = REPOSITORY_ROOT,
) -> ReleaseEvidenceRetention:
    """Publish one complete no-overwrite handoff under an exact data-release prefix."""
    candidate = _candidate(candidate_root)

    budget = _ReadBudget(_MAX_TOTAL_READ_BYTES)
    candidate_descriptor = evidence_descriptor = -1
    output_parent = stage_descriptor = -1
    try:
        candidate_descriptor = _open_root(candidate_root, "retention candidate")
        evidence_descriptor = _open_root(evidence_root, "retention evidence")
        candidate_identity = os.fstat(candidate_descriptor)
        evidence_identity = os.fstat(evidence_descriptor)
        manifest_raw = _read_bounded(
            candidate_descriptor,
            _MANIFEST,
            "retention manifest",
            maximum=_MAX_MANIFEST_BYTES,
            budget=budget,
        )
        _strict_json(manifest_raw, "retention manifest")
        evidence_files = {
            logical: _read_bounded(
                evidence_descriptor,
                logical,
                f"retention evidence {logical}",
                maximum=_MAX_BUNDLE_BYTES,
                budget=budget,
            )
            for logical in _EVIDENCE_PATHS
        }
        evidence_baseline = _validate_tree(evidence_descriptor, evidence_files)
        cryptographic_raw, cryptographic = _receipt(
            cryptographic_receipt,
            "cryptographic verification receipt",
            "cryptographic-verification-receipt.schema.json",
            budget,
        )
        readback_raw, readback = _receipt(
            public_readback_receipt,
            "public-readback verification receipt",
            "public-readback-verification-receipt.schema.json",
            budget,
        )
        trusted_invocation = cryptographic.get("trustedInvocationUri")
        if not isinstance(trusted_invocation, str):
            _fail("cryptographic receipt invocation is invalid")
        pair = _validate_candidate_evidence_pair(
            candidate_root,
            evidence_root,
            repository_root=repository_root,
            trusted_invocation_uri=trusted_invocation,
            allow_production_envelope=True,
        )
        if pair.candidate_id != candidate.candidate_id:
            _fail("candidate and finalized evidence identities differ")
        run_id = _bind_receipts(
            manifest_raw,
            evidence_files,
            cryptographic_raw,
            cryptographic,
            readback,
            candidate_id=candidate.candidate_id,
            data_release_id=candidate.data_release_id,
            data_provenance_class=pair.data_provenance_class,
        )
        if (
            not output_root.is_absolute()
            or output_root.name != "supply-chain"
            or output_root.parent.name != candidate.data_release_id
        ):
            _fail("retention output must be an absolute dataReleaseId/supply-chain path")
        retained = {
            _MANIFEST: manifest_raw,
            **evidence_files,
            _CRYPTO: cryptographic_raw,
            _READBACK: readback_raw,
        }
        receipt, receipt_raw = _retention_document(
            retained,
            candidate_id=candidate.candidate_id,
            data_release_id=candidate.data_release_id,
            data_provenance_class=pair.data_provenance_class,
            controlled_build_run_id=run_id,
        )
        stage_files = {**retained, _RETENTION: receipt_raw}

        output_parent = _output_parent(output_root)
        output_parent_identity = os.fstat(output_parent)
        _require_absent(output_parent, output_root.name)
        for left, right in (
            (candidate_root, repository_root),
            (evidence_root, cryptographic_receipt.parent),
            (public_readback_receipt.parent, repository_root),
        ):
            _require_parent_outside_authorities(
                output_parent,
                candidate_root=left,
                repository_root=right,
                label="retention output parent",
            )
        stage_name, stage_descriptor, stage_identity = _new_stage(output_parent)
        for logical, raw in stage_files.items():
            _snapshot_fd(stage_descriptor, logical, raw)
        os.fsync(stage_descriptor)
        stage_baseline = _validate_tree(stage_descriptor, stage_files)

        if _candidate(candidate_root) != candidate:
            _fail("candidate changed before retention handoff publication")
        _validate_tree(evidence_descriptor, evidence_files, baseline=evidence_baseline)
        _require_current_path(candidate_root, candidate_descriptor, candidate_identity, "candidate")
        _require_current_path(evidence_root, evidence_descriptor, evidence_identity, "evidence")
        reread_budget = _ReadBudget(2 * _MAX_RECEIPT_BYTES)
        if (
            _read_external(
                cryptographic_receipt, "cryptographic verification receipt", reread_budget
            )
            != cryptographic_raw
            or _read_external(
                public_readback_receipt, "public-readback verification receipt", reread_budget
            )
            != readback_raw
        ):
            _fail("verification receipt changed before retention publication")
        _publish(
            output_parent,
            output_parent_identity,
            stage_identity,
            stage_descriptor,
            stage_files,
            stage_baseline,
            output_root.parent,
            stage_name,
            output_root.name,
        )
    finally:
        _close_quietly(stage_descriptor)
        _close_quietly(output_parent)
        _close_quietly(evidence_descriptor)
        _close_quietly(candidate_descriptor)
    return ReleaseEvidenceRetention(
        candidate_id=candidate.candidate_id,
        data_release_id=candidate.data_release_id,
        output_root=output_root,
        deterministic_identity=str(receipt["deterministicIdentity"]),
        retained_file_count=len(stage_files),
    )
