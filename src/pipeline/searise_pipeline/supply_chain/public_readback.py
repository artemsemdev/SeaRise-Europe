"""Verify public manifest/provenance bytes against freshly verified Sigstore subjects."""

from __future__ import annotations

import hashlib
import http.client
import ipaddress
import json
import os
import re
import socket
import ssl
import stat
import threading
import time
import urllib.parse
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from queue import Queue
from typing import Any, Callable, Iterable, Mapping, NoReturn, Sequence

from .candidate_evidence import _open_root
from .contracts import SupplyChainContractError, _validate_schema
from .sbom import write_new_immutable_bytes
from .sigstore_verifier import verify_candidate_evidence_cryptographically

_SCHEMA_URI = (
    "https://artemsemdev.github.io/SeaRise-Europe/contracts/supply-chain/v1/"
    "public-readback-verification-receipt.schema.json"
)
_SUBJECT_PATHS = ("manifest.json", "provenance.intoto.jsonl")
_MAX_SUBJECT_BYTES = 8 * 1024 * 1024
_READBACK_DEADLINE_SECONDS = 30.0
_REVIEWED_PUBLIC_ORIGINS = frozenset({"https://artemsemdev.github.io"})
_SHA256 = re.compile(r"[0-9a-f]{64}")


@dataclass(frozen=True)
class PublicReadbackVerification:
    """Canonical audit bytes proving public subjects match verified local bytes."""

    receipt: Mapping[str, Any]
    receipt_bytes: bytes


@dataclass(frozen=True)
class _ReceiptBoundary:
    parent_inode: tuple[int, int]
    protected_root_inodes: frozenset[tuple[int, int]]


def _fail(message: str) -> NoReturn:
    raise SupplyChainContractError(message)


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _canonical(document: Mapping[str, Any]) -> bytes:
    try:
        return (
            json.dumps(document, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n"
        ).encode("utf-8")
    except (RecursionError, UnicodeEncodeError, ValueError) as exc:
        raise SupplyChainContractError(
            f"public readback receipt is not canonical JSON: {exc}"
        ) from exc


def _identity(value: os.stat_result) -> tuple[int, ...]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_nlink,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def _read_subject(root: Path, logical: str) -> bytes:
    descriptor = _open_root(root, "signed subject")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        child = os.open(logical, flags | getattr(os, "O_NONBLOCK", 0), dir_fd=descriptor)
        try:
            before = os.fstat(child)
            linked = os.stat(logical, dir_fd=descriptor, follow_symlinks=False)
            if (
                not stat.S_ISREG(before.st_mode)
                or before.st_nlink != 1
                or before.st_size > _MAX_SUBJECT_BYTES
                or _identity(before) != _identity(linked)
            ):
                _fail(f"verified subject is not one bounded stable regular file: {logical}")
            chunks: list[bytes] = []
            remaining = before.st_size
            while remaining:
                chunk = os.read(child, min(1024 * 1024, remaining))
                if not chunk:
                    _fail(f"verified subject ended early: {logical}")
                chunks.append(chunk)
                remaining -= len(chunk)
            if os.read(child, 1):
                _fail(f"verified subject exceeds its declared size: {logical}")
            after = os.fstat(child)
            linked = os.stat(logical, dir_fd=descriptor, follow_symlinks=False)
            if _identity(before) != _identity(after) or _identity(after) != _identity(linked):
                _fail(f"verified subject changed while read: {logical}")
            return b"".join(chunks)
        finally:
            os.close(child)
    except SupplyChainContractError:
        raise
    except OSError as exc:
        raise SupplyChainContractError(f"could not read verified subject: {logical}") from exc
    finally:
        os.close(descriptor)


def _origin(
    value: str,
    *,
    reviewed_origins: Iterable[str] = _REVIEWED_PUBLIC_ORIGINS,
) -> str:
    try:
        parsed = urllib.parse.urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise SupplyChainContractError("public readback origin is malformed") from exc
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or port not in (None, 443)
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
    ):
        _fail("public readback origin must be one canonical HTTPS origin")
    host = _public_host(parsed.hostname)
    canonical = f"https://{host}"
    if value != canonical:
        _fail("public readback origin must already be canonical")
    if canonical not in frozenset(reviewed_origins):
        _fail("public readback origin is not in the reviewed allowlist")
    return canonical


