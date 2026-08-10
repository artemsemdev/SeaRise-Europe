"""Validate the versioned release gate report and deterministic rendering."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from searise_pipeline.gate_report import (
    GateReportError,
    render_gate_report_markdown,
    validate_gate_report_semantics,
)

REPO_ROOT = Path(__file__).parents[4]
CONTRACT_DIR = REPO_ROOT / "contracts" / "release-gates" / "v1"
SCHEMA_PATH = CONTRACT_DIR / "gate-report.schema.json"
VALID_DIR = CONTRACT_DIR / "fixtures" / "valid"
INVALID_DIR = CONTRACT_DIR / "fixtures" / "invalid"
SEMANTIC_INVALID_DIR = CONTRACT_DIR / "fixtures" / "semantic-invalid"
SEMANTIC_SCHEMA_INVALID_NAMES = (
    "automation-release.json",
    "blocked-waivable-metric-releasable.json",
    "critical-flag-downgrade.json",
    "waivable-metric-automation.json",
)


def _read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _validator() -> Draft202012Validator:
    return Draft202012Validator(
        _read(SCHEMA_PATH),
        format_checker=FormatChecker(),
    )


def test_gate_report_schema_passes_the_draft_2020_12_metaschema() -> None:
    Draft202012Validator.check_schema(_read(SCHEMA_PATH))


def test_gate_report_fixture_matrix_covers_fail_closed_boundaries() -> None:
    assert {path.name for path in VALID_DIR.glob("*.json")} == {
        "approved-candidate.json",
        "blocked-candidate.json",
    }
    assert {path.name for path in INVALID_DIR.glob("*.json")} == {
        "automation-owner-approval.json",
        "automation-release.json",
        "blocked-waivable-metric-releasable.json",
        "critical-flag-downgrade.json",
        "missing-measurement.json",
        "non-waivable-fail-releasable.json",
        "unsupported-waiver-record.json",
        "unknown-reason.json",
        "unknown-status.json",
        "unknown-unit.json",
        "waivable-metric-automation.json",
    }
    assert {path.name for path in SEMANTIC_INVALID_DIR.glob("*.json")} == {
        "automated-validation-contradiction.json",
        "stop-reason-aggregation-contradiction.json",
        "target-status-contradiction.json",
    }


@pytest.mark.parametrize(
    "fixture_path",
    sorted(VALID_DIR.glob("*.json")),
    ids=lambda path: path.name,
)
def test_python_accepts_shared_semantic_valid_vectors(fixture_path: Path) -> None:
    report = _read(fixture_path)

    _validator().validate(report)
    validate_gate_report_semantics(report)


def test_blocked_gate_report_golden_exercises_all_decision_states() -> None:
    report = _read(VALID_DIR / "blocked-candidate.json")

    assert [check["status"] for check in report["checks"]] == [
        "pass",
        "not-measured",
        "fail",
    ]


@pytest.mark.parametrize(
    "fixture_path",
    sorted(INVALID_DIR.glob("*.json")),
    ids=lambda path: path.name,
)
def test_python_rejects_every_negative_gate_report_fixture(
    fixture_path: Path,
) -> None:
    assert list(_validator().iter_errors(_read(fixture_path)))


def test_gate_report_semantics_reject_nondeterministic_ordering() -> None:
    report = _read(VALID_DIR / "blocked-candidate.json")
    report["checks"][0], report["checks"][1] = (
        report["checks"][1],
        report["checks"][0],
    )
    _validator().validate(report)

    with pytest.raises(GateReportError, match="checkId order"):
        validate_gate_report_semantics(report)


@pytest.mark.parametrize(
    "fixture_path",
    sorted(SEMANTIC_INVALID_DIR.glob("*.json")),
    ids=lambda path: path.name,
)
def test_python_rejects_shared_semantic_invalid_vectors(fixture_path: Path) -> None:
    report = _read(fixture_path)
    _validator().validate(report)

    with pytest.raises(GateReportError):
        validate_gate_report_semantics(report)


@pytest.mark.parametrize("fixture_name", SEMANTIC_SCHEMA_INVALID_NAMES)
def test_python_semantics_reject_schema_guard_regressions(fixture_name: str) -> None:
    report = _read(INVALID_DIR / fixture_name)
    assert list(_validator().iter_errors(report))

    with pytest.raises(GateReportError):
        validate_gate_report_semantics(report)


def test_markdown_renderer_matches_the_committed_golden_byte_for_byte() -> None:
    report = _read(VALID_DIR / "blocked-candidate.json")
    expected = (VALID_DIR / "blocked-candidate.md").read_text(encoding="utf-8")

    first = render_gate_report_markdown(report)
    second = render_gate_report_markdown(copy.deepcopy(report))

    assert first == second == expected
