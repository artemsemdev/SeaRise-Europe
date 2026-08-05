"""Validate observed Chromium delivery traces and bind them to a candidate."""

from __future__ import annotations

import gzip
import json
import re
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlsplit

import numpy as np

from searise_pipeline.science.contracts import ScienceContractError

from .evidence import candidate_binding, load_json, sha256

_TRACE_KEYS = {
    "schemaVersion",
    "harness",
    "candidate",
    "profiles",
    "target",
    "toolchain",
    "coldLookupSamples",
    "warmLookupSamples",
}
_REQUEST_KEYS = {
    "kind",
    "path",
    "artifactPath",
    "status",
    "responseBytes",
    "range",
    "contentRange",
}
_MIN_TOTAL_MEMORY_BYTES = 512 * 1024 * 1024
_MAX_TOTAL_MEMORY_BYTES = 16 * 1024**4


def _non_negative_integer(value: object, field: str) -> int:
    if type(value) is not int or value < 0:
        raise ScienceContractError(f"{field} must be a non-negative integer")
    return value


def _positive_integer(value: object, field: str) -> int:
    if type(value) is not int or value <= 0:
        raise ScienceContractError(f"{field} must be a positive integer")
    return value


def _finite_positive_number(value: object, field: str) -> float:
    if type(value) not in (int, float) or not np.isfinite(value) or value <= 0:
        raise ScienceContractError(f"{field} must be finite and positive")
    return float(value)


def _validate_profiles(value: object) -> tuple[Mapping[str, Any], int]:
    if not isinstance(value, dict) or set(value) != {"hardware", "browser", "network"}:
        raise ScienceContractError("Browser delivery trace lacks exact environment profiles")
    hardware = value["hardware"]
    browser = value["browser"]
    network = value["network"]
    if (
        not isinstance(hardware, dict)
        or set(hardware) != {"operatingSystem", "architecture", "cpu", "totalMemoryBytes"}
        or not isinstance(hardware.get("operatingSystem"), str)
        or re.fullmatch(r"(?:darwin|linux) \S+", hardware["operatingSystem"]) is None
        or hardware.get("architecture") not in {"arm64", "x64"}
        or not isinstance(hardware.get("cpu"), str)
        or not hardware["cpu"].strip()
        or hardware["cpu"] == "unknown"
    ):
        raise ScienceContractError("Browser delivery trace has an invalid hardware profile")
    total_memory = _positive_integer(
        hardware.get("totalMemoryBytes"), "Hardware total-memory byte count"
    )
    if not _MIN_TOTAL_MEMORY_BYTES <= total_memory <= _MAX_TOTAL_MEMORY_BYTES:
        raise ScienceContractError("Hardware total-memory byte count is not realistic")
    if (
        not isinstance(browser, dict)
        or set(browser) != {"engine", "version"}
        or browser.get("engine") != "Chromium"
        or not isinstance(browser.get("version"), str)
        or re.fullmatch(r"\d+(?:\.\d+){1,3}", browser["version"]) is None
    ):
        raise ScienceContractError("Browser delivery trace has an invalid browser profile")
    if (
        not isinstance(network, dict)
        or set(network) != {"transport", "cacheControl", "origin"}
        or network.get("transport") != "loopback-http-1.1"
        or network.get("cacheControl") != "immutable"
        or not isinstance(network.get("origin"), str)
    ):
        raise ScienceContractError("Browser delivery trace has an invalid network profile")
    try:
        origin = urlsplit(network["origin"])
        port = origin.port
    except ValueError as exc:
        raise ScienceContractError("Browser delivery origin is not valid") from exc
    if (
        origin.scheme != "http"
        or origin.hostname != "127.0.0.1"
        or port is None
        or not 1 <= port <= 65535
        or origin.username is not None
        or origin.password is not None
        or origin.path
        or origin.query
        or origin.fragment
    ):
        raise ScienceContractError("Browser delivery origin is not loopback HTTP")
    return value, total_memory


