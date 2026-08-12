"""Atomic local handoff for exact release supply-chain evidence bytes."""

from __future__ import annotations

import hashlib
import os
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Iterator, Mapping

from searise_pipeline.candidate_completeness import (
    CandidateContractError,
    validate_candidate_document,
    validate_candidate_root,
)

from .candidate_evidence import (
    _ENVELOPE,
    _MANIFEST,
    _PROVENANCE,
    _RECEIPT,
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
    _quarantine_failed_publication,
    _read_bounded,
    _read_external,
    _ReadBudget,
    _require_absent,
    _require_current_path,
    _require_parent_outside_authorities,
    _require_published_tree,
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
_RETAINED_PATHS = tuple(
    sorted(
        (_MANIFEST, *_EVIDENCE_PATHS, _CRYPTO, _READBACK),
        key=lambda item: item.as_posix(),
    )
)
_COMPLETE_PATHS = (*_RETAINED_PATHS, _RETENTION)


@dataclass(frozen=True)
class ReleaseEvidenceRetention:
    """Identity committed with one exact local evidence handoff."""

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


def _candidate(path: Path | int) -> Any:
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


def _bind_descriptor(descriptor: Mapping[str, Any], raw: bytes, label: str) -> None:
    if descriptor.get("sha256") != _sha256(raw) or (
        "byteSize" in descriptor and descriptor.get("byteSize") != len(raw)
    ):
        _fail(f"{label} descriptor differs from its exact retained bytes")


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
        "receiptType": "phase-1-release-evidence-local-handoff-v1",
        "candidateId": candidate_id,
        "dataReleaseId": data_release_id,
        "dataProvenanceClass": data_provenance_class,
        "controlledBuildRunId": controlled_build_run_id,
        "files": [
            _descriptor(path, files[path])
            for path in sorted(files, key=lambda item: item.as_posix())
        ],
        "handoff": {
            "class": "local-atomic-no-overwrite",
            "initialPublicationOverwriteAllowed": False,
            "externalRetentionPolicy": "required-not-verified",
            "deletionPrevention": "not-verified",
            "coRetentionWithDataRelease": "not-verified",
        },
        "claims": {
            "exactLocalEvidenceSet": True,
            "cryptographicVerificationReceiptRetained": True,
            "publicReadbackReceiptRetained": True,
            "receiptAuthorityReverified": False,
            "productionClaim": False,
            "publicationApproval": False,
            "scientificApproval": False,
        },
    }
    document["deterministicIdentity"] = _sha256(_canonical(document))
    _validate_schema(document, "release-evidence-retention-receipt.schema.json")
    return document, _canonical(document)


def _candidate_snapshot_files(
    candidate: int,
    manifest: Mapping[str, Any],
    manifest_raw: bytes,
    budget: _ReadBudget,
) -> dict[PurePosixPath, bytes]:
    files = {
        _MANIFEST: manifest_raw,
        _RECEIPT: _read_bounded(
            candidate,
            _RECEIPT,
            "retention candidate build receipt",
            maximum=_MAX_RECEIPT_BYTES,
            budget=budget,
        ),
    }
    for artifact in manifest["artifacts"]:
        if artifact["role"] != "source-receipt":
            continue
        logical = PurePosixPath(artifact["path"])
        if logical in files:
            _fail(f"duplicate retention candidate snapshot path: {logical}")
        files[logical] = _read_bounded(
            candidate,
            logical,
            f"retention candidate source receipt {logical}",
            maximum=_MAX_RECEIPT_BYTES,
            budget=budget,
        )
    return files


@contextmanager
def _exact_pair_snapshot(
    candidate_files: Mapping[PurePosixPath, bytes],
    evidence_files: Mapping[PurePosixPath, bytes],
) -> Iterator[tuple[Path, Path]]:
    """Expose exact held bytes through one private pathname-only validator boundary."""
    try:
        with tempfile.TemporaryDirectory(
            prefix="searise-retention-pair-",
            dir=Path(tempfile.gettempdir()).resolve(),
        ) as temporary:
            root = Path(temporary)
            candidate = root / "candidate"
            evidence = root / "evidence"
            candidate.mkdir(mode=0o700)
            evidence.mkdir(mode=0o700)
            candidate_descriptor = _open_root(candidate, "retention candidate snapshot")
            evidence_descriptor = _open_root(evidence, "retention evidence snapshot")
            try:
                for logical, raw in candidate_files.items():
                    _snapshot_fd(candidate_descriptor, logical, raw)
                for logical, raw in evidence_files.items():
                    _snapshot_fd(evidence_descriptor, logical, raw)
                os.fsync(candidate_descriptor)
                os.fsync(evidence_descriptor)
                _validate_tree(candidate_descriptor, candidate_files)
                _validate_tree(evidence_descriptor, evidence_files)
            finally:
                _close_quietly(evidence_descriptor)
                _close_quietly(candidate_descriptor)
            yield candidate, evidence
    except OSError as exc:
        raise SupplyChainContractError(
            "could not create exact retention validation snapshot"
        ) from exc


