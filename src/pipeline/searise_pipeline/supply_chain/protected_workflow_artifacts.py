"""Fail-closed boundaries for protected-workflow artifact transport.

The helpers in this module authenticate metadata supplied by GitHub's API and
extract already authenticated ZIP bytes.  They do not approve a candidate,
sign anything, or make production, publication, or scientific claims.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, BinaryIO, Callable, Mapping, NoReturn

REPOSITORY = "artemsemdev/SeaRise-Europe"
REPOSITORY_ID = 1196432661
CONTROLLED_WORKFLOW_NAME = "Controlled offline release build"
CONTROLLED_WORKFLOW_PATH = ".github/workflows/offline-release-controlled.yml"
TRUSTED_BRANCH = "master"

_AUTHORITY_TYPE = "protected-candidate-artifact-authority"
_PROFILE = re.compile(r"(?:regional|full-europe)\Z")
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_REVISION = re.compile(r"[0-9a-f]{40}\Z")
_RUN_ID = re.compile(r"[1-9][0-9]*\Z")
_DATE = re.compile(r"[0-9]{8}\Z")
_TIMESTAMP = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z\Z")
_ARTIFACT_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_BUILD_ID = re.compile(r"build-[a-z0-9][a-z0-9.-]+-[0-9a-f]{12}\Z")
_RELEASE_ID = re.compile(r"searise-europe-v[0-9]+\.[0-9]+\.[0-9]+-[0-9]{8}-[0-9a-f]{12}\Z")
_VERSION = re.compile(r"3\.[0-9]+\.[0-9]+\Z")
_TOOL_NAME = re.compile(r"[a-z0-9][a-z0-9.-]+\Z")
_RELEASE_PATH = re.compile(
    r"(?!.*(?:^|/)\.\.?(?:/|$))(?!.*[?#\\])"
    r"(?:[A-Za-z0-9][A-Za-z0-9._-]*)(?:/[A-Za-z0-9][A-Za-z0-9._-]*)*\Z"
)
_ARTIFACT_ROLES = frozenset(
    {
        "release-manifest",
        "contract-schema",
        "scenario-config",
        "methodology",
        "source-attribution",
        "source-receipt",
        "build-receipt",
        "support-boundary",
        "coastal-boundary",
        "settlement-search-index",
        "settlement-geoparquet",
        "projection-analysis-cog",
        "projection-visual-pmtiles",
        "projection-geoparquet",
        "quality-summary",
        "release-gate-report",
        "architecture-evidence",
        "stac-catalog",
        "stac-collection",
        "stac-item",
        "checksums",
        "provenance",
        "signature",
    }
)
_MEDIA_TYPES = frozenset(
    {
        "application/json",
        "application/geo+json",
        "application/vnd.apache.parquet",
        "application/vnd.in-toto+json",
        "application/vnd.pmtiles",
        "application/vnd.searise.search-index+json",
        "application/vnd.dev.sigstore.bundle+json;version=0.3",
        "application/x-ndjson",
        "image/tiff; application=geotiff; profile=cloud-optimized",
        "text/markdown",
        "text/plain",
    }
)

_MAX_METADATA_BYTES = 1024 * 1024
_MAX_MANIFEST_BYTES = 8 * 1024 * 1024
_MAX_ARTIFACT_BYTES = 64 * 1024 * 1024 * 1024
_MAX_CANDIDATE_BYTES = 256 * 1024 * 1024 * 1024
_MAX_CANDIDATE_ARCHIVE_BYTES = _MAX_CANDIDATE_BYTES + 64 * 1024 * 1024
_MAX_EVIDENCE_FILE_BYTES = 1024 * 1024
_MAX_EVIDENCE_BYTES = 2 * 1024 * 1024
_MAX_EVIDENCE_ARCHIVE_BYTES = 4 * 1024 * 1024
_MAX_CANDIDATE_MEMBERS = 128
_READ_SIZE = 1024 * 1024
_IDENTITY_FIELDS = (
    "st_dev",
    "st_ino",
    "st_mode",
    "st_nlink",
    "st_size",
    "st_mtime_ns",
    "st_ctime_ns",
)
_FALSE_CLAIMS = {
    "production": False,
    "publication": False,
    "scientificApproval": False,
}
_EXECUTION_STAGES = (
    "verify-sources",
    "inspect",
    "normalize",
    "derive",
    "package",
    "validate",
    "assemble-release",
)
_EVIDENCE_FILES = frozenset(
    {
        "evidence-envelope.json",
        "manifest.sigstore.json",
        "provenance.intoto.jsonl",
        "provenance.sigstore.json",
        "sbom/build-plane.cdx.json",
        "sbom/frontend-npm.cdx.json",
        "sbom/nuget/searise-api-net8.0.cdx.json",
        "sbom/nuget/searise-application-net8.0.cdx.json",
        "sbom/nuget/searise-domain-net8.0.cdx.json",
        "sbom/nuget/searise-infrastructure-net8.0.cdx.json",
        "sbom/python-release-linux-x86-64-cp311.cdx.json",
        "sbom/python-release-macos-arm64-cp311.cdx.json",
        "sbom/python-settlement-spatial-linux-x86-64-cp311.cdx.json",
        "sbom/python-settlement-spatial-macos-arm64-cp311.cdx.json",
    }
)
_EVIDENCE_DIRECTORIES = frozenset({"sbom", "sbom/nuget"})


class ProtectedWorkflowArtifactError(ValueError):
    """Protected workflow metadata or archive bytes violated the trust boundary."""


def _fail(message: str) -> NoReturn:
    raise ProtectedWorkflowArtifactError(message)


def _identity(value: os.stat_result) -> tuple[int, ...]:
    return tuple(int(getattr(value, field)) for field in _IDENTITY_FIELDS)


def _open_parent(path: Path) -> int:
    absolute = path.absolute()
    flags = os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(absolute.anchor, flags)
    try:
        for part in absolute.parts[1:-1]:
            child = os.open(part, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        return descriptor
    except Exception:
        os.close(descriptor)
        raise


def _positive(value: object, label: str) -> int:
    if type(value) is not int or value <= 0:
        _fail(f"{label} must be a positive integer")
    return value


def _exact_keys(value: object, keys: set[str], label: str) -> Mapping[str, Any]:
    if type(value) is not dict or set(value) != keys:
        _fail(f"{label} must contain exactly {sorted(keys)}")
    return value


def _object(value: object, label: str) -> Mapping[str, Any]:
    if type(value) is not dict:
        _fail(f"{label} must be an object")
    return value


def _array(value: object, label: str) -> list[Any]:
    if type(value) is not list:
        _fail(f"{label} must be an array")
    return value


def _matches(value: object, pattern: re.Pattern[str], label: str) -> str:
    if type(value) is not str or pattern.fullmatch(value) is None:
        _fail(f"{label} is invalid")
    return value


def _calendar_value(value: object, pattern: re.Pattern[str], format: str, label: str) -> str:
    rendered = _matches(value, pattern, label)
    try:
        parsed = datetime.strptime(rendered, format)
    except ValueError as exc:
        raise ProtectedWorkflowArtifactError(f"{label} is not a real calendar value") from exc
    if format.endswith("Z") and parsed.replace(tzinfo=timezone.utc).strftime(format) != rendered:
        _fail(f"{label} is not canonical")
    return rendered


def _require_unique(values: list[Any], label: str) -> None:
    encoded = [
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        for value in values
    ]
    if len(set(encoded)) != len(encoded):
        _fail(f"{label} must not contain duplicate entries")


def _reject_constant(value: str) -> NoReturn:
    _fail(f"JSON contains forbidden non-finite value {value}")


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            _fail(f"JSON contains duplicate key {key!r}")
        result[key] = value
    return result


def _open_regular(path: Path, label: str, maximum: int) -> tuple[int, os.stat_result]:
    if ".." in path.parts:
        _fail(f"{label} path must not contain parent traversal")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    flags |= getattr(os, "O_NONBLOCK", 0)
    parent = -1
    try:
        parent = _open_parent(path)
        descriptor = os.open(path.absolute().name, flags, dir_fd=parent)
    except OSError as exc:
        raise ProtectedWorkflowArtifactError(
            f"{label} must be a readable non-symlink file"
        ) from exc
    finally:
        if parent >= 0:
            os.close(parent)
    metadata = os.fstat(descriptor)
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_nlink != 1
        or metadata.st_size <= 0
        or metadata.st_size > maximum
    ):
        os.close(descriptor)
        _fail(f"{label} must be one linked, non-empty regular file within its byte ceiling")
    return descriptor, metadata


def _confirm_binding(path: Path, descriptor: int, before: os.stat_result, label: str) -> None:
    after = os.fstat(descriptor)
    parent = -1
    try:
        parent = _open_parent(path)
        linked = os.stat(path.absolute().name, dir_fd=parent, follow_symlinks=False)
    except OSError as exc:
        raise ProtectedWorkflowArtifactError(f"{label} changed while it was read") from exc
    finally:
        if parent >= 0:
            os.close(parent)
    if _identity(before) != _identity(after) or _identity(after) != _identity(linked):
        _fail(f"{label} changed while it was read")


def _read_bounded(path: Path, label: str, maximum: int = _MAX_METADATA_BYTES) -> bytes:
    descriptor, before = _open_regular(path, label, maximum)
    try:
        remaining = before.st_size
        chunks: list[bytes] = []
        while remaining:
            chunk = os.read(descriptor, min(_READ_SIZE, remaining))
            if not chunk:
                _fail(f"{label} was truncated while it was read")
            chunks.append(chunk)
            remaining -= len(chunk)
        if os.read(descriptor, 1):
            _fail(f"{label} grew while it was read")
        _confirm_binding(path, descriptor, before, label)
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _json_bytes(raw: bytes, label: str) -> Mapping[str, Any]:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ProtectedWorkflowArtifactError(f"{label} must be UTF-8 JSON") from exc
    if text.startswith("\ufeff"):
        _fail(f"{label} must not contain a byte-order mark")
    try:
        value = json.loads(
            text,
            object_pairs_hook=_pairs,
            parse_constant=_reject_constant,
        )
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise ProtectedWorkflowArtifactError(f"{label} must be valid strict JSON") from exc
    return _object(value, label)


def _load_json(path: Path, label: str, maximum: int = _MAX_METADATA_BYTES) -> Mapping[str, Any]:
    return _json_bytes(_read_bounded(path, label, maximum), label)


def _canonical(document: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(
            document,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def _write_new(path: Path, content: bytes, label: str) -> None:
    if ".." in path.parts:
        _fail(f"{label} path must not contain parent traversal")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    parent = -1
    try:
        parent = _open_parent(path)
        descriptor = os.open(path.absolute().name, flags, 0o400, dir_fd=parent)
    except OSError as exc:
        raise ProtectedWorkflowArtifactError(f"{label} must be a new non-symlink file") from exc
    finally:
        if parent >= 0:
            os.close(parent)
    try:
        view = memoryview(content)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                _fail(f"{label} write made no progress")
            view = view[written:]
        os.fsync(descriptor)
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
            _fail(f"{label} did not remain one linked regular file")
        _confirm_binding(path, descriptor, metadata, label)
    finally:
        os.close(descriptor)


@dataclass(frozen=True)
class CandidateArtifactAuthority:
    """Exact non-publishing authority for one controlled candidate artifact."""

    profile: str
    source_revision: str
    workflow_id: int
    run_id: int
    artifact_id: int
    artifact_name: str
    artifact_sha256: str
    artifact_byte_size: int
    production: bool = False
    publication: bool = False
    scientific_approval: bool = False

    def __post_init__(self) -> None:
        if any(
            value is not False
            for value in (self.production, self.publication, self.scientific_approval)
        ):
            _fail("candidate artifact authority cannot broaden a forbidden claim")
        _matches(self.profile, _PROFILE, "candidate authority profile")
        _matches(self.source_revision, _REVISION, "candidate authority source revision")
        _positive(self.workflow_id, "candidate authority workflow id")
        _positive(self.run_id, "candidate authority run id")
        _positive(self.artifact_id, "candidate authority artifact id")
        _positive(self.artifact_byte_size, "candidate authority artifact byte size")
        if self.artifact_byte_size > _MAX_CANDIDATE_ARCHIVE_BYTES:
            _fail("candidate authority artifact exceeds the archive byte ceiling")
        if self.artifact_name != (
            f"offline-release-{self.profile}-{self.source_revision}-{self.run_id}"
        ):
            _fail("candidate authority artifact name is invalid")
        _matches(self.artifact_sha256, _SHA, "candidate authority artifact SHA-256")

    def as_document(self) -> dict[str, Any]:
        return {
            "artifact": {
                "byteSize": self.artifact_byte_size,
                "id": self.artifact_id,
                "name": self.artifact_name,
                "sha256": self.artifact_sha256,
            },
            "claims": dict(_FALSE_CLAIMS),
            "profile": self.profile,
            "receiptType": _AUTHORITY_TYPE,
            "repository": {"fullName": REPOSITORY, "id": REPOSITORY_ID},
            "run": {
                "attempt": 1,
                "conclusion": "success",
                "event": "workflow_dispatch",
                "headBranch": TRUSTED_BRANCH,
                "headSha": self.source_revision,
                "id": self.run_id,
                "status": "completed",
            },
            "schemaVersion": 1,
            "workflow": {"id": self.workflow_id, "path": CONTROLLED_WORKFLOW_PATH},
        }


def _repository(value: object, label: str) -> int:
    repository = _object(value, label)
    if repository.get("full_name") != REPOSITORY:
        _fail(f"{label} full_name differs from the reviewed repository")
    repository_id = _positive(repository.get("id"), f"{label} id")
    if repository_id != REPOSITORY_ID:
        _fail(f"{label} id differs from the reviewed repository")
    return repository_id


def validate_candidate_artifact_authority(
    run_json: Path,
    artifacts_json: Path,
    *,
    profile: str,
    source_revision: str,
    candidate_run_id: int,
) -> CandidateArtifactAuthority:
    """Atomically bind one trusted run to its complete one-artifact inventory."""
    _matches(profile, _PROFILE, "candidate profile")
    _matches(source_revision, _REVISION, "source revision")
    candidate_run_id = _positive(candidate_run_id, "candidate run id")
    run = _load_json(run_json, "candidate run response")
    expected_run = {
        "id": candidate_run_id,
        "run_attempt": 1,
        "event": "workflow_dispatch",
        "status": "completed",
        "conclusion": "success",
        "head_branch": TRUSTED_BRANCH,
        "head_sha": source_revision,
        "path": CONTROLLED_WORKFLOW_PATH,
        "name": CONTROLLED_WORKFLOW_NAME,
        "pull_requests": [],
    }
    for key, expected in expected_run.items():
        if run.get(key) != expected or type(run.get(key)) is not type(expected):
            _fail(f"candidate run {key} differs from the reviewed value")
    workflow_id = _positive(run.get("workflow_id"), "candidate workflow id")
    _repository(run.get("repository"), "candidate run repository")
    _repository(run.get("head_repository"), "candidate run head repository")

    inventory = _load_json(artifacts_json, "candidate artifact inventory")
    if inventory.get("total_count") != 1 or type(inventory.get("total_count")) is not int:
        _fail("candidate artifact inventory must report exactly one artifact")
    artifacts = _array(inventory.get("artifacts"), "candidate artifacts")
    if len(artifacts) != 1:
        _fail("candidate artifact inventory must be complete and contain one artifact")
    artifact = _object(artifacts[0], "candidate artifact")
    expected_name = f"offline-release-{profile}-{source_revision}-{candidate_run_id}"
    if artifact.get("name") != expected_name:
        _fail("candidate artifact name differs from the reviewed value")
    if artifact.get("expired") is not False:
        _fail("candidate artifact must be unexpired")
    artifact_id = _positive(artifact.get("id"), "candidate artifact id")
    artifact_bytes = _positive(artifact.get("size_in_bytes"), "candidate artifact byte size")
    if artifact_bytes > _MAX_CANDIDATE_ARCHIVE_BYTES:
        _fail("candidate artifact exceeds the candidate archive byte ceiling")
    digest = artifact.get("digest")
    if type(digest) is not str or not digest.startswith("sha256:"):
        _fail("candidate artifact digest must be an exact SHA-256 digest")
    artifact_sha256 = _matches(digest[7:], _SHA, "candidate artifact digest")
    expected_api = f"https://api.github.com/repos/{REPOSITORY}/actions/artifacts/{artifact_id}"
    if (
        artifact.get("url") != expected_api
        or artifact.get("archive_download_url") != f"{expected_api}/zip"
    ):
        _fail("candidate artifact URLs differ from the reviewed repository and artifact")
    workflow_run = _exact_keys(
        artifact.get("workflow_run"),
        {"id", "repository_id", "head_repository_id", "head_branch", "head_sha"},
        "candidate artifact workflow_run",
    )
    expected_binding = {
        "id": candidate_run_id,
        "repository_id": REPOSITORY_ID,
        "head_repository_id": REPOSITORY_ID,
        "head_branch": TRUSTED_BRANCH,
        "head_sha": source_revision,
    }
    if workflow_run != expected_binding or any(
        type(workflow_run[key]) is not type(expected) for key, expected in expected_binding.items()
    ):
        _fail("candidate artifact workflow_run differs from the exact reviewed run binding")
    return CandidateArtifactAuthority(
        profile=profile,
        source_revision=source_revision,
        workflow_id=workflow_id,
        run_id=candidate_run_id,
        artifact_id=artifact_id,
        artifact_name=expected_name,
        artifact_sha256=artifact_sha256,
        artifact_byte_size=artifact_bytes,
    )


def write_candidate_artifact_authority(path: Path, authority: CandidateArtifactAuthority) -> None:
    """Commit one canonical authority receipt without overwriting any path."""
    _write_new(path, _canonical(authority.as_document()), "candidate authority receipt")


def load_candidate_artifact_authority(path: Path) -> CandidateArtifactAuthority:
    """Load an exact canonical receipt emitted by the atomic authority validator."""
    raw = _read_bounded(path, "candidate authority receipt")
    document = _json_bytes(raw, "candidate authority receipt")
    if raw != _canonical(document):
        _fail("candidate authority receipt is not canonical JSON")
    _exact_keys(
        document,
        {
            "artifact",
            "claims",
            "profile",
            "receiptType",
            "repository",
            "run",
            "schemaVersion",
            "workflow",
        },
        "candidate authority receipt",
    )
    if (
        type(document["schemaVersion"]) is not int
        or document["schemaVersion"] != 1
        or type(document["receiptType"]) is not str
        or document["receiptType"] != _AUTHORITY_TYPE
    ):
        _fail("candidate authority receipt identity is invalid")
    if type(document["claims"]) is not dict or set(document["claims"]) != set(_FALSE_CLAIMS):
        _fail("candidate authority receipt broadens a forbidden claim")
    if any(document["claims"][key] is not False for key in _FALSE_CLAIMS):
        _fail("candidate authority receipt broadens a forbidden claim")
    repository = _exact_keys(
        document["repository"], {"fullName", "id"}, "candidate authority repository"
    )
    if (
        type(repository["fullName"]) is not str
        or repository["fullName"] != REPOSITORY
        or type(repository["id"]) is not int
        or repository["id"] != REPOSITORY_ID
    ):
        _fail("candidate authority receipt repository is invalid")
    profile = _matches(document["profile"], _PROFILE, "candidate authority profile")
    workflow = _exact_keys(document["workflow"], {"id", "path"}, "candidate authority workflow")
    if type(workflow["path"]) is not str or workflow["path"] != CONTROLLED_WORKFLOW_PATH:
        _fail("candidate authority workflow path is invalid")
    workflow_id = _positive(workflow["id"], "candidate authority workflow id")
    run = _exact_keys(
        document["run"],
        {"attempt", "conclusion", "event", "headBranch", "headSha", "id", "status"},
        "candidate authority run",
    )
    source_revision = _matches(run["headSha"], _REVISION, "candidate authority source revision")
    if (
        type(run["attempt"]) is not int
        or run["attempt"] != 1
        or type(run["conclusion"]) is not str
        or run["conclusion"] != "success"
        or type(run["event"]) is not str
        or run["event"] != "workflow_dispatch"
        or type(run["headBranch"]) is not str
        or run["headBranch"] != TRUSTED_BRANCH
        or type(run["status"]) is not str
        or run["status"] != "completed"
    ):
        _fail("candidate authority run state is invalid")
    run_id = _positive(run["id"], "candidate authority run id")
    artifact = _exact_keys(
        document["artifact"], {"byteSize", "id", "name", "sha256"}, "candidate authority artifact"
    )
    artifact_id = _positive(artifact["id"], "candidate authority artifact id")
    artifact_size = _positive(artifact["byteSize"], "candidate authority artifact byte size")
    if artifact_size > _MAX_CANDIDATE_ARCHIVE_BYTES:
        _fail("candidate authority artifact exceeds the archive byte ceiling")
    expected_name = f"offline-release-{profile}-{source_revision}-{run_id}"
    if artifact["name"] != expected_name:
        _fail("candidate authority artifact name is invalid")
    digest = _matches(artifact["sha256"], _SHA, "candidate authority artifact SHA-256")
    return CandidateArtifactAuthority(
        profile=profile,
        source_revision=source_revision,
        workflow_id=workflow_id,
        run_id=run_id,
        artifact_id=artifact_id,
        artifact_name=expected_name,
        artifact_sha256=digest,
        artifact_byte_size=artifact_size,
    )


def _logical(name: str, label: str) -> PurePosixPath:
    if not name or "\\" in name or "\x00" in name:
        _fail(f"{label} contains a non-canonical path")
    path = PurePosixPath(name)
    if (
        path.is_absolute()
        or path.as_posix() != name
        or any(part in ("", ".", "..") for part in path.parts)
    ):
        _fail(f"{label} contains a non-canonical path")
    return path


def _archive_descriptor(
    path: Path, label: str, expected_size: int, expected_sha256: str, maximum: int
) -> tuple[int, os.stat_result]:
    expected_size = _positive(expected_size, f"{label} expected byte size")
    _matches(expected_sha256, _SHA, f"{label} expected SHA-256")
    if expected_size > maximum:
        _fail(f"{label} expected byte size exceeds its ceiling")
    descriptor, before = _open_regular(path, label, maximum)
    if before.st_size != expected_size:
        os.close(descriptor)
        _fail(f"{label} byte size differs from its authority")
    digest = hashlib.sha256()
    remaining = before.st_size
    while remaining:
        chunk = os.read(descriptor, min(_READ_SIZE, remaining))
        if not chunk:
            os.close(descriptor)
            _fail(f"{label} was truncated while hashing")
        digest.update(chunk)
        remaining -= len(chunk)
    if os.read(descriptor, 1):
        os.close(descriptor)
        _fail(f"{label} grew while hashing")
    if digest.hexdigest() != expected_sha256:
        os.close(descriptor)
        _fail(f"{label} SHA-256 differs from its authority")
    os.lseek(descriptor, 0, os.SEEK_SET)
    return descriptor, before


def _output_root(path: Path) -> int:
    if ".." in path.parts or path.name in ("", ".", ".."):
        _fail("output root must be one new canonical directory")
    absolute = path.absolute()
    flags = os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(absolute.anchor, flags)
    try:
        for part in absolute.parts[1:-1]:
            child = os.open(part, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        try:
            os.mkdir(absolute.name, 0o700, dir_fd=descriptor)
        except OSError as exc:
            raise ProtectedWorkflowArtifactError("output root must not already exist") from exc
        child = os.open(absolute.name, flags, dir_fd=descriptor)
        os.close(descriptor)
        return child
    except Exception:
        os.close(descriptor)
        raise


def _open_directory(root: int, path: PurePosixPath) -> int:
    flags = os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.dup(root)
    try:
        for part in path.parts:
            child = os.open(part, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        return descriptor
    except Exception:
        os.close(descriptor)
        raise


def _make_directories(root: int, directories: set[PurePosixPath]) -> None:
    created: set[PurePosixPath] = set()
    for logical in sorted(directories, key=lambda item: (len(item.parts), item.as_posix())):
        parent = _open_directory(root, logical.parent)
        try:
            if logical not in created:
                os.mkdir(logical.name, 0o700, dir_fd=parent)
                created.add(logical)
        except OSError as exc:
            raise ProtectedWorkflowArtifactError(
                f"cannot create exact archive directory {logical}"
            ) from exc
        finally:
            os.close(parent)


def _extract_file(
    root: int, archive: zipfile.ZipFile, logical: PurePosixPath, info: zipfile.ZipInfo
) -> None:
    directory = _open_directory(root, logical.parent)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(logical.name, flags, 0o400, dir_fd=directory)
        try:
            with archive.open(info, "r") as source:
                remaining = info.file_size
                while remaining:
                    chunk = source.read(min(_READ_SIZE, remaining))
                    if not chunk:
                        _fail(f"archive member {logical} was truncated")
                    view = memoryview(chunk)
                    while view:
                        written = os.write(descriptor, view)
                        if written <= 0:
                            _fail(f"archive member {logical} write made no progress")
                        view = view[written:]
                    remaining -= len(chunk)
                if source.read(1):
                    _fail(f"archive member {logical} exceeds its declared size")
            os.fsync(descriptor)
            metadata = os.fstat(descriptor)
            if (
                not stat.S_ISREG(metadata.st_mode)
                or metadata.st_nlink != 1
                or metadata.st_size != info.file_size
            ):
                _fail(f"archive member {logical} did not remain one exact regular file")
        finally:
            os.close(descriptor)
    except OSError as exc:
        raise ProtectedWorkflowArtifactError(
            f"cannot create exact archive member {logical}"
        ) from exc
    finally:
        os.close(directory)


def _inspect_zip(
    archive: zipfile.ZipFile,
    *,
    label: str,
    file_limit: Callable[[PurePosixPath], int],
    total_limit: int,
    member_limit: int,
    expected_files: frozenset[str] | None,
    expected_directories: frozenset[str] | None,
) -> tuple[dict[PurePosixPath, zipfile.ZipInfo], set[PurePosixPath]]:
    if len(archive.infolist()) > member_limit:
        _fail(f"{label} contains too many members")
    files: dict[PurePosixPath, zipfile.ZipInfo] = {}
    explicit_directories: set[PurePosixPath] = set()
    total = 0
    for info in archive.infolist():
        raw_name = info.filename
        is_directory = info.is_dir()
        name = raw_name[:-1] if is_directory and raw_name.endswith("/") else raw_name
        logical = _logical(name, label)
        kind = stat.S_IFMT(info.external_attr >> 16)
        if info.flag_bits & 1:
            _fail(f"{label} contains an encrypted member")
        if info.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
            _fail(f"{label} contains an unsupported compression method")
        if is_directory:
            if raw_name != f"{name}/" or logical in explicit_directories or logical in files:
                _fail(f"{label} contains a duplicate or non-canonical directory")
            if kind not in (0, stat.S_IFDIR) or info.file_size != 0:
                _fail(f"{label} contains a non-directory directory entry")
            explicit_directories.add(logical)
            continue
        if logical in files or logical in explicit_directories or kind not in (0, stat.S_IFREG):
            _fail(f"{label} contains a duplicate or non-regular file")
        maximum = file_limit(logical)
        if info.file_size <= 0 or info.file_size > maximum:
            _fail(f"{label} member {logical} is empty or exceeds its byte ceiling")
        total += info.file_size
        if total > total_limit:
            _fail(f"{label} exceeds its total expanded-byte ceiling")
        files[logical] = info
    file_names = frozenset(path.as_posix() for path in files)
    directory_names = frozenset(path.as_posix() for path in explicit_directories)
    if expected_files is not None and file_names != expected_files:
        _fail(f"{label} does not contain the exact expected file inventory")
    if expected_directories is not None and not directory_names.issubset(expected_directories):
        _fail(f"{label} contains an unexpected explicit directory")
    directories = set(explicit_directories)
    for logical in files:
        parent = logical.parent
        while parent != PurePosixPath("."):
            if parent in files:
                _fail(f"{label} contains a file/directory collision")
            directories.add(parent)
            parent = parent.parent
    if expected_directories is not None and directories != {
        PurePosixPath(item) for item in expected_directories
    }:
        _fail(f"{label} does not contain the exact expected directory inventory")
    return files, directories


def _extract_zip(
    archive_path: Path,
    output_root: Path,
    *,
    label: str,
    expected_size: int,
    expected_sha256: str,
    archive_limit: int,
    file_limit: Callable[[PurePosixPath], int],
    total_limit: int,
    member_limit: int,
    expected_files: frozenset[str] | None = None,
    expected_directories: frozenset[str] | None = None,
) -> int:
    descriptor, before = _archive_descriptor(
        archive_path, label, expected_size, expected_sha256, archive_limit
    )
    root = -1
    try:
        stream: BinaryIO = os.fdopen(os.dup(descriptor), "rb")
        with stream, zipfile.ZipFile(stream, "r") as archive:
            files, directories = _inspect_zip(
                archive,
                label=label,
                file_limit=file_limit,
                total_limit=total_limit,
                member_limit=member_limit,
                expected_files=expected_files,
                expected_directories=expected_directories,
            )
            root = _output_root(output_root)
            _make_directories(root, directories)
            for logical, info in sorted(files.items(), key=lambda item: item[0].as_posix()):
                _extract_file(root, archive, logical, info)
        _confirm_binding(archive_path, descriptor, before, label)
        os.fsync(root)
        return os.dup(root)
    except (zipfile.BadZipFile, RuntimeError, NotImplementedError) as exc:
        raise ProtectedWorkflowArtifactError(
            f"{label} must be one valid supported ZIP archive"
        ) from exc
    finally:
        os.close(descriptor)
        if root >= 0:
            os.close(root)


def _read_extracted(root: int, logical: PurePosixPath, label: str, maximum: int) -> bytes:
    directory = _open_directory(root, logical.parent)
    descriptor = -1
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    flags |= getattr(os, "O_NONBLOCK", 0)
    try:
        descriptor = os.open(logical.name, flags, dir_fd=directory)
        metadata = os.fstat(descriptor)
        linked = os.stat(logical.name, dir_fd=directory, follow_symlinks=False)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_nlink != 1
            or metadata.st_size <= 0
            or metadata.st_size > maximum
            or _identity(metadata) != _identity(linked)
        ):
            _fail(f"{label} is not one stable bounded regular file")
        chunks: list[bytes] = []
        remaining = metadata.st_size
        while remaining:
            chunk = os.read(descriptor, min(_READ_SIZE, remaining))
            if not chunk:
                _fail(f"{label} was truncated")
            chunks.append(chunk)
            remaining -= len(chunk)
        if os.read(descriptor, 1) or _identity(metadata) != _identity(os.fstat(descriptor)):
            _fail(f"{label} changed while it was read")
        return b"".join(chunks)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        os.close(directory)


def _strict_document(
    root: int, path: str, label: str, maximum: int = _MAX_METADATA_BYTES
) -> Mapping[str, Any]:
    return _json_bytes(_read_extracted(root, PurePosixPath(path), label, maximum), label)


def _file_identity(
    value: object,
    label: str,
    *,
    byte_size: bool = False,
    public_output: bool = False,
) -> Mapping[str, Any]:
    keys = {"path", "sha256"}
    if byte_size or public_output:
        keys.add("byteSize")
    if public_output:
        keys.update({"role", "mediaType"})
    item = _exact_keys(value, keys, label)
    if (
        type(item["path"]) is not str
        or len(item["path"]) > 512
        or _RELEASE_PATH.fullmatch(item["path"]) is None
    ):
        _fail(f"{label} path is not a canonical release-relative path")
    _matches(item["sha256"], _SHA, f"{label} SHA-256")
    if public_output:
        if item["role"] not in _ARTIFACT_ROLES or item["mediaType"] not in _MEDIA_TYPES:
            _fail(f"{label} role or mediaType is not in the release contract")
    if byte_size or public_output:
        observed_size = _positive(item["byteSize"], f"{label} byte size")
        if observed_size > _MAX_ARTIFACT_BYTES:
            _fail(f"{label} exceeds the candidate per-artifact byte ceiling")
    return item


def _validate_dispatch(
    document: Mapping[str, Any], authority: CandidateArtifactAuthority
) -> Mapping[str, Any]:
    dispatch = _exact_keys(
        document,
        {
            "schemaVersion",
            "profile",
            "sourceRevision",
            "reviewedInput",
            "releaseDate",
            "receiptTimestamps",
            "workflowRunId",
            "publicationAttempted",
            "activationAttempted",
        },
        "dispatch receipt",
    )
    if (
        type(dispatch["schemaVersion"]) is not int
        or dispatch["schemaVersion"] != 1
        or dispatch["profile"] != authority.profile
        or dispatch["sourceRevision"] != authority.source_revision
        or dispatch["workflowRunId"] != str(authority.run_id)
        or dispatch["publicationAttempted"] is not False
        or dispatch["activationAttempted"] is not False
    ):
        _fail("dispatch receipt differs from the exact non-publishing candidate run")
    reviewed = _exact_keys(
        dispatch["reviewedInput"], {"runId", "artifactName", "bundleSha256"}, "reviewed input"
    )
    _matches(reviewed["runId"], _RUN_ID, "reviewed input run id")
    _matches(reviewed["artifactName"], _ARTIFACT_NAME, "reviewed input artifact name")
    _matches(reviewed["bundleSha256"], _SHA, "reviewed input bundle SHA-256")
    _calendar_value(dispatch["releaseDate"], _DATE, "%Y%m%d", "dispatch release date")
    timestamps = _exact_keys(
        dispatch["receiptTimestamps"], {"startedAt", "completedAt"}, "receipt timestamps"
    )
    _calendar_value(
        timestamps["startedAt"],
        _TIMESTAMP,
        "%Y-%m-%dT%H:%M:%SZ",
        "receipt start timestamp",
    )
    _calendar_value(
        timestamps["completedAt"],
        _TIMESTAMP,
        "%Y-%m-%dT%H:%M:%SZ",
        "receipt completion timestamp",
    )
    if timestamps["startedAt"] > timestamps["completedAt"]:
        _fail("dispatch receipt timestamps are reversed")
    return dispatch


def _validate_execution(
    document: Mapping[str, Any], authority: CandidateArtifactAuthority
) -> Mapping[str, Any]:
    execution = _exact_keys(
        document,
        {
            "schemaVersion",
            "receiptType",
            "buildId",
            "planIdentitySha256",
            "dataReleaseId",
            "profile",
            "networkAccess",
            "status",
            "stages",
            "finalOutputs",
            "candidate",
            "resourceUsage",
        },
        "execution receipt",
    )
    if (
        type(execution["schemaVersion"]) is not int
        or execution["schemaVersion"] != 1
        or execution["receiptType"] != "offline-build-execution"
        or execution["profile"] != authority.profile
        or execution["networkAccess"] != "disabled"
        or execution["status"] != "complete"
    ):
        _fail("execution receipt differs from the exact complete offline candidate")
    _matches(execution["buildId"], _BUILD_ID, "execution build id")
    _matches(execution["planIdentitySha256"], _SHA, "execution plan identity")
    _matches(execution["dataReleaseId"], _RELEASE_ID, "execution data release id")
    stages = _array(execution["stages"], "execution stages")
    if len(stages) != len(_EXECUTION_STAGES):
        _fail("execution receipt must contain the exact seven-stage inventory")
    for index, (stage_value, expected_stage) in enumerate(zip(stages, _EXECUTION_STAGES)):
        stage = _exact_keys(
            stage_value,
            {
                "stage",
                "stageKeySha256",
                "cacheStatus",
                "durationSeconds",
                "outputs",
                "warnings",
                "qualityResults",
            },
            f"execution stage {index}",
        )
        if stage["stage"] != expected_stage or stage["cacheStatus"] != "miss":
            _fail("controlled execution stages must be exact ordered cache misses")
        _matches(stage["stageKeySha256"], _SHA, f"execution stage {index} key")
        if type(stage["durationSeconds"]) not in (int, float) or stage["durationSeconds"] < 0:
            _fail(f"execution stage {index} duration is invalid")
        outputs = _array(stage["outputs"], f"execution stage {index} outputs")
        if not outputs:
            _fail(f"execution stage {index} outputs are empty")
        for output_index, output in enumerate(outputs):
            _file_identity(output, f"execution stage {index} output {output_index}", byte_size=True)
        _require_unique(outputs, f"execution stage {index} outputs")
        warnings = _array(stage["warnings"], f"execution stage {index} warnings")
        if any(type(item) is not str or not item or len(item) > 256 for item in warnings) or len(
            set(warnings)
        ) != len(warnings):
            _fail(f"execution stage {index} warnings are invalid")
        _object(stage["qualityResults"], f"execution stage {index} quality results")
    final_outputs = _array(execution["finalOutputs"], "execution final outputs")
    if not final_outputs or stages[-1]["outputs"] != final_outputs:
        _fail("execution final outputs differ from assemble-release outputs")
    for index, output in enumerate(final_outputs):
        _file_identity(output, f"execution final output {index}", byte_size=True)
    _require_unique(final_outputs, "execution final outputs")
    candidate = _exact_keys(
        execution["candidate"], {"fileCount", "byteSize", "inventorySha256"}, "execution candidate"
    )
    _positive(candidate["fileCount"], "execution candidate file count")
    _positive(candidate["byteSize"], "execution candidate byte size")
    _matches(candidate["inventorySha256"], _SHA, "execution candidate inventory SHA-256")
    encoded = json.dumps(
        final_outputs, ensure_ascii=False, allow_nan=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    if candidate != {
        "fileCount": len(final_outputs),
        "byteSize": sum(item["byteSize"] for item in final_outputs),
        "inventorySha256": hashlib.sha256(encoded).hexdigest(),
    }:
        _fail("execution candidate summary differs from the exact final output inventory")
    if candidate["byteSize"] > _MAX_CANDIDATE_BYTES:
        _fail("execution candidate summary exceeds the candidate total byte ceiling")
    usage = _exact_keys(
        execution["resourceUsage"],
        {"totalDurationSeconds", "peakProcessRssBytes"},
        "execution resource usage",
    )
    if type(usage["totalDurationSeconds"]) not in (int, float) or usage["totalDurationSeconds"] < 0:
        _fail("execution total duration is invalid")
    _positive(usage["peakProcessRssBytes"], "execution peak RSS")
    return execution


def _validate_build(
    document: Mapping[str, Any],
    authority: CandidateArtifactAuthority,
    dispatch: Mapping[str, Any],
    execution: Mapping[str, Any],
) -> None:
    build = _exact_keys(
        document,
        {
            "$schema",
            "schemaVersion",
            "dataReleaseId",
            "dataProvenanceClass",
            "buildId",
            "codeRevision",
            "buildMode",
            "networkAccess",
            "startedAt",
            "completedAt",
            "environment",
            "tools",
            "sourceReceipts",
            "inputs",
            "parametersSha256",
            "outputs",
            "reproducibilityComparison",
        },
        "build receipt",
    )
    if (
        build["$schema"]
        != "https://artemsemdev.github.io/SeaRise-Europe/contracts/release/v1/build-receipt.schema.json"
        or build["schemaVersion"] != "1.0.0"
        or build["dataReleaseId"] != execution["dataReleaseId"]
        or build["dataProvenanceClass"] != "real-source"
        or build["buildId"] != execution["buildId"]
        or build["codeRevision"] != authority.source_revision
        or build["buildMode"] != "offline"
        or build["networkAccess"] != "disabled"
        or build["startedAt"] != dispatch["receiptTimestamps"]["startedAt"]
        or build["completedAt"] != dispatch["receiptTimestamps"]["completedAt"]
    ):
        _fail("build receipt differs from the exact real-source offline execution")
    environment = _exact_keys(
        build["environment"],
        {"platform", "architecture", "pythonVersion", "lock"},
        "build environment",
    )
    if environment["platform"] != "linux" or environment["architecture"] != "x86_64":
        _fail("controlled build environment must be Linux x86_64")
    _matches(environment["pythonVersion"], _VERSION, "build Python version")
    _file_identity(environment["lock"], "build environment lock")
    tools = _array(build["tools"], "build tools")
    if not tools:
        _fail("build tools must not be empty")
    for index, value in enumerate(tools):
        tool = _exact_keys(value, {"name", "version", "identitySha256"}, f"build tool {index}")
        _matches(tool["name"], _TOOL_NAME, f"build tool {index} name")
        if type(tool["version"]) is not str or not tool["version"]:
            _fail(f"build tool {index} version is invalid")
        _matches(tool["identitySha256"], _SHA, f"build tool {index} identity")
    _require_unique(tools, "build tools")
    for field in ("sourceReceipts", "inputs"):
        values = _array(build[field], f"build {field}")
        if not values:
            _fail(f"build {field} must not be empty")
        for index, value in enumerate(values):
            _file_identity(value, f"build {field} {index}")
        _require_unique(values, f"build {field}")
    _matches(build["parametersSha256"], _SHA, "build parameters SHA-256")
    outputs = _array(build["outputs"], "build outputs")
    if not outputs:
        _fail("build outputs must not be empty")
    for index, value in enumerate(outputs):
        _file_identity(value, f"build output {index}", public_output=True)
    _require_unique(outputs, "build outputs")
    comparison = _exact_keys(
        build["reproducibilityComparison"],
        {"identityFields", "excludedVolatileFields"},
        "build reproducibility comparison",
    )
    if comparison != {
        "identityFields": [
            "dataReleaseId",
            "codeRevision",
            "environment.lock.sha256",
            "tools",
            "sourceReceipts",
            "inputs",
            "parametersSha256",
            "outputs",
        ],
        "excludedVolatileFields": ["startedAt", "completedAt"],
    }:
        _fail("build reproducibility comparison is invalid")


def extract_protected_candidate(
    archive_path: Path, output_root: Path, authority_path: Path
) -> CandidateArtifactAuthority:
    """Extract one authority-bound candidate and validate its boundary receipts."""
    authority = load_candidate_artifact_authority(authority_path)

    def candidate_limit(path: PurePosixPath) -> int:
        if path in {PurePosixPath("execution.json"), PurePosixPath("dispatch.json")}:
            return _MAX_METADATA_BYTES
        if path == PurePosixPath("candidate/manifest.json"):
            return _MAX_MANIFEST_BYTES
        if path == PurePosixPath("candidate/receipts/build.json"):
            return _MAX_METADATA_BYTES
        return _MAX_ARTIFACT_BYTES

    root = _extract_zip(
        archive_path,
        output_root,
        label="protected candidate archive",
        expected_size=authority.artifact_byte_size,
        expected_sha256=authority.artifact_sha256,
        archive_limit=_MAX_CANDIDATE_ARCHIVE_BYTES,
        file_limit=candidate_limit,
        total_limit=_MAX_CANDIDATE_BYTES + _MAX_MANIFEST_BYTES + 2 * _MAX_METADATA_BYTES,
        member_limit=_MAX_CANDIDATE_MEMBERS,
    )
    try:
        top = {entry.name: entry for entry in os.scandir(root)}
        if set(top) != {"candidate", "execution.json", "dispatch.json"}:
            _fail("candidate archive top level must contain exactly candidate and two receipts")
        if not top["candidate"].is_dir(follow_symlinks=False):
            _fail("candidate archive candidate entry must be a directory")
        dispatch = _validate_dispatch(
            _strict_document(root, "dispatch.json", "dispatch receipt"), authority
        )
        execution = _validate_execution(
            _strict_document(root, "execution.json", "execution receipt"), authority
        )
        _validate_build(
            _strict_document(root, "candidate/receipts/build.json", "build receipt"),
            authority,
            dispatch,
            execution,
        )
        linearized = _open_existing_root(output_root)
        try:
            if _identity(os.fstat(linearized)) != _identity(os.fstat(root)):
                _fail("candidate output root changed before descriptor linearization")
        finally:
            os.close(linearized)
    finally:
        os.close(root)
    return authority


def _open_existing_root(path: Path) -> int:
    absolute = path.absolute()
    flags = os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(absolute.anchor, flags)
    try:
        for part in absolute.parts[1:]:
            child = os.open(part, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        return descriptor
    except Exception:
        os.close(descriptor)
        raise


def extract_protected_evidence(
    archive_path: Path,
    output_root: Path,
    *,
    expected_sha256: str,
    expected_byte_size: int,
) -> None:
    """Extract one exact bounded protected evidence artifact without approving it."""
    root = _extract_zip(
        archive_path,
        output_root,
        label="protected evidence archive",
        expected_size=expected_byte_size,
        expected_sha256=expected_sha256,
        archive_limit=_MAX_EVIDENCE_ARCHIVE_BYTES,
        file_limit=lambda _path: _MAX_EVIDENCE_FILE_BYTES,
        total_limit=_MAX_EVIDENCE_BYTES,
        member_limit=len(_EVIDENCE_FILES) + len(_EVIDENCE_DIRECTORIES),
        expected_files=_EVIDENCE_FILES,
        expected_directories=_EVIDENCE_DIRECTORIES,
    )
    try:
        linearized = _open_existing_root(output_root)
        try:
            if _identity(os.fstat(linearized)) != _identity(os.fstat(root)):
                _fail("evidence output root changed before descriptor linearization")
        finally:
            os.close(linearized)
    finally:
        os.close(root)
