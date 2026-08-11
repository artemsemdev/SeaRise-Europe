"""Fail-closed byte-range validation for the nine reviewed projection COGs."""

from __future__ import annotations

import hashlib
import json
import re
import time
from collections.abc import Mapping as RuntimeMapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Literal, Mapping, NoReturn, Protocol

from ..release.evidence import binding_sha256, safe_candidate_path, sha256
from ..science import ScienceContractError
from .projection_bundle import load_reviewed_projection_evidence

_COG_PATH = re.compile(r"analysis/(ssp1-26|ssp2-45|ssp5-85)/(2030|2050|2100)\.tif")
_CONTENT_RANGE = re.compile(r"bytes ([0-9]+)-([0-9]+)/([0-9]+)")
_PROBE_BYTES = 64


@dataclass(frozen=True)
class CogArtifactIdentity:
    """Owner-reviewed immutable identity for one analysis COG."""

    path: str
    byte_size: int
    sha256: str


@dataclass(frozen=True)
class RangeResponse:
    """Transport-neutral representation of one ranged response."""

    status: int
    headers: Mapping[str, str]
    body: bytes


class RangeTransport(Protocol):
    """Transport adapter used by the validator; ordinary tests stay offline."""

    def get_range(
        self,
        artifact: CogArtifactIdentity,
        *,
        start: int,
        end: int,
    ) -> RangeResponse:
        """Return a response for the inclusive byte range."""


def load_reviewed_cog_identities(repository_root: Path) -> tuple[CogArtifactIdentity, ...]:
    """Bind the exact 3 x 3 COG matrix to the approved Phase 0R evidence."""
    evidence = load_reviewed_projection_evidence(repository_root)
    binding_hashes = evidence.binding.get("artifactHashes")
    trace_candidate = evidence.delivery_trace.get("candidate")
    if not isinstance(trace_candidate, dict):
        _fail("validated projection trace lost its candidate")
    trace_hashes = trace_candidate.get("artifactHashes")
    trace_sizes = trace_candidate.get("artifactByteSizes")
    if not all(isinstance(value, dict) for value in (binding_hashes, trace_hashes, trace_sizes)):
        _fail("reviewed COG range inventory is malformed")
    assert isinstance(binding_hashes, dict)
    assert isinstance(trace_hashes, dict)
    assert isinstance(trace_sizes, dict)
    paths = sorted(path for path in binding_hashes if _COG_PATH.fullmatch(path))
    expected_paths = {
        f"analysis/{scenario}/{horizon}.tif"
        for scenario in ("ssp1-26", "ssp2-45", "ssp5-85")
        for horizon in (2030, 2050, 2100)
    }
    if set(paths) != expected_paths:
        _fail("reviewed COG range inventory is not the exact 3 x 3 matrix")

    identities: list[CogArtifactIdentity] = []
    for path in paths:
        digest = binding_hashes[path]
        byte_size = trace_sizes.get(path)
        if (
            not isinstance(digest, str)
            or re.fullmatch(r"[0-9a-f]{64}", digest) is None
            or trace_hashes.get(path) != digest
            or type(byte_size) is not int
            or byte_size <= _PROBE_BYTES * 3
        ):
            _fail(f"reviewed COG identity is inconsistent: {path}")
        identities.append(CogArtifactIdentity(path=path, byte_size=byte_size, sha256=digest))
    return tuple(identities)


