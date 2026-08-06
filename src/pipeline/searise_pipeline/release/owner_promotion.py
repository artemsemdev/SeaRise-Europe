"""Protected, GitHub-bound owner promotion for the Phase 0R release."""

from __future__ import annotations

import json
import math
import re
import stat
import subprocess
import urllib.error
import urllib.request
import zipfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from searise_pipeline.science.contracts import ScienceContractError

from .evidence import (
    binding_sha256,
    load_json,
    load_json_snapshot,
    sha256,
)
from .promotion import (
    _BUILD_CHECKS,
    _validate_binding,
    _validate_reproducibility_report,
)

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


def _git(repository_root: Path, *arguments: str) -> str:
    try:
        return subprocess.run(
            ["git", "-C", str(repository_root), *arguments],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ScienceContractError("Git integration verification failed") from exc


def _changed_paths(repository_root: Path, first: str, second: str) -> dict[str, str]:
    output = _git(
        repository_root,
        "diff",
        "--name-status",
        "--no-renames",
        first,
        second,
        "--",
    )
    changes: dict[str, str] = {}
    for line in output.splitlines():
        fields = line.split("\t")
        if len(fields) != 2 or fields[0] not in {"A", "M"}:
            raise ScienceContractError("Evidence-only revision contains a forbidden change")
        status, path = fields
        if path in changes or path not in _ALLOWED_EVIDENCE_DELTA:
            raise ScienceContractError("Evidence-only revision changed a forbidden path")
        changes[path] = status
    return changes


def _tree_blob(repository_root: Path, revision: str, path: str) -> str:
    output = _git(repository_root, "ls-tree", revision, "--", path)
    try:
        metadata, observed_path = output.split("\t", 1)
        mode, kind, object_id = metadata.split(" ", 2)
    except ValueError as exc:
        raise ScienceContractError("Evidence-only revision has an invalid tree entry") from exc
    if (
        observed_path != path
        or mode != "100644"
        or kind != "blob"
        or _GIT_SHA.fullmatch(object_id) is None
    ):
        raise ScienceContractError("Evidence-only revision contains a symlink or submodule")
    return object_id


def _verify_evidence_only_delta(
    repository_root: Path,
    source_revision: str,
    evidence_revision: str,
) -> dict[str, dict[str, str]]:
    """Allow a linear post-build delta containing only fixed evidence paths."""
    _require(
        source_revision != evidence_revision,
        "Final evidence revision must advance the candidate source revision",
    )
    _git(repository_root, "merge-base", "--is-ancestor", source_revision, evidence_revision)
    commits = _git(
        repository_root,
        "rev-list",
        "--reverse",
        "--ancestry-path",
        f"{source_revision}..{evidence_revision}",
    ).splitlines()
    _require(bool(commits), "Final evidence revision has no direct ancestry path")
    previous = source_revision
    cumulative: set[str] = set()
    for commit in commits:
        parents = _git(repository_root, "show", "-s", "--format=%P", commit).split()
        _require(
            parents == [previous],
            "Evidence-only revision must be a direct linear descendant",
        )
        commit_changes = _changed_paths(repository_root, previous, commit)
        for path in commit_changes:
            _tree_blob(repository_root, commit, path)
        cumulative.update(commit_changes)
        previous = commit
    _require(previous == evidence_revision, "Evidence-only revision is not the direct head")
    _require(
        set(_REQUIRED_EVIDENCE_DELTA).issubset(cumulative),
        "Evidence-only revision does not commit the complete fixed evidence bundle",
    )

    final_changes = _changed_paths(repository_root, source_revision, evidence_revision)
    _require(
        set(_REQUIRED_EVIDENCE_DELTA).issubset(final_changes),
        "Required evidence was reverted before the final evidence revision",
    )
    records: dict[str, dict[str, str]] = {}
    for path in sorted(final_changes):
        evidence_blob = _tree_blob(repository_root, evidence_revision, path)
        _require(
            _tree_blob(repository_root, "HEAD", path) == evidence_blob,
            "Committed evidence changed after the final integration head",
        )
        working_path = repository_root / path
        _require(
            working_path.is_file() and not working_path.is_symlink(),
            "Committed evidence is not a regular checkout file",
        )
        _require(
            _git(repository_root, "hash-object", "--", path) == evidence_blob,
            "Committed evidence checkout bytes differ from the reviewed tree",
        )
        records[path] = {
            "status": final_changes[path],
            "gitBlobSha1": evidence_blob,
            "sha256": sha256(working_path),
        }
    return records


def _validate_context(context: Mapping[str, str], repository_root: Path) -> dict[str, str]:
    required = {
        "GITHUB_REPOSITORY": REPOSITORY,
        "GITHUB_REF": MASTER_REF,
        "GITHUB_ACTOR": OWNER_LOGIN,
        "GITHUB_TRIGGERING_ACTOR": OWNER_LOGIN,
        "GITHUB_WORKFLOW": "Phase 0R owner promotion",
        "GITHUB_WORKFLOW_REF": f"{REPOSITORY}/{OWNER_WORKFLOW}@{MASTER_REF}",
        "SEARISE_OWNER_ENVIRONMENT": OWNER_ENVIRONMENT,
    }
    for key, expected in required.items():
        _require(context.get(key) == expected, f"{key} is outside the owner authority boundary")
    for key in ("GITHUB_SHA",):
        _require(_GIT_SHA.fullmatch(context.get(key, "")) is not None, f"{key} is invalid")
    for key in ("GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT"):
        _exact_positive_decimal(context.get(key, ""), key)
    _require(
        context["GITHUB_RUN_ATTEMPT"] == "1",
        "Protected owner promotion must use a fresh workflow run",
    )
    _require(
        repository_root.is_dir() and not repository_root.is_symlink(), "Repository root is invalid"
    )
    _require(
        Path(_git(repository_root, "rev-parse", "--show-toplevel")).resolve()
        == repository_root.resolve(),
        "Repository root is not the exact worktree",
    )
    _require(
        _git(repository_root, "rev-parse", "HEAD") == context["GITHUB_SHA"],
        "Checked-out master differs from GITHUB_SHA",
    )
    return dict(context)


def _parse_checksums(path: Path) -> dict[str, str]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ScienceContractError("Cannot read committed macOS checksums") from exc
    declared: dict[str, str] = {}
    for line in lines:
        parts = line.split("  ", 1)
        if (
            len(parts) != 2
            or _SHA256.fullmatch(parts[0]) is None
            or parts[1] not in _BUNDLE_FILES
            or parts[1] in declared
        ):
            raise ScienceContractError("Committed macOS checksum inventory is malformed")
        declared[parts[1]] = parts[0]
    if set(declared) != set(_BUNDLE_FILES):
        raise ScienceContractError("Committed macOS checksum inventory is incomplete")
    return declared


def _load_committed_evidence(
    repository_root: Path,
    contract: Mapping[str, Any],
) -> tuple[
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    int,
    dict[str, Any],
]:
    root = repository_root / MAC_EVIDENCE_ROOT
    _require(root.is_dir() and not root.is_symlink(), "Committed macOS evidence root is missing")
    files = {name: root / name for name in _BUNDLE_FILES}
    _require(
        all(path.is_file() and not path.is_symlink() for path in files.values()),
        "Committed macOS evidence files are incomplete",
    )
    checksums = _parse_checksums(root / "checksums.txt")
    actual = {name: sha256(path) for name, path in files.items()}
    _require(actual == checksums, "Committed macOS evidence differs from checksums")
    summary_hashes = {**actual, "checksums.txt": sha256(root / "checksums.txt")}

    binding = _validate_binding(
        load_json(files["candidate-binding.json"]),
        release_contract_id=contract["releaseContractId"],
    )
    receipt = load_json(files["build-receipt.json"])
    _require(
        sha256(files["build-receipt.json"]) == binding["buildReceiptSha256"]
        and receipt.get("releaseId") == binding["releaseId"]
        and receipt.get("sourceRevision") == binding["sourceRevision"]
        and receipt.get("environmentIdentity") == binding["environmentIdentity"],
        "Committed macOS build receipt differs from its candidate binding",
    )
    delivery = _validate_delivery_report(
        load_json(files["delivery-report.json"]),
        binding=binding,
        contract=contract,
    )
    _require(
        delivery["trace"]["sha256"] == actual["browser-trace-macos-arm64.json"]
        and delivery["buildTiming"]["sha256"]
        == actual["build-timing-macos-arm64.json"],
        "Committed raw delivery inputs differ from the delivery report",
    )
    reproducibility = _validate_reproducibility_report(
        load_json(files["reproducibility-report.json"]),
        binding=binding,
        contract=contract,
    )
    automated_gate = dict(load_json(files["automated-gate.json"]))
    gate_checks = automated_gate.get("checks")
    _require(
        set(automated_gate)
        == {
            "schemaVersion",
            "gateId",
            "issue",
            "releaseId",
            "scientificDisposition",
            "automatedValidation",
            "releaseDisposition",
            "phase1Unlocked",
            "checks",
            "blockingChecks",
            "fallback",
            "evidenceBindings",
            "externalVerificationRequired",
        }
        and type(automated_gate.get("schemaVersion")) is int
        and automated_gate["schemaVersion"] == 1
        and automated_gate.get("gateId") == "phase-0r-ar6-regional-release-v1"
        and type(automated_gate.get("issue")) is int
        and automated_gate["issue"] == 110
        and automated_gate.get("releaseId") == binding["releaseId"]
        and automated_gate.get("scientificDisposition")
        == contract["scientificDisposition"]
        and automated_gate.get("automatedValidation") == "pending"
        and automated_gate.get("releaseDisposition") == "pending-owner"
        and automated_gate.get("phase1Unlocked") is False
        and automated_gate.get("blockingChecks") == ["crossEnvironmentReproducibility"]
        and automated_gate.get("fallback") == "do-not-publish-or-unlock-phase-1",
        "Committed automated gate is not the strict pending-external result",
    )
    _require(
        type(gate_checks) is dict
        and set(gate_checks)
        == _BUILD_CHECKS | {"crossEnvironmentReproducibility", "deliveryMeasurements"}
        and all(gate_checks[name] is True for name in _BUILD_CHECKS)
        and gate_checks["crossEnvironmentReproducibility"] is False
        and gate_checks["deliveryMeasurements"] is True,
        "Committed automated gate checks are not the strict finalizer result",
    )
    bindings = automated_gate.get("evidenceBindings")
    _require(
        type(bindings) is dict
        and bindings
        == {
            "candidateBindingSha256": binding_sha256(binding),
            "manifestSha256": binding["manifestSha256"],
            "reproducibilityReportSha256": actual["reproducibility-report.json"],
            "deliveryReportSha256": actual["delivery-report.json"],
            "deliveryTraceSha256": delivery["trace"]["sha256"],
            "buildTimingSha256": delivery["buildTiming"]["sha256"],
            "browserHarnessSha256": delivery["harness"]["sha256"],
        },
        "Committed automated gate evidence bindings differ",
    )
    required_external = reproducibility["requiredExternalBindings"]
    required_verification = automated_gate.get("externalVerificationRequired")
    _require(
        required_verification
        == {
            "reproducibilityProvenance": {
                "status": "pending-external-verification",
                "provider": "github-actions",
                "requiredExternalBindings": required_external,
            }
        },
        "Committed automated gate requires another external binding set",
    )
    summary = load_json(repository_root / SUMMARY_PATH)
    expected_summary_files = {
        (MAC_EVIDENCE_ROOT / name).as_posix(): digest for name, digest in summary_hashes.items()
    }
    _require(
        set(summary)
        == {
            "schemaVersion",
            "releaseId",
            "sourceRevision",
            "integrationPullRequest",
            "committedEvidence",
        }
        and type(summary.get("schemaVersion")) is int
        and summary["schemaVersion"] == 1
        and summary.get("releaseId") == binding["releaseId"]
        and summary.get("sourceRevision") == binding["sourceRevision"]
        and type(summary.get("integrationPullRequest")) is int
        and summary["integrationPullRequest"] > 0
        and summary.get("committedEvidence") == {"files": expected_summary_files},
        "Committed evidence summary is detached from the fixed bundle",
    )
    _require(
        delivery["status"] == "passed"
        and reproducibility["status"] == "pending-external-provenance"
        and reproducibility["localComparisonStatus"] == "passed"
        and reproducibility["externalProvenanceStatus"] == "required",
        "Committed evidence is not ready for protected provenance verification",
    )
    return (
        binding,
        reproducibility,
        automated_gate,
        summary_hashes,
        summary["integrationPullRequest"],
        delivery,
    )


def _safe_extract(
    archive: Path,
    destination: Path,
    *,
    platform: str,
) -> tuple[Path, Path, Path | None]:
    timing_name = {
        "linux": "build-timing-linux.json",
        "macos": "build-timing-macos-arm64.json",
    }.get(platform)
    _require(timing_name is not None, "Validation artifact platform is unsupported")
    trace_name = "browser-trace-macos-arm64.json" if platform == "macos" else None
    required_evidence = {timing_name}
    if trace_name is not None:
        required_evidence.add(trace_name)
    destination.mkdir(parents=True, exist_ok=False)
    try:
        with zipfile.ZipFile(archive) as bundle:
            names: set[str] = set()
            total = 0
            for item in bundle.infolist():
                relative = Path(item.filename)
                mode = item.external_attr >> 16
                file_type = stat.S_IFMT(mode)
                if (
                    not item.filename
                    or relative.is_absolute()
                    or relative.as_posix() != item.filename.rstrip("/")
                    or any(part in {"", ".", ".."} for part in relative.parts)
                    or item.filename in names
                    or stat.S_ISLNK(mode)
                    or (file_type and not (stat.S_ISREG(mode) or stat.S_ISDIR(mode)))
                ):
                    raise ScienceContractError("Validation artifact ZIP contains an unsafe path")
                names.add(item.filename)
                total += item.file_size
                if total > _MAX_ARTIFACT_BYTES:
                    raise ScienceContractError(
                        "Expanded validation artifact exceeds the fixed limit"
                    )
                allowed = (
                    relative.parts[0] == LINUX_CANDIDATE_DIRECTORY
                    or item.filename in required_evidence
                )
                if not allowed:
                    raise ScienceContractError(
                        "Validation artifact ZIP contains an unexpected path"
                    )
            _require(
                required_evidence.issubset(names),
                "Validation artifact lacks required platform evidence",
            )
            bundle.extractall(destination)
    except (OSError, zipfile.BadZipFile) as exc:
        raise ScienceContractError("Validation artifact is not a readable ZIP") from exc
    candidate = destination / LINUX_CANDIDATE_DIRECTORY
    _require(
        candidate.is_dir() and not candidate.is_symlink(),
        f"{platform} candidate is missing from validation artifact",
    )
    return (
        candidate,
        destination / timing_name,
        destination / trace_name if trace_name is not None else None,
    )


def _validate_trusted_timing(
    path: Path,
    *,
    binding: Mapping[str, Any],
    contract: Mapping[str, Any],
) -> dict[str, Any]:
    timing, timing_sha256 = load_json_snapshot(path)
    _require(
        type(timing) is dict
        and set(timing)
        == {
            "schemaVersion",
            "candidate",
            "timer",
            "startedBeforeSourceVerification",
            "endedAfterAtomicCandidatePublish",
            "fullCleanBuildDurationSeconds",
        }
        and type(timing.get("schemaVersion")) is int
        and timing["schemaVersion"] == 1
        and timing.get("candidate") == binding
        and timing.get("timer") == "python-time-perf-counter"
        and timing.get("startedBeforeSourceVerification") is True
        and timing.get("endedAfterAtomicCandidatePublish") is True,
        "Trusted build timing is detached or incomplete",
    )
    duration = _finite_non_negative_number(
        timing["fullCleanBuildDurationSeconds"],
        "Trusted full clean build duration",
    )
    _require(
        duration > 0 and duration <= contract["budgets"]["buildDurationSeconds"],
        "Trusted full clean build exceeds the release budget",
    )
    return {
        "path": path.name,
        "sha256": timing_sha256,
        "fullCleanBuildDurationSeconds": duration,
    }


def _verify_validation_run(
    api: GitHubApi,
    run_id: int,
    source_revision: str,
    download_root: Path,
) -> tuple[dict[str, Any], dict[str, Path], dict[str, Path], Path]:
    run = api.get_json(f"/repos/{REPOSITORY}/actions/runs/{run_id}")
    workflow_id = run.get("workflow_id")
    repository_id = run.get("repository", {}).get("id")
    _require(
        run.get("id") == run_id
        and run.get("event") == "workflow_dispatch"
        and run.get("status") == "completed"
        and run.get("conclusion") == "success"
        and run.get("head_sha") == source_revision
        and run.get("head_branch") == "master"
        and run.get("path") == VALIDATION_WORKFLOW
        and run.get("repository", {}).get("full_name") == REPOSITORY
        and run.get("head_repository", {}).get("full_name") == REPOSITORY
        and type(repository_id) is int
        and repository_id > 0
        and run.get("head_repository", {}).get("id") == repository_id
        and run.get("actor", {}).get("login") == OWNER_LOGIN
        and run.get("triggering_actor", {}).get("login") == OWNER_LOGIN
        and type(workflow_id) is int
        and workflow_id > 0
        and run.get("run_attempt") == 1,
        "Release-validation run is outside the fixed provenance boundary",
    )
    workflow = api.get_json(f"/repos/{REPOSITORY}/actions/workflows/{workflow_id}")
    _require(
        workflow.get("path") == VALIDATION_WORKFLOW
        and workflow.get("name") == VALIDATION_WORKFLOW_NAME
        and workflow.get("state") == "active",
        "Release-validation run used another workflow",
    )
    jobs_document = api.get_json(
        f"/repos/{REPOSITORY}/actions/runs/{run_id}/attempts/1/jobs?per_page=100"
    )
    jobs = jobs_document.get("jobs")
    _require(
        type(jobs) is list and jobs_document.get("total_count") == len(jobs) and len(jobs) <= 100,
        "Release-validation job inventory is incomplete",
    )
    expected_job_names = {
        "linux": VALIDATION_JOB_NAME,
        "macos": MAC_VALIDATION_JOB_NAME,
    }
    matching_jobs = {
        platform: [job for job in jobs if job.get("name") == name]
        for platform, name in expected_job_names.items()
    }
    _require(
        all(
            len(matches) == 1
            and type(matches[0].get("id")) is int
            and matches[0]["id"] > 0
            and matches[0].get("run_id") == run_id
            and matches[0].get("head_sha") == source_revision
            and matches[0].get("status") == "completed"
            and matches[0].get("conclusion") == "success"
            for matches in matching_jobs.values()
        )
        and len({matches[0]["id"] for matches in matching_jobs.values()}) == 2,
        "Exact Linux and macOS release-validation jobs did not pass independently",
    )
    expected_names = {
        "linux": f"ar6-linux-candidate-{source_revision}-{run_id}",
        "macos": f"ar6-macos-arm64-candidate-{source_revision}-{run_id}",
    }
    artifact_document = api.get_json(
        f"/repos/{REPOSITORY}/actions/runs/{run_id}/artifacts?per_page=100"
    )
    artifacts = artifact_document.get("artifacts")
    _require(
        type(artifacts) is list
        and artifact_document.get("total_count") == 2
        and len(artifacts) == 2,
        "Release-validation artifact inventory is incomplete",
    )
    matching = {
        platform: [item for item in artifacts if item.get("name") == name]
        for platform, name in expected_names.items()
    }
    _require(
        all(
            len(matches) == 1
            and matches[0].get("expired") is False
            and type(matches[0].get("id")) is int
            and matches[0]["id"] > 0
            and type(matches[0].get("size_in_bytes")) is int
            and matches[0]["size_in_bytes"] > 0
            and type(matches[0].get("digest")) is str
            and matches[0]["digest"].startswith("sha256:")
            and _SHA256.fullmatch(matches[0]["digest"].removeprefix("sha256:"))
            is not None
            and matches[0].get("workflow_run")
            == {
                "id": run_id,
                "repository_id": repository_id,
                "head_repository_id": repository_id,
                "head_branch": "master",
                "head_sha": source_revision,
            }
            for matches in matching.values()
        )
        and len({matches[0]["id"] for matches in matching.values()}) == 2,
        "Exact Linux and macOS release-validation artifacts are unavailable",
    )
    download_root.mkdir(parents=True, exist_ok=False)
    candidates: dict[str, Path] = {}
    timings: dict[str, Path] = {}
    mac_trace: Path | None = None
    artifact_records: dict[str, dict[str, Any]] = {}
    for platform in ("linux", "macos"):
        artifact = dict(matching[platform][0])
        archive = download_root / f"{platform}-candidate.zip"
        api.download(
            f"/repos/{REPOSITORY}/actions/artifacts/{artifact['id']}/zip",
            archive,
        )
        _require(
            archive.is_file()
            and not archive.is_symlink()
            and archive.stat().st_size == artifact["size_in_bytes"]
            and sha256(archive) == artifact["digest"].removeprefix("sha256:"),
            "Downloaded validation artifact differs from GitHub metadata",
        )
        artifact["downloadSha256"] = sha256(archive)
        artifact["downloadedBytes"] = archive.stat().st_size
        artifact_records[platform] = artifact
        candidate, timing, trace = _safe_extract(
            archive,
            download_root / f"{platform}-extracted",
            platform=platform,
        )
        candidates[platform] = candidate
        timings[platform] = timing
        if platform == "macos":
            _require(trace is not None, "macOS validation trace is missing")
            mac_trace = trace
    if mac_trace is None:
        raise ScienceContractError("macOS validation trace is missing")
    return {
        "run": run,
        "workflow": workflow,
        "jobs": {platform: matches[0] for platform, matches in matching_jobs.items()},
        "artifacts": artifact_records,
    }, candidates, timings, mac_trace


def _verify_release_merges(
    api: GitHubApi,
    integration_pr_number: int,
    evidence_pr_number: int,
    source_revision: str,
    context: Mapping[str, str],
    repository_root: Path,
) -> dict[str, Any]:
    integration_pull = api.get_json(
        f"/repos/{REPOSITORY}/pulls/{integration_pr_number}"
    )
    _require(
        integration_pull.get("number") == integration_pr_number
        and integration_pull.get("state") == "closed"
        and integration_pull.get("merged") is True
        and integration_pull.get("base", {}).get("ref") == "master"
        and integration_pull.get("base", {}).get("repo", {}).get("full_name")
        == REPOSITORY
        and integration_pull.get("head", {}).get("repo", {}).get("full_name")
        == REPOSITORY
        and integration_pull.get("merge_commit_sha") == source_revision,
        "Code integration pull request did not produce the candidate source revision",
    )
    evidence_pull = api.get_json(f"/repos/{REPOSITORY}/pulls/{evidence_pr_number}")
    merge_sha = evidence_pull.get("merge_commit_sha", "")
    evidence_revision = evidence_pull.get("head", {}).get("sha", "")
    _require(
        evidence_pull.get("number") == evidence_pr_number
        and evidence_pull.get("state") == "closed"
        and evidence_pull.get("merged") is True
        and evidence_pull.get("base", {}).get("ref") == "master"
        and evidence_pull.get("base", {}).get("sha") == source_revision
        and evidence_pull.get("base", {}).get("repo", {}).get("full_name") == REPOSITORY
        and _GIT_SHA.fullmatch(evidence_revision) is not None
        and evidence_pull.get("head", {}).get("repo", {}).get("full_name") == REPOSITORY
        and _GIT_SHA.fullmatch(merge_sha) is not None,
        "Evidence-only pull request is not the exact merged source",
    )
    source_comparison = api.get_json(
        f"/repos/{REPOSITORY}/compare/{source_revision}...{evidence_revision}"
    )
    _require(
        source_comparison.get("status") == "ahead"
        and source_comparison.get("merge_base_commit", {}).get("sha") == source_revision,
        "Evidence head is not a direct descendant of the candidate source",
    )
    evidence_delta = _verify_evidence_only_delta(
        repository_root,
        source_revision,
        evidence_revision,
    )
    master = api.get_json(f"/repos/{REPOSITORY}/commits/master")
    _require(
        master.get("sha") == context["GITHUB_SHA"] == merge_sha,
        "Current GitHub master is not the exact evidence merge",
    )
    parents = _git(repository_root, "show", "-s", "--format=%P", merge_sha).split()
    _require(
        parents == [source_revision, evidence_revision]
        and _git(repository_root, "rev-parse", "HEAD") == merge_sha
        and _git(repository_root, "rev-parse", f"{evidence_revision}^{{tree}}")
        == _git(repository_root, "rev-parse", f"{merge_sha}^{{tree}}"),
        "Evidence merge parents or tree differ from the reviewed evidence head",
    )
    return {
        "integrationPull": integration_pull,
        "evidencePull": evidence_pull,
        "master": master,
        "sourceComparison": source_comparison,
        "evidenceDelta": evidence_delta,
    }


def _external_binding_requirements(gate: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    try:
        provenance = gate["externalVerificationRequired"]["reproducibilityProvenance"]
        required = provenance["requiredExternalBindings"]
    except (KeyError, TypeError) as exc:
        raise ScienceContractError("Automated gate lacks external binding requirements") from exc
    if (
        provenance.get("status") != "pending-external-verification"
        or provenance.get("provider") != "github-actions"
        or set(provenance) != {"status", "provider", "requiredExternalBindings"}
        or type(required) is not list
        or len(required) != 2
        or any(
            type(item) is not dict
            or set(item)
            != {
                "candidateBindingSha256",
                "releaseId",
                "sourceRevision",
                "receiptBuildRunId",
                "validatedEnvironmentProfile",
            }
            for item in required
        )
    ):
        raise ScienceContractError("Automated gate requires another external binding set")
    return required


def _decision_title(validation_run_id: int, pr_number: int) -> str:
    return (
        f"Phase 0R owner decision from validation run {validation_run_id} "
        f"for evidence PR #{pr_number}"
    )


def _decision_artifact_name(release_id: str, source_revision: str) -> str:
    _require(
        re.fullmatch(r"[a-z0-9]+(?:[.-][a-z0-9]+)*", release_id) is not None
        and _GIT_SHA.fullmatch(source_revision) is not None,
        "Owner decision identity is not canonical",
    )
    return f"phase-0r-owner-decision-{release_id}-{source_revision}"


def _verify_no_prior_decision(
    api: GitHubApi,
    validation_run_id: int,
    pr_number: int,
    release_id: str,
    source_revision: str,
    context: Mapping[str, str],
    repository_root: Path,
) -> None:
    """Reject concurrent or prior authority for the same release candidate."""
    committed_records = _git(
        repository_root,
        "ls-tree",
        "-r",
        "--name-only",
        "HEAD",
        "--",
        OWNER_RECORD_ROOT.as_posix(),
    ).splitlines()
    if committed_records:
        expected_records = {
            (OWNER_RECORD_ROOT / name).as_posix() for name in _OWNER_RECORD_FILES
        }
        _require(
            set(committed_records) == expected_records,
            "Permanent owner record root is incomplete or ambiguous",
        )
        raise ScienceContractError(
            "A permanent authoritative owner decision already exists"
        )
    document = api.get_json(
        f"/repos/{REPOSITORY}/actions/workflows/{Path(OWNER_WORKFLOW).name}/runs"
        "?event=workflow_dispatch&per_page=100"
    )
    runs = document.get("workflow_runs")
    _require(
        type(runs) is list
        and document.get("total_count") == len(runs)
        and len(runs) <= 100,
        "Owner decision history is incomplete or ambiguous",
    )
    current_run_id = int(context["GITHUB_RUN_ID"])
    current_title = _decision_title(validation_run_id, pr_number)
    artifact_name = _decision_artifact_name(release_id, source_revision)
    for run in runs:
        _require(type(run) is dict, "Owner decision history is malformed")
        if run.get("id") == current_run_id:
            _require(
                run.get("display_title") == current_title,
                "Current owner decision identity is ambiguous",
            )
            continue
        if run.get("status") != "completed":
            raise ScienceContractError("A concurrent owner decision run is already active")
        if run.get("conclusion") != "success":
            continue
        _require(
            type(run.get("id")) is int
            and run["id"] > 0
            and run.get("event") == "workflow_dispatch"
            and run.get("run_attempt") == 1
            and run.get("path") == OWNER_WORKFLOW
            and run.get("head_branch") == "master"
            and run.get("repository", {}).get("full_name") == REPOSITORY
            and run.get("actor", {}).get("login") == OWNER_LOGIN
            and run.get("triggering_actor", {}).get("login") == OWNER_LOGIN,
            "Prior owner decision provenance is ambiguous",
        )
        title_match = re.fullmatch(
            r"Phase 0R owner decision from validation run ([1-9][0-9]*) "
            r"for evidence PR #([1-9][0-9]*)",
            run.get("display_title", ""),
        )
        _require(title_match is not None, "Prior owner decision identity is ambiguous")
        prior_validation_run_id = int(title_match.group(1))
        prior_validation = api.get_json(
            f"/repos/{REPOSITORY}/actions/runs/{prior_validation_run_id}"
        )
        _require(
            prior_validation.get("id") == prior_validation_run_id
            and prior_validation.get("event") == "workflow_dispatch"
            and prior_validation.get("status") == "completed"
            and prior_validation.get("conclusion") == "success"
            and prior_validation.get("run_attempt") == 1
            and prior_validation.get("path") == VALIDATION_WORKFLOW
            and prior_validation.get("head_branch") == "master"
            and _GIT_SHA.fullmatch(prior_validation.get("head_sha", "")) is not None,
            "Prior owner decision validation identity is ambiguous",
        )
        if prior_validation["head_sha"] != source_revision:
            continue
        artifacts_document = api.get_json(
            f"/repos/{REPOSITORY}/actions/runs/{run['id']}/artifacts?per_page=100"
        )
        artifacts = artifacts_document.get("artifacts")
        _require(
            type(artifacts) is list
            and artifacts_document.get("total_count") == len(artifacts)
            and len(artifacts) <= 100,
            "Prior owner decision artifact history is ambiguous",
        )
        matching = [item for item in artifacts if item.get("name") == artifact_name]
        _require(
            len(matching) == 1
            and matching[0].get("expired") is False
            and type(matching[0].get("id")) is int
            and matching[0]["id"] > 0,
            "Prior owner decision artifact is missing or ambiguous",
        )
        raise ScienceContractError(
            "An authoritative owner decision already exists for this release candidate"
        )
