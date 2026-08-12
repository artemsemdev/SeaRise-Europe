"""Public readback must equal subjects freshly verified through Cosign."""

from __future__ import annotations

import hashlib
import http.client
import inspect
import json
import socket
import ssl
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

import searise_pipeline.supply_chain.public_readback as readback
from searise_pipeline.supply_chain import SupplyChainContractError
from tests.supply_chain.test_candidate_evidence_pair import ROOT, _load, _pair
from tests.supply_chain.test_sigstore_verifier import RUN_ID, _production_envelope, _tool


def _verify(
    tmp_path: Path,
    *,
    fetch: Any | None = None,
    receipt: bool = False,
) -> tuple[readback.PublicReadbackVerification, Path, Path]:
    candidate, evidence = _pair(tmp_path / "pair", data_provenance_class="real-source")
    _production_envelope(evidence)
    tool, lock = _tool(tmp_path)
    roots = {
        "manifest.json": candidate,
        "provenance.intoto.jsonl": evidence,
    }

    def exact(url: str, size: int) -> bytes:
        logical = url.rsplit("/", 1)[1]
        raw = (roots[logical] / logical).read_bytes()
        assert len(raw) == size
        return raw

    result = readback._verify_public_signed_subjects(
        candidate,
        evidence,
        repository_root=ROOT,
        controlled_build_run_id=RUN_ID,
        cosign_executable=tool,
        cosign_tool_lock=lock,
        trusted_cosign_tool_lock_sha256=hashlib.sha256(lock.read_bytes()).hexdigest(),
        expected_origin="https://downloads.example.test",
        manifest_url="https://downloads.example.test/release/manifest.json",
        provenance_url="https://downloads.example.test/release/provenance.intoto.jsonl",
        receipt_path=(tmp_path / "public-readback.json") if receipt else None,
        fetch=fetch or exact,
        clock=lambda: datetime(2026, 8, 12, 2, 0, tzinfo=timezone.utc),
        reviewed_origins={"https://downloads.example.test"},
    )
    return result, candidate, evidence


def test_reverifies_signatures_and_emits_schema_valid_public_receipt(tmp_path: Path) -> None:
    result, candidate, evidence = _verify(tmp_path, receipt=True)
    document = result.receipt
    schema = _load(
        ROOT / "contracts/supply-chain/v1/public-readback-verification-receipt.schema.json"
    )
    Draft202012Validator(schema).validate(document)
    assert (
        result.receipt_bytes
        == (
            json.dumps(document, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n"
        ).encode()
    )
    assert (tmp_path / "public-readback.json").read_bytes() == result.receipt_bytes
    assert document["observedAt"] == "2026-08-12T02:00:00Z"
    assert [item["path"] for item in document["subjects"]] == [
        "manifest.json",
        "provenance.intoto.jsonl",
    ]
    assert (
        document["subjects"][0]["sha256"]
        == hashlib.sha256((candidate / "manifest.json").read_bytes()).hexdigest()
    )
    assert (
        document["subjects"][1]["sha256"]
        == hashlib.sha256((evidence / "provenance.intoto.jsonl").read_bytes()).hexdigest()
    )
    assert document["claims"] == {
        "cryptographicSubjectsReverified": True,
        "publicBytesMatched": True,
        "productionClaim": False,
        "publicationApproval": False,
        "scientificApproval": False,
    }


@pytest.mark.parametrize("logical", ["manifest.json", "provenance.intoto.jsonl"])
def test_public_byte_tamper_fails_without_receipt(tmp_path: Path, logical: str) -> None:
    def tampered(url: str, size: int) -> bytes:
        fetched = url.rsplit("/", 1)[1]
        root = tmp_path / "pair" / ("candidate" if fetched == "manifest.json" else "evidence")
        raw = bytearray((root / fetched).read_bytes())
        assert len(raw) == size
        if fetched == logical:
            raw[0] ^= 1
        return bytes(raw)

    with pytest.raises(SupplyChainContractError, match="public bytes differ"):
        _verify(tmp_path, fetch=tampered, receipt=True)
    assert not (tmp_path / "public-readback.json").exists()


@pytest.mark.parametrize(
    ("origin", "url"),
    [
        ("http://downloads.example.test", "https://downloads.example.test/release/manifest.json"),
        (
            "https://user@downloads.example.test",
            "https://downloads.example.test/release/manifest.json",
        ),
        (
            "https://downloads.example.test/base",
            "https://downloads.example.test/release/manifest.json",
        ),
        ("https://downloads.example.test", "https://other.example.test/release/manifest.json"),
        (
            "https://downloads.example.test",
            "https://downloads.example.test/release/../manifest.json",
        ),
        (
            "https://downloads.example.test",
            "https://downloads.example.test/release/manifest.json?q=1",
        ),
        (
            "https://downloads.example.test",
            "https://downloads.example.test/release/%6danifest.json",
        ),
        ("https://downloads.example.test", "https://downloads.example.test/release/%zz.json"),
        ("https://downloads.example.test", "https://downloads.example.test/release\\manifest.json"),
        ("https://127.0.0.1", "https://127.0.0.1/release/manifest.json"),
        ("https://localhost", "https://localhost/release/manifest.json"),
        ("https://DOWNLOADS.example.test", "https://downloads.example.test/release/manifest.json"),
        ("https://downloads.example.test/", "https://downloads.example.test/release/manifest.json"),
        ("https://downloads.example.test", "https://downloads.example.test/rélease/manifest.json"),
    ],
)
def test_public_url_boundary_rejects_unsafe_or_different_origins(origin: str, url: str) -> None:
    with pytest.raises(SupplyChainContractError, match="origin|URL|host"):
        normalized = readback._origin(origin, reviewed_origins={origin})
        readback._subject_url(url, normalized)


def test_exported_api_has_no_fetch_or_clock_override() -> None:
    parameters = inspect.signature(readback.verify_public_signed_subjects).parameters
    assert "fetch" not in parameters
    assert "observed_at" not in parameters
    assert "clock" not in parameters


def test_unreviewed_public_origin_is_rejected() -> None:
    with pytest.raises(SupplyChainContractError, match="reviewed allowlist"):
        readback._origin("https://downloads.example.test")


def test_dns_resolution_rejects_any_nonpublic_address(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        readback.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443)),
        ],
    )
    with pytest.raises(SupplyChainContractError, match="outside the public Internet"):
        readback._resolve_public_addresses("artemsemdev.github.io")