def validate_reviewed_cog_range_access(
    bundle_root: Path,
    *,
    repository_root: Path,
    transport: RangeTransport,
    clock_ns: Callable[[], int] = time.perf_counter_ns,
) -> dict[str, Any]:
    """Validate canonical and TIFF-reader-driven range paths for all nine COGs."""
    evidence = load_reviewed_projection_evidence(repository_root)
    identities = load_reviewed_cog_identities(repository_root)
    artifact_reports: list[dict[str, Any]] = []
    for artifact in identities:
        trusted_path = _trusted_artifact(bundle_root, artifact)
        trusted_bytes = trusted_path.read_bytes()
        access = _ValidatedRangeAccess(artifact, trusted_bytes, transport, clock_ns)
        probes = _canonical_probes(artifact)
        for label, start in probes:
            access.read(start, _PROBE_BYTES, label=label)
        _validate_tiff_reader_path(access)
        expected = _expected_request_coordinates(artifact)
        observed = tuple(
            (item.label, item.start, item.requested_end, item.actual_end)
            for item in access.requests
        )
        if observed != expected or len({item[:3] for item in observed}) != len(expected):
            _fail(f"COG range request coordinates changed: {artifact.path}")
        artifact_reports.append(
            {
                "path": artifact.path,
                "sha256": artifact.sha256,
                "byteSize": artifact.byte_size,
                "canonicalProbes": [label for label, _ in probes],
                "readerRangeRequests": 3,
                "rangeRequests": access.request_count,
                "requestCoordinates": [list(item) for item in observed],
                "requests": [item.as_evidence() for item in access.requests],
            }
        )
    binding = evidence.binding
    return {
        "schemaVersion": 1,
        "evidenceType": "reviewed-cog-range-access",
        "reviewedProjectionCandidate": {
            "releaseId": binding["releaseId"],
            "releaseContractId": binding["releaseContractId"],
            "manifestSha256": binding["manifestSha256"],
            "candidateBindingSha256": binding_sha256(binding),
            "sourceRevision": binding["sourceRevision"],
        },
        "artifactCount": len(artifact_reports),
        "rangeRequestCount": sum(item["rangeRequests"] for item in artifact_reports),
        "artifacts": artifact_reports,
        "evidenceDisposition": "fixture-validation-only",
    }


class _ValidatedRangeAccess:
    def __init__(
        self,
        artifact: CogArtifactIdentity,
        trusted_bytes: bytes,
        transport: RangeTransport,
        clock_ns: Callable[[], int] = time.perf_counter_ns,
    ) -> None:
        self.artifact = artifact
        self._trusted = trusted_bytes
        self._transport = transport
        self._clock_ns = clock_ns
        self.request_count = 0
        self.reader_request_count = 0
        self.requests: list[_RequestRecord] = []

    def read(self, start: int, length: int, *, label: str = "reader") -> bytes:
        if type(start) is not int or type(length) is not int or start < 0 or length <= 0:
            _fail(f"invalid COG range request for {self.artifact.path}")
        if start >= self.artifact.byte_size:
            _fail(f"COG range begins beyond the artifact: {self.artifact.path}")
        requested_end = start + length - 1
        actual_end = min(requested_end, self.artifact.byte_size - 1)
        started_ns = self._clock_ns()
        response = self._transport.get_range(
            self.artifact,
            start=start,
            end=requested_end,
        )
        completed_ns = self._clock_ns()
        if (
            type(started_ns) is not int
            or type(completed_ns) is not int
            or started_ns < 0
            or completed_ns < started_ns
        ):
            _fail(f"COG range latency clock is invalid for {self.artifact.path}")
        body, headers = _validate_range_response(
            self.artifact,
            response,
            start=start,
            actual_end=actual_end,
            trusted=self._trusted,
        )
        self.request_count += 1
        self.requests.append(
            _RequestRecord(
                label=label,
                start=start,
                requested_end=requested_end,
                actual_end=actual_end,
                status=response.status,
                content_range=headers["content-range"],
                content_length=headers["content-length"],
                accept_ranges=headers["accept-ranges"],
                response_bytes=len(body),
                response_sha256=hashlib.sha256(body).hexdigest(),
                latency_nanoseconds=completed_ns - started_ns,
            )
        )
        if label.startswith("reader-"):
            self.reader_request_count += 1
        return body


@dataclass(frozen=True)
class _RequestRecord:
    label: str
    start: int
    requested_end: int
    actual_end: int
    status: int
    content_range: str
    content_length: str
    accept_ranges: str
    response_bytes: int
    response_sha256: str
    latency_nanoseconds: int

    def as_evidence(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "requestedRange": f"bytes={self.start}-{self.requested_end}",
            "status": self.status,
            "contentRange": self.content_range,
            "contentLength": self.content_length,
            "acceptRanges": self.accept_ranges,
            "responseBytes": self.response_bytes,
            "responseSha256": self.response_sha256,
            "latencyNanoseconds": self.latency_nanoseconds,
        }


