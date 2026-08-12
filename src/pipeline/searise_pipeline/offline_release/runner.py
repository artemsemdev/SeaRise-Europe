"""Operator-facing execution with immutable success and failure evidence."""

from __future__ import annotations

import hashlib
import json
import os
import resource
import shutil
import stat
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from jsonschema import Draft202012Validator, ValidationError  # type: ignore[import-untyped]

from .engine import BuildRunResult, OutputIdentity, run_build
from .handlers import release_handlers
from .model import BuildPlanError, FailureCode, StageFailure
from .profiles import CompiledProfile, compile_profile

_FAILURE_SUMMARIES = {
    FailureCode.INVALID_PLAN: "build plan or path preflight failed",
    FailureCode.SOURCE_VERIFICATION_FAILED: "declared source identity verification failed",
    FailureCode.STALE_CACHE: "cached stage failed closed verification",
    FailureCode.STAGE_EXECUTION_FAILED: "stage execution failed",
    FailureCode.OUTPUT_VALIDATION_FAILED: "stage output validation failed",
    FailureCode.ATOMIC_PROMOTION_FAILED: "atomic candidate promotion failed",
    FailureCode.INCOMPLETE_BUILD: "operator execution did not complete",
    FailureCode.DISK_PRESSURE: "storage capacity prevented completion",
}
_RECEIPT_SCHEMA = Path(__file__).parent / "schemas/operator-receipt.schema.json"


@dataclass(frozen=True)
class _PromotedCandidate:
    path: Path
    device: int
    inode: int
    outputs: tuple[OutputIdentity, ...]


@dataclass(frozen=True)
class _ReceiptLinkIdentity:
    device: int
    inode: int


def execute_profile_build(
    *,
    profile_path: Path,
    input_root: Path,
    code_revision: str,
    release_date: str,
    started_at: str,
    completed_at: str,
    cache_directory: Path,
    output_directory: Path,
    execution_receipt_path: Path,
    failure_receipt_path: Path,
) -> BuildRunResult:
    """Compile and execute one profile while recording exactly one final receipt."""
    started = time.perf_counter()
    compiled: CompiledProfile | None = None
    output_preexisting = os.path.lexists(output_directory)
    promoted_candidate: _PromotedCandidate | None = None
    execution_candidate = execution_receipt_path.resolve(strict=False)
    failure_candidate = failure_receipt_path.resolve(strict=False)
    cache_candidate = cache_directory.resolve(strict=False)
    output_candidate = output_directory.resolve(strict=False)
    if execution_candidate == failure_candidate:
        raise StageFailure(
            FailureCode.INVALID_PLAN,
            None,
            "execution and failure receipt paths must differ",
        )
    if _overlap(failure_candidate, cache_candidate) or _overlap(
        failure_candidate, output_candidate
    ):
        raise StageFailure(
            FailureCode.INVALID_PLAN,
            None,
            "failure receipt, cache, and candidate paths must be disjoint",
        )
    failure_path = _prepare_receipt_path(failure_candidate, label="failure receipt")
    try:
        if _overlap(execution_candidate, cache_candidate) or _overlap(
            execution_candidate, output_candidate
        ):
            raise StageFailure(
                FailureCode.INVALID_PLAN,
                None,
                "execution receipt, cache, and candidate paths must be disjoint",
            )
        execution_path = _prepare_receipt_path(
            execution_candidate,
            label="execution receipt",
        )
        compiled = compile_profile(
            profile_path,
            input_root=input_root,
            code_revision=code_revision,
            release_date=release_date,
            started_at=started_at,
            completed_at=completed_at,
        )
        result = run_build(
            compiled.plan,
            input_root=input_root,
            cache_directory=cache_directory,
            output_directory=output_directory,
            handlers=release_handlers(compiled),
        )
        promoted_candidate = _capture_promoted_candidate(result)
        receipt = _success_receipt(
            result,
            total_duration_seconds=time.perf_counter() - started,
        )
        _write_immutable_json(execution_path, receipt)
        return result
    except Exception as exc:
        failure = _classify_failure(exc)
        candidate_state = _candidate_state(
            output_directory,
            preexisting=output_preexisting,
        )
        if promoted_candidate is not None and not output_preexisting:
            candidate_state = _discard_unreceipted_candidate(promoted_candidate)
        _write_immutable_json(
            failure_path,
            _failure_receipt(
                failure,
                compiled=compiled,
                total_duration_seconds=time.perf_counter() - started,
                candidate_state=candidate_state,
            ),
        )
        if failure is exc:
            raise
        raise failure from exc


