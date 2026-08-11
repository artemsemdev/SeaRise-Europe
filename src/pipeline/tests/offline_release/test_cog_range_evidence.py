from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from searise_pipeline.offline_release.cog_range_evidence import (
    capture_loopback_cog_range_evidence,
    validate_reviewed_cog_range_evidence,
)
from searise_pipeline.science import ScienceContractError

REPOSITORY_ROOT = Path(__file__).parents[4]
FIXTURE_ROOT = (
    REPOSITORY_ROOT / "contracts/release/v1/fixtures/release/"
    "searise-europe-v1.0.0-20260810-c096aeab4e09"
)
SOURCE_REVISION = "1" * 40
TESTED_REVISION = "2" * 40
PRODUCER_INPUTS = {
    "source_revision": SOURCE_REVISION,
    "tested_revision": TESTED_REVISION,
    "workflow_run_id": 123456789,
    "workflow_run_attempt": 2,
    "workflow_job": "pipeline",
}
EXPECTED_PRODUCER = {
    "sourceRevision": SOURCE_REVISION,
    "testedRevision": TESTED_REVISION,
    "workflowRunId": 123456789,
    "workflowRunAttempt": 2,
    "workflowJob": "pipeline",
    "clock": "time.perf_counter_ns",
}


def test_persists_exact_candidate_bound_loopback_http_evidence(tmp_path: Path) -> None:
    output = tmp_path / "cog-range-evidence.json"

    report = capture_loopback_cog_range_evidence(
        FIXTURE_ROOT,
        repository_root=REPOSITORY_ROOT,
        output_path=output,
        execution_id="github-123456789-2-pipeline",
        **PRODUCER_INPUTS,
    )

    persisted = json.loads(output.read_text(encoding="utf-8"))
    assert (
        validate_reviewed_cog_range_evidence(
            output,
            bundle_root=FIXTURE_ROOT,
            repository_root=REPOSITORY_ROOT,
            expected_producer=EXPECTED_PRODUCER,
        )
        == persisted
    )
    assert report["producer"] == EXPECTED_PRODUCER
    assert report["reviewedProjectionCandidate"]["candidateBindingSha256"] == (
        "aff21bf005f37e3aa1e386e15694eca6715e2310373cd4f502a50685b5560cae"
    )
    requests = [request for artifact in report["artifacts"] for request in artifact["requests"]]
    assert len(requests) == report["rangeRequestCount"] == 54
    assert all(request["latencyNanoseconds"] >= 0 for request in requests)
    assert [item["case"] for item in report["rejectionControls"]] == [
        "malformed",
        "ignored",
        "truncated",
        "substituted",
        "corrupt",
    ]
    assert report["evidenceDisposition"] == ("candidate-bound-loopback-http-validation-only")
    assert "No public origin" in report["limitations"][1]

    mutations: list[dict[str, object]] = []
    detached = deepcopy(report)
    detached["servedCandidate"]["manifestSha256"] = "0" * 64
    mutations.append(detached)
    wrong_status = deepcopy(report)
    wrong_status["artifacts"][0]["requests"][0]["status"] = 200
    mutations.append(wrong_status)
    invalid_latency = deepcopy(report)
    invalid_latency["artifacts"][0]["requests"][0]["latencyNanoseconds"] = -1
    mutations.append(invalid_latency)
    accepted_control = deepcopy(report)
    accepted_control["rejectionControls"][0]["outcome"] = "accepted"
    mutations.append(accepted_control)
    forged_execution = deepcopy(report)
    forged_execution["executionId"] = "forged-valid-execution"
    mutations.append(forged_execution)
    for field, forged_value in (
        ("sourceRevision", "3" * 40),
        ("testedRevision", "4" * 40),
        ("workflowRunId", 123456790),
        ("workflowRunAttempt", 3),
        ("workflowJob", "release"),
        ("clock", "time.time_ns"),
    ):
        forged_producer = deepcopy(report)
        forged_producer["producer"][field] = forged_value
        mutations.append(forged_producer)
    extra_producer_field = deepcopy(report)
    extra_producer_field["producer"]["actor"] = "untrusted"
    mutations.append(extra_producer_field)
    uppercase_revision = deepcopy(report)
    uppercase_revision["producer"]["sourceRevision"] = "A" * 40
    mutations.append(uppercase_revision)
    non_positive_run = deepcopy(report)
    non_positive_run["producer"]["workflowRunId"] = 0
    mutations.append(non_positive_run)
    invalid_job = deepcopy(report)
    invalid_job["producer"]["workflowJob"] = "Pipeline job"
    mutations.append(invalid_job)

    for index, mutation in enumerate(mutations):
        changed = tmp_path / f"changed-{index}.json"
        changed.write_text(json.dumps(mutation), encoding="utf-8")
        with pytest.raises(ScienceContractError, match="COG"):
            validate_reviewed_cog_range_evidence(
                changed,
                bundle_root=FIXTURE_ROOT,
                repository_root=REPOSITORY_ROOT,
                expected_producer=EXPECTED_PRODUCER,
            )
