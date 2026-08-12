"""Manifest-last assembly of a real-source Phase 1 candidate."""

from __future__ import annotations

import copy
import hashlib
import os
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from .assembler import (
    _ASSEMBLY_LOCK,
    _MAX_TEMPLATE_BYTES,
    _TEMPLATE,
    CandidateAssemblyError,
    CandidateAssemblySummary,
    _canonical,
    _cleanup_staging,
    _commit_matches,
    _create_owned_directory,
    _entry_identity,
    _fail,
    _final_publication_gate,
    _freeze,
    _fsync_tree,
    _make_staging,
    _open_trusted_output_parent,
    _read_stable_file,
    _rename_no_overwrite,
    _rollback_owned_promotion,
    _same_candidate_bytes,
    _StageOwnership,
    _sync_directory,
    _sync_rename_parents,
    _write_new,
)
from .byte_gate import validate_candidate_root
from .qa_dispatch import QaValidatorDispatcher
from .qa_execution import execute_candidate_qa, execute_pre_gate_qa
from .qa_report import build_pre_gate_report
from .validator import CandidateContractError, load_candidate_bytes, validate_candidate_document

_PRE_GATE_COUNT = 51
_MAX_INPUT_BYTES = 2 * 1024 * 1024 * 1024
_MAX_TOTAL_INPUT_BYTES = 8 * 1024 * 1024 * 1024


@dataclass(frozen=True)
class ProductionCandidateMetadata:
    """Stable identities supplied by the controlled build workflow."""

    candidate_id: str
    data_release_id: str
    generated_at: str


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _input_paths(root: Path) -> set[str]:
    observed: set[str] = set()
    for directory, directories, files in os.walk(root, followlinks=False):
        parent = Path(directory)
        if any((parent / name).is_symlink() for name in directories):
            _fail("assembly-input-path", "pre-gate input contains a symlink directory")
        for name in files:
            path = parent / name
            try:
                relative = path.relative_to(root).as_posix()
            except ValueError as exc:
                raise CandidateAssemblyError(
                    "assembly-input-path", "pre-gate input escapes its root"
                ) from exc
            if relative in observed:
                _fail("assembly-input-path", "pre-gate input paths are not unique")
            observed.add(relative)
    return observed


def _load_production_inputs(
    input_root: Path,
    metadata: ProductionCandidateMetadata,
) -> tuple[dict[str, Any], dict[str, bytes]]:
    template_raw = _read_stable_file(
        _TEMPLATE, code="assembly-template", maximum_bytes=_MAX_TEMPLATE_BYTES
    )
    candidate = copy.deepcopy(load_candidate_bytes(template_raw))
    required = candidate["artifacts"][:_PRE_GATE_COUNT]
    expected_paths = {str(artifact["path"]) for artifact in required}
    if _input_paths(input_root) != expected_paths:
        _fail(
            "assembly-input-inventory",
            "input root must contain exactly the 51 pre-gate artifact paths",
        )

    candidate["candidateId"] = metadata.candidate_id
    candidate["dataReleaseId"] = metadata.data_release_id
    candidate["dataProvenanceClass"] = "real-source"
    payloads: dict[str, bytes] = {}
    total = 0
    for artifact in candidate["artifacts"]:
        artifact["dataReleaseId"] = metadata.data_release_id
        artifact["dataProvenanceClass"] = "real-source"
    for artifact in required:
        logical = PurePosixPath(str(artifact["path"]))
        raw = _read_stable_file(
            input_root.joinpath(*logical.parts),
            code="assembly-input-bytes",
            maximum_bytes=_MAX_INPUT_BYTES,
        )
        if not raw:
            _fail("assembly-input-bytes", f"pre-gate input is empty: {logical}")
        total += len(raw)
        if total > _MAX_TOTAL_INPUT_BYTES:
            _fail("assembly-input-bytes", "pre-gate inputs exceed the assembly limit")
        artifact.update(byteSize=len(raw), sha256=_sha256(raw))
        payloads[str(artifact["artifactId"])] = raw
    return candidate, payloads


