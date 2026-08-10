"""Integration tests for cache-safe and atomic stage execution."""

from __future__ import annotations

import hashlib
import json
import os
from copy import deepcopy
from pathlib import Path

import pytest

from searise_pipeline.offline_release import (
    BuildPlan,
    FailureCode,
    StageContext,
    StageFailure,
    StageName,
    StageOutcome,
    run_build,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fixture(tmp_path: Path) -> tuple[Path, dict[str, object]]:
    root = tmp_path / "inputs"
    for relative, content in (
        ("locks/python.txt", b"python-lock\n"),
        ("receipts/sources/source.json", b'{"verified":true}\n'),
        ("recipes/fixture.json", b'{"profile":"fixture"}\n'),
    ):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    plan: dict[str, object] = {
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
            "lock": {
                "path": "locks/python.txt",
                "sha256": _sha256(root / "locks/python.txt"),
            },
        },
        "tools": [
            {
                "name": "searise-pipeline",
                "version": "0.1.0",
                "identitySha256": "d" * 64,
            }
        ],
        "sourceReceipts": [
            {
                "path": "receipts/sources/source.json",
                "sha256": _sha256(root / "receipts/sources/source.json"),
            }
        ],
        "inputs": [
            {
                "path": "recipes/fixture.json",
                "sha256": _sha256(root / "recipes/fixture.json"),
            }
        ],
        "parameters": {"compression": "stable", "locale": "C"},
        "stageGraph": [stage.value for stage in StageName],
    }
    return root, plan


def _handlers(
    calls: list[StageName], *, fail_at: StageName | None = None
) -> dict[StageName, object]:
    handlers = {}
    for stage in StageName:

        def handler(context: StageContext, current: StageName = stage) -> StageOutcome:
            assert context.stage is current
            calls.append(current)
            if current is fail_at:
                raise StageFailure(
                    FailureCode.STAGE_EXECUTION_FAILED,
                    current,
                    "injected safe failure",
                )
            upstream = {
                dependency.value: [item.sha256 for item in outputs]
                for dependency, outputs in context.dependency_outputs.items()
            }
            document = {
                "planIdentitySha256": context.plan.identity_sha256,
                "stage": current.value,
                "upstream": upstream,
            }
            path = context.output_directory / f"{current.value}.json"
            path.write_text(
                json.dumps(document, separators=(",", ":"), sort_keys=True) + "\n",
                encoding="utf-8",
            )
            return StageOutcome(
                warnings=("fixture-only",),
                quality_results={"complete": True, "fileCount": 1},
            )

        handlers[stage] = handler
    return handlers


def _run(
    tmp_path: Path,
    plan: BuildPlan,
    root: Path,
    handlers,
    *,
    output_name: str,
    cache_name: str = "cache",
):
    return run_build(
        plan,
        input_root=root,
        cache_directory=tmp_path / cache_name,
        output_directory=tmp_path / output_name,
        handlers=handlers,
    )


def test_clean_build_runs_one_graph_and_atomically_publishes_candidate(
    tmp_path: Path,
) -> None:
    root, document = _fixture(tmp_path)
    calls: list[StageName] = []

    result = _run(
        tmp_path,
        BuildPlan.from_mapping(document),
        root,
        _handlers(calls),
        output_name="candidate",
    )

    assert calls == list(StageName)
    assert result.output_directory.is_dir()
    assert [path.name for path in result.output_directory.iterdir()] == [
        "assemble-release.json"
    ]
    assert [stage.cache_status for stage in result.stages] == ["miss"] * 7
    assert result.execution_receipt["status"] == "complete"
    assert result.execution_receipt["networkAccess"] == "disabled"
    assert len(result.execution_receipt["stages"]) == 7
    assert all(stage.duration_seconds >= 0 for stage in result.stages)
    assert not list((tmp_path / "cache").rglob(".*-*"))


def test_failed_build_has_no_candidate_and_resume_reuses_only_verified_stages(
    tmp_path: Path,
) -> None:
    root, document = _fixture(tmp_path)
    plan = BuildPlan.from_mapping(document)
    failed_calls: list[StageName] = []

    with pytest.raises(StageFailure) as raised:
        _run(
            tmp_path,
            plan,
            root,
            _handlers(failed_calls, fail_at=StageName.NORMALIZE),
            output_name="candidate",
        )

    assert raised.value.code is FailureCode.STAGE_EXECUTION_FAILED
    assert raised.value.stage is StageName.NORMALIZE
    assert failed_calls == [
        StageName.VERIFY_SOURCES,
        StageName.INSPECT,
        StageName.NORMALIZE,
    ]
    assert not (tmp_path / "candidate").exists()

    resumed_calls: list[StageName] = []
    resumed = _run(
        tmp_path,
        plan,
        root,
        _handlers(resumed_calls),
        output_name="candidate",
    )

    assert resumed_calls == list(StageName)[2:]
    assert [stage.cache_status for stage in resumed.stages] == [
        "hit",
        "hit",
        "miss",
        "miss",
        "miss",
        "miss",
        "miss",
    ]
    assert resumed.execution_receipt["status"] == "complete"