def create_delivery_report(
    candidate: Path,
    trace_path: Path,
    harness_path: Path,
    build_timing_path: Path,
    *,
    contract: Mapping[str, Any],
) -> Mapping[str, Any]:
    """Recompute metrics only from the pinned executable browser trace."""
    specification = contract["deliveryMeasurement"]
    if (
        harness_path.name != Path(specification["harnessPath"]).name
        or sha256(harness_path) != specification["harnessSha256"]
    ):
        raise ScienceContractError("Browser delivery harness differs from the contract")
    trace = load_json(trace_path)
    binding = candidate_binding(candidate, contract=contract)
    manifest = load_json(candidate / "manifest.json")
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list):
        raise ScienceContractError("Release manifest has no delivery artifact inventory")
    try:
        artifact_byte_sizes = {
            item["path"]: _positive_integer(
                item.get("byteSize"), f"Release artifact byte size: {item['path']}"
            )
            for item in artifacts
            if isinstance(item, dict)
        }
    except (KeyError, TypeError) as exc:
        raise ScienceContractError("Release manifest has invalid delivery artifact sizes") from exc
    if len(artifact_byte_sizes) != len(artifacts):
        raise ScienceContractError("Release manifest has invalid delivery artifact sizes")
    build_timing = load_json(build_timing_path)
    if (
        build_timing.get("candidate") != binding
        or build_timing.get("timer") != "python-time-perf-counter"
        or build_timing.get("startedBeforeSourceVerification") is not True
        or build_timing.get("endedAfterAtomicCandidatePublish") is not True
    ):
        raise ScienceContractError("Full clean build timing is detached or incomplete")
    expected_trace_binding = {
        "releaseId": binding["releaseId"],
        "manifestSha256": binding["manifestSha256"],
        "artifactHashes": binding["artifactHashes"],
        "artifactByteSizes": artifact_byte_sizes,
    }
    if (
        set(trace) != _TRACE_KEYS
        or type(trace.get("schemaVersion")) is not int
        or trace["schemaVersion"] != 1
        or trace.get("harness") != specification["harnessPath"]
        or trace.get("candidate") != expected_trace_binding
    ):
        raise ScienceContractError("Browser delivery trace is detached from the candidate")
    profiles, total_memory_bytes = _validate_profiles(trace.get("profiles"))
    if trace.get("toolchain") != {
        "playwrightVersion": specification["playwrightVersion"],
        "geotiffVersion": specification["geotiffVersion"],
        "packageLockSha256": specification["packageLockSha256"],
    }:
        raise ScienceContractError("Browser measurement toolchain differs from the contract")
    target = trace.get("target", {})
    lookup_evidence = load_json(candidate / "build-evidence.json")["lookupGoldenEvidence"]
    sealed_target = lookup_evidence["browserBenchmarkTarget"]
    if (
        type(sealed_target.get("sourceLocationId")) is not int
        or not isinstance(sealed_target.get("expectedValuesMillimetres"), list)
        or len(sealed_target["expectedValuesMillimetres"]) != 3
        or any(type(value) is not int for value in sealed_target["expectedValuesMillimetres"])
    ):
        raise ScienceContractError("Sealed browser target has invalid projection values")
    expected_cog_path = f"analysis/{sealed_target['scenario']}/{sealed_target['horizon']}.tif"
    expected_grid_path = "analysis/source-grid.json.gz"
    try:
        expected_cog_bytes = artifact_byte_sizes[expected_cog_path]
        expected_grid_bytes = artifact_byte_sizes[expected_grid_path]
    except KeyError as exc:
        raise ScienceContractError(
            "Browser target artifacts are absent from the sealed manifest"
        ) from exc
    try:
        with gzip.open(candidate / expected_grid_path, "rt", encoding="utf-8") as stream:
            source_grid = json.load(stream)
        location_ids = source_grid["locationIds"]
        matching_indexes = [
            index
            for index, location_id in enumerate(location_ids)
            if location_id == sealed_target["sourceLocationId"]
        ]
        if len(matching_indexes) != 1:
            raise ValueError("benchmark source ID is absent or duplicated")
        source_index = matching_indexes[0]
        source_row, source_column = divmod(source_index, source_grid["width"])
        cog_row = source_grid["height"] - 1 - source_row
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ScienceContractError(
            "Cannot derive the browser target from the sealed source-grid"
        ) from exc
    expected_target = {
        **sealed_target,
        "cogPath": expected_cog_path,
        "sourceGridPath": expected_grid_path,
        "sourceRow": source_row,
        "sourceColumn": source_column,
        "cogRow": cog_row,
        "goldenEvidenceSha256": lookup_evidence["sha256"],
    }
    if target != expected_target:
        raise ScienceContractError("Browser target is detached from independent goldens")
    cold = trace.get("coldLookupSamples", [])
    warm = trace.get("warmLookupSamples", [])
    if (
        not isinstance(cold, list)
        or not isinstance(warm, list)
        or len(cold) != specification["minimumColdLookups"]
        or len(warm) != specification["minimumWarmLookups"]
        or any(not isinstance(sample, dict) for sample in [*cold, *warm])
    ):
        raise ScienceContractError("Browser delivery trace has unexpected cold or warm samples")

    def validate_sample(
        sample: Mapping[str, Any], *, cold_sample: bool
    ) -> tuple[float, int, int, int]:
        requests = sample.get("requests")
        if not isinstance(requests, list) or any(
            not isinstance(item, dict) or set(item) != _REQUEST_KEYS for item in requests
        ):
            raise ScienceContractError("Browser delivery sample lacks observed HTTP requests")
        expected_request_paths = {
            "cog": ("/projection.tif", expected_cog_path),
            "source-grid": ("/source-grid.json.gz", expected_grid_path),
        }
        if any(
            item.get("kind") not in expected_request_paths
            or (item.get("path"), item.get("artifactPath")) != expected_request_paths[item["kind"]]
            for item in requests
        ):
            raise ScienceContractError(
                "Browser request trace is detached from the exact COG or source-grid"
            )
        range_requests = [item for item in requests if item.get("kind") == "cog"]
        grid_requests = [item for item in requests if item.get("kind") == "source-grid"]
        if (cold_sample and (len(grid_requests) != 1 or not range_requests)) or (
            not cold_sample and requests
        ):
            raise ScienceContractError(
                "Browser lookup requests differ from the cold/warm cache contract"
            )
        if cold_sample:
            grid_request = grid_requests[0]
            if (
                type(grid_request.get("status")) is not int
                or grid_request["status"] != 200
                or grid_request.get("range") is not None
                or grid_request.get("contentRange") is not None
                or grid_request.get("responseBytes") != expected_grid_bytes
            ):
                raise ScienceContractError(
                    "Source-grid response differs from its sealed artifact bytes"
                )
        for item in range_requests:
            range_value = item.get("range")
            match = (
                re.fullmatch(r"bytes=(\d+)-(\d*)", range_value)
                if isinstance(range_value, str)
                else None
            )
            if type(item.get("status")) is not int or item.get("status") != 206 or match is None:
                raise ScienceContractError("COG lookup did not use successful HTTP Range responses")
            start = int(match.group(1))
            requested_end = int(match.group(2)) if match.group(2) else expected_cog_bytes - 1
            if start >= expected_cog_bytes or requested_end < start:
                raise ScienceContractError("COG request Range is outside the sealed artifact")
            response_end = min(requested_end, expected_cog_bytes - 1)
            expected_content_range = f"bytes {start}-{response_end}/{expected_cog_bytes}"
            expected_response_bytes = response_end - start + 1
            if (
                item.get("contentRange") != expected_content_range
                or item.get("responseBytes") != expected_response_bytes
            ):
                raise ScienceContractError(
                    "COG Content-Range differs from its sealed artifact bytes"
                )
        observed_count = len(range_requests)
        response_bytes = [
            _positive_integer(item.get("responseBytes"), "Browser response byte count")
            for item in requests
        ]
        observed_bytes = sum(response_bytes)
        declared_count = _non_negative_integer(
            sample.get("rangeRequestCount"), "Browser Range request count"
        )
        declared_bytes = _non_negative_integer(
            sample.get("transferBytes"), "Browser transfer byte count"
        )
        if (
            observed_count != declared_count
            or observed_bytes != declared_bytes
            or (cold_sample and observed_count == 0)
        ):
            raise ScienceContractError("Browser delivery sample aggregates differ from its trace")
        before = _positive_integer(sample.get("heapBeforeBytes"), "Browser heap-before byte count")
        after = _positive_integer(sample.get("heapAfterBytes"), "Browser heap-after byte count")
        peak = _positive_integer(sample.get("peakHeapBytes"), "Browser peak-heap byte count")
        duration = _finite_positive_number(
            sample.get("durationMilliseconds"), "Browser lookup duration"
        )
        if peak < before or max(before, after, peak) > total_memory_bytes:
            raise ScienceContractError(
                "Browser delivery sample contains invalid timing or heap data"
            )
        values = sample.get("valuesMillimetres")
        if (
            not isinstance(values, list)
            or len(values) != 3
            or any(type(value) is not int for value in values)
            or values != target.get("expectedValuesMillimetres")
            or type(sample.get("locationId")) is not int
            or sample.get("locationId") != target.get("sourceLocationId")
        ):
            raise ScienceContractError("Browser lookup did not return an ID and three quantiles")
        return duration, observed_count, observed_bytes, max(peak, after) - before

    cold_metrics = [validate_sample(sample, cold_sample=True) for sample in cold]
    warm_metrics = [validate_sample(sample, cold_sample=False) for sample in warm]
    budgets = contract["budgets"]
    full_duration = _finite_positive_number(
        build_timing.get("fullCleanBuildDurationSeconds"),
        "Full clean build duration",
    )
    metrics = {
        "fullCleanBuildDurationSeconds": full_duration,
        "browserHeapBytes": max(item[3] for item in [*cold_metrics, *warm_metrics]),
        "rangeRequestCount": max(item[1] for item in cold_metrics),
        "coldTransferBytes": max(item[2] for item in cold_metrics),
        "lookupP95Milliseconds": round(
            float(np.percentile([item[0] for item in warm_metrics], 95)), 6
        ),
    }
    if metrics["browserHeapBytes"] <= 0:
        raise ScienceContractError("Browser delivery trace records no measurable heap growth")
    passed = (
        metrics["fullCleanBuildDurationSeconds"] <= budgets["buildDurationSeconds"]
        and metrics["browserHeapBytes"] <= budgets["browserHeapBytes"]
        and metrics["rangeRequestCount"] <= budgets["rangeRequestCount"]
        and metrics["coldTransferBytes"] <= budgets["coldTransferBytes"]
        and metrics["lookupP95Milliseconds"] <= budgets["lookupP95Milliseconds"]
    )
    return {
        "schemaVersion": 1,
        "status": "passed" if passed else "failed",
        "candidate": binding,
        "trace": {"path": trace_path.name, "sha256": sha256(trace_path)},
        "buildTiming": {
            "path": build_timing_path.name,
            "sha256": sha256(build_timing_path),
        },
        "harness": {
            "path": specification["harnessPath"],
            "sha256": specification["harnessSha256"],
        },
        "profiles": profiles,
        "coldLookupSampleCount": len(cold),
        "warmLookupSampleCount": len(warm),
        **metrics,
    }