def test_incomplete_http_body_is_mapped_to_contract_error(monkeypatch: pytest.MonkeyPatch) -> None:
    class Headers:
        @staticmethod
        def getheader(_name: str) -> None:
            return None

    class Response(Headers):
        status = 200

    class Connection:
        sock = object()

        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            pass

        @staticmethod
        def request(*_args: Any, **_kwargs: Any) -> None:
            pass

        @staticmethod
        def _reset_remaining_timeout(**_kwargs: Any) -> None:
            pass

        @staticmethod
        def getresponse() -> Response:
            return Response()

        @staticmethod
        def close() -> None:
            pass

        @staticmethod
        def abort() -> None:
            pass

    monkeypatch.setattr(readback, "_resolve_public_addresses", lambda _host, **_kwargs: ())
    monkeypatch.setattr(readback, "_PinnedHTTPSConnection", Connection)
    monkeypatch.setattr(
        readback,
        "_read_response_chunk",
        lambda *_args: (_ for _ in ()).throw(http.client.IncompleteRead(b"")),
    )
    with pytest.raises(SupplyChainContractError, match="readback failed"):
        readback._fetch("https://artemsemdev.github.io/manifest.json", 1)


def test_total_deadline_shutdown_interrupts_real_makefile_header_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instances: list[Connection] = []

    class Connection(readback._PinnedHTTPSConnection):
        def __init__(self, host: str, addresses: Any, *, deadline: float) -> None:
            super().__init__(host, addresses, deadline=deadline)
            active, self.peer = socket.socketpair()
            assert self._publish_socket(active)
            self.header_read_started = threading.Event()
            instances.append(self)

        @staticmethod
        def request(*_args: Any, **_kwargs: Any) -> None:
            pass

        def _reset_remaining_timeout(self, **_kwargs: Any) -> None:
            # Exercise the timer's abort path rather than a per-read socket timeout.
            pass

        def getresponse(self) -> None:
            active = self.sock
            assert active is not None
            with active.makefile("rb") as stream:
                self.header_read_started.set()
                stream.readline()
            raise OSError("connection aborted at total deadline")

        def close(self) -> None:
            super().close()
            self.peer.close()

    monkeypatch.setattr(readback, "_READBACK_DEADLINE_SECONDS", 0.02)
    monkeypatch.setattr(readback, "_resolve_public_addresses", lambda _host, **_kwargs: ())
    monkeypatch.setattr(readback, "_PinnedHTTPSConnection", Connection)
    started = time.monotonic()
    with pytest.raises(SupplyChainContractError, match="readback failed"):
        readback._fetch("https://artemsemdev.github.io/manifest.json", 1)
    assert time.monotonic() - started < 0.5
    assert instances and instances[0].header_read_started.is_set()


