"""Verify public manifest/provenance bytes against freshly verified Sigstore subjects."""

from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import re
import stat
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Mapping, NoReturn

from .candidate_evidence import _open_root
from .contracts import SupplyChainContractError, _validate_schema
from .sbom import write_new_sbom
from .sigstore_verifier import verify_candidate_evidence_cryptographically

_SCHEMA_URI = (
    "https://artemsemdev.github.io/SeaRise-Europe/contracts/supply-chain/v1/"
    "public-readback-verification-receipt.schema.json"
)
_SUBJECT_PATHS = ("manifest.json", "provenance.intoto.jsonl")
_MAX_SUBJECT_BYTES = 8 * 1024 * 1024
_SHA256 = re.compile(r"[0-9a-f]{64}")


@dataclass(frozen=True)
class PublicReadbackVerification:
    """Canonical audit bytes proving public subjects match verified local bytes."""

    receipt: Mapping[str, Any]
    receipt_bytes: bytes


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


def _origin(value: str) -> str:
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


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


def _fetch(url: str, expected_size: int) -> bytes:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/octet-stream",
            "Accept-Encoding": "identity",
            "User-Agent": "SeaRise-Europe-public-readback-v1",
        },
        method="GET",
    )
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        with opener.open(request, timeout=30) as response:
            if response.status != 200 or response.geturl() != url:
                _fail("public subject response identity differs")
            encoding = response.headers.get("Content-Encoding")
            if encoding not in (None, "identity"):
                _fail("public subject response uses content encoding")
            declared = response.headers.get("Content-Length")
            if declared is not None and (not declared.isdigit() or int(declared) != expected_size):
                _fail("public subject Content-Length differs")
            chunks: list[bytes] = []
            remaining = expected_size
            while remaining:
                chunk = response.read(min(65536, remaining))
                if not chunk:
                    _fail("public subject response ended early")
                chunks.append(chunk)
                remaining -= len(chunk)
            if response.read(1):
                _fail("public subject response exceeds the signed byte size")
            return b"".join(chunks)
    except SupplyChainContractError:
        raise
    except (OSError, urllib.error.URLError) as exc:
        raise SupplyChainContractError("public subject readback failed") from exc


def _write_new(path: Path, raw: bytes) -> None:
    if not path.is_absolute() or ".." in path.parts or not path.name:
        _fail("public readback receipt path must be absolute and canonical")
    write_new_sbom(path, raw)


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
    observed_at: datetime | None = None,
    fetch: Callable[[str, int], bytes] = _fetch,
) -> PublicReadbackVerification:
    """Reverify signatures, then require public bytes to equal both signed subjects."""
    verification = verify_candidate_evidence_cryptographically(
        candidate_root,
        evidence_root,
        repository_root=repository_root,
        controlled_build_run_id=controlled_build_run_id,
        cosign_executable=cosign_executable,
        cosign_tool_lock=cosign_tool_lock,
        trusted_cosign_tool_lock_sha256=trusted_cosign_tool_lock_sha256,
    )
    origin = _origin(expected_origin)
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
        if public != local:
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
    instant = observed_at or datetime.now(timezone.utc)
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
    if receipt_path is not None:
        _write_new(receipt_path, raw)
    return PublicReadbackVerification(receipt=document, receipt_bytes=raw)
