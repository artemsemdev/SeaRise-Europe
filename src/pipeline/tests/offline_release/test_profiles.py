"""Tests for explicit offline release profiles and resolved build plans."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from searise_pipeline.offline_release import (
    BuildPlanError,
    BuildProfile,
    ProfileAvailability,
    StageName,
    compile_profile,
    load_profile_definition,
)

REPO_ROOT = Path(__file__).parents[4]
PROFILE_ROOT = REPO_ROOT / "src/pipeline/offline_release/profiles"


def test_all_profiles_validate_and_declare_the_identical_graph() -> None:
    schema = json.loads((PROFILE_ROOT / "profile.schema.json").read_text(encoding="utf-8"))
    definitions = []
    for profile in BuildProfile:
        path = PROFILE_ROOT / f"{profile.value}.json"
        document = json.loads(path.read_text(encoding="utf-8"))
        Draft202012Validator(schema).validate(document)
        definitions.append(load_profile_definition(path))

    assert [definition.profile for definition in definitions] == list(BuildProfile)
    assert {definition.stage_names for definition in definitions} == {tuple(StageName)}
    assert definitions[0].availability is ProfileAvailability.FIXTURE_READY
    assert all(
        definition.availability is ProfileAvailability.CONTROLLED_INPUT_REQUIRED
        for definition in definitions[1:]
    )


def test_fixture_profile_compiles_every_checked_input_into_a_stable_plan() -> None:
    kwargs = {
        "input_root": REPO_ROOT,
        "code_revision": "a" * 40,
        "release_date": "20260810",
        "started_at": "2026-08-10T12:00:00Z",
        "completed_at": "2026-08-10T12:00:01Z",
    }
    first = compile_profile(PROFILE_ROOT / "fixture.json", **kwargs)
    second = compile_profile(PROFILE_ROOT / "fixture.json", **kwargs)

    assert first.plan == second.plan
    assert first.plan.identity_sha256 == second.plan.identity_sha256
    assert first.plan.data_release_id.startswith("searise-europe-v1.0.0-20260810-")
    assert len(first.plan.inputs) >= 50
    assert tuple(first.plan.inputs) == tuple(sorted(first.plan.inputs))
    assert first.plan.source_receipts[0] in first.plan.inputs
    assert first.plan.parameters["receiptTimestamps"] == {
        "startedAt": "2026-08-10T12:00:00Z",
        "completedAt": "2026-08-10T12:00:01Z",
    }


@pytest.mark.parametrize("field", ["code_revision", "release_date", "completed_at"])
def test_run_identity_changes_when_an_explicit_build_input_changes(field: str) -> None:
    kwargs = {
        "input_root": REPO_ROOT,
        "code_revision": "a" * 40,
        "release_date": "20260810",
        "started_at": "2026-08-10T12:00:00Z",
        "completed_at": "2026-08-10T12:00:01Z",
    }
    baseline = compile_profile(PROFILE_ROOT / "fixture.json", **kwargs)
    changed = dict(kwargs)
    changed[field] = {
        "code_revision": "b" * 40,
        "release_date": "20260811",
        "completed_at": "2026-08-10T12:00:02Z",
    }[field]

    candidate = compile_profile(PROFILE_ROOT / "fixture.json", **changed)

    assert candidate.plan.identity_sha256 != baseline.plan.identity_sha256
    assert candidate.plan.data_release_id != baseline.plan.data_release_id


@pytest.mark.parametrize("profile", ["regional", "full-europe"])
def test_controlled_profiles_fail_explicitly_when_inputs_are_absent(profile: str) -> None:
    with pytest.raises(BuildPlanError, match="input is unavailable"):
        compile_profile(
            PROFILE_ROOT / f"{profile}.json",
            input_root=REPO_ROOT,
            code_revision="a" * 40,
            release_date="20260810",
            started_at="2026-08-10T12:00:00Z",
            completed_at="2026-08-10T12:00:01Z",
        )


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda value: value.update({"unexpected": True}), "exact version 1 fields"),
        (lambda value: value.update({"inputRootPath": "../escape"}), "unsafe"),
        (lambda value: value["stageGraph"].reverse(), "complete and ordered"),
        (
            lambda value: value["tools"][0]["identityPaths"].append(
                value["tools"][0]["identityPaths"][0]
            ),
            "unique and sorted",
        ),
    ],
)
def test_profile_loader_rejects_ambiguous_or_unsafe_configuration(
    tmp_path: Path, mutation, message: str
) -> None:
    document = json.loads((PROFILE_ROOT / "fixture.json").read_text(encoding="utf-8"))
    changed = deepcopy(document)
    mutation(changed)
    path = tmp_path / "profile.json"
    path.write_text(json.dumps(changed), encoding="utf-8")

    with pytest.raises(BuildPlanError, match=message):
        load_profile_definition(path)


@pytest.mark.parametrize(
    ("started", "completed", "message"),
    [
        ("2026-08-10T12:00:00+02:00", "2026-08-10T12:00:01Z", "UTC"),
        ("2026-08-10T12:00:02Z", "2026-08-10T12:00:01Z", "precede"),
    ],
)
def test_profile_compiler_rejects_ambiguous_timestamps(
    started: str, completed: str, message: str
) -> None:
    with pytest.raises(BuildPlanError, match=message):
        compile_profile(
            PROFILE_ROOT / "fixture.json",
            input_root=REPO_ROOT,
            code_revision="a" * 40,
            release_date="20260810",
            started_at=started,
            completed_at=completed,
        )