def _validate_retained_semantics(
    files: Mapping[PurePosixPath, bytes],
    receipt: Mapping[str, Any],
) -> None:
    manifest = _strict_json(files[_MANIFEST], "retained candidate manifest")
    try:
        validate_candidate_document(manifest)
    except CandidateContractError as exc:
        raise SupplyChainContractError(str(exc)) from exc
    envelope = _strict_json(files[_ENVELOPE], "retained evidence envelope")
    provenance = _strict_json(files[_PROVENANCE], "retained provenance")
    cryptographic = _strict_json(files[_CRYPTO], "retained cryptographic receipt")
    readback = _strict_json(files[_READBACK], "retained public-readback receipt")
    _validate_schema(envelope, "evidence-envelope.schema.json")
    _validate_schema(cryptographic, "cryptographic-verification-receipt.schema.json")
    _validate_schema(readback, "public-readback-verification-receipt.schema.json")

    identities = ("candidateId", "dataReleaseId", "dataProvenanceClass")
    if any(manifest.get(key) != receipt.get(key) for key in identities):
        _fail("retention receipt identity differs from its retained candidate manifest")
    if any(envelope.get(key) != receipt.get(key) for key in identities):
        _fail("retention receipt identity differs from its retained evidence envelope")
    try:
        external = provenance["predicate"]["buildDefinition"]["externalParameters"]
    except (KeyError, TypeError) as exc:
        raise SupplyChainContractError("retained provenance identity is malformed") from exc
    if any(external.get(key) != receipt.get(key) for key in identities):
        _fail("retention receipt identity differs from its retained provenance")

    _bind_descriptor(envelope["candidateManifest"], files[_MANIFEST], "candidate manifest")
    _bind_descriptor(envelope["provenance"], files[_PROVENANCE], "provenance")
    signatures = envelope["signatures"]
    if tuple(item.get("path") for item in signatures) != _SIGNATURE_PATHS:
        _fail("retained signature descriptors are not the exact ordered inventory")
    for descriptor in signatures:
        _bind_descriptor(
            descriptor,
            files[PurePosixPath(descriptor["path"])],
            f"signature {descriptor['path']}",
        )
    sboms = envelope["softwareBillsOfMaterials"]
    if tuple(item.get("path") for item in sboms) != _SBOM_PATHS:
        _fail("retained SBOM descriptors are not the exact ordered inventory")
    for descriptor in sboms:
        logical = PurePosixPath(descriptor["path"])
        _bind_descriptor(descriptor, files[logical], f"SBOM {logical}")
        _strict_json(files[logical], f"retained SBOM {logical}")
    _bind_receipts(
        files[_MANIFEST],
        files,
        files[_CRYPTO],
        cryptographic,
        readback,
        candidate_id=str(receipt["candidateId"]),
        data_release_id=str(receipt["dataReleaseId"]),
        data_provenance_class=str(receipt["dataProvenanceClass"]),
    )
    if cryptographic["controlledBuildRunId"] != receipt["controlledBuildRunId"]:
        _fail("retention receipt run differs from its retained verification receipts")


def _validate_receipt(
    receipt_raw: bytes,
    retained: Mapping[PurePosixPath, bytes],
) -> dict[str, Any]:
    receipt = _strict_json(receipt_raw, "release evidence retention receipt")
    if receipt_raw != _canonical(receipt):
        _fail("release evidence retention receipt must be canonical JSON")
    _validate_schema(receipt, "release-evidence-retention-receipt.schema.json")
    descriptors = receipt["files"]
    if tuple(item["path"] for item in descriptors) != tuple(
        path.as_posix() for path in _RETAINED_PATHS
    ):
        _fail("retention receipt does not declare the exact ordered file inventory")
    for descriptor, logical in zip(descriptors, _RETAINED_PATHS):
        _bind_descriptor(descriptor, retained[logical], f"retained file {logical}")
    unsigned = dict(receipt)
    claimed_identity = unsigned.pop("deterministicIdentity")
    if claimed_identity != _sha256(_canonical(unsigned)):
        _fail("retention receipt deterministic identity does not match its unsigned bytes")
    _validate_retained_semantics(retained, receipt)
    return receipt