def test_pinned_connection_enforces_tls_identity_and_falls_back_addresses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts: list[tuple[object, ...]] = []
    raw_sockets: list[Any] = []
    wrap_calls: list[tuple[str, bool]] = []

    class RawSocket:
        def __init__(self, family: int) -> None:
            self.family = family
            self.closed = False
            raw_sockets.append(self)

        def settimeout(self, value: float) -> None:
            assert 0 < value <= 1

        def connect(self, address: tuple[object, ...]) -> None:
            attempts.append(address)
            if address[0] == "93.184.216.34":
                raise OSError("first public address unavailable")

        def close(self) -> None:
            self.closed = True

    class TlsSocket:
        def __init__(self, raw: RawSocket) -> None:
            self.raw = raw
            self.handshakes = 0
            self.closed = False

        def settimeout(self, value: float) -> None:
            assert 0 < value <= 1

        def do_handshake(self) -> None:
            self.handshakes += 1

        @staticmethod
        def getpeername() -> tuple[str, int, int, int]:
            return ("2606:2800:220:1:248:1893:25c8:1946", 443, 0, 0)

        def close(self) -> None:
            self.closed = True

    class Context:
        verify_mode = ssl.CERT_REQUIRED
        check_hostname = True

        @staticmethod
        def wrap_socket(
            raw: RawSocket,
            *,
            server_hostname: str,
            do_handshake_on_connect: bool,
        ) -> TlsSocket:
            wrap_calls.append((server_hostname, do_handshake_on_connect))
            return TlsSocket(raw)

    monkeypatch.setattr(
        readback.socket,
        "socket",
        lambda family, _socket_type: RawSocket(family),
    )
    monkeypatch.setattr(readback.ssl, "create_default_context", lambda: Context())
    addresses = (
        (socket.AF_INET, ("93.184.216.34", 443), "93.184.216.34"),
        (
            socket.AF_INET6,
            ("2606:2800:220:1:248:1893:25c8:1946", 443, 0, 0),
            "2606:2800:220:1:248:1893:25c8:1946",
        ),
    )
    connection = readback._PinnedHTTPSConnection(
        "artemsemdev.github.io",
        addresses,
        deadline=time.monotonic() + 1,
    )

    connection.connect()

    assert attempts == [addresses[0][1], addresses[1][1]]
    assert raw_sockets[0].closed
    assert wrap_calls == [("artemsemdev.github.io", False)]
    assert isinstance(connection.sock, TlsSocket)
    assert connection.sock.handshakes == 1
    connection.close()


@pytest.mark.parametrize(
    ("verify_mode", "check_hostname"),
    [(ssl.CERT_NONE, False), (ssl.CERT_REQUIRED, False)],
)
def test_pinned_connection_rejects_nonverifying_tls_context(
    monkeypatch: pytest.MonkeyPatch,
    verify_mode: ssl.VerifyMode,
    check_hostname: bool,
) -> None:
    class Context:
        pass

    context = Context()
    context.verify_mode = verify_mode
    context.check_hostname = check_hostname
    monkeypatch.setattr(readback.ssl, "create_default_context", lambda: context)
    connection = readback._PinnedHTTPSConnection(
        "artemsemdev.github.io",
        ((socket.AF_INET, ("93.184.216.34", 443), "93.184.216.34"),),
        deadline=time.monotonic() + 1,
    )

    with pytest.raises(SupplyChainContractError, match="hostname verification"):
        connection.connect()


