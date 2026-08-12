"""Identity-safe, resumable execution of the offline release stage graph."""

from __future__ import annotations

import errno
import hashlib
import json
import os
import shutil
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Mapping

from jsonschema import (  # type: ignore[import-untyped]
    Draft202012Validator,
    SchemaError,
    ValidationError,
)

from .model import (
    BuildPlan,
    FailureCode,
    FileIdentity,
    StageFailure,
    StageName,
    _canonical_json,
    stage_graph,
)

_STAGE_RECEIPT_SCHEMA = Path(__file__).parent / "schemas/stage-receipt.schema.json"


@dataclass(frozen=True, order=True)
class OutputIdentity:
    """Verified identity of one stage-produced file."""

    path: str
    byte_size: int
    sha256: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "byteSize": self.byte_size,
            "sha256": self.sha256,
        }


@dataclass(frozen=True)
class StageOutcome:
    """Bounded diagnostics supplied by one successful stage handler."""

    warnings: tuple[str, ...] = ()
    quality_results: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if (
            self.warnings != tuple(sorted(set(self.warnings)))
            or any(
                not warning or len(warning) > 256 or "\n" in warning
                for warning in self.warnings
            )
        ):
            raise ValueError("stage warnings must be unique, sorted, single-line messages")
        canonical = _canonical_json(self.quality_results, field="qualityResults")
        object.__setattr__(
            self,
            "quality_results",
            MappingProxyType(json.loads(canonical)),
        )


@dataclass(frozen=True)
class StageContext:
    """Explicit read/write boundary passed to a stage handler."""

    plan: BuildPlan
    stage: StageName
    input_root: Path
    output_directory: Path
    dependency_directories: Mapping[StageName, Path]
    dependency_outputs: Mapping[StageName, tuple[OutputIdentity, ...]]


StageHandler = Callable[[StageContext], StageOutcome]


@dataclass(frozen=True)
class StageRun:
    """One stage execution or verified resume event."""

    stage: StageName
    stage_key_sha256: str
    cache_status: str
    duration_seconds: float
    outputs: tuple[OutputIdentity, ...]
    warnings: tuple[str, ...]
    quality_results: Mapping[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage.value,
            "stageKeySha256": self.stage_key_sha256,
            "cacheStatus": self.cache_status,
            "durationSeconds": self.duration_seconds,
            "outputs": [output.as_dict() for output in self.outputs],
            "warnings": list(self.warnings),
            "qualityResults": dict(self.quality_results),
        }


@dataclass(frozen=True)
class BuildRunResult:
    """Completed candidate and its current-run execution evidence."""

    output_directory: Path
    stages: tuple[StageRun, ...]
    execution_receipt: Mapping[str, Any]


