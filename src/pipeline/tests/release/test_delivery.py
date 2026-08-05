"""Mutation tests for observed browser-delivery evidence."""

from __future__ import annotations

import copy
import gzip
import hashlib
import json
from pathlib import Path

import pytest

import searise_pipeline.release.delivery as delivery
from searise_pipeline.science import ScienceContractError

from .test_source_fixture import contract

BINDING = {
    "releaseId": "candidate-v1",
    "releaseContractId": "ar6-europe-regional-release-v1",
    "manifestSha256": "a" * 64,
    "buildReceiptSha256": "b" * 64,
    "buildEvidenceSha256": "c" * 64,
    "sourceReceiptSha256": "d" * 64,
    "artifactHashes": {"analysis/value.tif": "e" * 64},
    "candidateFileHashes": {"manifest.json": "a" * 64},
    "sourceRevision": "f" * 40,
    "environmentIdentity": {"buildRunId": "test"},
}
TARGET = {
    "scenario": "ssp2-45",
    "horizon": 2050,
    "sourceLocationId": 123,
    "expectedValuesMillimetres": [100, 120, 140],
}


def _write(path: Path, document: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document) + "\n", encoding="utf-8")


def _sample(*, cold: bool) -> dict[str, object]:
    requests = (
        [
            {
                "kind": "cog",
                "path": "/projection.tif",
                "artifactPath": "analysis/ssp2-45/2050.tif",
                "status": 206,
                "responseBytes": 100,
                "range": "bytes=0-99",
            },
            {
                "kind": "source-grid",
                "path": "/source-grid.json.gz",
                "artifactPath": "analysis/source-grid.json.gz",
                "status": 200,
                "responseBytes": 50,
                "range": None,
            },
        ]
        if cold
        else []
    )
    return {
        "durationMilliseconds": 2,
        "heapBeforeBytes": 1000,
        "heapAfterBytes": 1200,
        "peakHeapBytes": 1300,
        "locationId": TARGET["sourceLocationId"],
        "valuesMillimetres": copy.deepcopy(TARGET["expectedValuesMillimetres"]),
        "rangeRequestCount": 1 if cold else 0,
        "transferBytes": 150 if cold else 0,
        "requests": requests,
    }


def _inputs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    release = copy.deepcopy(contract())
    harness = tmp_path / "measure-ar6-release.mjs"
    harness.write_text("// measured browser harness\n", encoding="utf-8")
    release["deliveryMeasurement"]["harnessSha256"] = hashlib.sha256(
        harness.read_bytes()
    ).hexdigest()
    candidate = tmp_path / "candidate"
    source_ids = [-1] * (76 * 46)
    source_ids[5 * 76 + 7] = TARGET["sourceLocationId"]
    source_grid_path = candidate / "analysis/source-grid.json.gz"
    source_grid_path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(source_grid_path, "wt", encoding="utf-8") as stream:
        json.dump({"width": 76, "height": 46, "locationIds": source_ids}, stream)
    _write(
        candidate / "build-evidence.json",
        {"lookupGoldenEvidence": {"sha256": "1" * 64, "browserBenchmarkTarget": TARGET}},
    )
    trace = {
        "schemaVersion": 1,
        "harness": release["deliveryMeasurement"]["harnessPath"],
        "candidate": {
            "releaseId": BINDING["releaseId"],
            "manifestSha256": BINDING["manifestSha256"],
            "artifactHashes": copy.deepcopy(BINDING["artifactHashes"]),
        },
        "profiles": {
            "hardware": {"cpu": "test"},
            "browser": {"engine": "Chromium", "version": "test"},
            "network": {"transport": "loopback"},
        },
        "toolchain": {
            "playwrightVersion": release["deliveryMeasurement"]["playwrightVersion"],
            "geotiffVersion": release["deliveryMeasurement"]["geotiffVersion"],
            "packageLockSha256": release["deliveryMeasurement"]["packageLockSha256"],
        },
        "target": {
            **TARGET,
            "cogPath": "analysis/ssp2-45/2050.tif",
            "sourceGridPath": "analysis/source-grid.json.gz",
            "sourceRow": 5,
            "sourceColumn": 7,
            "cogRow": 40,
            "goldenEvidenceSha256": "1" * 64,
        },
        "coldLookupSamples": [_sample(cold=True) for _ in range(10)],
        "warmLookupSamples": [_sample(cold=False) for _ in range(100)],
    }
    trace_path = tmp_path / "trace.json"
    timing_path = tmp_path / "timing.json"
    _write(trace_path, trace)
    _write(
        timing_path,
        {
            "candidate": BINDING,
            "timer": "python-time-perf-counter",
            "startedBeforeSourceVerification": True,
            "endedAfterAtomicCandidatePublish": True,
            "fullCleanBuildDurationSeconds": 10,
        },
    )
    monkeypatch.setattr(delivery, "candidate_binding", lambda _: BINDING)
    return release, candidate, trace, trace_path, timing_path, harness


