"""Test the non-authoritative Phase 0 recovery automation."""

from __future__ import annotations

import copy
import gzip
import hashlib
import io
import json
import subprocess
from pathlib import Path

import pytest

import searise_pipeline.release.promotion as promotion_module
from searise_pipeline.release import evaluate_recovery_gate, finalize_recovery_gate
from searise_pipeline.release.evidence import binding_sha256, candidate_binding
from searise_pipeline.science import ScienceContractError

from .test_evidence import _candidate, _environment_identity, _seal
from .test_source_fixture import contract

REPOSITORY_ROOT = Path(__file__).parents[4]
COG_PATH = "analysis/ssp2-45/2050.tif"
GRID_PATH = "analysis/source-grid.json.gz"
TARGET = {
    "scenario": "ssp2-45",
    "horizon": 2050,
    "sourceLocationId": 123,
    "expectedValuesMillimetres": [100, 120, 140],
}


BUILD_CHECKS = {
    "sourceArchiveAndMembersVerified": True,
    "sourceContentSeal": True,
    "completeScenarioHorizonMatrix": True,
    "nonAllNodataLayers": True,
    "cogStructureAndValues": True,
    "sourceGridIdentity": True,
    "geoparquetSchemaAndValues": True,
    "pmtilesStructureAndProperties": True,
    "crossArtifactSemanticParity": True,
    "lookupGoldenParity": True,
    "licenceAndAttribution": True,
    "artifactBudgets": True,
}
REPRODUCIBILITY = {
    "status": "passed",
    "independentEnvironmentCount": 2,
    "maximumScientificValueDifferenceMillimetres": 0,
    "validIdSetDifference": 0,
    "byteIdentityWithinPinnedToolchain": True,
}
DELIVERY = {
    "status": "passed",
    "fullCleanBuildDurationSeconds": 20,
    "browserHeapBytes": 8 * 1024 * 1024,
    "rangeRequestCount": 4,
    "coldTransferBytes": 128 * 1024,
    "lookupP95Milliseconds": 2,
}


def _evaluate(**overrides):
    arguments = {
        "contract": contract(),
        "reproducibility_report": REPRODUCIBILITY,
        "delivery_report": DELIVERY,
        **overrides,
    }
    return evaluate_recovery_gate(
        {"releaseId": "candidate-v1", "checks": BUILD_CHECKS},
        **arguments,
    )


def test_complete_automation_cannot_approve_or_unlock() -> None:
    gate = _evaluate()

    assert gate["automatedValidation"] == "passed"
    assert gate["releaseDisposition"] == "pending-owner"
    assert gate["phase1Unlocked"] is False
    assert gate["blockingChecks"] == []
    assert gate["fallback"] == "do-not-publish-or-unlock-phase-1"


@pytest.mark.parametrize(
    "authority_argument",
    [
        {"owner_decision": "approved"},
        {"final_integration_merged_to_master": True},
        {"phase1_unlocked": True},
    ],
)
def test_direct_callers_have_no_unlock_capable_arguments(authority_argument) -> None:
    with pytest.raises(TypeError, match="unexpected keyword argument"):
        _evaluate(**authority_argument)


def test_missing_external_evidence_stays_pending() -> None:
    gate = _evaluate(reproducibility_report=None, delivery_report=None)

    assert gate["automatedValidation"] == "pending"
    assert gate["releaseDisposition"] == "pending-owner"
    assert gate["phase1Unlocked"] is False
    assert gate["blockingChecks"] == [
        "crossEnvironmentReproducibility",
        "deliveryMeasurements",
    ]


def test_pending_external_provenance_is_not_misreported_as_failure() -> None:
    gate = _evaluate(
        reproducibility_report={
            **REPRODUCIBILITY,
            "status": "pending-external-provenance",
            "independentEnvironmentCount": 0,
        }
    )

    assert gate["automatedValidation"] == "pending"
    assert gate["blockingChecks"] == ["crossEnvironmentReproducibility"]


def test_present_failed_report_fails_even_when_other_report_is_missing() -> None:
    gate = _evaluate(
        reproducibility_report={**REPRODUCIBILITY, "status": "failed"},
        delivery_report=None,
    )

    assert gate["automatedValidation"] == "failed"
    assert gate["releaseDisposition"] == "pending-owner"
    assert gate["phase1Unlocked"] is False