def run_build(
    plan: BuildPlan,
    *,
    input_root: Path,
    cache_directory: Path,
    output_directory: Path,
    handlers: Mapping[StageName, StageHandler],
) -> BuildRunResult:
    """Execute or resume every stage, then atomically publish one candidate."""
    graph = stage_graph(plan.profile)
    expected_handlers = {definition.name for definition in graph}
    if set(handlers) != expected_handlers:
        raise StageFailure(
            FailureCode.INVALID_PLAN,
            None,
            "handlers must cover the exact stage graph",
        )
    input_root = _real_directory(input_root, label="input root")
    cache_directory = _prepare_cache(cache_directory, input_root=input_root)
    output_directory = _prepare_output(
        output_directory,
        input_root=input_root,
        cache_directory=cache_directory,
    )
    if os.path.lexists(output_directory):
        raise StageFailure(
            FailureCode.ATOMIC_PROMOTION_FAILED,
            StageName.ASSEMBLE_RELEASE,
            "immutable candidate path already exists",
        )
    _verify_declared_inputs(plan, input_root)

    stage_runs: list[StageRun] = []
    cache_roots: dict[StageName, Path] = {}
    outputs_by_stage: dict[StageName, tuple[OutputIdentity, ...]] = {}
    keys_by_stage: dict[StageName, str] = {}
    for definition in graph:
        dependencies = definition.dependencies
        upstream = [
            {
                "stage": dependency.value,
                "stageKeySha256": keys_by_stage[dependency],
                "outputs": [
                    output.as_dict() for output in outputs_by_stage[dependency]
                ],
            }
            for dependency in dependencies
        ]
        stage_key = _stage_key(plan, definition.name, upstream)
        started = time.perf_counter()
        cache_root = cache_directory / "stages" / definition.name.value / stage_key
        cached = _load_cache(cache_root, stage=definition.name, stage_key=stage_key)
        if cached is None:
            outputs, outcome = _execute_stage(
                plan,
                stage=definition.name,
                stage_key=stage_key,
                input_root=input_root,
                cache_root=cache_root,
                dependency_directories={
                    dependency: cache_roots[dependency] / "payload"
                    for dependency in dependencies
                },
                dependency_outputs={
                    dependency: outputs_by_stage[dependency]
                    for dependency in dependencies
                },
                handler=handlers[definition.name],
            )
            cache_status = "miss"
        else:
            outputs, outcome = cached
            cache_status = "hit"
        duration = round(time.perf_counter() - started, 6)
        run = StageRun(
            stage=definition.name,
            stage_key_sha256=stage_key,
            cache_status=cache_status,
            duration_seconds=duration,
            outputs=outputs,
            warnings=outcome.warnings,
            quality_results=outcome.quality_results,
        )
        stage_runs.append(run)
        cache_roots[definition.name] = cache_root
        outputs_by_stage[definition.name] = outputs
        keys_by_stage[definition.name] = stage_key

    final_stage = StageName.ASSEMBLE_RELEASE
    _publish_candidate(
        cache_roots[final_stage] / "payload",
        output_directory,
        expected=outputs_by_stage[final_stage],
    )
    receipt = {
        "schemaVersion": 1,
        "buildId": plan.build_id,
        "planIdentitySha256": plan.identity_sha256,
        "dataReleaseId": plan.data_release_id,
        "profile": plan.profile.value,
        "networkAccess": "disabled",
        "status": "complete",
        "stages": [run.as_dict() for run in stage_runs],
        "finalOutputs": [
            output.as_dict() for output in outputs_by_stage[final_stage]
        ],
    }
    return BuildRunResult(
        output_directory=output_directory,
        stages=tuple(stage_runs),
        execution_receipt=MappingProxyType(receipt),
    )


def _execute_stage(
    plan: BuildPlan,
    *,
    stage: StageName,
    stage_key: str,
    input_root: Path,
    cache_root: Path,
    dependency_directories: Mapping[StageName, Path],
    dependency_outputs: Mapping[StageName, tuple[OutputIdentity, ...]],
    handler: StageHandler,
) -> tuple[tuple[OutputIdentity, ...], StageOutcome]:
    cache_root.parent.mkdir(parents=True, exist_ok=True)
    try:
        with tempfile.TemporaryDirectory(
            prefix=f".{stage.value}-", dir=cache_root.parent
        ) as temporary:
            temporary_root = Path(temporary)
            payload = temporary_root / "payload"
            payload.mkdir()
            context = StageContext(
                plan=plan,
                stage=stage,
                input_root=input_root,
                output_directory=payload,
                dependency_directories=MappingProxyType(dict(dependency_directories)),
                dependency_outputs=MappingProxyType(dict(dependency_outputs)),
            )
            outcome = handler(context)
            if not isinstance(outcome, StageOutcome):
                raise StageFailure(
                    FailureCode.OUTPUT_VALIDATION_FAILED,
                    stage,
                    "handler did not return StageOutcome",
                )
            outputs = _inventory(payload, stage=stage)
            receipt = {
                "schemaVersion": 1,
                "stage": stage.value,
                "stageKeySha256": stage_key,
                "status": "complete",
                "outputs": [output.as_dict() for output in outputs],
                "warnings": list(outcome.warnings),
                "qualityResults": dict(outcome.quality_results),
            }
            try:
                _validate_stage_receipt(receipt)
            except (
                OSError,
                json.JSONDecodeError,
                SchemaError,
                ValidationError,
            ) as exc:
                raise StageFailure(
                    FailureCode.OUTPUT_VALIDATION_FAILED,
                    stage,
                    "stage receipt failed schema validation",
                ) from exc
            _write_json(temporary_root / "receipt.json", receipt)
            if cache_root.exists():
                cached = _load_cache(cache_root, stage=stage, stage_key=stage_key)
                if cached is None:
                    raise AssertionError("existing cache unexpectedly disappeared")
                return cached
            try:
                os.rename(temporary_root, cache_root)
                return outputs, outcome
            except OSError as exc:
                if exc.errno not in {errno.EEXIST, errno.ENOTEMPTY}:
                    raise
                cached = _load_cache(cache_root, stage=stage, stage_key=stage_key)
                if cached is None:
                    raise AssertionError("concurrent cache object disappeared")
                return cached
    except StageFailure:
        raise
    except OSError as exc:
        code = (
            FailureCode.DISK_PRESSURE
            if exc.errno in {errno.ENOSPC, errno.EDQUOT}
            else FailureCode.STAGE_EXECUTION_FAILED
        )
        raise StageFailure(code, stage, f"{type(exc).__name__} during stage execution") from exc
    except Exception as exc:
        raise StageFailure(
            FailureCode.STAGE_EXECUTION_FAILED,
            stage,
            f"{type(exc).__name__} during stage execution",
        ) from exc