def _public_host(value: str) -> str:
    try:
        host = value.encode("idna").decode("ascii").lower()
        ipaddress.ip_address(host)
    except UnicodeError as exc:
        raise SupplyChainContractError("public readback host is malformed") from exc
    except ValueError:
        pass
    else:
        _fail("public readback host must be a DNS name, not an IP address")
    labels = host.split(".")
    if (
        len(labels) < 2
        or host == "localhost"
        or host.endswith(".localhost")
        or any(
            not label
            or len(label) > 63
            or re.fullmatch(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?", label) is None
            for label in labels
        )
    ):
        _fail("public readback host must be one canonical public DNS name")
    return host


def _subject_url(value: str, expected_origin: str) -> str:
    try:
        parsed = urllib.parse.urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise SupplyChainContractError("public subject URL is malformed") from exc
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or port not in (None, 443)
        or not parsed.path.startswith("/")
        or "//" in parsed.path
        or parsed.query
        or parsed.fragment
        or not parsed.path.isascii()
        or "%" in parsed.path
        or "\\" in parsed.path
        or any(ord(character) < 0x21 or ord(character) == 0x7F for character in parsed.path)
        or urllib.parse.unquote(parsed.path) != parsed.path
        or any(part in {"", ".", ".."} for part in PurePosixPath(parsed.path).parts[1:])
    ):
        _fail("public subject URL must be one canonical HTTPS URL")
    host = _public_host(parsed.hostname)
    canonical = f"https://{host}{parsed.path}"
    if value != canonical:
        _fail("public subject URL must already be canonical")
    if f"https://{host}" != expected_origin:
        _fail("public subject URL differs from the reviewed origin")
    return canonical


_ResolvedAddress = tuple[int, tuple[object, ...], str]


