"""Persist candidate-bound COG Range evidence through loopback HTTP."""

from __future__ import annotations

import contextlib
import hashlib
import re
import threading
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterator, Mapping
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, NoReturn

import click

from ..release.evidence import (
    binding_sha256,
    ensure_outside_candidate,
    load_json_snapshot,
    safe_candidate_path,
    write_new_json_record,
)
from ..science import ScienceContractError
from .cog_range import (
    CogArtifactIdentity,
    RangeResponse,
    RangeTransport,
    load_reviewed_cog_identities,
    load_served_cog_candidate_identity,
    validate_reviewed_cog_range_access,
)
from .projection_bundle import load_reviewed_projection_evidence

_EXECUTION_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}")
_REVISION = re.compile(r"[0-9a-f]{40}")
_WORKFLOW_JOB = re.compile(r"[a-z][a-z0-9_-]{0,63}")
_RANGE_HEADER = re.compile(r"bytes=([0-9]+)-([0-9]+)")
_CLOCK = "time.perf_counter_ns"
_DISPOSITION = "candidate-bound-loopback-http-validation-only"
_LIMITATIONS = [
    "Latency is a runner-local loopback measurement and is not a release budget.",
    "No public origin, CDN, cache, CORS, TLS, or production delivery claim is made.",
]
_REJECTION_CASES = {
    "malformed": "headers do not describe",
    "ignored": "ignored or rejected",
    "truncated": "truncated or substituted",
    "substituted": "differs from the reviewed artifact",
    "corrupt": "differs from the reviewed artifact",
}


class _LoopbackHttpRangeTransport:
    def __init__(self, port: int) -> None:
        self._base_url = f"http://127.0.0.1:{port}/"
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def get_range(
        self,
        artifact: CogArtifactIdentity,
        *,
        start: int,
        end: int,
    ) -> RangeResponse:
        url = urllib.parse.urljoin(
            self._base_url,
            urllib.parse.quote(artifact.path, safe="/"),
        )
        request = urllib.request.Request(
            url,
            headers={"Range": f"bytes={start}-{end}"},
            method="GET",
        )
        try:
            response = self._opener.open(request, timeout=10)
        except urllib.error.HTTPError as exc:
            with exc:
                return RangeResponse(exc.code, dict(exc.headers.items()), exc.read())
        except (OSError, urllib.error.URLError) as exc:
            raise ScienceContractError("Cannot read COG bytes from loopback HTTP") from exc
        with response:
            return RangeResponse(
                response.status,
                dict(response.headers.items()),
                response.read(),
            )


class _MutatingTransport:
    def __init__(self, transport: RangeTransport, case: str) -> None:
        self._transport = transport
        self._case = case
        self.request_count = 0

    def get_range(
        self,
        artifact: CogArtifactIdentity,
        *,
        start: int,
        end: int,
    ) -> RangeResponse:
        response = self._transport.get_range(artifact, start=start, end=end)
        self.request_count += 1
        if self.request_count != 1:
            return response
        headers = dict(response.headers)
        body = response.body
        if self._case == "malformed":
            headers["Content-Range"] = "bytes malformed"
            return RangeResponse(response.status, headers, body)
        if self._case == "ignored":
            return RangeResponse(200, headers, body)
        if self._case == "truncated":
            return RangeResponse(response.status, headers, body[:-1])
        if self._case == "substituted":
            return RangeResponse(response.status, headers, body[1:] + body[:1])
        if self._case == "corrupt":
            return RangeResponse(response.status, headers, bytes([body[0] ^ 1]) + body[1:])
        _fail("COG evidence mutation case is unsupported")