@pytest.mark.parametrize("mutation", ["parameter", "code", "tool", "source"])
def test_identity_changes_invalidate_affected_intermediates(
    tmp_path: Path, mutation: str
) -> None:
    root, document = _fixture(tmp_path)
    baseline_calls: list[StageName] = []
    _run(
        tmp_path,
        BuildPlan.from_mapping(document),
        root,
        _handlers(baseline_calls),
        output_name="first",
    )
    changed = deepcopy(document)
    if mutation == "parameter":
        changed["parameters"] = {"compression": "other", "locale": "C"}
    elif mutation == "code":
        changed["codeRevision"] = "c" * 40
    elif mutation == "tool":
        changed["tools"][0]["identitySha256"] = "e" * 64  # type: ignore[index]
    else:
        source = root / "receipts/sources/source.json"
        source.write_bytes(b'{"verified":true,"revision":2}\n')
        changed["sourceReceipts"][0]["sha256"] = _sha256(source)  # type: ignore[index]

    calls: list[StageName] = []
    result = _run(
        tmp_path,
        BuildPlan.from_mapping(changed),
        root,
        _handlers(calls),
        output_name="second",
    )

    assert calls == list(StageName)
    assert [stage.cache_status for stage in result.stages] == ["miss"] * 7


def test_tampered_cache_fails_closed_instead_of_being_reused(tmp_path: Path) -> None:
    root, document = _fixture(tmp_path)
    plan = BuildPlan.from_mapping(document)
    first = _run(
        tmp_path,
        plan,
        root,
        _handlers([]),
        output_name="first",
    )
    stage = first.stages[0]
    cached = (
        tmp_path
        / "cache/stages"
        / stage.stage.value
        / stage.stage_key_sha256
        / "payload/verify-sources.json"
    )
    cached.write_bytes(cached.read_bytes() + b"tamper")

    with pytest.raises(StageFailure) as raised:
        _run(
            tmp_path,
            plan,
            root,
            _handlers([]),
            output_name="second",
        )

    assert raised.value.code is FailureCode.STALE_CACHE
    assert raised.value.stage is StageName.VERIFY_SOURCES
    assert not (tmp_path / "second").exists()


@pytest.mark.parametrize("failure", ["wrong-hash", "symlink"])
def test_declared_inputs_are_reverified_before_cache_use(
    tmp_path: Path, failure: str
) -> None:
    root, document = _fixture(tmp_path)
    if failure == "wrong-hash":
        (root / "recipes/fixture.json").write_bytes(b"changed\n")
    else:
        target = root / "actual.json"
        target.write_bytes(b'{"profile":"fixture"}\n')
        (root / "recipes/fixture.json").unlink()
        os.symlink(target, root / "recipes/fixture.json")

    with pytest.raises(StageFailure) as raised:
        _run(
            tmp_path,
            BuildPlan.from_mapping(document),
            root,
            _handlers([]),
            output_name="candidate",
        )

    assert raised.value.code is FailureCode.SOURCE_VERIFICATION_FAILED
    assert not (tmp_path / "candidate").exists()


def test_invalid_stage_output_and_existing_candidate_fail_closed(tmp_path: Path) -> None:
    root, document = _fixture(tmp_path)
    plan = BuildPlan.from_mapping(document)
    handlers = _handlers([])

    def empty_stage(context: StageContext) -> StageOutcome:
        return StageOutcome()

    handlers[StageName.VERIFY_SOURCES] = empty_stage
    with pytest.raises(StageFailure) as raised:
        _run(tmp_path, plan, root, handlers, output_name="candidate")
    assert raised.value.code is FailureCode.OUTPUT_VALIDATION_FAILED
    assert not (tmp_path / "candidate").exists()

    existing = tmp_path / "existing"
    existing.mkdir()
    with pytest.raises(StageFailure) as raised:
        _run(tmp_path, plan, root, _handlers([]), output_name="existing")
    assert raised.value.code is FailureCode.ATOMIC_PROMOTION_FAILED


def test_two_clean_outputs_have_identical_final_bytes(tmp_path: Path) -> None:
    root, document = _fixture(tmp_path)
    plan = BuildPlan.from_mapping(document)
    first = _run(
        tmp_path,
        plan,
        root,
        _handlers([]),
        output_name="first",
        cache_name="cache-one",
    )
    second = _run(
        tmp_path,
        plan,
        root,
        _handlers([]),
        output_name="second",
        cache_name="cache-two",
    )

    assert first.stages[-1].outputs == second.stages[-1].outputs
    assert (tmp_path / "first/assemble-release.json").read_bytes() == (
        tmp_path / "second/assemble-release.json"
    ).read_bytes()
    assert [stage.cache_status for stage in first.stages] == ["miss"] * 7
    assert [stage.cache_status for stage in second.stages] == ["miss"] * 7