def _load_cache(
    cache_root: Path, *, stage: StageName, stage_key: str
) -> tuple[tuple[OutputIdentity, ...], StageOutcome] | None:
    if not os.path.lexists(cache_root):
        return None
    try:
        if cache_root.is_symlink() or not cache_root.is_dir():
            raise ValueError("cache object is not a real directory")
        entries = {path.name for path in cache_root.iterdir()}
        if entries != {"payload", "receipt.json"}:
            raise ValueError("cache object has an incomplete or extra entry")
        receipt_path = cache_root / "receipt.json"
        if receipt_path.is_symlink():
            raise ValueError("cache receipt is a symlink")
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        _validate_stage_receipt(receipt)
        expected_keys = {
            "schemaVersion",
            "stage",
            "stageKeySha256",
            "status",
            "outputs",
            "warnings",
            "qualityResults",
        }
        if (
            not isinstance(receipt, dict)
            or set(receipt) != expected_keys
            or receipt["schemaVersion"] != 1
            or receipt["stage"] != stage.value
            or receipt["stageKeySha256"] != stage_key
            or receipt["status"] != "complete"
        ):
            raise ValueError("cache receipt identity differs")
        outputs = _inventory(cache_root / "payload", stage=stage)
        if receipt["outputs"] != [output.as_dict() for output in outputs]:
            raise ValueError("cache output identities differ")
        outcome = StageOutcome(
            warnings=tuple(receipt["warnings"]),
            quality_results=receipt["qualityResults"],
        )
        return outputs, outcome
    except (
        OSError,
        ValueError,
        TypeError,
        KeyError,
        json.JSONDecodeError,
        SchemaError,
        ValidationError,
    ) as exc:
        raise StageFailure(
            FailureCode.STALE_CACHE,
            stage,
            f"cached stage failed closed verification ({type(exc).__name__})",
        ) from exc


def _stage_key(plan: BuildPlan, stage: StageName, upstream: list[dict[str, Any]]) -> str:
    payload = {
        "stageContractVersion": 1,
        "stage": stage.value,
        "planIdentitySha256": plan.identity_sha256,
        "upstream": upstream,
    }
    encoded = _canonical_json(payload, field="stage identity").encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _verify_declared_inputs(plan: BuildPlan, root: Path) -> None:
    declared = (*plan.source_receipts, *plan.inputs, plan.environment.lock)
    for identity in declared:
        try:
            path = _safe_input_path(root, identity)
            if _sha256(path) != identity.sha256:
                raise ValueError("declared SHA-256 differs from file bytes")
        except (OSError, ValueError) as exc:
            raise StageFailure(
                FailureCode.SOURCE_VERIFICATION_FAILED,
                StageName.VERIFY_SOURCES,
                f"declared input failed verification: {identity.path}",
            ) from exc


def _safe_input_path(root: Path, identity: FileIdentity) -> Path:
    relative = Path(identity.path)
    unresolved = root / relative
    if any(
        (root / Path(*relative.parts[:index])).is_symlink()
        for index in range(1, len(relative.parts) + 1)
    ):
        raise ValueError("declared input contains a symlink")
    resolved = unresolved.resolve(strict=True)
    if root not in resolved.parents or not resolved.is_file():
        raise ValueError("declared input escapes its root or is not a file")
    return resolved


