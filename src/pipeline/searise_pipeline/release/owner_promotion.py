"""Protected, GitHub-bound owner promotion for the Phase 0R release."""

from __future__ import annotations

import json
import math
import re
import urllib.error
import urllib.request
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from searise_pipeline.science.contracts import ScienceContractError

from .promotion import _validate_binding

REPOSITORY = "artemsemdev/SeaRise-Europe"
OWNER_LOGIN = "artemsemdev"
MASTER_REF = "refs/heads/master"
OWNER_WORKFLOW = ".github/workflows/phase-0r-owner-promotion.yml"
VALIDATION_WORKFLOW = ".github/workflows/ci.yml"
VALIDATION_WORKFLOW_NAME = "CI"
VALIDATION_JOB_ID = "ar6-release-evidence"
VALIDATION_JOB_NAME = "Full-source Linux AR6 candidate"
MAC_VALIDATION_JOB_ID = "ar6-release-evidence-macos"
MAC_VALIDATION_JOB_NAME = "Full-source macOS ARM64 AR6 candidate"
OWNER_ENVIRONMENT = "phase-0r-owner-approval"
MAC_EVIDENCE_ROOT = Path("src/pipeline/evidence/ar6-regional-release/macos-arm64-cp39")
SUMMARY_PATH = Path("src/pipeline/evidence/ar6-regional-release-evidence.json")
OWNER_RECORD_ROOT = Path("src/pipeline/evidence/ar6-regional-release/owner-promotion")
CONTRACT_PATH = Path("src/pipeline/science/ar6-regional-release.json")
LINUX_CANDIDATE_DIRECTORY = "phase-0r-ar6-v1"
_BUNDLE_FILES = (
    "candidate-binding.json",
    "build-receipt.json",
    "build-timing-macos-arm64.json",
    "browser-trace-macos-arm64.json",
    "delivery-report.json",
    "reproducibility-report.json",
    "automated-gate.json",
)
_SHA256 = re.compile(r"[0-9a-f]{64}")
_GIT_SHA = re.compile(r"[0-9a-f]{40}")
_POSITIVE_DECIMAL = re.compile(r"[1-9][0-9]*")
_MAX_ARTIFACT_BYTES = 128 * 1024 * 1024
_REDIRECT_CODES = {302, 303, 307, 308}
_ARTIFACT_HOST_SUFFIXES = (
    ".actions.githubusercontent.com",
    ".blob.core.windows.net",
)
_REQUIRED_EVIDENCE_DELTA = tuple(
    (MAC_EVIDENCE_ROOT / name).as_posix() for name in (*_BUNDLE_FILES, "checksums.txt")
) + (SUMMARY_PATH.as_posix(),)
_ALLOWED_EVIDENCE_DELTA = frozenset(
    (
        *_REQUIRED_EVIDENCE_DELTA,
        "CHANGELOG.md",
        "docs/evidence/phase-0r-regional-release.md",
    )
)
_OWNER_RECORD_FILES = {
    "owner-attestation.json",
    "integration-merge.json",
    "promotion.json",
    "final-gate.json",
    "checksums.txt",
}