def _terminal_bytes(
    candidate: dict[str, Any],
    report_json: bytes,
    report_markdown: bytes,
    payloads: dict[str, bytes],
) -> tuple[bytes, dict[str, bytes]]:
    artifacts = candidate["artifacts"]
    payloads = {
        **payloads,
        "release-gate-report-json": report_json,
        "release-gate-report-markdown": report_markdown,
    }
    for artifact in artifacts[51:53]:
        raw = payloads[str(artifact["artifactId"])]
        artifact.update(byteSize=len(raw), sha256=_sha256(raw))
    subjects = sorted(
        ({"path": item["path"], "sha256": item["sha256"]} for item in artifacts[:53]),
        key=lambda item: item["path"],
    )
    candidate["checksumInventory"]["subjects"] = subjects
    checksums = "".join(
        f"{item['sha256']}  {item['path']}\n" for item in subjects
    ).encode("utf-8")
    artifacts[53].update(byteSize=len(checksums), sha256=_sha256(checksums))
    payloads["checksums"] = checksums
    validate_candidate_document(candidate)
    return _canonical(candidate), payloads


def _assemble_once(
    input_root: Path,
    output_directory: Path,
    metadata: ProductionCandidateMetadata,
    dispatcher: QaValidatorDispatcher,
) -> CandidateAssemblySummary:
    try:
        candidate, payloads = _load_production_inputs(input_root, metadata)
    except (CandidateAssemblyError, CandidateContractError):
        raise
    output = output_directory
    if output.name in {"", ".", ".."}:
        _fail("assembly-publication", "candidate output path is unsafe")

    promoted = False
    complete = False
    parent_descriptor = -1
    temporary_descriptor = -1
    temporary_identity: tuple[int, int] | None = None
    stage_descriptor = -1
    ownership: _StageOwnership | None = None
    temporary_name = ""
    stage_name: str | None = "candidate"
    parent = output.parent
    artifacts = candidate["artifacts"]
    stage_paths = [*(str(item["path"]) for item in artifacts), "manifest.json"]
    try:
        parent, parent_descriptor = _open_trusted_output_parent(output)
        output = parent / output.name
        if _entry_identity(parent_descriptor, output.name) is not None:
            _fail("assembly-publication", "immutable candidate output already exists")
        temporary_name, temporary_descriptor, temporary_identity = _make_staging(
            parent_descriptor
        )
        stage_descriptor, stage_identity = _create_owned_directory(
            temporary_descriptor, "candidate", 0o700
        )
        ownership = _StageOwnership(root=stage_identity, directories={}, files={})
        for artifact in artifacts[:_PRE_GATE_COUNT]:
            _write_new(
                stage_descriptor,
                str(artifact["path"]),
                payloads[str(artifact["artifactId"])],
                ownership,
            )
        stage_path = parent / temporary_name / "candidate"
        pre_gate = execute_pre_gate_qa(
            stage_path,
            artifacts[:_PRE_GATE_COUNT],
            dispatcher,
            candidate_id=metadata.candidate_id,
            data_release_id=metadata.data_release_id,
            data_provenance_class="real-source",
        )
        if not pre_gate.releasable:
            _fail("assembly-gate", "pre-terminal candidate QA did not pass")
        report_json, report_markdown = build_pre_gate_report(
            pre_gate, generated_at=metadata.generated_at
        )
        manifest_raw, all_payloads = _terminal_bytes(
            candidate, report_json, report_markdown, payloads
        )
        for artifact in artifacts[_PRE_GATE_COUNT:]:
            _write_new(
                stage_descriptor,
                str(artifact["path"]),
                all_payloads[str(artifact["artifactId"])],
                ownership,
            )
        _write_new(stage_descriptor, "manifest.json", manifest_raw, ownership)
        _freeze(stage_descriptor, stage_paths, ownership)
        _fsync_tree(stage_descriptor, stage_paths, ownership)
        _sync_directory(temporary_descriptor)
        gated = validate_candidate_root(stage_descriptor)
        full_gate = execute_candidate_qa(stage_path, dispatcher)
        if not full_gate.releasable:
            _fail("assembly-gate", "sealed candidate QA did not pass")
        _rename_no_overwrite(
            temporary_descriptor, "candidate", parent_descriptor, output.name
        )
        promoted = True
        stage_name = None
        os.fchmod(stage_descriptor, 0o555)
        _sync_directory(stage_descriptor)
        _sync_rename_parents(temporary_descriptor, parent_descriptor)
        if not _commit_matches(parent, parent_descriptor, output.name, stage_descriptor):
            _fail("foreign-replacement", "candidate identity changed during publication")
        final = validate_candidate_root(stage_descriptor)
        if not _commit_matches(parent, parent_descriptor, output.name, stage_descriptor):
            _fail("foreign-replacement", "candidate identity changed after validation")
        if not _same_candidate_bytes(final, gated):
            _fail("foreign-replacement", "published candidate differs from the staged gate")
        sealed = _final_publication_gate(
            parent, parent_descriptor, output.name, stage_descriptor, final
        )
        complete = True
        return CandidateAssemblySummary(
            candidate_id=sealed.candidate_id,
            artifact_count=sealed.artifact_count,
            artifact_bytes=sealed.artifact_bytes,
            manifest_sha256=sealed.manifest_sha256,
            output_directory=output,
        )
    except CandidateAssemblyError:
        raise
    except CandidateContractError as exc:
        code = "foreign-replacement" if promoted else "assembly-gate"
        raise CandidateAssemblyError(code, "independent production candidate gate failed") from exc
    except OSError as exc:
        raise CandidateAssemblyError(
            "assembly-publication", "candidate could not be promoted without overwrite"
        ) from exc
    finally:
        primary_error = sys.exc_info()[1]
        cleanup_failure: CandidateAssemblyError | None = None
        try:
            try:
                if promoted and not complete:
                    if ownership is None:
                        _fail("assembly-publication", "promoted candidate ownership is unavailable")
                    stage_name = _rollback_owned_promotion(
                        parent_descriptor,
                        output.name,
                        temporary_descriptor,
                        stage_descriptor,
                        ownership,
                    )
                if temporary_descriptor >= 0 and temporary_identity is not None:
                    _cleanup_staging(
                        parent_descriptor,
                        temporary_name,
                        temporary_descriptor,
                        temporary_identity,
                        stage_descriptor,
                        stage_name,
                        ownership,
                    )
            except CandidateAssemblyError as exc:
                cleanup_failure = exc
            except OSError as exc:
                cleanup_failure = CandidateAssemblyError(
                    "assembly-cleanup", "candidate cleanup could not complete safely"
                )
                cleanup_failure.__cause__ = exc
        finally:
            for descriptor in (stage_descriptor, temporary_descriptor, parent_descriptor):
                if descriptor < 0:
                    continue
                try:
                    os.close(descriptor)
                except OSError as exc:
                    if cleanup_failure is None:
                        cleanup_failure = CandidateAssemblyError(
                            "assembly-cleanup", "candidate descriptors could not be closed"
                        )
                        cleanup_failure.__cause__ = exc
        if cleanup_failure is not None and not complete:
            if isinstance(primary_error, CandidateAssemblyError):
                primary_error.preserve_cleanup_error(cleanup_failure)
            else:
                raise cleanup_failure from primary_error


def assemble_production_candidate(
    input_root: Path,
    output_directory: Path,
    metadata: ProductionCandidateMetadata,
    dispatcher: QaValidatorDispatcher,
) -> CandidateAssemblySummary:
    """Validate 51 exact inputs, seal terminal files, and publish without overwrite."""
    if not _ASSEMBLY_LOCK.acquire(blocking=False):
        _fail("assembly-reentrant", "candidate assembly is already active in this process")
    try:
        return _assemble_once(input_root, output_directory, metadata, dispatcher)
    finally:
        _ASSEMBLY_LOCK.release()