def capture_loopback_cog_range_evidence(
    bundle_root: Path,
    *,
    repository_root: Path,
    output_path: Path,
    execution_id: str,
    source_revision: str,
    tested_revision: str,
    workflow_run_id: int,
    workflow_run_attempt: int,
    workflow_job: str,
) -> dict[str, Any]:
    """Run positive and negative HTTP probes and commit one immutable report."""
    if _EXECUTION_ID.fullmatch(execution_id) is None:
        _fail("COG range evidence execution identity is invalid")
    producer = _producer_identity(
        source_revision=source_revision,
        tested_revision=tested_revision,
        workflow_run_id=workflow_run_id,
        workflow_run_attempt=workflow_run_attempt,
        workflow_job=workflow_job,
    )
    resolved_output = ensure_outside_candidate(
        bundle_root,
        output_path,
        label="COG range evidence",
        require_new=True,
    )
    identities = load_reviewed_cog_identities(repository_root)
    served_candidate = load_served_cog_candidate_identity(bundle_root, identities)
    with _serve_candidate_ranges(bundle_root, identities) as transport:
        positive = validate_reviewed_cog_range_access(
            bundle_root,
            repository_root=repository_root,
            transport=transport,
        )
        rejection_controls = _run_rejection_controls(
            bundle_root,
            repository_root=repository_root,
            transport=transport,
        )
    report = {
        **positive,
        "executionId": execution_id,
        "producer": producer,
        "servedCandidate": served_candidate,
        "transport": {
            "protocol": "HTTP/1.1",
            "scope": "loopback",
            "networkExposure": "process-local",
        },
        "rejectionControls": rejection_controls,
        "evidenceDisposition": _DISPOSITION,
        "limitations": _LIMITATIONS,
    }
    _validate_evidence_document(
        report,
        bundle_root=bundle_root,
        repository_root=repository_root,
        expected_producer=producer,
    )
    write_new_json_record(resolved_output, report)
    return report


def validate_reviewed_cog_range_evidence(
    evidence_path: Path,
    *,
    bundle_root: Path,
    repository_root: Path,
    expected_producer: Mapping[str, Any],
) -> Mapping[str, Any]:
    """Recompute every immutable binding in a persisted Range report."""
    _validate_producer(expected_producer)
    if evidence_path.is_symlink() or not evidence_path.is_file():
        _fail("COG range evidence is absent or unsafe")
    document, _ = load_json_snapshot(evidence_path)
    _validate_evidence_document(
        document,
        bundle_root=bundle_root,
        repository_root=repository_root,
        expected_producer=expected_producer,
    )
    return document


def _run_rejection_controls(
    bundle_root: Path,
    *,
    repository_root: Path,
    transport: RangeTransport,
) -> list[dict[str, Any]]:
    controls: list[dict[str, Any]] = []
    for case, failure_marker in _REJECTION_CASES.items():
        mutated = _MutatingTransport(transport, case)
        try:
            validate_reviewed_cog_range_access(
                bundle_root,
                repository_root=repository_root,
                transport=mutated,
            )
        except ScienceContractError as exc:
            if mutated.request_count != 1 or failure_marker not in str(exc):
                _fail(f"COG {case} rejection control failed closed incorrectly")
            controls.append(
                {
                    "case": case,
                    "outcome": "rejected",
                    "requestCountBeforeRejection": mutated.request_count,
                }
            )
        else:
            _fail(f"COG {case} rejection control was accepted")
    return controls


def _validate_evidence_document(
    document: Mapping[str, Any],
    *,
    bundle_root: Path,
    repository_root: Path,
    expected_producer: Mapping[str, Any],
) -> None:
    expected_keys = {
        "schemaVersion",
        "evidenceType",
        "executionId",
        "producer",
        "servedCandidate",
        "reviewedProjectionCandidate",
        "artifactCount",
        "rangeRequestCount",
        "artifacts",
        "transport",
        "rejectionControls",
        "evidenceDisposition",
        "limitations",
    }
    if type(document) is not dict or set(document) != expected_keys:
        _fail("COG range evidence fields differ from the exact contract")
    execution_id = document["executionId"]
    if type(execution_id) is not str or _EXECUTION_ID.fullmatch(execution_id) is None:
        _fail("COG range evidence execution identity is invalid")
    _validate_producer(document["producer"])
    if document["producer"] != expected_producer:
        _fail("COG range evidence producer identity changed")
    identities = load_reviewed_cog_identities(repository_root)
    if document["servedCandidate"] != load_served_cog_candidate_identity(bundle_root, identities):
        _fail("COG range evidence served candidate binding changed")
    reviewed = load_reviewed_projection_evidence(repository_root).binding
    expected_reviewed = {
        "releaseId": reviewed["releaseId"],
        "releaseContractId": reviewed["releaseContractId"],
        "manifestSha256": reviewed["manifestSha256"],
        "candidateBindingSha256": binding_sha256(reviewed),
        "sourceRevision": reviewed["sourceRevision"],
    }
    if document["reviewedProjectionCandidate"] != expected_reviewed:
        _fail("COG range evidence reviewed candidate binding changed")
    if (
        document["schemaVersion"] != 1
        or document["evidenceType"] != "reviewed-cog-range-access"
        or document["artifactCount"] != 9
        or document["rangeRequestCount"] != 54
        or document["transport"]
        != {
            "protocol": "HTTP/1.1",
            "scope": "loopback",
            "networkExposure": "process-local",
        }
        or document["evidenceDisposition"] != _DISPOSITION
        or document["limitations"] != _LIMITATIONS
    ):
        _fail("COG range evidence scope or disposition changed")
    _validate_artifact_reports(
        document["artifacts"],
        identities=identities,
        bundle_root=bundle_root,
    )
    _validate_rejection_controls(document["rejectionControls"])


