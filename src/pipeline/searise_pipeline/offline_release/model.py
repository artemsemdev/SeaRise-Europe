"""Closed identities and stage graph for the offline release builder."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from enum import Enum
from pathlib import PurePosixPath
from typing import Any, Mapping, NoReturn


class BuildPlanError(ValueError):
    """Raised when a build plan is incomplete, unsafe, or ambiguous."""


class BuildProfile(str, Enum):
    """Supported data volumes; every profile executes the same graph."""

    FIXTURE = "fixture"
    REGIONAL = "regional"
    FULL_EUROPE = "full-europe"


class StageName(str, Enum):
    """Ordered, typed stage names used by receipts and diagnostics."""

    VERIFY_SOURCES = "verify-sources"
    INSPECT = "inspect"
    NORMALIZE = "normalize"
    DERIVE = "derive"
    PACKAGE = "package"
    VALIDATE = "validate"
    ASSEMBLE_RELEASE = "assemble-release"


class FailureCode(str, Enum):
    """Stable failure taxonomy for operators and machine evidence."""

    INVALID_PLAN = "invalid-plan"
    SOURCE_VERIFICATION_FAILED = "source-verification-failed"
    STALE_CACHE = "stale-cache"
    STAGE_EXECUTION_FAILED = "stage-execution-failed"
    OUTPUT_VALIDATION_FAILED = "output-validation-failed"
    ATOMIC_PROMOTION_FAILED = "atomic-promotion-failed"
    INCOMPLETE_BUILD = "incomplete-build"
    DISK_PRESSURE = "disk-pressure"


@dataclass(frozen=True)
class StageFailure(RuntimeError):
    """One classified failure without an unbounded exception payload."""

    code: FailureCode
    stage: StageName | None
    detail: str

    def __str__(self) -> str:
        location = self.stage.value if self.stage is not None else "preflight"
        return f"{self.code.value} at {location}: {self.detail}"


@dataclass(frozen=True, order=True)
class FileIdentity:
    """Content identity for a repository-relative input or receipt."""

    path: str
    sha256: str

    @classmethod
    def from_mapping(cls, value: object, *, field: str) -> FileIdentity:
        document = _exact_mapping(value, {"path", "sha256"}, field=field)
        path = _relative_path(document["path"], field=f"{field}.path")
        digest = _sha256(document["sha256"], field=f"{field}.sha256")
        return cls(path=path, sha256=digest)

    def as_public_dict(self) -> dict[str, str]:
        return {"path": self.path, "sha256": self.sha256}


@dataclass(frozen=True, order=True)
class ToolIdentity:
    """Pinned executable or library identity used by every stage."""

    name: str
    version: str
    identity_sha256: str

    @classmethod
    def from_mapping(cls, value: object, *, field: str) -> ToolIdentity:
        document = _exact_mapping(
            value,
            {"name", "version", "identitySha256"},
            field=field,
        )
        name = document["name"]
        version = document["version"]
        if not isinstance(name, str) or re.fullmatch(r"[a-z0-9][a-z0-9.-]+", name) is None:
            _fail(f"{field}.name must be a canonical tool name")
        if not isinstance(version, str) or not version.strip():
            _fail(f"{field}.version must be non-empty")
        return cls(
            name=name,
            version=version,
            identity_sha256=_sha256(
                document["identitySha256"], field=f"{field}.identitySha256"
            ),
        )

    def as_public_dict(self) -> dict[str, str]:
        return {
            "name": self.name,
            "version": self.version,
            "identitySha256": self.identity_sha256,
        }


@dataclass(frozen=True)
class EnvironmentIdentity:
    """Pinned interpreter environment recorded in the public build receipt."""

    platform: str
    architecture: str
    python_version: str
    lock: FileIdentity

    @classmethod
    def from_mapping(cls, value: object) -> EnvironmentIdentity:
        document = _exact_mapping(
            value,
            {"platform", "architecture", "pythonVersion", "lock"},
            field="environment",
        )
        platform = document["platform"]
        architecture = document["architecture"]
        python_version = document["pythonVersion"]
        if platform not in {"linux", "darwin"}:
            _fail("environment.platform must be linux or darwin")
        if architecture not in {"x86_64", "arm64"}:
            _fail("environment.architecture must be x86_64 or arm64")
        if not isinstance(python_version, str) or re.fullmatch(
            r"3\.[0-9]+\.[0-9]+", python_version
        ) is None:
            _fail("environment.pythonVersion must be an exact Python 3 version")
        return cls(
            platform=platform,
            architecture=architecture,
            python_version=python_version,
            lock=FileIdentity.from_mapping(document["lock"], field="environment.lock"),
        )

    def as_public_dict(self) -> dict[str, Any]:
        return {
            "platform": self.platform,
            "architecture": self.architecture,
            "pythonVersion": self.python_version,
            "lock": self.lock.as_public_dict(),
        }


@dataclass(frozen=True)
class StageDefinition:
    """One graph node and its complete direct dependencies."""

    name: StageName
    dependencies: tuple[StageName, ...]


_STAGE_GRAPH = (
    StageDefinition(StageName.VERIFY_SOURCES, ()),
    StageDefinition(StageName.INSPECT, (StageName.VERIFY_SOURCES,)),
    StageDefinition(StageName.NORMALIZE, (StageName.INSPECT,)),
    StageDefinition(StageName.DERIVE, (StageName.NORMALIZE,)),
    StageDefinition(StageName.PACKAGE, (StageName.DERIVE,)),
    StageDefinition(StageName.VALIDATE, (StageName.PACKAGE,)),
    StageDefinition(StageName.ASSEMBLE_RELEASE, (StageName.VALIDATE,)),
)


def stage_graph(profile: BuildProfile) -> tuple[StageDefinition, ...]:
    """Return the one graph shared by fixture, regional, and full-Europe builds."""
    if not isinstance(profile, BuildProfile):
        _fail("profile must be a BuildProfile")
    return _STAGE_GRAPH


@dataclass(frozen=True)
class BuildPlan:
    """Strict machine-readable description of one candidate build."""

    schema_version: int
    profile: BuildProfile
    data_release_id: str
    data_provenance_class: str
    code_revision: str
    environment: EnvironmentIdentity
    tools: tuple[ToolIdentity, ...]
    source_receipts: tuple[FileIdentity, ...]
    inputs: tuple[FileIdentity, ...]
    parameters_json: str

    @classmethod
    def from_mapping(cls, value: object) -> BuildPlan:
        document = _exact_mapping(
            value,
            {
                "schemaVersion",
                "profile",
                "dataReleaseId",
                "dataProvenanceClass",
                "codeRevision",
                "networkAccess",
                "environment",
                "tools",
                "sourceReceipts",
                "inputs",
                "parameters",
                "stageGraph",
            },
            field="build plan",
        )
        if document["schemaVersion"] != 1:
            _fail("build plan schemaVersion must be 1")
        try:
            profile = BuildProfile(document["profile"])
        except (TypeError, ValueError) as exc:
            raise BuildPlanError("build plan profile is unsupported") from exc
        if document["networkAccess"] != "disabled":
            _fail("offline build networkAccess must be disabled")
        release_id = document["dataReleaseId"]
        if not isinstance(release_id, str) or re.fullmatch(
            r"searise-europe-v[0-9]+\.[0-9]+\.[0-9]+-[0-9]{8}-[a-f0-9]{12}",
            release_id,
        ) is None:
            _fail("dataReleaseId does not match the public v1 contract")
        provenance = document["dataProvenanceClass"]
        if provenance not in {"real-source", "synthetic-fixture"}:
            _fail("dataProvenanceClass is unsupported")
        revision = document["codeRevision"]
        if not isinstance(revision, str) or re.fullmatch(r"[a-f0-9]{40}", revision) is None:
            _fail("codeRevision must be one exact Git commit SHA")
        declared_graph = document["stageGraph"]
        expected_graph = [stage.name.value for stage in stage_graph(profile)]
        if declared_graph != expected_graph:
            _fail("stageGraph must declare the complete ordered offline graph")
        tools = _identity_tuple(document["tools"], ToolIdentity, field="tools")
        sources = _identity_tuple(
            document["sourceReceipts"], FileIdentity, field="sourceReceipts"
        )
        inputs = _identity_tuple(document["inputs"], FileIdentity, field="inputs")
        parameters_json = _canonical_json(document["parameters"], field="parameters")
        return cls(
            schema_version=1,
            profile=profile,
            data_release_id=release_id,
            data_provenance_class=provenance,
            code_revision=revision,
            environment=EnvironmentIdentity.from_mapping(document["environment"]),
            tools=tools,
            source_receipts=sources,
            inputs=inputs,
            parameters_json=parameters_json,
        )

    @property
    def parameters(self) -> Mapping[str, Any]:
        value = json.loads(self.parameters_json)
        if not isinstance(value, dict):
            raise AssertionError("validated parameters unexpectedly changed shape")
        return value

    @property
    def parameters_sha256(self) -> str:
        return hashlib.sha256(self.parameters_json.encode("utf-8")).hexdigest()

    @property
    def identity_sha256(self) -> str:
        payload = {
            "schemaVersion": self.schema_version,
            "profile": self.profile.value,
            "dataReleaseId": self.data_release_id,
            "dataProvenanceClass": self.data_provenance_class,
            "codeRevision": self.code_revision,
            "networkAccess": "disabled",
            "environment": self.environment.as_public_dict(),
            "tools": [tool.as_public_dict() for tool in self.tools],
            "sourceReceipts": [item.as_public_dict() for item in self.source_receipts],
            "inputs": [item.as_public_dict() for item in self.inputs],
            "parametersSha256": self.parameters_sha256,
            "stageGraph": [stage.name.value for stage in stage_graph(self.profile)],
        }
        return hashlib.sha256(_canonical_json(payload, field="identity").encode()).hexdigest()

    @property
    def build_id(self) -> str:
        return f"build-{self.profile.value}-{self.identity_sha256[:12]}"


def _identity_tuple(value: object, kind: type[Any], *, field: str) -> tuple[Any, ...]:
    if not isinstance(value, list) or not value:
        _fail(f"{field} must be a non-empty array")
    parsed = tuple(
        kind.from_mapping(item, field=f"{field}[{index}]")
        for index, item in enumerate(value)
    )
    if parsed != tuple(sorted(parsed)) or len(set(parsed)) != len(parsed):
        _fail(f"{field} must be unique and sorted by stable identity")
    return parsed


def _exact_mapping(value: object, keys: set[str], *, field: str) -> Mapping[str, Any]:
    if not isinstance(value, dict) or set(value) != keys:
        _fail(f"{field} must contain exactly: {', '.join(sorted(keys))}")
    return value


def _relative_path(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 512:
        _fail(f"{field} must be a non-empty release-relative path")
    candidate = PurePosixPath(value)
    if (
        candidate.is_absolute()
        or candidate.as_posix() != value
        or any(part in {"", ".", ".."} for part in candidate.parts)
        or re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9._-]*(?:/[A-Za-z0-9][A-Za-z0-9._-]*)*",
            value,
        )
        is None
    ):
        _fail(f"{field} is unsafe or non-canonical")
    return value


def _sha256(value: object, *, field: str) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[a-f0-9]{64}", value) is None:
        _fail(f"{field} must be a lowercase SHA-256")
    return value


def _canonical_json(value: object, *, field: str) -> str:
    if not isinstance(value, dict):
        _fail(f"{field} must be an object")
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as exc:
        raise BuildPlanError(f"{field} is not canonical JSON: {exc}") from exc


def _fail(message: str) -> NoReturn:
    raise BuildPlanError(message)