def _resolve_public_addresses(
    host: str,
    *,
    deadline: float | None = None,
) -> tuple[_ResolvedAddress, ...]:
    results: Queue[object] = Queue(maxsize=1)

    def resolve() -> None:
        try:
            results.put(socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM))
        except BaseException as exc:
            results.put(exc)

    resolver = threading.Thread(target=resolve, name="searise-public-readback-dns", daemon=True)
    resolver.start()
    timeout = None if deadline is None else max(0.0, deadline - time.monotonic())
    resolver.join(timeout)
    if resolver.is_alive():
        _fail("public subject DNS resolution exceeded the readback deadline")
    result = results.get_nowait()
    if isinstance(result, BaseException):
        if isinstance(result, socket.gaierror):
            raise SupplyChainContractError("public subject DNS resolution failed") from result
        raise result
    records = result
    if not isinstance(records, list):
        _fail("public subject DNS returned an invalid result")
    resolved: list[_ResolvedAddress] = []
    seen: set[tuple[int, str]] = set()
    for family, socket_type, protocol, _canonical, sockaddr in records:
        if family not in (socket.AF_INET, socket.AF_INET6) or socket_type != socket.SOCK_STREAM:
            continue
        address = str(sockaddr[0])
        try:
            parsed = ipaddress.ip_address(address)
        except ValueError as exc:
            raise SupplyChainContractError(
                "public subject DNS returned a malformed address"
            ) from exc
        if not parsed.is_global:
            _fail("public subject DNS resolved outside the public Internet")
        key = family, parsed.compressed
        if key not in seen:
            seen.add(key)
            resolved.append((family, tuple(sockaddr), parsed.compressed))
    if not resolved:
        _fail("public subject DNS returned no public address")
    return tuple(resolved)


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(
        self,
        host: str,
        addresses: Sequence[_ResolvedAddress],
        *,
        deadline: float,
    ) -> None:
        super().__init__(host, 443, timeout=_READBACK_DEADLINE_SECONDS)
        self._addresses = addresses
        self._deadline = deadline
        self._socket_lock = threading.Lock()
        self._aborted = threading.Event()

    def _remaining(self) -> float:
        if self._aborted.is_set():
            raise TimeoutError("public subject readback was aborted")
        remaining = self._deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("public subject readback deadline expired")
        return remaining

    def _publish_socket(self, active: socket.socket) -> bool:
        with self._socket_lock:
            if self._aborted.is_set():
                return False
            self.sock = active
            return True

    def _release_socket(self, active: socket.socket) -> None:
        with self._socket_lock:
            if self.sock is active:
                self.sock = None

    def _reset_remaining_timeout(self, *, require_socket: bool = False) -> None:
        remaining = self._remaining()
        self.timeout = remaining
        with self._socket_lock:
            active = self.sock
        if require_socket and active is None:
            raise OSError("public subject connection closed unexpectedly")
        if active is not None:
            active.settimeout(remaining)

    def abort(self) -> None:
        """Interrupt in-flight socket and make later connection work fail closed."""
        self._aborted.set()
        with self._socket_lock:
            active = self.sock
            self.sock = None
        if active is None:
            return
        try:
            active.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            active.close()
        except OSError:
            pass

    def connect(self) -> None:
        last_error: OSError | None = None
        context = ssl.create_default_context()
        if context.verify_mode != ssl.CERT_REQUIRED or not context.check_hostname:
            _fail("public subject TLS context does not enforce hostname verification")
        for family, sockaddr, expected_peer in self._addresses:
            raw: socket.socket | None = None
            wrapped: ssl.SSLSocket | None = None
            succeeded = False
            try:
                raw = socket.socket(family, socket.SOCK_STREAM)
                if not self._publish_socket(raw):
                    raise TimeoutError("public subject readback was aborted")
                raw.settimeout(self._remaining())
                raw.connect(sockaddr)
                self._release_socket(raw)
                wrapped = context.wrap_socket(
                    raw,
                    server_hostname=self.host,
                    do_handshake_on_connect=False,
                )
                raw = None
                if not self._publish_socket(wrapped):
                    raise TimeoutError("public subject readback was aborted")
                wrapped.settimeout(self._remaining())
                wrapped.do_handshake()
                wrapped.settimeout(self._remaining())
                peer = ipaddress.ip_address(str(wrapped.getpeername()[0])).compressed
                if peer != expected_peer:
                    raise OSError("public subject peer differs from its pinned DNS address")
                succeeded = True
                return
            except OSError as exc:
                last_error = exc
            finally:
                active = wrapped if wrapped is not None else raw
                if active is not None and not succeeded:
                    self._release_socket(active)
                    try:
                        active.close()
                    except OSError:
                        pass
        raise OSError("could not connect to a pinned public address") from last_error


def _read_response_chunk(
    response: http.client.HTTPResponse,
    connection: _PinnedHTTPSConnection,
    size: int,
) -> bytes:
    connection._reset_remaining_timeout(require_socket=True)
    return response.read1(size)


