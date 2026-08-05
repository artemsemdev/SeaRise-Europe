"""Validate observed Chromium delivery traces and bind them to a candidate."""

from __future__ import annotations

import gzip
import json
from pathlib import Path
from typing import Any, Mapping

import numpy as np

from searise_pipeline.science.contracts import ScienceContractError

from .evidence import candidate_binding, load_json, sha256


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
        trace.get("schemaVersion") != 1
        or trace.get("harness") != specification["harnessPath"]
        or trace.get("candidate") != expected_trace_binding
    ):
        raise ScienceContractError("Browser delivery trace is detached from the candidate")
    profiles = trace.get("profiles", {})
    if (
        not profiles.get("hardware")
        or not profiles.get("network")
        or profiles.get("browser", {}).get("engine") != "Chromium"
        or not profiles.get("browser", {}).get("version")
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
    expected_cog_path = (
        f"analysis/{sealed_target['scenario']}/{sealed_target['horizon']}.tif"
    )
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
        len(cold) < specification["minimumColdLookups"]
        or len(warm) < specification["minimumWarmLookups"]
    ):
        raise ScienceContractError("Browser delivery trace has too few cold or warm samples")

    def validate_sample(
        sample: Mapping[str, Any], *, cold_sample: bool
    ) -> tuple[float, int, int, int]:
        requests = sample.get("requests")
        if not isinstance(requests, list):
            raise ScienceContractError("Browser delivery sample lacks observed HTTP requests")
        expected_request_paths = {
            "cog": ("/projection.tif", expected_cog_path),
            "source-grid": ("/source-grid.json.gz", expected_grid_path),
        }
        if any(
            item.get("kind") not in expected_request_paths
            or (
                item.get("path"), item.get("artifactPath")
            ) != expected_request_paths[item["kind"]]
            for item in requests
        ):
            raise ScienceContractError(
                "Browser request trace is detached from the exact COG or source-grid"
            )
        range_requests = [item for item in requests if item.get("kind") == "cog"]
        grid_requests = [
            item for item in requests if item.get("kind") == "source-grid"
        ]
        if any(item.get("status") != 206 or not item.get("range") for item in range_requests):
            raise ScienceContractError("COG lookup did not use successful HTTP Range responses")
        if (
            cold_sample
            and (
                len(grid_requests) != 1
                or grid_requests[0].get("status") != 200
                or grid_requests[0].get("range") is not None
            )
        ) or (not cold_sample and requests):
            raise ScienceContractError(
                "Browser lookup requests differ from the cold/warm cache contract"
            )
        observed_count = len(range_requests)
        response_bytes = [int(item["responseBytes"]) for item in requests]
        if any(value < 0 for value in response_bytes):
            raise ScienceContractError("Browser delivery trace contains negative byte counts")
        observed_bytes = sum(response_bytes)
        if (
            observed_count != sample.get("rangeRequestCount")
            or observed_bytes != sample.get("transferBytes")
            or (cold_sample and observed_count == 0)
        ):
            raise ScienceContractError("Browser delivery sample aggregates differ from its trace")
        before = int(sample.get("heapBeforeBytes", -1))
        after = int(sample.get("heapAfterBytes", -1))
        peak = int(sample.get("peakHeapBytes", -1))
        duration = float(sample.get("durationMilliseconds", float("nan")))
        if (
            before < 0
            or after < 0
            or peak < max(before, after)
            or not np.isfinite(duration)
            or duration < 0
        ):
            raise ScienceContractError(
                "Browser delivery sample contains invalid timing or heap data"
            )
        values = sample.get("valuesMillimetres")
        if (
            values != target.get("expectedValuesMillimetres")
            or sample.get("locationId") != target.get("sourceLocationId")
        ):
            raise ScienceContractError("Browser lookup did not return an ID and three quantiles")
        return duration, observed_count, observed_bytes, max(0, peak - before)

    cold_metrics = [validate_sample(sample, cold_sample=True) for sample in cold]
    warm_metrics = [validate_sample(sample, cold_sample=False) for sample in warm]
    budgets = contract["budgets"]
    full_duration = float(build_timing.get("fullCleanBuildDurationSeconds", float("nan")))
    if not np.isfinite(full_duration) or full_duration < 0:
        raise ScienceContractError("Full clean build duration must be finite and non-negative")
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