def validate_release_evidence_retention(output_root: Path) -> ReleaseEvidenceRetention:
    """Validate one exact local handoff without asserting external retention policy."""
    if (
        not output_root.is_absolute()
        or ".." in output_root.parts
        or output_root.name != "supply-chain"
    ):
        _fail("retention root must be an absolute canonical supply-chain path")
    descriptor = -1
    try:
        descriptor = _open_root(output_root, "release evidence retention")
        identity = os.fstat(descriptor)
        budget = _ReadBudget(_MAX_TOTAL_READ_BYTES)
        retained = {
            logical: _read_bounded(
                descriptor,
                logical,
                f"retained file {logical}",
                maximum=(_MAX_MANIFEST_BYTES if logical == _MANIFEST else _MAX_BUNDLE_BYTES),
                budget=budget,
            )
            for logical in _RETAINED_PATHS
        }
        receipt_raw = _read_bounded(
            descriptor,
            _RETENTION,
            "release evidence retention receipt",
            maximum=_MAX_RECEIPT_BYTES,
            budget=budget,
        )
        expected = {**retained, _RETENTION: receipt_raw}
        baseline = _validate_tree(descriptor, expected)
        receipt = _validate_receipt(receipt_raw, retained)
        if output_root.parent.name != receipt["dataReleaseId"]:
            _fail("retention root is not under its declared data release ID")
        _validate_tree(descriptor, expected, baseline=baseline)
        _require_current_path(
            output_root,
            descriptor,
            identity,
            "release evidence retention",
        )
    except OSError as exc:
        raise SupplyChainContractError("could not validate local evidence handoff") from exc
    finally:
        _close_quietly(descriptor)
    return ReleaseEvidenceRetention(
        candidate_id=str(receipt["candidateId"]),
        data_release_id=str(receipt["dataReleaseId"]),
        output_root=output_root,
        deterministic_identity=str(receipt["deterministicIdentity"]),
        retained_file_count=len(_COMPLETE_PATHS),
    )


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
    budget = _ReadBudget(_MAX_TOTAL_READ_BYTES)
    candidate_descriptor = evidence_descriptor = -1
    output_parent = stage_descriptor = -1
    try:
        candidate_descriptor = _open_root(candidate_root, "retention candidate")
        evidence_descriptor = _open_root(evidence_root, "retention evidence")
        candidate_identity = os.fstat(candidate_descriptor)
        evidence_identity = os.fstat(evidence_descriptor)
        candidate = _candidate(candidate_descriptor)
        manifest_raw = _read_bounded(
            candidate_descriptor,
            _MANIFEST,
            "retention manifest",
            maximum=_MAX_MANIFEST_BYTES,
            budget=budget,
        )
        manifest = _strict_json(manifest_raw, "retention manifest")
        if candidate.manifest_sha256 != _sha256(manifest_raw):
            _fail("candidate byte authority differs from the retained manifest bytes")
        candidate_files = _candidate_snapshot_files(
            candidate_descriptor,
            manifest,
            manifest_raw,
            budget,
        )
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
        with _exact_pair_snapshot(candidate_files, evidence_files) as (
            candidate_copy,
            evidence_copy,
        ):
            pair = _validate_candidate_evidence_pair(
                candidate_copy,
                evidence_copy,
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
        committed = False
        try:
            for logical, raw in stage_files.items():
                _snapshot_fd(stage_descriptor, logical, raw)
            os.fsync(stage_descriptor)
            stage_baseline = _validate_tree(stage_descriptor, stage_files)

            if _candidate(candidate_descriptor) != candidate:
                _fail("candidate changed before retention handoff publication")
            _validate_tree(evidence_descriptor, evidence_files, baseline=evidence_baseline)
            _require_current_path(
                candidate_root, candidate_descriptor, candidate_identity, "candidate"
            )
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
            try:
                _require_published_tree(
                    output_parent,
                    stage_identity,
                    stage_descriptor,
                    stage_files,
                    stage_baseline,
                    output_root.name,
                )
                _require_current_path(
                    output_root.parent,
                    output_parent,
                    output_parent_identity,
                    "retention output parent",
                )
            except Exception as primary:
                _quarantine_failed_publication(
                    output_parent,
                    stage_identity,
                    output_root.name,
                )
                if isinstance(primary, SupplyChainContractError):
                    raise
                raise SupplyChainContractError(
                    "published retention evidence changed before the result checkpoint"
                ) from primary
            committed = True
        except Exception:
            if not committed:
                _quarantine_failed_publication(
                    output_parent,
                    stage_identity,
                    output_root.name,
                )
            raise
    except OSError as exc:
        raise SupplyChainContractError("could not publish local evidence handoff") from exc
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