def test_unverified_source_and_all_nodata_layer_fail_automation() -> None:
    checks = {
        **BUILD_CHECKS,
        "sourceArchiveAndMembersVerified": False,
        "nonAllNodataLayers": False,
    }
    gate = evaluate_recovery_gate(
        {"releaseId": "fixture-v1", "checks": checks},
        contract=contract(),
        reproducibility_report=REPRODUCIBILITY,
        delivery_report=DELIVERY,
    )

    assert gate["automatedValidation"] == "failed"
    assert gate["blockingChecks"][:2] == [
        "sourceArchiveAndMembersVerified",
        "nonAllNodataLayers",
    ]
    assert gate["releaseDisposition"] == "pending-owner"
    assert gate["phase1Unlocked"] is False


@pytest.mark.parametrize(
    ("report_name", "field", "invalid_value"),
    [
        ("delivery", "browserHeapBytes", True),
        ("delivery", "lookupP95Milliseconds", float("nan")),
        ("delivery", "fullCleanBuildDurationSeconds", -1),
        ("reproducibility", "independentEnvironmentCount", True),
        ("reproducibility", "validIdSetDifference", 0.0),
    ],
)
def test_automation_rejects_coerced_or_invalid_metrics(
    report_name: str,
    field: str,
    invalid_value: object,
) -> None:
    reports = {
        "delivery_report": DELIVERY,
        "reproducibility_report": REPRODUCIBILITY,
    }
    key = f"{report_name}_report"
    reports[key] = {**reports[key], field: invalid_value}

    gate = _evaluate(**reports)

    assert gate["automatedValidation"] == "failed"
    assert gate["releaseDisposition"] == "pending-owner"
    assert gate["phase1Unlocked"] is False


def test_delivery_transfer_budget_is_required() -> None:
    release = contract()
    over_budget = {
        **DELIVERY,
        "coldTransferBytes": release["budgets"]["coldTransferBytes"] + 1,
    }

    gate = evaluate_recovery_gate(
        {"releaseId": "candidate-v1", "checks": BUILD_CHECKS},
        contract=release,
        reproducibility_report=REPRODUCIBILITY,
        delivery_report=over_budget,
    )

    assert gate["checks"]["deliveryMeasurements"] is False
    assert gate["blockingChecks"] == ["deliveryMeasurements"]