class GitHubApi:
    """Small mockable GitHub REST client with a bounded download path."""

    def __init__(self, token: str) -> None:
        if not token:
            raise ScienceContractError("GITHUB_TOKEN is required")
        self._token = token

    def _request(self, path: str) -> urllib.request.Request:
        if not path.startswith("/"):
            raise ScienceContractError("GitHub API path must be repository-relative")
        return urllib.request.Request(
            "https://api.github.com" + path,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self._token}",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "SeaRise-Europe-owner-promotion",
            },
        )

    @staticmethod
    def _open_no_redirect(
        request: urllib.request.Request,
        *,
        timeout: int,
    ):
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                return None

        return urllib.request.build_opener(NoRedirect()).open(request, timeout=timeout)

    @staticmethod
    def _artifact_redirect(location: object) -> str:
        _require(type(location) is str and bool(location), "Artifact redirect is missing")
        parsed = urlsplit(location)
        host = parsed.hostname or ""
        _require(
            parsed.scheme == "https"
            and parsed.username is None
            and parsed.password is None
            and parsed.port in {None, 443}
            and bool(parsed.path)
            and bool(parsed.query)
            and any(host.endswith(suffix) for suffix in _ARTIFACT_HOST_SUFFIXES),
            "Artifact redirect target is outside trusted HTTPS storage",
        )
        return location

    def get_json(self, path: str) -> Mapping[str, Any]:
        try:
            with urllib.request.urlopen(self._request(path), timeout=30) as response:
                payload = response.read(8 * 1024 * 1024 + 1)
        except (OSError, urllib.error.HTTPError) as exc:
            raise ScienceContractError(f"GitHub API request failed: {path}") from exc
        if len(payload) > 8 * 1024 * 1024:
            raise ScienceContractError("GitHub API response exceeds the fixed limit")
        try:
            document = json.loads(payload)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ScienceContractError("GitHub API returned invalid JSON") from exc
        if type(document) is not dict:
            raise ScienceContractError("GitHub API response must be an object")
        return document

    def download(self, path: str, destination: Path) -> None:
        redirect_response = None
        try:
            try:
                redirect_response = self._open_no_redirect(
                    self._request(path),
                    timeout=30,
                )
            except urllib.error.HTTPError as exc:
                if exc.code not in _REDIRECT_CODES:
                    raise
                redirect_response = exc
            with redirect_response:
                _require(
                    redirect_response.getcode() in _REDIRECT_CODES,
                    "GitHub artifact endpoint did not return the required redirect",
                )
                signed_url = self._artifact_redirect(
                    redirect_response.headers.get("Location")
                )
            storage_request = urllib.request.Request(
                signed_url,
                headers={
                    "Accept": "application/octet-stream",
                    "User-Agent": "SeaRise-Europe-owner-promotion",
                },
            )
            with self._open_no_redirect(storage_request, timeout=60) as response:
                _require(
                    response.getcode() == 200 and response.geturl() == signed_url,
                    "Artifact storage attempted an unexpected redirect",
                )
                content_length = response.headers.get("Content-Length")
                _require(
                    content_length is None
                    or (
                        content_length.isdecimal()
                        and int(content_length) <= _MAX_ARTIFACT_BYTES
                    ),
                    "Validation artifact exceeds the fixed limit",
                )
                with destination.open("xb") as stream:
                    total = 0
                    while chunk := response.read(1024 * 1024):
                        total += len(chunk)
                        if total > _MAX_ARTIFACT_BYTES:
                            raise ScienceContractError(
                                "Validation artifact exceeds the fixed limit"
                            )
                        stream.write(chunk)
        except FileExistsError as exc:
            raise ScienceContractError("Validation artifact download path already exists") from exc
        except (OSError, urllib.error.HTTPError) as exc:
            destination.unlink(missing_ok=True)
            raise ScienceContractError("Validation artifact download failed") from exc


def _exact_positive_decimal(value: str, label: str) -> int:
    if type(value) is not str or _POSITIVE_DECIMAL.fullmatch(value) is None:
        raise ScienceContractError(f"{label} must be a canonical positive decimal")
    return int(value)


def _require(value: bool, message: str) -> None:
    if not value:
        raise ScienceContractError(message)


def _exact_object(value: object, keys: set[str], label: str) -> dict[str, Any]:
    if type(value) is not dict or set(value) != keys:
        raise ScienceContractError(f"{label} does not match its exact schema")
    return value


def _exact_non_negative_integer(value: object, label: str) -> int:
    if type(value) is not int or value < 0:
        raise ScienceContractError(f"{label} must be an exact non-negative integer")
    return value


def _finite_non_negative_number(value: object, label: str) -> float:
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        raise ScienceContractError(f"{label} must be finite and non-negative")
    return float(value)