def _fetch(url: str, expected_size: int) -> bytes:
    parsed = urllib.parse.urlsplit(url)
    host = parsed.hostname
    if host is None:
        _fail("public subject URL has no host")
    deadline = time.monotonic() + _READBACK_DEADLINE_SECONDS
    connection = _PinnedHTTPSConnection(
        host,
        _resolve_public_addresses(host, deadline=deadline),
        deadline=deadline,
    )
    timeout = max(0.0, deadline - time.monotonic())
    deadline_timer = threading.Timer(timeout, connection.abort)
    deadline_timer.daemon = True
    deadline_timer.start()
    path = parsed.path
    try:
        connection._reset_remaining_timeout()
        connection.request(
            "GET",
            path,
            headers={
                "Accept": "application/octet-stream",
                "Accept-Encoding": "identity",
                "Host": host,
                "User-Agent": "SeaRise-Europe-public-readback-v1",
            },
        )
        connection._reset_remaining_timeout(require_socket=True)
        response = connection.getresponse()
        if response.status != 200:
            _fail("public subject response identity differs")
        encoding = response.getheader("Content-Encoding")
        if encoding not in (None, "identity"):
            _fail("public subject response uses content encoding")
        declared = response.getheader("Content-Length")
        if declared is not None and (not declared.isdigit() or int(declared) != expected_size):
            _fail("public subject Content-Length differs")
        chunks: list[bytes] = []
        remaining = expected_size
        while remaining:
            chunk = _read_response_chunk(response, connection, min(65536, remaining))
            if not chunk:
                _fail("public subject response ended early")
            chunks.append(chunk)
            remaining -= len(chunk)
        if _read_response_chunk(response, connection, 1):
            _fail("public subject response exceeds the signed byte size")
        return b"".join(chunks)
    except SupplyChainContractError:
        raise
    except (OSError, http.client.HTTPException) as exc:
        raise SupplyChainContractError("public subject readback failed") from exc
    finally:
        deadline_timer.cancel()
        connection.close()


def _inode(value: os.stat_result) -> tuple[int, int]:
    return value.st_dev, value.st_ino


def _has_ancestor(directory: int, protected: frozenset[tuple[int, int]]) -> bool:
    cursor = os.dup(directory)
    flags = os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        while True:
            current = _inode(os.fstat(cursor))
            if current in protected:
                return True
            parent = os.open("..", flags, dir_fd=cursor)
            parent_inode = _inode(os.fstat(parent))
            if parent_inode == current:
                os.close(parent)
                return False
            os.close(cursor)
            cursor = parent
    finally:
        try:
            os.close(cursor)
        except OSError:
            pass


def _receipt_boundary(path: Path, protected_roots: Sequence[Path]) -> _ReceiptBoundary:
    if not path.is_absolute() or ".." in path.parts or not path.name:
        _fail("public readback receipt path must be absolute and canonical")
    parent = _open_root(path.parent, "public readback receipt parent")
    roots: list[int] = []
    try:
        for root in protected_roots:
            roots.append(_open_root(root, "protected readback input"))
        protected = frozenset(_inode(os.fstat(root)) for root in roots)
        try:
            if _has_ancestor(parent, protected):
                _fail("public readback receipt parent overlaps a protected input root")
        except OSError as exc:
            raise SupplyChainContractError(
                "public readback receipt ancestry could not be inspected"
            ) from exc
        try:
            os.stat(path.name, dir_fd=parent, follow_symlinks=False)
        except FileNotFoundError:
            pass
        except OSError as exc:
            raise SupplyChainContractError(
                "public readback receipt identity could not be inspected"
            ) from exc
        else:
            _fail("public readback receipt path already exists or aliases an input")
        return _ReceiptBoundary(
            parent_inode=_inode(os.fstat(parent)),
            protected_root_inodes=protected,
        )
    finally:
        for root in roots:
            try:
                os.close(root)
            except OSError:
                pass
        try:
            os.close(parent)
        except OSError:
            pass


def _write_new(path: Path, raw: bytes, boundary: _ReceiptBoundary) -> None:
    write_new_immutable_bytes(
        path,
        raw,
        label="public readback receipt",
        mode=0o400,
        partial_prefix=".searise-public-readback-",
        required_parent_inode=boundary.parent_inode,
        forbidden_ancestor_inodes=boundary.protected_root_inodes,
    )


