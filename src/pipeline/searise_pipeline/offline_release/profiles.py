"""Explicit fixture, regional, and full-Europe build-profile compilation."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from .model import (
    BuildPlan,
    BuildPlanError,
    BuildProfile,
    FileIdentity,
    StageName,
    ToolIdentity,
    _canonical_json,
    _relative_path,
)


class ProfileAvailability(str, Enum):
    """Whether all inputs are committed or supplied by a controlled run."""

    FIXTURE_READY = "fixture-ready"
    CONTROLLED_INPUT_REQUIRED = "controlled-input-required"


@dataclass(frozen=True)
class ProfileTool:
    """Tool version and the exact files that define its local implementation."""

    name: str
    version: str
    identity_paths: tuple[str, ...]


@dataclass(frozen=True)
class ProfileDefinition:
    """Checked-in profile definition before file identities are resolved."""

    profile: BuildProfile
    availability: ProfileAvailability
    data_version: str
    data_provenance_class: str
    input_root_path: str
    schema_directory: str
    environment: Mapping[str, str]
    tools: tuple[ProfileTool, ...]
    source_receipt_paths: tuple[str, ...]
    parameters: Mapping[str, Any]
    stage_names: tuple[StageName, ...]


@dataclass(frozen=True)
class CompiledProfile:
    """Resolved profile and immutable build plan for one invocation."""

    definition: ProfileDefinition
    plan: BuildPlan


def load_profile_definition(path: Path) -> ProfileDefinition:
    """Load a strict profile without requiring controlled inputs to exist."""
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BuildPlanError(f"cannot read build profile: {exc}") from exc
    required = {
        "$schema",
        "schemaVersion",
        "profile",
        "availability",
        "dataVersion",
        "dataProvenanceClass",
        "inputRootPath",
        "schemaDirectory",
        "environment",
        "tools",
        "sourceReceiptPaths",
        "parameters",
        "stageGraph",
    }
    if not isinstance(document, dict) or set(document) != required:
        raise BuildPlanError("profile must contain the exact version 1 fields")
    if document["$schema"] != "./profile.schema.json" or document["schemaVersion"] != 1:
        raise BuildPlanError("profile schema identity must be version 1")
    try:
        profile = BuildProfile(document["profile"])
        availability = ProfileAvailability(document["availability"])
    except (TypeError, ValueError) as exc:
        raise BuildPlanError("profile or availability is unsupported") from exc
    data_version = document["dataVersion"]
    if not isinstance(data_version, str) or re.fullmatch(
        r"[0-9]+\.[0-9]+\.[0-9]+", data_version
    ) is None:
        raise BuildPlanError("dataVersion must be exact SemVer")
    provenance = document["dataProvenanceClass"]
    if provenance not in {"real-source", "synthetic-fixture"}:
        raise BuildPlanError("profile dataProvenanceClass is unsupported")
    input_root_path = _relative_path(document["inputRootPath"], field="inputRootPath")
    schema_directory = _relative_path(
        document["schemaDirectory"], field="schemaDirectory"
    )
    environment = _environment(document["environment"])
    tools = _tools(document["tools"])
    source_paths = _paths(document["sourceReceiptPaths"], field="sourceReceiptPaths")
    parameters_json = _canonical_json(document["parameters"], field="parameters")
    expected_stages = tuple(StageName)
    try:
        stages = tuple(StageName(item) for item in document["stageGraph"])
    except (TypeError, ValueError) as exc:
        raise BuildPlanError("profile stageGraph contains an unknown stage") from exc
    if stages != expected_stages:
        raise BuildPlanError("profile stageGraph must be complete and ordered")
    return ProfileDefinition(
        profile=profile,
        availability=availability,
        data_version=data_version,
        data_provenance_class=provenance,
        input_root_path=input_root_path,
        schema_directory=schema_directory,
        environment=environment,
        tools=tools,
        source_receipt_paths=source_paths,
        parameters=json.loads(parameters_json),
        stage_names=stages,
    )


def compile_profile(
    profile_path: Path,
    *,
    input_root: Path,
    code_revision: str,
    release_date: str,
    started_at: str,
    completed_at: str,
) -> CompiledProfile:
    """Resolve every profile file and produce one deterministic build plan."""
    definition = load_profile_definition(profile_path)
    root = _real_root(input_root)
    profile_relative = _relative_from_root(root, profile_path)
    input_directory = _resolve_directory(root, definition.input_root_path)
    schema_directory = _resolve_directory(root, definition.schema_directory)
    lock_path = definition.environment["lockPath"]
    lock = _file_identity(root, lock_path)
    source_receipts = tuple(
        sorted(_file_identity(root, relative) for relative in definition.source_receipt_paths)
    )
    input_paths = {
        profile_relative,
        *(
            path.relative_to(root).as_posix()
            for path in _inventory_files(root, input_directory)
        ),
        *(
            path.relative_to(root).as_posix()
            for path in _inventory_files(root, schema_directory, suffix=".schema.json")
        ),
    }
    inputs = tuple(sorted(_file_identity(root, relative) for relative in input_paths))
    tools = tuple(sorted(_tool_identity(root, tool) for tool in definition.tools))
    started = _utc_timestamp(started_at, field="startedAt")
    completed = _utc_timestamp(completed_at, field="completedAt")
    if completed < started:
        raise BuildPlanError("completedAt cannot precede startedAt")
    if re.fullmatch(r"[0-9]{8}", release_date) is None:
        raise BuildPlanError("release date must use YYYYMMDD")
    parameters = {
        **definition.parameters,
        "profileAvailability": definition.availability.value,
        "inputRootPath": definition.input_root_path,
        "schemaDirectory": definition.schema_directory,
        "receiptTimestamps": {
            "startedAt": started_at,
            "completedAt": completed_at,
        },
    }
    release_identity = {
        "profile": definition.profile.value,
        "dataVersion": definition.data_version,
        "releaseDate": release_date,
        "codeRevision": code_revision,
        "environmentLock": lock.as_public_dict(),
        "tools": [tool.as_public_dict() for tool in tools],
        "sourceReceipts": [item.as_public_dict() for item in source_receipts],
        "inputs": [item.as_public_dict() for item in inputs],
        "parameters": parameters,
    }
    suffix = hashlib.sha256(
        _canonical_json(release_identity, field="release identity").encode("utf-8")
    ).hexdigest()[:12]
    data_release_id = (
        f"searise-europe-v{definition.data_version}-{release_date}-{suffix}"
    )
    environment = {
        "platform": definition.environment["platform"],
        "architecture": definition.environment["architecture"],
        "pythonVersion": definition.environment["pythonVersion"],
        "lock": lock.as_public_dict(),
    }
    plan = BuildPlan.from_mapping(
        {
            "schemaVersion": 1,
            "profile": definition.profile.value,
            "dataReleaseId": data_release_id,
            "dataProvenanceClass": definition.data_provenance_class,
            "codeRevision": code_revision,
            "networkAccess": "disabled",
            "environment": environment,
            "tools": [tool.as_public_dict() for tool in tools],
            "sourceReceipts": [item.as_public_dict() for item in source_receipts],
            "inputs": [item.as_public_dict() for item in inputs],
            "parameters": parameters,
            "stageGraph": [stage.value for stage in definition.stage_names],
        }
    )
    return CompiledProfile(definition=definition, plan=plan)


def _environment(value: object) -> Mapping[str, str]:
    required = {"platform", "architecture", "pythonVersion", "lockPath"}
    if not isinstance(value, dict) or set(value) != required:
        raise BuildPlanError("profile environment must contain exact pinned fields")
    if value["platform"] not in {"linux", "darwin"}:
        raise BuildPlanError("profile environment platform is unsupported")
    if value["architecture"] not in {"x86_64", "arm64"}:
        raise BuildPlanError("profile environment architecture is unsupported")
    if not isinstance(value["pythonVersion"], str) or re.fullmatch(
        r"3\.[0-9]+\.[0-9]+", value["pythonVersion"]
    ) is None:
        raise BuildPlanError("profile Python version must be exact")
    return {
        "platform": value["platform"],
        "architecture": value["architecture"],
        "pythonVersion": value["pythonVersion"],
        "lockPath": _relative_path(value["lockPath"], field="environment.lockPath"),
    }


def _tools(value: object) -> tuple[ProfileTool, ...]:
    if not isinstance(value, list) or not value:
        raise BuildPlanError("profile tools must be a non-empty array")
    tools = []
    for index, item in enumerate(value):
        if not isinstance(item, dict) or set(item) != {"name", "version", "identityPaths"}:
            raise BuildPlanError(f"tools[{index}] must contain exact identity fields")
        name = item["name"]
        version = item["version"]
        if not isinstance(name, str) or re.fullmatch(r"[a-z0-9][a-z0-9.-]+", name) is None:
            raise BuildPlanError(f"tools[{index}].name is not canonical")
        if not isinstance(version, str) or not version:
            raise BuildPlanError(f"tools[{index}].version is empty")
        tools.append(
            ProfileTool(
                name=name,
                version=version,
                identity_paths=_repository_paths(
                    item["identityPaths"], field=f"tools[{index}].identityPaths"
                ),
            )
        )
    result = tuple(tools)
    if result != tuple(sorted(result, key=lambda tool: tool.name)) or len(
        {tool.name for tool in result}
    ) != len(result):
        raise BuildPlanError("profile tools must have unique sorted names")
    return result


def _paths(value: object, *, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise BuildPlanError(f"{field} must be a non-empty array")
    paths = tuple(_relative_path(item, field=field) for item in value)
    if paths != tuple(sorted(set(paths))):
        raise BuildPlanError(f"{field} must be unique and sorted")
    return paths


def _repository_paths(value: object, *, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise BuildPlanError(f"{field} must be a non-empty array")
    paths = tuple(_repository_path(item, field=field) for item in value)
    if paths != tuple(sorted(set(paths))):
        raise BuildPlanError(f"{field} must be unique and sorted")
    return paths


def _repository_path(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 512:
        raise BuildPlanError(f"{field} must be a non-empty repository path")
    candidate = PurePosixPath(value)
    if (
        candidate.is_absolute()
        or candidate.as_posix() != value
        or any(part in {"", ".", ".."} for part in candidate.parts)
        or re.fullmatch(
            r"[A-Za-z0-9_][A-Za-z0-9._-]*(?:/[A-Za-z0-9_][A-Za-z0-9._-]*)*",
            value,
        )
        is None
    ):
        raise BuildPlanError(f"{field} is unsafe or non-canonical")
    return value


def _tool_identity(root: Path, tool: ProfileTool) -> ToolIdentity:
    files = [_file_identity(root, relative).as_public_dict() for relative in tool.identity_paths]
    digest = hashlib.sha256(
        _canonical_json({"files": files}, field="tool identity").encode("utf-8")
    ).hexdigest()
    return ToolIdentity(tool.name, tool.version, digest)


def _file_identity(root: Path, relative: str) -> FileIdentity:
    path = _resolve_file(root, relative)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return FileIdentity(relative, digest)


def _inventory_files(root: Path, directory: Path, *, suffix: str = "") -> tuple[Path, ...]:
    entries = list(directory.rglob("*"))
    if any(path.is_symlink() for path in entries):
        raise BuildPlanError("profile input tree contains a symlink")
    files = tuple(
        sorted(
            path
            for path in entries
            if path.is_file() and (not suffix or path.name.endswith(suffix))
        )
    )
    if not files or any(root not in path.resolve().parents for path in files):
        raise BuildPlanError("profile input tree is empty or unsafe")
    return files


def _resolve_file(root: Path, relative: str) -> Path:
    path = _resolve(root, relative)
    if not path.is_file():
        raise BuildPlanError(f"profile input file is unavailable: {relative}")
    return path


def _resolve_directory(root: Path, relative: str) -> Path:
    path = _resolve(root, relative)
    if not path.is_dir():
        raise BuildPlanError(f"profile input directory is unavailable: {relative}")
    return path


def _resolve(root: Path, relative: str) -> Path:
    unresolved = root / relative
    if any(
        (root / Path(*Path(relative).parts[:index])).is_symlink()
        for index in range(1, len(Path(relative).parts) + 1)
    ):
        raise BuildPlanError(f"profile input path contains a symlink: {relative}")
    try:
        resolved = unresolved.resolve(strict=True)
    except OSError as exc:
        raise BuildPlanError(f"profile input is unavailable: {relative}") from exc
    if root not in resolved.parents:
        raise BuildPlanError(f"profile input escapes repository root: {relative}")
    return resolved


def _real_root(path: Path) -> Path:
    try:
        if path.is_symlink():
            raise OSError("input root is a symlink")
        root = path.resolve(strict=True)
    except OSError as exc:
        raise BuildPlanError("input root is unavailable") from exc
    if not root.is_dir():
        raise BuildPlanError("input root is not a directory")
    return root


def _relative_from_root(root: Path, path: Path) -> str:
    try:
        resolved = path.resolve(strict=True)
        if path.is_symlink():
            raise OSError("profile path is a symlink")
        return resolved.relative_to(root).as_posix()
    except (OSError, ValueError) as exc:
        raise BuildPlanError("profile definition must be a real file under input root") from exc


def _utc_timestamp(value: str, *, field: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise BuildPlanError(f"{field} must be an explicit UTC timestamp")
    try:
        parsed = datetime.fromisoformat(value.removesuffix("Z") + "+00:00")
    except ValueError as exc:
        raise BuildPlanError(f"{field} is not an RFC 3339 timestamp") from exc
    if parsed.tzinfo != timezone.utc:
        raise BuildPlanError(f"{field} must use UTC")
    return parsed