def _write_json(path: Path, document: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, sort_keys=True) + "\n", encoding="utf-8")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _source_revision() -> str:
    return subprocess.run(
        ["git", "-C", str(REPOSITORY_ROOT), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _environment(release: dict[str, object], platform: str) -> dict[str, object]:
    if platform == "macos-arm64-cp311":
        environment = _environment_identity(release)
        environment["buildRunId"] = "mac-build"
        return environment
    toolchain = release["toolchain"]
    python = toolchain["python"]
    tippecanoe = toolchain["tippecanoe"]
    pmtiles = toolchain["pmtiles"]
    python_pin = python["profiles"][platform]
    vector_platform = "linux-x86_64"
    reference = tippecanoe["referenceBuilds"][vector_platform]
    asset = pmtiles["assets"][vector_platform]
    return {
        "buildRunId": "linux-build",
        "python": {
            "platform": platform,
            "python_version": python_pin["pythonVersion"],
            "lock_path": python_pin["lockPath"],
            "lock_sha256": python_pin["lockSha256"],
            "packages": python["packageVersions"],
            "gdal_version": python_pin["gdal"],
            "rasterio_proj_version": python_pin["rasterioProj"],
            "pyproj_proj_version": python_pin["pyprojProj"],
        },
        "vector": {
            "tippecanoe_version": tippecanoe["version"],
            "tippecanoe_source_sha256": tippecanoe["sourceSha256"],
            "tippecanoe_binary_sha256": reference["tippecanoeBinarySha256"],
            "pmtiles_version": pmtiles["version"],
            "pmtiles_commit": pmtiles["commit"],
            "pmtiles_distribution_platform": vector_platform,
            "pmtiles_distribution_sha256": asset["sha256"],
            "decode_binary_sha256": reference["decodeBinarySha256"],
        },
    }


def _grid_bytes() -> bytes:
    location_ids = [-1] * (76 * 46)
    location_ids[5 * 76 + 7] = TARGET["sourceLocationId"]
    encoded = json.dumps(
        {"width": 76, "height": 46, "locationIds": location_ids},
        separators=(",", ":"),
    ).encode("utf-8")
    buffer = io.BytesIO()
    with gzip.GzipFile(fileobj=buffer, mode="wb", mtime=0) as stream:
        stream.write(encoded)
    return buffer.getvalue()


def _real_candidate(
    root: Path,
    *,
    release: dict[str, object],
    source_revision: str,
    platform: str,
) -> dict[str, object]:
    _candidate(root)
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    replacements = (
        (manifest["artifacts"][0], COG_PATH, b"sealed-cog-bytes\n"),
        (manifest["artifacts"][1], GRID_PATH, _grid_bytes()),
    )
    for record, relative, encoded in replacements:
        previous = root / record["path"]
        replacement = root / relative
        replacement.parent.mkdir(parents=True, exist_ok=True)
        previous.unlink()
        replacement.write_bytes(encoded)
        record.update(
            path=relative,
            byteSize=replacement.stat().st_size,
            sha256=_sha(replacement),
        )
    _write_json(manifest_path, manifest)
    receipt_path = root / "build-receipt.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["sourceRevision"] = source_revision
    receipt["environmentIdentity"] = _environment(release, platform)
    _write_json(receipt_path, receipt)
    contract_sha256 = hashlib.sha256(
        (
            json.dumps(release, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            + "\n"
        ).encode("utf-8")
    ).hexdigest()
    _write_json(root / "source-receipt.json", {"releaseContractSha256": contract_sha256})
    _write_json(
        root / "build-evidence.json",
        {
            "schemaVersion": 1,
            "releaseId": "candidate-v1",
            "checks": BUILD_CHECKS,
            "lookupGoldenEvidence": {
                "sha256": "1" * 64,
                "browserBenchmarkTarget": TARGET,
            },
            "totals": {
                "cogBytes": 1,
                "pmtilesBytes": 1,
                "geoparquetBytes": 1,
                "coreArtifactBytes": 3,
            },
        },
    )
    _seal(root)
    return candidate_binding(root, contract=release)


def _sample(*, cold: bool, cog_bytes: int, grid_bytes: int) -> dict[str, object]:
    requests = (
        [
            {
                "kind": "cog",
                "path": "/projection.tif",
                "artifactPath": COG_PATH,
                "status": 206,
                "responseBytes": cog_bytes,
                "range": f"bytes=0-{cog_bytes - 1}",
                "contentRange": f"bytes 0-{cog_bytes - 1}/{cog_bytes}",
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
        "transferBytes": cog_bytes + grid_bytes if cold else 0,
        "requests": requests,
    }


def _promotion_inputs(tmp_path: Path) -> dict[str, object]:
    release = contract()
    source_revision = _source_revision()
    candidate = tmp_path / "candidate"
    other_candidate = tmp_path / "candidate-linux"
    binding = _real_candidate(
        candidate,
        release=release,
        source_revision=source_revision,
        platform="macos-arm64-cp311",
    )
    other_binding = _real_candidate(
        other_candidate,
        release=release,
        source_revision=source_revision,
        platform="linux-x86_64-cp311",
    )
    profiles = sorted(
        [binding["validatedEnvironmentProfile"], other_binding["validatedEnvironmentProfile"]],
        key=lambda item: (
            item["pythonPlatform"],
            item["pythonLockSha256"],
            item["vectorPlatform"],
            item["tippecanoeBinarySha256"],
        ),
    )
    candidates = [binding, other_binding]
    reproducibility = {
        "schemaVersion": 1,
        "status": "pending-external-provenance",
        "localComparisonStatus": "passed",
        "externalProvenanceStatus": "required",
        "candidates": candidates,
        "environments": [item["environmentIdentity"] for item in candidates],
        "independentEnvironmentCount": 0,
        "receiptProfileCount": 2,
        "receiptProfiles": profiles,
        "requiredExternalBindings": [
            {
                "candidateBindingSha256": binding_sha256(item),
                "releaseId": item["releaseId"],
                "sourceRevision": item["sourceRevision"],
                "receiptBuildRunId": item["environmentIdentity"]["buildRunId"],
                "validatedEnvironmentProfile": item["validatedEnvironmentProfile"],
            }
            for item in candidates
        ],
        "externalProvenanceRequirement": {
            "provider": "github-actions",
            "candidateBindingRequired": True,
            "distinctTrustedRunCount": 2,
            "distinctValidatedProfileCount": 2,
            "receiptProfilesAreProof": False,
        },
        "maximumScientificValueDifferenceMillimetres": 0,
        "validIdSetDifference": 0,
        "byteIdentityWithinPinnedToolchain": True,
        "comparedArtifactCount": 31,
        "comparisonDurationSeconds": 1.25,
    }
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    reproducibility_path = evidence / "reproducibility.json"
    trace_path = evidence / "browser-trace.json"
    timing_path = evidence / "build-timing.json"
    harness_path = REPOSITORY_ROOT / release["deliveryMeasurement"]["harnessPath"]
    _write_json(reproducibility_path, reproducibility)
    manifest = json.loads((candidate / "manifest.json").read_text(encoding="utf-8"))
    artifact_byte_sizes = {
        item["path"]: item["byteSize"] for item in manifest["artifacts"]
    }
    cog_bytes = artifact_byte_sizes[COG_PATH]
    grid_bytes = artifact_byte_sizes[GRID_PATH]
    trace = {
        "schemaVersion": 1,
        "harness": release["deliveryMeasurement"]["harnessPath"],
        "candidate": {
            "releaseId": binding["releaseId"],
            "manifestSha256": binding["manifestSha256"],
            "artifactHashes": binding["artifactHashes"],
            "artifactByteSizes": artifact_byte_sizes,
        },
        "profiles": {
            "hardware": {
                "operatingSystem": "darwin 25.0.0",
                "architecture": "arm64",
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
            "cogPath": COG_PATH,
            "sourceGridPath": GRID_PATH,
            "sourceRow": 5,
            "sourceColumn": 7,
            "cogRow": 40,
            "goldenEvidenceSha256": "1" * 64,
        },
        "coldLookupSamples": [
            _sample(cold=True, cog_bytes=cog_bytes, grid_bytes=grid_bytes)
            for _ in range(10)
        ],
        "warmLookupSamples": [
            _sample(cold=False, cog_bytes=cog_bytes, grid_bytes=grid_bytes)
            for _ in range(100)
        ],
    }
    _write_json(trace_path, trace)
    _write_json(
        timing_path,
        {
            "schemaVersion": 1,
            "candidate": binding,
            "timer": "python-time-perf-counter",
            "startedBeforeSourceVerification": True,
            "endedAfterAtomicCandidatePublish": True,
            "fullCleanBuildDurationSeconds": 10,
        },
    )
    return {
        "release": release,
        "candidate": candidate,
        "binding": binding,
        "reproducibility": reproducibility_path,
        "trace": trace_path,
        "timing": timing_path,
        "harness": harness_path,
    }


def _finalize(inputs: dict[str, object]):
    return finalize_recovery_gate(
        inputs["candidate"],
        contract=inputs["release"],
        reproducibility_report_path=inputs["reproducibility"],
        delivery_trace_path=inputs["trace"],
        build_timing_path=inputs["timing"],
        harness_path=inputs["harness"],
        repository_root=REPOSITORY_ROOT,
    )


def test_finalizer_recomputes_real_delivery_for_a_sealed_candidate(tmp_path: Path) -> None:
    inputs = _promotion_inputs(tmp_path)

    gate = _finalize(inputs)

    assert gate["automatedValidation"] == "pending"
    assert gate["checks"]["deliveryMeasurements"] is True
    assert gate["checks"]["crossEnvironmentReproducibility"] is False
    assert gate["blockingChecks"] == ["crossEnvironmentReproducibility"]
    assert gate["releaseDisposition"] == "pending-owner"
    assert gate["phase1Unlocked"] is False
    assert gate["evidenceBindings"]["candidateBindingSha256"] == binding_sha256(
        inputs["binding"]
    )


def test_finalizer_does_not_accept_a_self_authored_delivery_summary(tmp_path: Path) -> None:
    inputs = _promotion_inputs(tmp_path)
    summary = tmp_path / "delivery-report.json"
    _write_json(summary, DELIVERY)

    with pytest.raises(TypeError, match="unexpected keyword argument"):
        finalize_recovery_gate(
            inputs["candidate"],
            contract=inputs["release"],
            reproducibility_report_path=inputs["reproducibility"],
            delivery_report_path=summary,
            repository_root=REPOSITORY_ROOT,
        )


@pytest.mark.parametrize(
    "mutation",
    ["public-origin", "zero-cost", "forged-range", "missing-trace"],
)
def test_finalizer_rejects_forged_or_missing_raw_delivery_inputs(
    tmp_path: Path,
    mutation: str,
) -> None:
    inputs = _promotion_inputs(tmp_path)
    trace_path = inputs["trace"]
    trace = json.loads(trace_path.read_text(encoding="utf-8"))
    if mutation == "public-origin":
        trace["profiles"]["network"]["origin"] = "https://measure.example.com"
    elif mutation == "zero-cost":
        for sample in [*trace["coldLookupSamples"], *trace["warmLookupSamples"]]:
            sample.update(
                durationMilliseconds=0,
                heapBeforeBytes=0,
                heapAfterBytes=0,
                peakHeapBytes=0,
                rangeRequestCount=0,
                transferBytes=0,
            )
            for request in sample["requests"]:
                request["responseBytes"] = 0
    elif mutation == "forged-range":
        trace["coldLookupSamples"][0]["requests"][0]["contentRange"] = "bytes 0-1/2"
    else:
        trace_path.unlink()
    if mutation != "missing-trace":
        _write_json(trace_path, trace)

    with pytest.raises(ScienceContractError):
        _finalize(inputs)


@pytest.mark.parametrize(
    ("field", "invalid"),
    [
        ("status", "passed"),
        ("independentEnvironmentCount", 2),
        ("receiptProfileCount", True),
        ("requiredExternalBindings", []),
    ],
)
def test_finalizer_rejects_forged_reproducibility_provenance(
    tmp_path: Path,
    field: str,
    invalid: object,
) -> None:
    inputs = _promotion_inputs(tmp_path)
    path = inputs["reproducibility"]
    report = json.loads(path.read_text(encoding="utf-8"))
    report[field] = invalid
    _write_json(path, report)

    with pytest.raises(ScienceContractError):
        _finalize(inputs)


@pytest.mark.parametrize("mutation", ["obsolete-pmtiles-binary", "missing-profile"])
def test_finalizer_enforces_the_current_candidate_binding_schema(
    tmp_path: Path,
    mutation: str,
) -> None:
    inputs = _promotion_inputs(tmp_path)
    path = inputs["reproducibility"]
    report = json.loads(path.read_text(encoding="utf-8"))
    candidate = report["candidates"][1]
    if mutation == "obsolete-pmtiles-binary":
        candidate["environmentIdentity"]["vector"]["pmtiles_binary_sha256"] = "0" * 64
    else:
        candidate.pop("validatedEnvironmentProfile")
    _write_json(path, report)

    with pytest.raises(ScienceContractError, match="exact schema"):
        _finalize(inputs)


def test_finalizer_hashes_the_same_reproducibility_snapshot_it_parses(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inputs = _promotion_inputs(tmp_path)
    path = inputs["reproducibility"]
    original_sha256 = _sha(path)
    original = promotion_module.load_json_snapshot

    def mutate_after_snapshot(observed_path: Path):
        document, digest = original(observed_path)
        if observed_path == path:
            _write_json(path, {"forged": True})
        return document, digest

    monkeypatch.setattr(promotion_module, "load_json_snapshot", mutate_after_snapshot)
    gate = _finalize(inputs)

    assert gate["evidenceBindings"]["reproducibilityReportSha256"] == original_sha256
    assert _sha(path) != original_sha256


def test_finalizer_rejects_candidate_evidence_changed_after_binding(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inputs = _promotion_inputs(tmp_path)
    original = promotion_module.create_delivery_report

    def mutate_candidate(*args, **kwargs):
        report = original(*args, **kwargs)
        _write_json(inputs["candidate"] / "build-evidence.json", {"forged": True})
        return report

    monkeypatch.setattr(promotion_module, "create_delivery_report", mutate_candidate)
    with pytest.raises(ScienceContractError, match="changed after candidate binding"):
        _finalize(inputs)


def test_finalizer_converts_git_process_errors_to_science_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inputs = _promotion_inputs(tmp_path)

    def missing_git(*_args, **_kwargs):
        raise FileNotFoundError("git unavailable")

    monkeypatch.setattr(promotion_module.subprocess, "run", missing_git)
    with pytest.raises(ScienceContractError, match="verify.*source revision"):
        _finalize(inputs)


def test_finalizer_has_no_owner_authority_argument(tmp_path: Path) -> None:
    inputs = _promotion_inputs(tmp_path)

    with pytest.raises(TypeError, match="unexpected keyword argument"):
        finalize_recovery_gate(
            inputs["candidate"],
            contract=inputs["release"],
            reproducibility_report_path=inputs["reproducibility"],
            delivery_trace_path=inputs["trace"],
            build_timing_path=inputs["timing"],
            harness_path=inputs["harness"],
            repository_root=REPOSITORY_ROOT,
            owner_decision="approved",
        )