def _validate_producer(value: Any) -> None:
    if type(value) is not dict or set(value) != {
        "sourceRevision",
        "testedRevision",
        "workflowRunId",
        "workflowRunAttempt",
        "workflowJob",
        "clock",
    }:
        _fail("COG range evidence producer fields differ from the exact contract")
    source_revision = value["sourceRevision"]
    tested_revision = value["testedRevision"]
    run_id = value["workflowRunId"]
    run_attempt = value["workflowRunAttempt"]
    workflow_job = value["workflowJob"]
    if (
        type(source_revision) is not str
        or _REVISION.fullmatch(source_revision) is None
        or type(tested_revision) is not str
        or _REVISION.fullmatch(tested_revision) is None
        or type(run_id) is not int
        or run_id <= 0
        or type(run_attempt) is not int
        or run_attempt <= 0
        or type(workflow_job) is not str
        or _WORKFLOW_JOB.fullmatch(workflow_job) is None
        or value["clock"] != _CLOCK
    ):
        _fail("COG range evidence producer identity is invalid")


def _producer_identity(
    *,
    source_revision: str,
    tested_revision: str,
    workflow_run_id: int,
    workflow_run_attempt: int,
    workflow_job: str,
) -> dict[str, Any]:
    producer = {
        "sourceRevision": source_revision,
        "testedRevision": tested_revision,
        "workflowRunId": workflow_run_id,
        "workflowRunAttempt": workflow_run_attempt,
        "workflowJob": workflow_job,
        "clock": _CLOCK,
    }
    _validate_producer(producer)
    return producer


def _validate_artifact_reports(
    value: Any,
    *,
    identities: tuple[CogArtifactIdentity, ...],
    bundle_root: Path,
) -> None:
    if not isinstance(value, list) or len(value) != 9:
        _fail("COG range evidence artifact inventory is incomplete")
    for report, identity in zip(value, identities):
        expected_coordinates = _expected_coordinates(identity)
        if type(report) is not dict or set(report) != {
            "path",
            "sha256",
            "byteSize",
            "canonicalProbes",
            "readerRangeRequests",
            "rangeRequests",
            "requestCoordinates",
            "requests",
        }:
            _fail("COG range evidence artifact fields differ from the exact contract")
        if (
            report["path"] != identity.path
            or report["sha256"] != identity.sha256
            or report["byteSize"] != identity.byte_size
            or report["canonicalProbes"] != ["beginning", "middle", "end"]
            or report["readerRangeRequests"] != 3
            or report["rangeRequests"] != 6
            or report["requestCoordinates"] != [list(item) for item in expected_coordinates]
            or not isinstance(report["requests"], list)
            or len(report["requests"]) != 6
        ):
            _fail(f"COG range evidence request map changed: {identity.path}")
        trusted = safe_candidate_path(bundle_root, identity.path).read_bytes()
        for request, coordinate in zip(report["requests"], expected_coordinates):
            label, start, requested_end, actual_end = coordinate
            body = trusted[start : actual_end + 1]
            latency = request.get("latencyNanoseconds") if isinstance(request, dict) else None
            expected_request = {
                "label": label,
                "requestedRange": f"bytes={start}-{requested_end}",
                "status": 206,
                "contentRange": f"bytes {start}-{actual_end}/{identity.byte_size}",
                "contentLength": str(len(body)),
                "acceptRanges": "bytes",
                "responseBytes": len(body),
                "responseSha256": hashlib.sha256(body).hexdigest(),
                "latencyNanoseconds": latency,
            }
            if (
                type(request) is not dict
                or set(request) != set(expected_request)
                or type(latency) is not int
                or latency < 0
                or request != expected_request
            ):
                _fail(f"COG range response evidence changed: {identity.path}/{label}")


