"""Contract tests for offline build plans and their fixed stage graph."""

from __future__ import annotations

from copy import deepcopy

import pytest

from searise_pipeline.offline_release import (
    BuildPlan,
    BuildProfile,
    FailureCode,
    StageFailure,
    StageName,
    stage_graph,
)
from searise_pipeline.offline_release.model import BuildPlanError


def _plan() -> dict[str, object]:
    return {
        "schemaVersion": 1,
        "profile": "fixture",
        "dataReleaseId": "searise-europe-v1.0.0-20260810-aaaaaaaaaaaa",
        "dataProvenanceClass": "synthetic-fixture",
        "codeRevision": "b" * 40,
        "networkAccess": "disabled",
        "environment": {
            "platform": "linux",
            "architecture": "x86_64",
            "pythonVersion": "3.11.13",
            "lock": {"path": "locks/python.txt", "sha256": "c" * 64},
        },
        "tools": [
            {
                "name": "searise-pipeline",
                "version": "0.1.0",
                "identitySha256": "d" * 64,
            }
        ],
        "sourceReceipts": [
            {"path": "receipts/sources/ipcc-ar6.json", "sha256": "e" * 64}
        ],
        "inputs": [
            {"path": "recipes/fixture.json", "sha256": "f" * 64}
        ],
        "parameters": {"compression": {"level": 9}, "locale": "C"},
        "stageGraph": [stage.value for stage in StageName],
    }


def test_every_profile_uses_the_same_closed_stage_graph() -> None:
    expected = tuple(StageName)

    for profile in BuildProfile:
        graph = stage_graph(profile)
        assert tuple(stage.name for stage in graph) == expected
        assert graph[0].dependencies == ()
        assert all(
            stage.dependencies == (graph[index - 1].name,)
            for index, stage in enumerate(graph[1:], start=1)
        )


def test_build_plan_has_stable_identity_and_public_build_id() -> None:
    first = _plan()
    second = _plan()
    second["parameters"] = {"locale": "C", "compression": {"level": 9}}

    left = BuildPlan.from_mapping(first)
    right = BuildPlan.from_mapping(second)

    assert left == right
    assert left.parameters_sha256 == right.parameters_sha256
    assert left.identity_sha256 == right.identity_sha256
    assert left.build_id == f"build-fixture-{left.identity_sha256[:12]}"
    assert left.parameters == {"compression": {"level": 9}, "locale": "C"}


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("parameters", "locale"), "en_US"),
        (("codeRevision",), "a" * 40),
        (("tools", 0, "identitySha256"), "1" * 64),
        (("sourceReceipts", 0, "sha256"), "2" * 64),
        (("inputs", 0, "sha256"), "3" * 64),
    ],
)
def test_every_build_input_changes_the_plan_identity(
    path: tuple[str | int, ...], value: object
) -> None:
    baseline = BuildPlan.from_mapping(_plan())
    changed = deepcopy(_plan())
    target: object = changed
    for part in path[:-1]:
        target = target[part]  # type: ignore[index]
    target[path[-1]] = value  # type: ignore[index]

    assert BuildPlan.from_mapping(changed).identity_sha256 != baseline.identity_sha256


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda plan: plan.update({"unexpected": True}), "contain exactly"),
        (lambda plan: plan.update({"profile": "large"}), "unsupported"),
        (lambda plan: plan.update({"networkAccess": "enabled"}), "disabled"),
        (lambda plan: plan.update({"codeRevision": "main"}), "Git commit"),
        (
            lambda plan: plan.update({"dataReleaseId": "../release"}),
            "public v1 contract",
        ),
        (
            lambda plan: plan["stageGraph"].pop(),  # type: ignore[union-attr]
            "complete ordered",
        ),
        (
            lambda plan: plan["inputs"][0].update({"path": "../escape"}),  # type: ignore[index,union-attr]
            "unsafe or non-canonical",
        ),
        (
            lambda plan: plan["tools"].append(dict(plan["tools"][0])),  # type: ignore[index,union-attr]
            "unique and sorted",
        ),
    ],
)
def test_build_plan_rejects_ambiguous_or_unsafe_documents(mutation, message: str) -> None:
    document = _plan()
    mutation(document)

    with pytest.raises(BuildPlanError, match=message):
        BuildPlan.from_mapping(document)


def test_stage_failure_has_stable_machine_code_and_bounded_location() -> None:
    failure = StageFailure(
        FailureCode.OUTPUT_VALIDATION_FAILED,
        StageName.VALIDATE,
        "artifact hash mismatch",
    )

    assert str(failure) == (
        "output-validation-failed at validate: artifact hash mismatch"
    )
    assert {code.value for code in FailureCode} == {
        "invalid-plan",
        "source-verification-failed",
        "stale-cache",
        "stage-execution-failed",
        "output-validation-failed",
        "atomic-promotion-failed",
        "incomplete-build",
        "disk-pressure",
    }
