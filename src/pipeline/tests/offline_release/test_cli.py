"""Operator CLI tests for immutable external build evidence."""

from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner
from jsonschema import Draft202012Validator

from searise_pipeline.offline_release import FailureCode, StageFailure, StageName
from searise_pipeline.offline_release import runner as build_runner
from searise_pipeline.offline_release.cli import cli

REPO_ROOT = Path(__file__).parents[4]
PROFILE = REPO_ROOT / "src/pipeline/offline_release/profiles/fixture.json"
RECEIPT_SCHEMA = (
    REPO_ROOT
    / "src/pipeline/searise_pipeline/offline_release/schemas/operator-receipt.schema.json"
)


def _arguments(tmp_path: Path, *, suffix: str = "one") -> list[str]:
    return [
        "--profile",
        str(PROFILE),
        "--input-root",
        str(REPO_ROOT),
        "--code-revision",
        "a" * 40,
        "--release-date",
        "20260810",
        "--started-at",
        "2026-08-10T12:00:00Z",
        "--completed-at",
        "2026-08-10T12:00:01Z",
        "--cache-dir",
        str(tmp_path / "cache"),
        "--output-dir",
        str(tmp_path / f"candidate-{suffix}"),
        "--execution-receipt",
        str(tmp_path / f"execution-{suffix}.json"),
        "--failure-receipt",
        str(tmp_path / f"failure-{suffix}.json"),
    ]