def _validate_range_response(
    artifact: CogArtifactIdentity,
    response: RangeResponse,
    *,
    start: int,
    actual_end: int,
    trusted: bytes,
) -> tuple[bytes, Mapping[str, str]]:
    if type(response) is not RangeResponse:
        _fail(f"COG transport returned an invalid response object: {artifact.path}")
    if type(response.status) is not int or response.status != 206:
        _fail(f"COG server ignored or rejected Range for {artifact.path}")
    if not isinstance(response.headers, RuntimeMapping) or type(response.body) is not bytes:
        _fail(f"COG range response types are malformed for {artifact.path}")
    headers: dict[str, str] = {}
    for key, value in response.headers.items():
        if type(key) is not str or type(value) is not str:
            _fail(f"COG range headers are malformed for {artifact.path}")
        lowered = key.lower()
        if lowered in headers:
            _fail(f"COG range headers are duplicated for {artifact.path}")
        headers[lowered] = value
    expected_length = actual_end - start + 1
    expected_content_range = f"bytes {start}-{actual_end}/{artifact.byte_size}"
    content_range = headers.get("content-range")
    if (
        content_range != expected_content_range
        or content_range is None
        or _CONTENT_RANGE.fullmatch(content_range) is None
        or headers.get("content-length") != str(expected_length)
        or headers.get("accept-ranges") != "bytes"
    ):
        _fail(f"COG range headers do not describe the requested bytes: {artifact.path}")
    if len(response.body) != expected_length:
        _fail(f"COG range body is truncated or substituted for {artifact.path}")
    if response.body != trusted[start : actual_end + 1]:
        _fail(f"COG range body differs from the reviewed artifact: {artifact.path}")
    return response.body, headers


def _canonical_probes(
    artifact: CogArtifactIdentity,
) -> tuple[tuple[str, int], ...]:
    middle_start = artifact.byte_size // 2 - _PROBE_BYTES // 2
    return (
        ("beginning", 0),
        ("middle", middle_start),
        ("end", artifact.byte_size - _PROBE_BYTES),
    )


def _expected_request_coordinates(
    artifact: CogArtifactIdentity,
) -> tuple[tuple[str, int, int, int], ...]:
    middle_start = artifact.byte_size // 2 - _PROBE_BYTES // 2
    return (
        ("beginning", 0, 63, 63),
        ("middle", middle_start, middle_start + 63, middle_start + 63),
        (
            "end",
            artifact.byte_size - 64,
            artifact.byte_size - 1,
            artifact.byte_size - 1,
        ),
        ("reader-browser", 0, 65535, artifact.byte_size - 1),
        ("reader-ifd-count", 192, 193, 193),
        ("reader-ifd-payload", 194, 449, 449),
    )


def _validate_tiff_reader_path(access: _ValidatedRangeAccess) -> int:
    """Follow TIFF offsets from returned bytes so the reader drives later ranges."""
    before = access.reader_request_count
    # The browser GeoTIFF reader recorded by the approved trace starts with a
    # 64 KiB request. These reviewed COGs are smaller, so a compliant server
    # clips the returned Content-Range at EOF while retaining status 206.
    header_body = access.read(0, 64 * 1024, label="reader-browser")
    if len(header_body) < 16:
        _fail(f"reviewed COG is too small for a TIFF header: {access.artifact.path}")
    header = header_body[:16]
    if header[:2] == b"II":
        byteorder: Literal["little", "big"] = "little"
    elif header[:2] == b"MM":
        byteorder = "big"
    else:
        _fail(f"reviewed COG lacks a TIFF byte-order marker: {access.artifact.path}")
    magic = int.from_bytes(header[2:4], byteorder)
    if magic == 42:
        ifd_offset = int.from_bytes(header[4:8], byteorder)
        count_bytes = 2
        entry_bytes = 12
        next_ifd_bytes = 4
    elif magic == 43 and int.from_bytes(header[4:6], byteorder) == 8 and header[6:8] == b"\x00\x00":
        ifd_offset = int.from_bytes(header[8:16], byteorder)
        count_bytes = 8
        entry_bytes = 20
        next_ifd_bytes = 8
    else:
        _fail(f"reviewed COG has an unsupported TIFF header: {access.artifact.path}")
    if ifd_offset < 16 or ifd_offset + count_bytes > access.artifact.byte_size:
        _fail(f"reviewed COG TIFF directory offset is out of bounds: {access.artifact.path}")
    count_raw = access.read(ifd_offset, count_bytes, label="reader-ifd-count")
    entry_count = int.from_bytes(count_raw, byteorder)
    payload_length = entry_count * entry_bytes + next_ifd_bytes
    payload_start = ifd_offset + count_bytes
    if (
        entry_count <= 0
        or payload_length <= next_ifd_bytes
        or payload_start + payload_length > access.artifact.byte_size
    ):
        _fail(f"reviewed COG TIFF directory is out of bounds: {access.artifact.path}")
    access.read(payload_start, payload_length, label="reader-ifd-payload")
    derived = access.requests[-2:]
    if (
        len(derived) != 2
        or derived[0].requested_end >= derived[1].start
        or len({(item.start, item.requested_end) for item in derived}) != 2
    ):
        _fail(f"reviewed COG TIFF reader ranges overlap: {access.artifact.path}")
    return access.reader_request_count - before