def _verify_public_signed_subjects(
    candidate_root: Path,
    evidence_root: Path,
    *,
    repository_root: Path,
    controlled_build_run_id: str,
    cosign_executable: Path,
    cosign_tool_lock: Path,
    trusted_cosign_tool_lock_sha256: str,
    expected_origin: str,
    manifest_url: str,
    provenance_url: str,
    receipt_path: Path | None = None,
    fetch: Callable[[str, int], bytes],
    clock: Callable[[], datetime],
    reviewed_origins: Iterable[str],
) -> PublicReadbackVerification:
    receipt_boundary = (
        _receipt_boundary(receipt_path, (candidate_root, evidence_root, repository_root))
        if receipt_path is not None
        else None
    )
    verification = verify_candidate_evidence_cryptographically(
        candidate_root,
        evidence_root,
        repository_root=repository_root,
        controlled_build_run_id=controlled_build_run_id,
        cosign_executable=cosign_executable,
        cosign_tool_lock=cosign_tool_lock,
        trusted_cosign_tool_lock_sha256=trusted_cosign_tool_lock_sha256,
    )
    origin = _origin(expected_origin, reviewed_origins=reviewed_origins)
    urls = {
        "manifest.json": _subject_url(manifest_url, origin),
        "provenance.intoto.jsonl": _subject_url(provenance_url, origin),
    }
    roots = {"manifest.json": candidate_root, "provenance.intoto.jsonl": evidence_root}
    verified_subjects = {item["path"]: item for item in verification.receipt["subjects"]}
    subjects = []
    for logical in _SUBJECT_PATHS:
        local = _read_subject(roots[logical], logical)
        expected = verified_subjects.get(logical)
        if (
            not isinstance(expected, Mapping)
            or _SHA256.fullmatch(str(expected.get("sha256"))) is None
            or _sha256(local) != expected["sha256"]
        ):
            _fail(f"local subject differs from fresh cryptographic verification: {logical}")
        public = fetch(urls[logical], len(local))
        if type(public) is not bytes or public != local:
            _fail(f"public bytes differ from the verified signed subject: {logical}")
        subjects.append(
            {
                "path": logical,
                "url": urls[logical],
                "byteSize": len(public),
                "sha256": _sha256(public),
                "matchesCryptographicallyVerifiedSubject": True,
            }
        )
    instant = clock()
    if instant.tzinfo is None or instant.utcoffset() is None:
        _fail("public readback observation instant must include a timezone")
    document = {
        "$schema": _SCHEMA_URI,
        "schemaVersion": "1.0.0",
        "receiptType": "phase-1-public-signed-subject-readback-v1",
        "candidateId": verification.receipt["candidateId"],
        "dataReleaseId": verification.receipt["dataReleaseId"],
        "controlledBuildRunId": controlled_build_run_id,
        "publicOrigin": origin,
        "observedAt": instant.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "cryptographicVerificationReceiptSha256": _sha256(verification.receipt_bytes),
        "subjects": subjects,
        "claims": {
            "cryptographicSubjectsReverified": True,
            "publicBytesMatched": True,
            "productionClaim": False,
            "publicationApproval": False,
            "scientificApproval": False,
        },
    }
    _validate_schema(document, "public-readback-verification-receipt.schema.json")
    raw = _canonical(document)
    if receipt_path is not None and receipt_boundary is not None:
        _write_new(receipt_path, raw, receipt_boundary)
    return PublicReadbackVerification(receipt=document, receipt_bytes=raw)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def verify_public_signed_subjects(
    candidate_root: Path,
    evidence_root: Path,
    *,
    repository_root: Path,
    controlled_build_run_id: str,
    cosign_executable: Path,
    cosign_tool_lock: Path,
    trusted_cosign_tool_lock_sha256: str,
    expected_origin: str,
    manifest_url: str,
    provenance_url: str,
    receipt_path: Path | None = None,
) -> PublicReadbackVerification:
    """Reverify signatures, then require approved public bytes to equal both subjects."""
    return _verify_public_signed_subjects(
        candidate_root,
        evidence_root,
        repository_root=repository_root,
        controlled_build_run_id=controlled_build_run_id,
        cosign_executable=cosign_executable,
        cosign_tool_lock=cosign_tool_lock,
        trusted_cosign_tool_lock_sha256=trusted_cosign_tool_lock_sha256,
        expected_origin=expected_origin,
        manifest_url=manifest_url,
        provenance_url=provenance_url,
        receipt_path=receipt_path,
        fetch=_fetch,
        clock=_utc_now,
        reviewed_origins=_REVIEWED_PUBLIC_ORIGINS,
    )