def _json(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def test_operator_receipt_schema_is_a_valid_draft_2020_12_contract() -> None:
    Draft202012Validator.check_schema(_json(RECEIPT_SCHEMA))


def test_cli_builds_candidate_and_commits_complete_execution_receipt(
    tmp_path: Path,
) -> None:
    result = CliRunner().invoke(cli, _arguments(tmp_path))

    assert result.exit_code == 0, result.output
    assert "publication not attempted" in result.output
    assert (tmp_path / "candidate-one/manifest.json").is_file()
    assert not (tmp_path / "failure-one.json").exists()
    receipt = _json(tmp_path / "execution-one.json")
    assert receipt["receiptType"] == "offline-build-execution"
    assert receipt["status"] == "complete"
    assert receipt["networkAccess"] == "disabled"
    assert len(receipt["stages"]) == 7  # type: ignore[arg-type]
    assert receipt["candidate"]["fileCount"] == 42  # type: ignore[index]
    assert receipt["candidate"]["byteSize"] > 0  # type: ignore[index]
    assert len(receipt["candidate"]["inventorySha256"]) == 64  # type: ignore[index]
    assert receipt["resourceUsage"]["totalDurationSeconds"] >= 0  # type: ignore[index]
    assert receipt["resourceUsage"]["peakProcessRssBytes"] > 0  # type: ignore[index]


def test_cli_resume_reuses_verified_cache_without_changing_candidate_identity(
    tmp_path: Path,
) -> None:
    first_result = CliRunner().invoke(cli, _arguments(tmp_path, suffix="one"))
    second_result = CliRunner().invoke(cli, _arguments(tmp_path, suffix="two"))

    assert first_result.exit_code == second_result.exit_code == 0
    first = _json(tmp_path / "execution-one.json")
    second = _json(tmp_path / "execution-two.json")
    assert [stage["cacheStatus"] for stage in first["stages"]] == ["miss"] * 7  # type: ignore[index]
    assert [stage["cacheStatus"] for stage in second["stages"]] == ["hit"] * 7  # type: ignore[index]
    assert first["finalOutputs"] == second["finalOutputs"]
    assert first["candidate"] == second["candidate"]
    assert first["dataReleaseId"] == second["dataReleaseId"]


def test_cli_failure_receipt_uses_taxonomy_without_recording_raw_exception(
    tmp_path: Path,
    monkeypatch,
) -> None:
    def fail_build(*args, **kwargs):
        raise StageFailure(
            FailureCode.DISK_PRESSURE,
            StageName.DERIVE,
            "credential=do-not-record\nraw backend diagnostic",
        )

    monkeypatch.setattr(build_runner, "run_build", fail_build)
    result = CliRunner().invoke(cli, _arguments(tmp_path))

    assert result.exit_code == 1
    assert "disk-pressure at derive" in result.output
    assert "failure receipt committed" in result.output
    assert "do-not-record" not in result.output
    assert not (tmp_path / "candidate-one").exists()
    assert not (tmp_path / "execution-one.json").exists()
    receipt_path = tmp_path / "failure-one.json"
    receipt = _json(receipt_path)
    assert receipt["status"] == "failed"
    assert receipt["candidateState"] == "not-created"
    assert receipt["failure"] == {
        "code": "disk-pressure",
        "stage": "derive",
        "detail": "storage capacity prevented completion",
    }
    assert "do-not-record" not in receipt_path.read_text(encoding="utf-8")


def test_cli_never_overwrites_an_immutable_execution_receipt(tmp_path: Path) -> None:
    first = CliRunner().invoke(cli, _arguments(tmp_path, suffix="one"))
    original = (tmp_path / "execution-one.json").read_bytes()
    repeated = _arguments(tmp_path, suffix="two")
    receipt_index = repeated.index("--execution-receipt") + 1
    repeated[receipt_index] = str(tmp_path / "execution-one.json")

    second = CliRunner().invoke(cli, repeated)

    assert first.exit_code == 0
    assert second.exit_code == 1
    assert (tmp_path / "execution-one.json").read_bytes() == original
    assert not (tmp_path / "candidate-two").exists()
    failure = _json(tmp_path / "failure-two.json")
    assert failure["failure"]["code"] == "invalid-plan"  # type: ignore[index]


def test_nested_receipt_path_cannot_create_a_partial_candidate(tmp_path: Path) -> None:
    arguments = _arguments(tmp_path)
    receipt_index = arguments.index("--execution-receipt") + 1
    arguments[receipt_index] = str(tmp_path / "candidate-one/execution.json")

    result = CliRunner().invoke(cli, arguments)

    assert result.exit_code == 1
    assert not (tmp_path / "candidate-one").exists()
    failure = _json(tmp_path / "failure-one.json")
    assert failure["candidateState"] == "not-created"
    assert failure["failure"]["code"] == "invalid-plan"  # type: ignore[index]


def test_execution_receipt_commit_failure_discards_new_candidate(
    tmp_path: Path,
    monkeypatch,
) -> None:
    original_write = build_runner._write_immutable_json

    def fail_execution_receipt(path, document):
        if document.get("receiptType") == "offline-build-execution":
            raise OSError("credential=do-not-record")
        original_write(path, document)

    monkeypatch.setattr(build_runner, "_write_immutable_json", fail_execution_receipt)

    result = CliRunner().invoke(cli, _arguments(tmp_path))

    assert result.exit_code == 1
    assert "incomplete-build at preflight" in result.output
    assert "do-not-record" not in result.output
    assert not (tmp_path / "candidate-one").exists()
    assert not (tmp_path / "execution-one.json").exists()
    assert not list(tmp_path.glob(".searise-unreceipted-*"))
    failure_path = tmp_path / "failure-one.json"
    failure = _json(failure_path)
    assert failure["candidateState"] == "discarded-unreceipted"
    assert failure["failure"] == {
        "code": "incomplete-build",
        "stage": None,
        "detail": "operator execution did not complete",
    }
    assert "do-not-record" not in failure_path.read_text(encoding="utf-8")


def test_failed_invocation_never_changes_a_preexisting_output(tmp_path: Path) -> None:
    candidate = tmp_path / "candidate-one"
    candidate.mkdir()
    sentinel = candidate / "owner.txt"
    sentinel.write_bytes(b"pre-existing\n")

    result = CliRunner().invoke(cli, _arguments(tmp_path))

    assert result.exit_code == 1
    assert sentinel.read_bytes() == b"pre-existing\n"
    assert set(candidate.iterdir()) == {sentinel}
    failure = _json(tmp_path / "failure-one.json")
    assert failure["candidateState"] == "pre-existing"
    assert failure["failure"]["code"] == "atomic-promotion-failed"  # type: ignore[index]


def test_receipt_failure_preserves_candidate_path_replacement(
    tmp_path: Path,
    monkeypatch,
) -> None:
    original_write = build_runner._write_immutable_json
    replacement = tmp_path / "candidate-one/replacement.txt"

    def replace_candidate_before_failure(path, document):
        if document.get("receiptType") == "offline-build-execution":
            (tmp_path / "candidate-one").rename(tmp_path / "original-candidate")
            replacement.parent.mkdir()
            replacement.write_bytes(b"unrelated replacement\n")
            raise OSError("credential=do-not-record")
        original_write(path, document)

    monkeypatch.setattr(
        build_runner,
        "_write_immutable_json",
        replace_candidate_before_failure,
    )

    result = CliRunner().invoke(cli, _arguments(tmp_path))

    assert result.exit_code == 1
    assert replacement.read_bytes() == b"unrelated replacement\n"
    assert set(replacement.parent.iterdir()) == {replacement}
    failure = _json(tmp_path / "failure-one.json")
    assert failure["candidateState"] == "identity-mismatch-preserved"
    assert "do-not-record" not in result.output