def load_served_cog_candidate_identity(
    bundle_root: Path,
    identities: tuple[CogArtifactIdentity, ...],
) -> dict[str, Any]:
    """Bind the served public candidate manifest to the reviewed COG matrix."""
    manifest_path = bundle_root / "manifest.json"
    if bundle_root.is_symlink() or not manifest_path.is_file() or manifest_path.is_symlink():
        _fail("served COG candidate manifest is absent or unsafe")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ScienceContractError("Cannot read served COG candidate manifest") from exc
    if not isinstance(manifest, dict):
        _fail("served COG candidate manifest must be an object")
    data_release_id = manifest.get("dataReleaseId")
    code_revision = manifest.get("codeRevision")
    provenance_class = manifest.get("dataProvenanceClass")
    artifacts = manifest.get("artifacts")
    if (
        type(data_release_id) is not str
        or not data_release_id
        or type(code_revision) is not str
        or re.fullmatch(r"[0-9a-f]{40}", code_revision) is None
        or type(provenance_class) is not str
        or provenance_class not in {"synthetic-fixture", "real-source"}
        or not isinstance(artifacts, list)
    ):
        _fail("served COG candidate identity is malformed")
    cog_records = [
        item
        for item in artifacts
        if isinstance(item, dict) and _COG_PATH.fullmatch(str(item.get("path")))
    ]
    records = {item.get("path"): item for item in cog_records}
    expected_paths = {identity.path for identity in identities}
    if len(cog_records) != 9 or len(records) != 9 or set(records) != expected_paths:
        _fail("served COG candidate does not declare the exact 3 x 3 matrix")
    artifact_set: dict[str, dict[str, Any]] = {}
    for identity in identities:
        record = records[identity.path]
        if (
            record.get("sha256") != identity.sha256
            or record.get("byteSize") != identity.byte_size
            or record.get("role") != "projection-analysis-cog"
            or record.get("scientificUse") != "exact-lookup"
        ):
            _fail(f"served COG manifest identity differs from review: {identity.path}")
        artifact_set[identity.path] = {
            "byteSize": identity.byte_size,
            "sha256": identity.sha256,
        }
    return {
        "dataReleaseId": data_release_id,
        "codeRevision": code_revision,
        "dataProvenanceClass": provenance_class,
        "manifestSha256": sha256(manifest_path),
        "projectionArtifactSetSha256": binding_sha256(artifact_set),
    }


def _trusted_artifact(bundle_root: Path, artifact: CogArtifactIdentity) -> Path:
    path = safe_candidate_path(bundle_root, artifact.path)
    if bundle_root.is_symlink() or not path.is_file() or path.is_symlink():
        _fail(f"reviewed COG is absent or unsafe: {artifact.path}")
    if path.stat().st_size != artifact.byte_size or sha256(path) != artifact.sha256:
        _fail(f"local COG differs from the reviewed identity: {artifact.path}")
    return path


def _fail(message: str) -> NoReturn:
    raise ScienceContractError(message)
