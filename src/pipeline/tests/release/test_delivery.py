"""Mutation tests for observed browser-delivery evidence."""

from __future__ import annotations

import copy
import gzip
import hashlib
import json
from pathlib import Path

import pytest

import searise_pipeline.release.delivery as delivery
from searise_pipeline.release import evaluate_recovery_gate
from searise_pipeline.science import ScienceContractError

from .test_evidence import _candidate, _seal
from .test_source_fixture import contract

COG_PATH = "analysis/ssp2-45/2050.tif"
GRID_PATH = "analysis/source-grid.json.gz"
COG_BYTES = 1000
BINDING = {
    "releaseId": "candidate-v1",
    "releaseContractId": "ar6-europe-regional-release-v1",
    "manifestSha256": "a" * 64,
    "buildReceiptSha256": "b" * 64,
    "buildEvidenceSha256": "c" * 64,
    "sourceReceiptSha256": "d" * 64,
    "artifactHashes": {COG_PATH: "e" * 64, GRID_PATH: "f" * 64},
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


def _sample(*, cold: bool, grid_bytes: int) -> dict[str, object]:
    requests = (
        [
            {
                "kind": "cog",
                "path": "/projection.tif",
                "artifactPath": COG_PATH,
                "status": 206,
                "responseBytes": 100,
                "range": "bytes=0-99",
                "contentRange": f"bytes 0-99/{COG_BYTES}",
            },
            {
                "kind": "source-grid",
                "path": "/source-grid.json.gz",
                "artifactPath": GRID_PATH,
                "status": 200,
                "responseBytes": grid_bytes,
                "range": None,
                "contentRange": None,
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
        "transferBytes": 100 + grid_bytes if cold else 0,
        "requests": requests,
    }


def _inputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    mock_binding: bool = True,
):
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
    grid_bytes = source_grid_path.stat().st_size
    artifact_byte_sizes = {COG_PATH: COG_BYTES, GRID_PATH: grid_bytes}
    _write(
        candidate / "manifest.json",
        {
            "artifacts": [
                {"path": path, "byteSize": byte_size}
                for path, byte_size in artifact_byte_sizes.items()
            ]
        },
    )
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
            "artifactByteSizes": artifact_byte_sizes,
        },
        "profiles": {
            "hardware": {
                "operatingSystem": "linux 6.8.0",
                "architecture": "x64",
                "cpu": "test cpu",
                "totalMemoryBytes": 8 * 1024**3,
            },
            "browser": {"engine": "Chromium", "version": "151.0.7922.34"},
            "network": {
                "transport": "loopback-http-1.1",
                "cacheControl": "immutable",
                "origin": "http://127.0.0.1:43117",
            },
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
        "coldLookupSamples": [_sample(cold=True, grid_bytes=grid_bytes) for _ in range(10)],
        "warmLookupSamples": [_sample(cold=False, grid_bytes=grid_bytes) for _ in range(100)],
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
    if mock_binding:
        monkeypatch.setattr(
            delivery,
            "candidate_binding",
            lambda _, *, contract: BINDING,
        )
    return release, candidate, trace, trace_path, timing_path, harness


def test_observed_browser_trace_passes_declared_budgets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    release, candidate, trace, trace_path, timing_path, harness = _inputs(tmp_path, monkeypatch)

    report = delivery.create_delivery_report(
        candidate, trace_path, harness, timing_path, contract=release
    )

    assert report["status"] == "passed"
    assert report["rangeRequestCount"] == 1
    assert report["coldTransferBytes"] == trace["coldLookupSamples"][0]["transferBytes"]
    assert report["browserHeapBytes"] == 300


def test_delivery_report_uses_real_contract_aware_candidate_binding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    release, fixture, trace, trace_path, timing_path, harness = _inputs(
        tmp_path,
        monkeypatch,
        mock_binding=False,
    )
    candidate = tmp_path / "real-candidate"
    _candidate(candidate)
    manifest_path = candidate / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    replacements = [
        (manifest["artifacts"][0], COG_PATH),
        (manifest["artifacts"][1], GRID_PATH),
    ]
    for record, relative in replacements:
        previous = candidate / record["path"]
        replacement = candidate / relative
        replacement.parent.mkdir(parents=True, exist_ok=True)
        previous.replace(replacement)
        record["path"] = relative
    (candidate / GRID_PATH).write_bytes((fixture / GRID_PATH).read_bytes())
    for record, relative in replacements:
        artifact = candidate / relative
        record["byteSize"] = artifact.stat().st_size
        record["sha256"] = hashlib.sha256(artifact.read_bytes()).hexdigest()
    _write(manifest_path, manifest)
    _write(
        candidate / "build-evidence.json",
        {
            "lookupGoldenEvidence": {
                "sha256": "1" * 64,
                "browserBenchmarkTarget": TARGET,
            }
        },
    )
    _seal(candidate)

    binding = delivery.candidate_binding(candidate, contract=release)
    artifact_byte_sizes = {item["path"]: item["byteSize"] for item in manifest["artifacts"]}
    trace["candidate"] = {
        "releaseId": binding["releaseId"],
        "manifestSha256": binding["manifestSha256"],
        "artifactHashes": binding["artifactHashes"],
        "artifactByteSizes": artifact_byte_sizes,
    }
    cog_bytes = artifact_byte_sizes[COG_PATH]
    grid_bytes = artifact_byte_sizes[GRID_PATH]
    for sample in trace["coldLookupSamples"]:
        cog_request = next(item for item in sample["requests"] if item["kind"] == "cog")
        cog_request["range"] = f"bytes=0-{cog_bytes - 1}"
        cog_request["contentRange"] = f"bytes 0-{cog_bytes - 1}/{cog_bytes}"
        cog_request["responseBytes"] = cog_bytes
        grid_request = next(item for item in sample["requests"] if item["kind"] == "source-grid")
        grid_request["responseBytes"] = grid_bytes
        sample["transferBytes"] = cog_bytes + grid_bytes
    _write(trace_path, trace)
    timing = json.loads(timing_path.read_text(encoding="utf-8"))
    timing["candidate"] = binding
    _write(timing_path, timing)

    report = delivery.create_delivery_report(
        candidate,
        trace_path,
        harness,
        timing_path,
        contract=release,
    )
    gate = evaluate_recovery_gate(
        {"checks": {}},
        contract=release,
        reproducibility_report=None,
        delivery_report=report,
    )

    assert report["status"] == "passed"
    assert report["candidate"] == binding
    assert gate["checks"]["deliveryMeasurements"] is True


@pytest.mark.parametrize(
    "mutation",
    [
        "boolean-schema-version",
        "invalid-profiles",
        "public-origin",
        "browser-extra-field",
        "extra-warm-sample",
        "target",
        "wrong-cog",
        "request-path",
        "artifact-path",
        "candidate-manifest-hash",
        "candidate-artifact-hash",
        "candidate-artifact-size",
        "grid-byte-size",
        "cog-range",
        "cog-content-range",
        "cog-response-size",
        "negative-bytes",
        "nan-bytes",
        "boolean-bytes",
        "boolean-count",
        "negative-duration",
        "zero-duration",
        "nan-duration",
        "boolean-duration",
        "boolean-heap",
        "zero-heap",
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
    elif mutation == "public-origin":
        trace["profiles"]["network"]["origin"] = "https://measure.example.com"
    elif mutation == "browser-extra-field":
        trace["profiles"]["browser"]["channel"] = "stable"
    elif mutation == "extra-warm-sample":
        trace["warmLookupSamples"].append(copy.deepcopy(trace["warmLookupSamples"][0]))
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
        trace["candidate"]["artifactHashes"][COG_PATH] = "0" * 64
    elif mutation == "candidate-artifact-size":
        trace["candidate"]["artifactByteSizes"][COG_PATH] += 1
    elif mutation == "grid-byte-size":
        trace["coldLookupSamples"][0]["requests"][1]["responseBytes"] -= 1
    elif mutation == "cog-range":
        trace["coldLookupSamples"][0]["requests"][0]["range"] = "bytes=0-98"
    elif mutation == "cog-content-range":
        trace["coldLookupSamples"][0]["requests"][0]["contentRange"] = "bytes 0-99/999"
    elif mutation == "cog-response-size":
        trace["coldLookupSamples"][0]["requests"][0]["responseBytes"] = 99
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
    elif mutation == "zero-duration":
        trace["warmLookupSamples"][0]["durationMilliseconds"] = 0
    elif mutation == "nan-duration":
        trace["warmLookupSamples"][0]["durationMilliseconds"] = float("nan")
    elif mutation == "boolean-duration":
        trace["warmLookupSamples"][0]["durationMilliseconds"] = True
    elif mutation == "boolean-heap":
        trace["warmLookupSamples"][0]["heapAfterBytes"] = True
    elif mutation == "zero-heap":
        trace["warmLookupSamples"][0]["heapBeforeBytes"] = 0
    elif mutation == "boolean-location-id":
        trace["warmLookupSamples"][0]["locationId"] = True
    else:
        trace["warmLookupSamples"][0]["valuesMillimetres"][0] = True
    _write(trace_path, trace)

    with pytest.raises(ScienceContractError):
        delivery.create_delivery_report(
            candidate, trace_path, harness, timing_path, contract=release
        )


def test_forged_public_zero_cost_trace_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    release, candidate, trace, trace_path, timing_path, harness = _inputs(tmp_path, monkeypatch)
    trace["profiles"]["hardware"] = {
        "operatingSystem": "public browser farm",
        "architecture": "x64",
        "cpu": "forged",
        "totalMemoryBytes": 1,
    }
    trace["profiles"]["network"]["origin"] = "https://measure.example.com"
    for sample in [*trace["coldLookupSamples"], *trace["warmLookupSamples"]]:
        sample["durationMilliseconds"] = 0
        sample["heapBeforeBytes"] = 0
        sample["heapAfterBytes"] = 0
        sample["peakHeapBytes"] = 0
        sample["rangeRequestCount"] = 0
        sample["transferBytes"] = 0
        for request in sample["requests"]:
            request["responseBytes"] = 0
    _write(trace_path, trace)

    with pytest.raises(ScienceContractError):
        delivery.create_delivery_report(
            candidate, trace_path, harness, timing_path, contract=release
        )


@pytest.mark.parametrize("invalid_duration", [-1, 0, float("nan"), True])
def test_invalid_build_timing_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    invalid_duration: object,
) -> None:
    release, candidate, _, trace_path, timing_path, harness = _inputs(tmp_path, monkeypatch)
    timing = json.loads(timing_path.read_text(encoding="utf-8"))
    timing["fullCleanBuildDurationSeconds"] = invalid_duration
    _write(timing_path, timing)

    with pytest.raises(ScienceContractError, match="finite and positive"):
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