def _success_receipt(
    result: BuildRunResult, *, total_duration_seconds: float
) -> dict[str, Any]:
    final_outputs = result.execution_receipt["finalOutputs"]
    encoded_inventory = json.dumps(
        final_outputs,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return {
        **result.execution_receipt,
        "receiptType": "offline-build-execution",
        "candidate": {
            "fileCount": len(final_outputs),
            "byteSize": sum(item["byteSize"] for item in final_outputs),
            "inventorySha256": hashlib.sha256(encoded_inventory).hexdigest(),
        },
        "resourceUsage": _resource_usage(total_duration_seconds),
    }


def _failure_receipt(
    failure: StageFailure,
    *,
    compiled: CompiledProfile | None,
    total_duration_seconds: float,
    candidate_state: str,
) -> dict[str, Any]:
    receipt: dict[str, Any] = {
        "schemaVersion": 1,
        "receiptType": "offline-build-failure",
        "networkAccess": "disabled",
        "status": "failed",
        "candidateState": candidate_state,
        "failure": {
            "code": failure.code.value,
            "stage": failure.stage.value if failure.stage is not None else None,
            "detail": _FAILURE_SUMMARIES[failure.code],
        },
        "resourceUsage": _resource_usage(total_duration_seconds),
    }
    if compiled is not None:
        receipt.update(
            {
                "buildId": compiled.plan.build_id,
                "planIdentitySha256": compiled.plan.identity_sha256,
                "dataReleaseId": compiled.plan.data_release_id,
                "profile": compiled.plan.profile.value,
            }
        )
    return receipt


def _classify_failure(exc: Exception) -> StageFailure:
    if isinstance(exc, StageFailure):
        return exc
    if isinstance(exc, BuildPlanError):
        return StageFailure(FailureCode.INVALID_PLAN, None, "profile compilation failed")
    return StageFailure(FailureCode.INCOMPLETE_BUILD, None, "operator execution failed")


def _resource_usage(total_duration_seconds: float) -> dict[str, Any]:
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    peak_bytes = int(peak if sys.platform == "darwin" else peak * 1024)
    return {
        "totalDurationSeconds": round(total_duration_seconds, 6),
        "peakProcessRssBytes": peak_bytes,
    }


def _candidate_state(path: Path, *, preexisting: bool) -> str:
    if preexisting:
        return "pre-existing"
    return "complete-unreceipted" if os.path.lexists(path) else "not-created"


def _discard_unreceipted_candidate(candidate: _PromotedCandidate) -> str:
    """Remove only the exact candidate promoted by this invocation."""
    if not os.path.lexists(candidate.path):
        return "not-created"
    if not _candidate_matches(candidate.path, candidate):
        return "identity-mismatch-preserved"
    quarantine_root: Path | None = None
    renamed = False
    try:
        quarantine_root = Path(
            tempfile.mkdtemp(prefix=".searise-unreceipted-", dir=candidate.path.parent)
        )
        quarantined = quarantine_root / "candidate"
        os.rename(candidate.path, quarantined)
        renamed = True
        if not _candidate_matches(quarantined, candidate):
            if not os.path.lexists(candidate.path):
                os.rename(quarantined, candidate.path)
                quarantine_root.rmdir()
                return "identity-mismatch-preserved"
            return "identity-mismatch-quarantined"
        shutil.rmtree(quarantine_root)
        return "discarded-unreceipted"
    except OSError:
        if quarantine_root is not None and not renamed:
            try:
                quarantine_root.rmdir()
            except OSError:
                pass
        if not os.path.lexists(candidate.path):
            return "quarantined-unreceipted"
        return "complete-unreceipted"


def _capture_promoted_candidate(result: BuildRunResult) -> _PromotedCandidate:
    try:
        metadata = result.output_directory.lstat()
        if not stat.S_ISDIR(metadata.st_mode):
            raise OSError("promoted candidate is not a real directory")
        candidate = _PromotedCandidate(
            path=result.output_directory,
            device=metadata.st_dev,
            inode=metadata.st_ino,
            outputs=result.stages[-1].outputs,
        )
        if not _candidate_matches(candidate.path, candidate):
            raise OSError("promoted candidate inventory changed")
        return candidate
    except OSError as exc:
        raise StageFailure(
            FailureCode.INCOMPLETE_BUILD,
            None,
            "promoted candidate identity could not be captured",
        ) from exc


def _candidate_matches(path: Path, expected: _PromotedCandidate) -> bool:
    try:
        metadata = path.lstat()
        if (
            not stat.S_ISDIR(metadata.st_mode)
            or metadata.st_dev != expected.device
            or metadata.st_ino != expected.inode
        ):
            return False
        entries = list(path.rglob("*"))
        if any(entry.is_symlink() for entry in entries):
            return False
        if any(not entry.is_dir() and not entry.is_file() for entry in entries):
            return False
        files = sorted(entry for entry in entries if entry.is_file())
        observed = tuple(
            OutputIdentity(
                path=file.relative_to(path).as_posix(),
                byte_size=file.stat().st_size,
                sha256=_sha256(file),
            )
            for file in files
        )
        return observed == expected.outputs
    except OSError:
        return False


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _prepare_receipt_path(path: Path, *, label: str) -> Path:
    absolute = path.absolute()
    if absolute.name in {"", ".", ".."}:
        raise StageFailure(FailureCode.INVALID_PLAN, None, f"{label} path is unsafe")
    absolute.parent.mkdir(parents=True, exist_ok=True)
    parent = absolute.parent.resolve(strict=True)
    prepared = parent / absolute.name
    if os.path.lexists(prepared):
        raise StageFailure(FailureCode.INVALID_PLAN, None, f"immutable {label} already exists")
    return prepared


def _overlap(left: Path, right: Path) -> bool:
    return left == right or left in right.parents or right in left.parents


def _write_immutable_json(path: Path, document: Mapping[str, Any]) -> None:
    try:
        schema = json.loads(_RECEIPT_SCHEMA.read_text(encoding="utf-8"))
        Draft202012Validator(schema).validate(document)
    except (OSError, json.JSONDecodeError, ValidationError) as exc:
        raise StageFailure(
            FailureCode.INCOMPLETE_BUILD,
            None,
            "operator receipt failed schema validation",
        ) from exc
    payload = (
        json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    temporary_name: str | None = None
    linked_identity: _ReceiptLinkIdentity | None = None
    link_created = False
    try:
        with tempfile.NamedTemporaryFile(
            prefix=f".{path.name}.",
            dir=path.parent,
            delete=False,
        ) as stream:
            temporary_name = stream.name
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
            metadata = os.fstat(stream.fileno())
            linked_identity = _ReceiptLinkIdentity(
                device=metadata.st_dev,
                inode=metadata.st_ino,
            )
        try:
            os.link(temporary_name, path)
            link_created = True
        except FileExistsError as exc:
            raise StageFailure(
                FailureCode.INVALID_PLAN,
                None,
                "immutable operator receipt already exists",
            ) from exc
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        os.unlink(temporary_name)
        temporary_name = None
    except StageFailure:
        raise
    except OSError as exc:
        if link_created and linked_identity is not None:
            _rollback_receipt_link(path, linked_identity)
        raise StageFailure(
            FailureCode.INCOMPLETE_BUILD,
            None,
            "operator receipt could not be committed",
        ) from exc
    finally:
        if temporary_name is not None:
            try:
                os.unlink(temporary_name)
            except OSError:
                pass


def _rollback_receipt_link(path: Path, expected: _ReceiptLinkIdentity) -> None:
    """Remove only the exact hard link created by this invocation."""
    if not _receipt_link_matches(path, expected):
        return
    quarantine_root: Path | None = None
    renamed = False
    try:
        quarantine_root = Path(
            tempfile.mkdtemp(prefix=".searise-receipt-rollback-", dir=path.parent)
        )
        quarantined = quarantine_root / "receipt"
        os.rename(path, quarantined)
        renamed = True
        if not _receipt_link_matches(quarantined, expected):
            if not os.path.lexists(path):
                os.rename(quarantined, path)
                quarantine_root.rmdir()
            return
        os.unlink(quarantined)
        quarantine_root.rmdir()
    except OSError:
        if quarantine_root is not None and not renamed:
            try:
                quarantine_root.rmdir()
            except OSError:
                pass


def _receipt_link_matches(path: Path, expected: _ReceiptLinkIdentity) -> bool:
    try:
        metadata = path.lstat()
        return (
            stat.S_ISREG(metadata.st_mode)
            and metadata.st_dev == expected.device
            and metadata.st_ino == expected.inode
        )
    except OSError:
        return False