def _validate_file_reference(value: object, label: str) -> None:
    reference = _exact_object(value, {"path", "sha256"}, label)
    path = Path(reference["path"]) if type(reference["path"]) is str else None
    _require(
        path is not None
        and not path.is_absolute()
        and bool(reference["path"])
        and path.as_posix() == reference["path"]
        and all(part not in {"", ".", ".."} for part in path.parts)
        and type(reference["sha256"]) is str
        and _SHA256.fullmatch(reference["sha256"]) is not None,
        f"{label} is not canonical",
    )


def _validate_delivery_report(
    value: object,
    *,
    binding: Mapping[str, Any],
    contract: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate the immutable report emitted from the raw delivery trace."""
    report = _exact_object(
        value,
        {
            "schemaVersion",
            "status",
            "candidate",
            "trace",
            "buildTiming",
            "harness",
            "profiles",
            "coldLookupSampleCount",
            "warmLookupSampleCount",
            "fullCleanBuildDurationSeconds",
            "browserHeapBytes",
            "rangeRequestCount",
            "coldTransferBytes",
            "lookupP95Milliseconds",
        },
        "Delivery report",
    )
    _require(
        type(report["schemaVersion"]) is int and report["schemaVersion"] == 1,
        "Delivery schema version is invalid",
    )
    _require(
        report["status"] in {"passed", "failed"} and type(report["status"]) is str,
        "Delivery status is invalid",
    )
    observed_binding = _validate_binding(
        report["candidate"],
        release_contract_id=contract["releaseContractId"],
    )
    _require(observed_binding == binding, "Delivery report is detached from the candidate")
    _validate_file_reference(report["trace"], "Delivery trace")
    _validate_file_reference(report["buildTiming"], "Build timing")
    _validate_file_reference(report["harness"], "Browser harness")
    profiles = _exact_object(
        report["profiles"],
        {"hardware", "network", "browser"},
        "Delivery profiles",
    )
    _require(
        all(type(profile) is dict and bool(profile) for profile in profiles.values()),
        "Delivery profiles are incomplete",
    )
    specification = contract["deliveryMeasurement"]
    browser = profiles["browser"]
    _require(
        browser.get("engine") == "Chromium"
        and type(browser.get("version")) is str
        and bool(browser["version"])
        and report["harness"]
        == {
            "path": specification["harnessPath"],
            "sha256": specification["harnessSha256"],
        }
        and report["trace"]["path"] == "browser-trace-macos-arm64.json"
        and report["buildTiming"]["path"] == "build-timing-macos-arm64.json",
        "Delivery tool identity differs from the contract",
    )
    _require(
        _exact_non_negative_integer(
            report["coldLookupSampleCount"], "Cold lookup sample count"
        )
        == specification["minimumColdLookups"]
        and _exact_non_negative_integer(
            report["warmLookupSampleCount"], "Warm lookup sample count"
        )
        == specification["minimumWarmLookups"],
        "Delivery report lacks required lookup samples",
    )
    metrics = {
        "buildDurationSeconds": _finite_non_negative_number(
            report["fullCleanBuildDurationSeconds"], "Build duration"
        ),
        "browserHeapBytes": _exact_non_negative_integer(
            report["browserHeapBytes"], "Browser heap bytes"
        ),
        "rangeRequestCount": _exact_non_negative_integer(
            report["rangeRequestCount"], "Range request count"
        ),
        "coldTransferBytes": _exact_non_negative_integer(
            report["coldTransferBytes"], "Cold transfer bytes"
        ),
        "lookupP95Milliseconds": _finite_non_negative_number(
            report["lookupP95Milliseconds"], "Lookup p95"
        ),
    }
    passed = all(
        metrics[name] <= contract["budgets"][name]
        for name in metrics
    )
    _require(
        passed == (report["status"] == "passed"),
        "Delivery status differs from measured budgets",
    )
    return report