def test_observed_browser_trace_passes_declared_budgets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    release, candidate, _, trace_path, timing_path, harness = _inputs(tmp_path, monkeypatch)

    report = delivery.create_delivery_report(
        candidate, trace_path, harness, timing_path, contract=release
    )

    assert report["status"] == "passed"
    assert report["rangeRequestCount"] == 1
    assert report["coldTransferBytes"] == 150
    assert report["browserHeapBytes"] == 300


@pytest.mark.parametrize(
    "mutation",
    [
        "boolean-schema-version",
        "invalid-profiles",
        "extra-warm-sample",
        "target",
        "wrong-cog",
        "request-path",
        "artifact-path",
        "candidate-manifest-hash",
        "candidate-artifact-hash",
        "negative-bytes",
        "nan-bytes",
        "boolean-bytes",
        "boolean-count",
        "negative-duration",
        "nan-duration",
        "boolean-duration",
        "boolean-heap",
        "boolean-location-id",
        "boolean-quantile",
    ],
)
def test_delivery_trace_tamper_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation: str
) -> None:
    release, candidate, trace, trace_path, timing_path, harness = _inputs(tmp_path, monkeypatch)
    if mutation == "boolean-schema-version":
        trace["schemaVersion"] = True
    elif mutation == "invalid-profiles":
        trace["profiles"] = []
    elif mutation == "extra-warm-sample":
        trace["warmLookupSamples"].append(_sample(cold=False))
    elif mutation == "target":
        trace["target"]["expectedValuesMillimetres"] = [1, 2, 3]
    elif mutation == "wrong-cog":
        trace["target"]["cogPath"] = "analysis/ssp5-85/2100.tif"
    elif mutation == "request-path":
        trace["coldLookupSamples"][0]["requests"][0]["path"] = "/layers/ssp2-45/2050.pmtiles"
    elif mutation == "artifact-path":
        trace["coldLookupSamples"][0]["requests"][0]["artifactPath"] = "analysis/ssp5-85/2050.tif"
    elif mutation == "candidate-manifest-hash":
        trace["candidate"]["manifestSha256"] = "0" * 64
    elif mutation == "candidate-artifact-hash":
        trace["candidate"]["artifactHashes"]["analysis/value.tif"] = "0" * 64
    elif mutation == "negative-bytes":
        trace["coldLookupSamples"][0]["requests"][0]["responseBytes"] = -1
    elif mutation == "nan-bytes":
        trace["coldLookupSamples"][0]["requests"][0]["responseBytes"] = float("nan")
    elif mutation == "boolean-bytes":
        trace["coldLookupSamples"][0]["requests"][0]["responseBytes"] = True
    elif mutation == "boolean-count":
        trace["coldLookupSamples"][0]["rangeRequestCount"] = True
    elif mutation == "negative-duration":
        trace["warmLookupSamples"][0]["durationMilliseconds"] = -1
    elif mutation == "nan-duration":
        trace["warmLookupSamples"][0]["durationMilliseconds"] = float("nan")
    elif mutation == "boolean-duration":
        trace["warmLookupSamples"][0]["durationMilliseconds"] = True
    elif mutation == "boolean-heap":
        trace["warmLookupSamples"][0]["heapAfterBytes"] = True
    elif mutation == "boolean-location-id":
        trace["warmLookupSamples"][0]["locationId"] = True
    else:
        trace["warmLookupSamples"][0]["valuesMillimetres"][0] = True
    _write(trace_path, trace)

    with pytest.raises(ScienceContractError):
        delivery.create_delivery_report(
            candidate, trace_path, harness, timing_path, contract=release
        )


@pytest.mark.parametrize("invalid_duration", [-1, float("nan"), True])
def test_invalid_build_timing_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    invalid_duration: object,
) -> None:
    release, candidate, _, trace_path, timing_path, harness = _inputs(tmp_path, monkeypatch)
    timing = json.loads(timing_path.read_text(encoding="utf-8"))
    timing["fullCleanBuildDurationSeconds"] = invalid_duration
    _write(timing_path, timing)

    with pytest.raises(ScienceContractError, match="finite and non-negative"):
        delivery.create_delivery_report(
            candidate, trace_path, harness, timing_path, contract=release
        )


def test_build_timing_candidate_hash_tamper_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    release, candidate, _, trace_path, timing_path, harness = _inputs(tmp_path, monkeypatch)
    timing = json.loads(timing_path.read_text(encoding="utf-8"))
    timing["candidate"]["manifestSha256"] = "0" * 64
    _write(timing_path, timing)

    with pytest.raises(ScienceContractError, match="detached or incomplete"):
        delivery.create_delivery_report(
            candidate, trace_path, harness, timing_path, contract=release
        )