@pytest.mark.parametrize("failure", ["peer-mismatch", "tls-failure"])
def test_pinned_connection_rejects_peer_drift_and_tls_failure(
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    closed: list[str] = []

    class RawSocket:
        @staticmethod
        def settimeout(_value: float) -> None:
            pass

        @staticmethod
        def connect(_address: tuple[object, ...]) -> None:
            pass

        @staticmethod
        def close() -> None:
            closed.append("raw")

    class TlsSocket:
        @staticmethod
        def settimeout(_value: float) -> None:
            pass

        @staticmethod
        def do_handshake() -> None:
            pass

        @staticmethod
        def getpeername() -> tuple[str, int]:
            return ("93.184.216.35", 443)

        @staticmethod
        def close() -> None:
            closed.append("tls")

    class Context:
        verify_mode = ssl.CERT_REQUIRED
        check_hostname = True

        @staticmethod
        def wrap_socket(
            _raw: RawSocket,
            *,
            server_hostname: str,
            do_handshake_on_connect: bool,
        ) -> TlsSocket:
            assert server_hostname == "artemsemdev.github.io"
            assert do_handshake_on_connect is False
            if failure == "tls-failure":
                raise ssl.SSLError("untrusted certificate")
            return TlsSocket()

    monkeypatch.setattr(readback.socket, "socket", lambda *_args: RawSocket())
    monkeypatch.setattr(readback.ssl, "create_default_context", lambda: Context())
    connection = readback._PinnedHTTPSConnection(
        "artemsemdev.github.io",
        ((socket.AF_INET, ("93.184.216.34", 443), "93.184.216.34"),),
        deadline=time.monotonic() + 1,
    )

    with pytest.raises(OSError, match="pinned public address"):
        connection.connect()

    assert connection.sock is None
    assert "tls" in closed if failure == "peer-mismatch" else "raw" in closed


@pytest.mark.parametrize("status", [301, 302, 307, 308])
def test_redirect_response_fails_after_exactly_one_request(
    monkeypatch: pytest.MonkeyPatch,
    status: int,
) -> None:
    instances: list[Connection] = []

    class Response:
        def __init__(self) -> None:
            self.status = status

    class Connection:
        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            self.requests = 0
            instances.append(self)

        def request(self, *_args: Any, **_kwargs: Any) -> None:
            self.requests += 1

        @staticmethod
        def _reset_remaining_timeout(**_kwargs: Any) -> None:
            pass

        @staticmethod
        def getresponse() -> Response:
            return Response()

        @staticmethod
        def abort() -> None:
            pass

        @staticmethod
        def close() -> None:
            pass

    monkeypatch.setattr(readback, "_resolve_public_addresses", lambda _host, **_kwargs: ())
    monkeypatch.setattr(readback, "_PinnedHTTPSConnection", Connection)

    with pytest.raises(SupplyChainContractError, match="response identity differs"):
        readback._fetch("https://artemsemdev.github.io/manifest.json", 1)

    assert len(instances) == 1
    assert instances[0].requests == 1


def test_existing_receipt_is_never_overwritten(tmp_path: Path) -> None:
    path = tmp_path / "public-readback.json"
    path.write_text("preserve\n", encoding="utf-8")
    with pytest.raises(SupplyChainContractError, match="already exists"):
        _verify(tmp_path, receipt=True)
    assert path.read_text(encoding="utf-8") == "preserve\n"


def test_relative_receipt_path_is_rejected_without_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SupplyChainContractError, match="absolute and canonical"):
        readback._write_new(Path("public-readback.json"), b"{}\n")
    assert not (tmp_path / "public-readback.json").exists()


def test_naive_observation_instant_is_rejected(tmp_path: Path) -> None:
    candidate, evidence = _pair(tmp_path / "pair", data_provenance_class="real-source")
    _production_envelope(evidence)
    tool, lock = _tool(tmp_path)
    roots = {"manifest.json": candidate, "provenance.intoto.jsonl": evidence}

    with pytest.raises(SupplyChainContractError, match="timezone"):
        readback._verify_public_signed_subjects(
            candidate,
            evidence,
            repository_root=ROOT,
            controlled_build_run_id=RUN_ID,
            cosign_executable=tool,
            cosign_tool_lock=lock,
            trusted_cosign_tool_lock_sha256=hashlib.sha256(lock.read_bytes()).hexdigest(),
            expected_origin="https://downloads.example.test",
            manifest_url="https://downloads.example.test/release/manifest.json",
            provenance_url="https://downloads.example.test/release/provenance.intoto.jsonl",
            fetch=lambda url, _size: (
                roots[url.rsplit("/", 1)[1]] / url.rsplit("/", 1)[1]
            ).read_bytes(),
            clock=lambda: datetime(2026, 8, 12, 2, 0),
            reviewed_origins={"https://downloads.example.test"},
        )
