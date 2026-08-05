"""Checksum-first source acquisition with structured audit receipts."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from urllib.parse import urlsplit, urlunsplit

from .registry import Asset, Source

TOOL_VERSION = "0.1.0"
TRANSIENT_HTTP_STATUSES = frozenset({408, 425, 429, 500, 502, 503, 504})
AUTH_HTTP_STATUSES = frozenset({401, 403})


@dataclass(frozen=True)
class Receipt:
    source_id: str
    asset_id: str
    requested_url: str
    resolved_url: str | None
    timestamp: str
    status: str
    byte_count: int
    sha256: str | None
    cache_decision: str
    attempts: int
    tool_version: str
    reason: str | None = None

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2, sort_keys=True) + "\n"


class AcquisitionError(RuntimeError):
    """An acquisition failed closed; ``receipt`` contains safe evidence."""

    def __init__(self, receipt: Receipt):
        super().__init__(receipt.reason or receipt.status)
        self.receipt = receipt


def scrub_url(url: str | None) -> str | None:
    """Remove userinfo, query credentials, and fragments from receipt URLs."""
    if url is None:
        return None
    parts = urlsplit(url)
    host = parts.hostname or ""
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    try:
        port = parts.port
    except ValueError:
        port = None
    netloc = f"{host}:{port}" if port is not None else host
    return urlunsplit((parts.scheme, netloc, parts.path, "", ""))


class Acquirer:
    def __init__(
        self,
        cache_root: Path,
        receipt_dir: Path,
        *,
        attempts: int = 3,
        backoff_seconds: float = 0.25,
        timeout_seconds: float = 30.0,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if attempts < 1:
            raise ValueError("attempts must be at least 1")
        self.cache_root = cache_root
        self.receipt_dir = receipt_dir
        self.attempts = attempts
        self.backoff_seconds = backoff_seconds
        self.timeout_seconds = timeout_seconds
        self.sleep = sleep

    def cache_path(self, source: Source, asset: Asset) -> Path:
        root = self.cache_root.resolve()
        target = (root / source.id / source.version / asset.cache_path).resolve()
        if target != root and root not in target.parents:
            raise ValueError(f"Cache path escapes cache root: {asset.cache_path}")
        return target

    def fetch(self, source: Source, asset: Asset) -> tuple[Path | None, Receipt]:
        """Acquire one locked asset, or record an expected 404 distinctly."""
        if source.licence.redistribution_status != "approved":
            self._reject(
                source,
                asset,
                reason=(
                    "permission-blocked: redistribution status is "
                    f"{source.licence.redistribution_status}"
                ),
                cache_decision="not-checked",
                attempts=0,
            )

        if asset.kind != "file":
            self._reject(
                source,
                asset,
                reason="manifest-driven-object-set-required",
                cache_decision="not-checked",
                attempts=0,
            )

        target = self.cache_path(source, asset)
        if target.exists():
            if asset.availability != "locked":
                self._reject(
                    source,
                    asset,
                    reason="unexpected cached bytes for an expected-absent asset",
                    cache_decision="invalid",
                    attempts=0,
                )
            size, digest = _hash_file(target)
            if size != asset.byte_size or digest != asset.sha256:
                self._reject(
                    source,
                    asset,
                    reason="cache-mismatch: size or SHA-256 differs from source lock",
                    cache_decision="invalid",
                    attempts=0,
                    byte_count=size,
                    sha256=digest,
                )
            receipt = self._receipt(
                source,
                asset,
                status="verified",
                cache_decision="hit",
                attempts=0,
                byte_count=size,
                sha256=digest,
                resolved_url=asset.resolved_url,
            )
            return target, receipt

        target.parent.mkdir(parents=True, exist_ok=True)
        return self._download(source, asset, target)

    def verify(self, source: Source, asset: Asset) -> tuple[Path, Receipt]:
        """Verify cached bytes without making a network request."""
        if asset.kind != "file":
            self._reject(
                source,
                asset,
                reason="manifest-driven-object-set-required",
                cache_decision="not-checked",
                attempts=0,
            )
        target = self.cache_path(source, asset)
        if asset.availability != "locked" or not target.is_file():
            self._reject(
                source,
                asset,
                reason="offline-miss: locked bytes are not present in the cache",
                cache_decision="miss",
                attempts=0,
            )
        size, digest = _hash_file(target)
        if size != asset.byte_size or digest != asset.sha256:
            self._reject(
                source,
                asset,
                reason="cache-mismatch: size or SHA-256 differs from source lock",
                cache_decision="invalid",
                attempts=0,
                byte_count=size,
                sha256=digest,
            )
        receipt = self._receipt(
            source,
            asset,
            status="verified",
            cache_decision="hit",
            attempts=0,
            byte_count=size,
            sha256=digest,
            resolved_url=asset.resolved_url,
        )
        return target, receipt

    def _download(
        self, source: Source, asset: Asset, target: Path
    ) -> tuple[Path | None, Receipt]:
        request = urllib.request.Request(
            asset.url,
            headers={
                "Accept": "*/*",
                "User-Agent": f"SeaRise-Europe-source-acquisition/{TOOL_VERSION}",
            },
        )
        for attempt in range(1, self.attempts + 1):
            try:
                with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                    return self._consume_response(source, asset, target, response, attempt)
            except urllib.error.HTTPError as exc:
                if exc.code == 404 and asset.availability == "expected-absent":
                    receipt = self._receipt(
                        source,
                        asset,
                        status="expected-absent",
                        cache_decision="absent",
                        attempts=attempt,
                        resolved_url=exc.geturl(),
                    )
                    return None, receipt
                if exc.code in AUTH_HTTP_STATUSES:
                    self._reject(
                        source,
                        asset,
                        reason=f"authentication-or-permission-error: HTTP {exc.code}",
                        cache_decision="miss",
                        attempts=attempt,
                        resolved_url=exc.geturl(),
                    )
                if exc.code not in TRANSIENT_HTTP_STATUSES:
                    self._reject(
                        source,
                        asset,
                        reason=f"permanent-http-error: HTTP {exc.code}",
                        cache_decision="miss",
                        attempts=attempt,
                        resolved_url=exc.geturl(),
                    )
                if attempt == self.attempts:
                    self._reject(
                        source,
                        asset,
                        reason=f"retry-exhausted: HTTP {exc.code}",
                        cache_decision="miss",
                        attempts=attempt,
                        resolved_url=exc.geturl(),
                    )
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                if attempt == self.attempts:
                    self._reject(
                        source,
                        asset,
                        reason=f"retry-exhausted: {type(exc).__name__}",
                        cache_decision="miss",
                        attempts=attempt,
                    )
            self.sleep(self.backoff_seconds * (2 ** (attempt - 1)))
        raise AssertionError("retry loop exited unexpectedly")

    def _consume_response(
        self,
        source: Source,
        asset: Asset,
        target: Path,
        response: object,
        attempt: int,
    ) -> tuple[Path, Receipt]:
        resolved_url = response.geturl()  # type: ignore[attr-defined]
        if resolved_url != asset.resolved_url:
            self._reject(
                source,
                asset,
                reason="resolved-url-mismatch",
                cache_decision="miss",
                attempts=attempt,
                resolved_url=resolved_url,
            )
        content_type = response.headers.get_content_type().lower()  # type: ignore[attr-defined]
        if content_type != asset.media_type:
            self._reject(
                source,
                asset,
                reason=f"media-type-mismatch: {content_type}",
                cache_decision="miss",
                attempts=attempt,
                resolved_url=resolved_url,
            )
        if asset.availability != "locked":
            self._reject(
                source,
                asset,
                reason="expected-absent asset returned bytes",
                cache_decision="miss",
                attempts=attempt,
                resolved_url=resolved_url,
            )

        content_length = response.headers.get("Content-Length")  # type: ignore[attr-defined]
        if content_length is not None and int(content_length) != asset.byte_size:
            self._reject(
                source,
                asset,
                reason="size-mismatch: Content-Length differs from source lock",
                cache_decision="miss",
                attempts=attempt,
                resolved_url=resolved_url,
            )

        temporary: Path | None = None
        digest = hashlib.sha256()
        byte_count = 0
        prefix = b""
        try:
            with tempfile.NamedTemporaryFile(
                dir=target.parent,
                prefix=f".{target.name}.",
                suffix=".part",
                delete=False,
            ) as handle:
                temporary = Path(handle.name)
                while True:
                    chunk = response.read(1024 * 1024)  # type: ignore[attr-defined]
                    if not chunk:
                        break
                    if len(prefix) < 512:
                        prefix += chunk[: 512 - len(prefix)]
                    byte_count += len(chunk)
                    if byte_count > (asset.byte_size or 0):
                        self._reject(
                            source,
                            asset,
                            reason="size-mismatch: response exceeds source lock",
                            cache_decision="miss",
                            attempts=attempt,
                            resolved_url=resolved_url,
                            byte_count=byte_count,
                        )
                    digest.update(chunk)
                    handle.write(chunk)

            actual_sha256 = digest.hexdigest()
            if _looks_like_html(prefix):
                self._reject(
                    source,
                    asset,
                    reason="html-or-login-response",
                    cache_decision="miss",
                    attempts=attempt,
                    resolved_url=resolved_url,
                    byte_count=byte_count,
                    sha256=actual_sha256,
                )
            if byte_count != asset.byte_size:
                self._reject(
                    source,
                    asset,
                    reason="size-mismatch: truncated response",
                    cache_decision="miss",
                    attempts=attempt,
                    resolved_url=resolved_url,
                    byte_count=byte_count,
                    sha256=actual_sha256,
                )
            if actual_sha256 != asset.sha256:
                self._reject(
                    source,
                    asset,
                    reason="checksum-mismatch",
                    cache_decision="miss",
                    attempts=attempt,
                    resolved_url=resolved_url,
                    byte_count=byte_count,
                    sha256=actual_sha256,
                )
            os.replace(temporary, target)
            temporary = None
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

        receipt = self._receipt(
            source,
            asset,
            status="acquired",
            cache_decision="miss",
            attempts=attempt,
            resolved_url=resolved_url,
            byte_count=byte_count,
            sha256=asset.sha256,
        )
        return target, receipt

    def _reject(
        self,
        source: Source,
        asset: Asset,
        *,
        reason: str,
        cache_decision: str,
        attempts: int,
        resolved_url: str | None = None,
        byte_count: int = 0,
        sha256: str | None = None,
    ) -> None:
        receipt = self._receipt(
            source,
            asset,
            status="rejected",
            cache_decision=cache_decision,
            attempts=attempts,
            resolved_url=resolved_url,
            byte_count=byte_count,
            sha256=sha256,
            reason=reason,
        )
        raise AcquisitionError(receipt)

    def _receipt(
        self,
        source: Source,
        asset: Asset,
        *,
        status: str,
        cache_decision: str,
        attempts: int,
        resolved_url: str | None = None,
        byte_count: int = 0,
        sha256: str | None = None,
        reason: str | None = None,
    ) -> Receipt:
        receipt = Receipt(
            source_id=source.id,
            asset_id=asset.id,
            requested_url=scrub_url(asset.url) or "",
            resolved_url=scrub_url(resolved_url),
            timestamp=datetime.now(timezone.utc).isoformat(),
            status=status,
            byte_count=byte_count,
            sha256=sha256,
            cache_decision=cache_decision,
            attempts=attempts,
            tool_version=TOOL_VERSION,
            reason=reason,
        )
        self.receipt_dir.mkdir(parents=True, exist_ok=True)
        receipt_name = (
            f"{source.id}-{asset.id}-{status}-{uuid.uuid4().hex[:12]}.json"
        )
        destination = self.receipt_dir / receipt_name
        temporary = destination.with_suffix(".tmp")
        temporary.write_text(receipt.to_json(), encoding="utf-8")
        os.replace(temporary, destination)
        return receipt


def _hash_file(path: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            size += len(chunk)
            digest.update(chunk)
    return size, digest.hexdigest()


def _looks_like_html(prefix: bytes) -> bool:
    normalized = prefix.lstrip().lower()
    return normalized.startswith((b"<!doctype html", b"<html", b"<head", b"<form"))