def _validate_rejection_controls(value: Any) -> None:
    expected = [
        {"case": case, "outcome": "rejected", "requestCountBeforeRejection": 1}
        for case in _REJECTION_CASES
    ]
    if value != expected:
        _fail("COG range rejection evidence changed")


def _expected_coordinates(
    identity: CogArtifactIdentity,
) -> tuple[tuple[str, int, int, int], ...]:
    middle = identity.byte_size // 2 - 32
    return (
        ("beginning", 0, 63, 63),
        ("middle", middle, middle + 63, middle + 63),
        ("end", identity.byte_size - 64, identity.byte_size - 1, identity.byte_size - 1),
        ("reader-browser", 0, 65535, identity.byte_size - 1),
        ("reader-ifd-count", 192, 193, 193),
        ("reader-ifd-payload", 194, 449, 449),
    )


class _CandidateRangeServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(
        self,
        bundle_root: Path,
        identities: tuple[CogArtifactIdentity, ...],
    ) -> None:
        self.bundle_root = bundle_root
        self.allowed_paths = {identity.path for identity in identities}
        super().__init__(("127.0.0.1", 0), _CandidateRangeHandler)


class _CandidateRangeHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:  # noqa: N802
        server = self.server
        assert isinstance(server, _CandidateRangeServer)
        relative = urllib.parse.unquote(urllib.parse.urlsplit(self.path).path).lstrip("/")
        match = _RANGE_HEADER.fullmatch(self.headers.get("Range", ""))
        if relative not in server.allowed_paths or match is None:
            self.send_error(404)
            return
        path = safe_candidate_path(server.bundle_root, relative)
        data = path.read_bytes()
        start, requested_end = (int(value) for value in match.groups())
        if start >= len(data) or requested_end < start:
            self.send_error(416)
            return
        actual_end = min(requested_end, len(data) - 1)
        body = data[start : actual_end + 1]
        self.send_response(206)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Range", f"bytes {start}-{actual_end}/{len(data)}")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        return


@contextlib.contextmanager
def _serve_candidate_ranges(
    bundle_root: Path,
    identities: tuple[CogArtifactIdentity, ...],
) -> Iterator[_LoopbackHttpRangeTransport]:
    server = _CandidateRangeServer(bundle_root, identities)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield _LoopbackHttpRangeTransport(server.server_port)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=10)
        if thread.is_alive():
            _fail("COG evidence loopback server did not stop")


@click.command()
@click.option(
    "--bundle-root",
    type=click.Path(path_type=Path, file_okay=False, exists=True),
    required=True,
)
@click.option(
    "--repository-root",
    type=click.Path(path_type=Path, file_okay=False, exists=True),
    required=True,
)
@click.option(
    "--output",
    "output_path",
    type=click.Path(path_type=Path, dir_okay=False),
    required=True,
)
@click.option("--execution-id", required=True)
@click.option("--source-revision", required=True)
@click.option("--tested-revision", required=True)
@click.option("--workflow-run-id", type=click.IntRange(min=1), required=True)
@click.option("--workflow-run-attempt", type=click.IntRange(min=1), required=True)
@click.option("--workflow-job", required=True)
def cli(
    bundle_root: Path,
    repository_root: Path,
    output_path: Path,
    execution_id: str,
    source_revision: str,
    tested_revision: str,
    workflow_run_id: int,
    workflow_run_attempt: int,
    workflow_job: str,
) -> None:
    """Capture immutable loopback HTTP evidence without a publication claim."""
    try:
        report = capture_loopback_cog_range_evidence(
            bundle_root,
            repository_root=repository_root,
            output_path=output_path,
            execution_id=execution_id,
            source_revision=source_revision,
            tested_revision=tested_revision,
            workflow_run_id=workflow_run_id,
            workflow_run_attempt=workflow_run_attempt,
            workflow_job=workflow_job,
        )
    except ScienceContractError as exc:
        raise click.ClickException(str(exc)) from None
    click.echo(
        f"wrote {report['rangeRequestCount']} candidate-bound COG Range measurements "
        f"to {output_path}"
    )


def _fail(message: str) -> NoReturn:
    raise ScienceContractError(message)


if __name__ == "__main__":
    cli()
