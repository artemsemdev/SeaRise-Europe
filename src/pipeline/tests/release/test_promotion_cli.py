"""Test the raw-evidence promotion command boundary."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from searise_pipeline.release.evidence import write_new_json_record
from searise_pipeline.science import ScienceContractError

from .test_recovery_gate import _promotion_inputs, _write_json

REPOSITORY_ROOT = Path(__file__).parents[4]


def _load_finalizer_cli():
    script_path = REPOSITORY_ROOT / "scripts/science/finalize_ar6_regional_release.py"
    spec = importlib.util.spec_from_file_location("searise_ar6_finalizer_cli", script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load finalizer CLI from {script_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


finalizer_cli = _load_finalizer_cli()


@pytest.mark.parametrize("record_name", ["output", "failure"])
def test_finalizer_cli_rejects_records_inside_candidate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    record_name: str,
) -> None:
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    records = {
        "output": tmp_path / "automated-gate.json",
        "failure": tmp_path / "failure-gate.json",
    }
    records[record_name] = candidate / f"{record_name}.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "finalize_ar6_regional_release.py",
            "--candidate",
            str(candidate),
            "--release-contract",
            "unused",
            "--reproducibility-report",
            "unused",
            "--delivery-trace",
            "unused",
            "--build-timing",
            "unused",
            "--harness",
            "unused",
            "--repository-root",
            str(REPOSITORY_ROOT),
            "--output",
            str(records["output"]),
            "--failure-gate",
            str(records["failure"]),
        ],
    )

    with pytest.raises(ScienceContractError, match="outside the immutable candidate"):
        finalizer_cli.main()

    assert not records["output"].exists()
    assert not records["failure"].exists()


def test_malformed_reproducibility_status_writes_immutable_failure_gate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inputs = _promotion_inputs(tmp_path)
    reproducibility = inputs["reproducibility"]
    report = json.loads(reproducibility.read_text(encoding="utf-8"))
    report["status"] = []
    _write_json(reproducibility, report)
    output = tmp_path / "automated-gate.json"
    failure = tmp_path / "failure-gate.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "finalize_ar6_regional_release.py",
            "--candidate",
            str(inputs["candidate"]),
            "--release-contract",
            str(REPOSITORY_ROOT / "src/pipeline/science/ar6-regional-release.json"),
            "--reproducibility-report",
            str(reproducibility),
            "--delivery-trace",
            str(inputs["trace"]),
            "--build-timing",
            str(inputs["timing"]),
            "--harness",
            str(inputs["harness"]),
            "--repository-root",
            str(REPOSITORY_ROOT),
            "--output",
            str(output),
            "--failure-gate",
            str(failure),
        ],
    )

    with pytest.raises(SystemExit) as raised:
        finalizer_cli.main()

    assert raised.value.code == 1
    assert not output.exists()
    blocked = json.loads(failure.read_text(encoding="utf-8"))
    assert blocked["automatedValidation"] == "failed"
    assert blocked["blockingChecks"] == ["promotionInputValidation"]
    assert blocked["failure"]["type"] == "ScienceContractError"
    with pytest.raises(ScienceContractError, match="already exists"):
        write_new_json_record(failure, {"forged": True})
