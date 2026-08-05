"""Local-HTTP integration tests for checksum-first acquisition."""

from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from searise_pipeline.sources.acquire import Acquirer, AcquisitionError
from searise_pipeline.sources.registry import Asset, Licence, Source

LOCKED_BYTES = b"locked-source-bytes\n"
HTML_BYTES = b"<!doctype html><html><form>login</form></html>"


class FixtureHandler(BaseHTTPRequestHandler):
    counts: dict[str, int] = {}

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler contract
        route = urlsplit(self.path).path
        self.counts[route] = self.counts.get(route, 0) + 1
        if route == "/redirect":
            self.send_response(302)
            self.send_header("Location", "/file")
            self.end_headers()
            return
        if route == "/retry":
            self.send_error(503)
            return
        if route == "/forbidden":
            self.send_error(403)
            return
        if route == "/missing":
            self.send_error(404)
            return

        body = {
            "/file": LOCKED_BYTES,
            "/truncated": LOCKED_BYTES[:-3],
            "/html": HTML_BYTES,
        }.get(route, b"wrong-source-bytes\n")
        media_type = "text/plain" if route == "/wrong-media" else "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", media_type)
        if route != "/truncated":
            self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        return


@pytest.fixture
def source_server():
    FixtureHandler.counts = {}
    server = ThreadingHTTPServer(("127.0.0.1", 0), FixtureHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    try:
        yield f"http://{host}:{port}", FixtureHandler.counts
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def _source(status: str = "approved") -> Source:
    return Source(
        id="fixture-source",
        selection_status="selected",
        publisher="Local fixture",
        canonical_record="https://example.test/source",
        version="v1",
        snapshot_date="2026-08-04",
        licence=Licence(
            name="Fixture licence",
            url="https://example.test/licence",
            spdx="CC0-1.0",
            attribution="Fixture",
            redistribution_status=status,
            reviewer="tests" if status == "approved" else None,
            reviewed_at="2026-08-04" if status == "approved" else None,
            required_acknowledgements=(),
        ),
        assets=(),
        coverage=(),
    )


def _asset(base_url: str, route: str = "/file", *, resolved_route: str | None = None) -> Asset:
    return Asset(
        id=urlsplit(route).path.strip("/") or "file",
        kind="file",
        url=f"{base_url}{route}",
        resolved_url=f"{base_url}{resolved_route or route}",
        resolved_version="v1",
        media_type="application/octet-stream",
        cache_path="fixture.bin",
        availability="locked",
        byte_size=len(LOCKED_BYTES),
        sha256=hashlib.sha256(LOCKED_BYTES).hexdigest(),
        roles=(),
        members=(),
        object_set=None,
    )


def _acquirer(tmp_path: Path, **kwargs) -> Acquirer:
    return Acquirer(
        tmp_path / "cache",
        tmp_path / "receipts",
        backoff_seconds=0,
        **kwargs,
    )


def _rejection(action, reason: str) -> AcquisitionError:
    with pytest.raises(AcquisitionError, match=reason) as caught:
        action()
    assert caught.value.receipt.status == "rejected"
    return caught.value


def test_fetch_atomically_promotes_verified_bytes_and_cache_hit_transfers_nothing(
    tmp_path: Path, source_server
):
    base_url, counts = source_server
    source = _source()
    asset = _asset(base_url)
    acquirer = _acquirer(tmp_path)

    path, first = acquirer.fetch(source, asset)
    cached, second = acquirer.fetch(source, asset)

    assert path == cached
    assert path is not None and path.read_bytes() == LOCKED_BYTES
    assert first.status == "acquired"
    assert second.status == "verified"
    assert second.cache_decision == "hit"
    assert counts["/file"] == 1
    assert not list(path.parent.glob("*.part"))


def test_offline_verify_never_uses_network(tmp_path: Path, source_server):
    base_url, counts = source_server
    source = _source()
    asset = _asset(base_url)
    acquirer = _acquirer(tmp_path)
    target = acquirer.cache_path(source, asset)
    target.parent.mkdir(parents=True)
    target.write_bytes(LOCKED_BYTES)

    _, receipt = acquirer.verify(source, asset)

    assert receipt.status == "verified"
    assert counts == {}


def test_corrupt_cache_fails_closed_without_network(tmp_path: Path, source_server):
    base_url, counts = source_server
    source = _source()
    asset = _asset(base_url)
    acquirer = _acquirer(tmp_path)
    target = acquirer.cache_path(source, asset)
    target.parent.mkdir(parents=True)
    target.write_bytes(b"corrupt")

    _rejection(lambda: acquirer.fetch(source, asset), "cache-mismatch")

    assert counts == {}


@pytest.mark.parametrize(
    ("route", "reason"),
    [
        ("/truncated", "size-mismatch"),
        ("/html", "html-or-login-response"),
        ("/wrong-media", "media-type-mismatch"),
        ("/forbidden", "authentication-or-permission-error"),
    ],
)
def test_negative_http_paths_are_rejected(
    tmp_path: Path, source_server, route: str, reason: str
):
    base_url, _ = source_server
    asset = _asset(base_url, route)
    if route == "/html":
        asset = replace(
            asset,
            byte_size=len(HTML_BYTES),
            sha256=hashlib.sha256(HTML_BYTES).hexdigest(),
        )

    error = _rejection(lambda: _acquirer(tmp_path).fetch(_source(), asset), reason)

    assert error.receipt.requested_url == f"{base_url}{route}"


def test_checksum_mismatch_is_rejected(tmp_path: Path, source_server):
    base_url, _ = source_server
    asset = replace(_asset(base_url), sha256="0" * 64)

    _rejection(lambda: _acquirer(tmp_path).fetch(_source(), asset), "checksum-mismatch")


def test_redirect_must_resolve_to_the_locked_url(tmp_path: Path, source_server):
    base_url, counts = source_server
    asset = _asset(base_url, "/redirect", resolved_route="/file")

    _, receipt = _acquirer(tmp_path).fetch(_source(), asset)

    assert receipt.status == "acquired"
    assert receipt.resolved_url == f"{base_url}/file"
    assert counts == {"/redirect": 1, "/file": 1}


def test_unexpected_redirect_target_is_rejected(tmp_path: Path, source_server):
    base_url, _ = source_server
    asset = _asset(base_url, "/redirect")

    _rejection(lambda: _acquirer(tmp_path).fetch(_source(), asset), "resolved-url-mismatch")


def test_retry_exhaustion_is_bounded(tmp_path: Path, source_server):
    base_url, counts = source_server
    asset = _asset(base_url, "/retry")

    error = _rejection(
        lambda: _acquirer(tmp_path, attempts=3).fetch(_source(), asset),
        "retry-exhausted",
    )

    assert error.receipt.attempts == 3
    assert counts["/retry"] == 3


def test_uncertain_rights_block_before_cache_or_network(tmp_path: Path, source_server):
    base_url, counts = source_server

    _rejection(
        lambda: _acquirer(tmp_path).fetch(_source("review-required"), _asset(base_url)),
        "permission-blocked",
    )

    assert counts == {}


def test_expected_absent_asset_has_distinct_receipt(tmp_path: Path, source_server):
    base_url, _ = source_server
    asset = replace(
        _asset(base_url, "/missing"),
        availability="expected-absent",
        byte_size=None,
        sha256=None,
    )

    path, receipt = _acquirer(tmp_path).fetch(_source(), asset)

    assert path is None
    assert receipt.status == "expected-absent"
    assert receipt.cache_decision == "absent"


def test_receipts_strip_credentials_and_query_values(tmp_path: Path, source_server):
    base_url, _ = source_server
    secret = "do-not-record-this-token"
    asset = _asset(f"{base_url}", f"/file?token={secret}")

    _, receipt = _acquirer(tmp_path).fetch(_source(), asset)
    receipt_files = list((tmp_path / "receipts").glob("*.json"))
    serialized = receipt.to_json() + receipt_files[0].read_text(encoding="utf-8")

    assert secret not in serialized
    assert "token=" not in serialized
    assert json.loads(receipt_files[0].read_text(encoding="utf-8"))["status"] == "acquired"