def _inventory(root: Path, *, stage: StageName) -> tuple[OutputIdentity, ...]:
    if root.is_symlink() or not root.is_dir():
        raise StageFailure(
            FailureCode.OUTPUT_VALIDATION_FAILED,
            stage,
            "stage output is not a real directory",
        )
    entries = list(root.rglob("*"))
    if not entries or any(path.is_symlink() for path in entries):
        raise StageFailure(
            FailureCode.OUTPUT_VALIDATION_FAILED,
            stage,
            "stage output is empty or contains a symlink",
        )
    files = sorted(path for path in entries if path.is_file())
    if not files or any(path.stat().st_size < 1 for path in files):
        raise StageFailure(
            FailureCode.OUTPUT_VALIDATION_FAILED,
            stage,
            "stage output must contain only non-empty inventoried files",
        )
    return tuple(
        OutputIdentity(
            path=path.relative_to(root).as_posix(),
            byte_size=path.stat().st_size,
            sha256=_sha256(path),
        )
        for path in files
    )


def _publish_candidate(
    payload: Path,
    output_directory: Path,
    *,
    expected: tuple[OutputIdentity, ...],
) -> None:
    try:
        with tempfile.TemporaryDirectory(
            prefix=".searise-candidate-", dir=output_directory.parent
        ) as temporary:
            staged = Path(temporary) / "candidate"
            shutil.copytree(payload, staged, copy_function=shutil.copyfile)
            if _inventory(staged, stage=StageName.ASSEMBLE_RELEASE) != expected:
                raise StageFailure(
                    FailureCode.ATOMIC_PROMOTION_FAILED,
                    StageName.ASSEMBLE_RELEASE,
                    "candidate copy differs from the verified assembly",
                )
            if os.path.lexists(output_directory):
                raise StageFailure(
                    FailureCode.ATOMIC_PROMOTION_FAILED,
                    StageName.ASSEMBLE_RELEASE,
                    "immutable candidate path appeared during promotion",
                )
            os.replace(staged, output_directory)
    except StageFailure:
        raise
    except OSError as exc:
        code = (
            FailureCode.DISK_PRESSURE
            if exc.errno in {errno.ENOSPC, errno.EDQUOT}
            else FailureCode.ATOMIC_PROMOTION_FAILED
        )
        raise StageFailure(code, StageName.ASSEMBLE_RELEASE, "candidate promotion failed") from exc


def _prepare_cache(path: Path, *, input_root: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    resolved = _real_directory(path, label="cache directory")
    if resolved == input_root or input_root in resolved.parents or resolved in input_root.parents:
        raise StageFailure(
            FailureCode.INVALID_PLAN,
            None,
            "cache directory and input root must be disjoint",
        )
    return resolved


def _prepare_output(
    path: Path, *, input_root: Path, cache_directory: Path
) -> Path:
    path = path.absolute()
    if path.name in {"", ".", ".."}:
        raise StageFailure(
            FailureCode.INVALID_PLAN,
            None,
            "candidate output path is unsafe",
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    parent = _real_directory(path.parent, label="candidate parent")
    resolved = parent / path.name
    for protected in (input_root, cache_directory):
        if (
            resolved == protected
            or protected in resolved.parents
            or resolved in protected.parents
        ):
            raise StageFailure(
                FailureCode.INVALID_PLAN,
                None,
                "candidate, cache, and input paths must be disjoint",
            )
    return resolved


def _real_directory(path: Path, *, label: str) -> Path:
    try:
        if path.is_symlink():
            raise OSError(f"{label} is a symlink")
        resolved = path.resolve(strict=True)
        if not resolved.is_dir():
            raise OSError(f"{label} is not a directory")
        return resolved
    except OSError as exc:
        raise StageFailure(FailureCode.INVALID_PLAN, None, f"{label} is unavailable") from exc


def _write_json(path: Path, document: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _validate_stage_receipt(document: Any) -> None:
    schema = json.loads(_STAGE_RECEIPT_SCHEMA.read_text(encoding="utf-8"))
    Draft202012Validator(schema).validate(document)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
