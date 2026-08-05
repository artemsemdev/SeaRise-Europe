"""Validate observed Chromium delivery traces and bind them to a candidate."""

from __future__ import annotations

import gzip
import json
import re
from pathlib import Path
from typing import Any, Mapping

import numpy as np

from searise_pipeline.science.contracts import ScienceContractError

from .evidence import candidate_binding, load_json, sha256


def _non_negative_integer(value: object, field: str) -> int:
    if type(value) is not int or value < 0:
        raise ScienceContractError(f"{field} must be a non-negative integer")
    return value


def _finite_non_negative_number(value: object, field: str) -> float:
    if type(value) not in (int, float) or not np.isfinite(value) or value < 0:
        raise ScienceContractError(f"{field} must be finite and non-negative")
    return float(value)


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
    binding = candidate_binding(candidate)
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
    }
    if (
        type(trace.get("schemaVersion")) is not int
        or trace["schemaVersion"] != 1
        or trace.get("harness") != specification["harnessPath"]
        or trace.get("candidate") != expected_trace_binding
    ):
        raise ScienceContractError("Browser delivery trace is detached from the candidate")
    profiles = trace.get("profiles", {})
    hardware_profile = profiles.get("hardware", {}) if isinstance(profiles, dict) else {}
    network_profile = profiles.get("network", {}) if isinstance(profiles, dict) else {}
    browser_profile = profiles.get("browser", {}) if isinstance(profiles, dict) else {}
    if (
        not isinstance(hardware_profile, dict)
        or not hardware_profile
        or not isinstance(network_profile, dict)
        or not network_profile
        or not isinstance(browser_profile, dict)
        or browser_profile.get("engine") != "Chromium"
        or not isinstance(browser_profile.get("version"), str)
        or not browser_profile["version"]
    ):
        raise ScienceContractError("Browser delivery trace lacks exact environment profiles")
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
        if not isinstance(requests, list) or any(not isinstance(item, dict) for item in requests):
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
        if any(
            type(item.get("status")) is not int
            or item["status"] != 206
            or not isinstance(item.get("range"), str)
            or re.fullmatch(r"bytes=\d+-\d*", item["range"]) is None
            for item in range_requests
        ):
            raise ScienceContractError("COG lookup did not use successful HTTP Range responses")
        if (
            cold_sample
            and (
                len(grid_requests) != 1
                or type(grid_requests[0].get("status")) is not int
                or grid_requests[0]["status"] != 200
                or grid_requests[0].get("range") is not None
            )
        ) or (not cold_sample and requests):
            raise ScienceContractError(
                "Browser lookup requests differ from the cold/warm cache contract"
            )
        observed_count = len(range_requests)
        response_bytes = [
            _non_negative_integer(item.get("responseBytes"), "Browser response byte count")
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
        before = _non_negative_integer(
            sample.get("heapBeforeBytes"), "Browser heap-before byte count"
        )
        after = _non_negative_integer(sample.get("heapAfterBytes"), "Browser heap-after byte count")
        peak = _non_negative_integer(sample.get("peakHeapBytes"), "Browser peak-heap byte count")
        duration = _finite_non_negative_number(
            sample.get("durationMilliseconds"), "Browser lookup duration"
        )
        if peak < before:
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
        return duration, observed_count, observed_bytes, max(0, max(peak, after) - before)

    cold_metrics = [validate_sample(sample, cold_sample=True) for sample in cold]
    warm_metrics = [validate_sample(sample, cold_sample=False) for sample in warm]
    budgets = contract["budgets"]
    full_duration = _finite_non_negative_number(
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
