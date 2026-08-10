"""Operator-facing execution with immutable success and failure evidence."""

from __future__ import annotations

import hashlib
import json
import os
import resource
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Mapping

from jsonschema import Draft202012Validator, ValidationError  # type: ignore[import-untyped]

from .engine import BuildRunResult, run_build
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
        receipt = _success_receipt(
            result,
            total_duration_seconds=time.perf_counter() - started,
        )
        _write_immutable_json(execution_path, receipt)
        return result
    except Exception as exc:
        failure = _classify_failure(exc)
        _write_immutable_json(
            failure_path,
            _failure_receipt(
                failure,
                compiled=compiled,
                total_duration_seconds=time.perf_counter() - started,
                candidate_state=_candidate_state(
                    output_directory,
                    preexisting=output_preexisting,
                ),
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
        os.link(temporary_name, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except FileExistsError as exc:
        raise StageFailure(
            FailureCode.INVALID_PLAN,
            None,
            "immutable operator receipt already exists",
        ) from exc
    except OSError as exc:
        raise StageFailure(
            FailureCode.INCOMPLETE_BUILD,
            None,
            "operator receipt could not be committed",
        ) from exc
    finally:
        if temporary_name is not None:
            try:
                os.unlink(temporary_name)
            except FileNotFoundError:
                pass
