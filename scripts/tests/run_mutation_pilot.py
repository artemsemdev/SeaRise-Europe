"""Bounded, repeatable mutation pilot for the pure five-state domain rule."""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
TARGET = ROOT / "src/pipeline/searise_pipeline/domain/result_state.py"
FIXTURE = ROOT / "tests/fixtures/tdd/five-state-characterization-v1.json"
DEFAULT_REPORT = ROOT / "tests/evidence/mutation-pilot-result-state.json"


@dataclass(frozen=True)
class Mutation:
    id: str
    before: str
    after: str
    risk: str


MUTATIONS = (
    Mutation(
        "invert-europe-support",
        "if not sample.in_europe:",
        "if sample.in_europe:",
        "Unsupported coordinates could be accepted as modeled Europe.",
    ),
    Mutation(
        "invert-coastal-scope",
        "if sample.in_coastal_zone is False:",
        "if sample.in_coastal_zone is True:",
        "Inland and coastal result states could be exchanged.",
    ),
    Mutation(
        "accept-unknown-coastal-scope",
        "if sample.in_coastal_zone is not True:",
        "if sample.in_coastal_zone is False:",
        "Unknown coastal membership could reach class interpretation.",
    ),
    Mutation(
        "invert-nodata-check",
        "if class_value is None:",
        "if class_value is not None:",
        "Missing data could be reported as a modeled class.",
    ),
    Mutation(
        "swap-exposed-class",
        "if class_value == 1:",
        "if class_value == 0:",
        "The exact exposed and non-exposed class semantics could be swapped.",
    ),
    Mutation(
        "collapse-non-exposed-state",
        'return "NoModeledExposureDetected"',
        'return "ModeledExposureDetected"',
        "A non-exposed cell could be presented as modeled exposure.",
    ),
    Mutation(
        "drop-class-interpretation",
        "return _state_for_class(sample.class_value)",
        'return "DataUnavailable"',
        "Valid coastal class evidence could be discarded.",
    ),
)


def _load_module(path: Path, module_name: str) -> Any:
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load mutated module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
        return module
    finally:
        sys.modules.pop(module_name, None)


def _assert_fixture(module: Any) -> None:
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    for case in fixture["cases"]:
        sample = module.AssessmentSample(
            in_europe=case["input"]["inEurope"],
            in_coastal_zone=case["input"]["inCoastalZone"],
            class_value=case["input"]["classValue"],
        )
        actual = module.determine_result_state(sample)
        if actual != case["expectedState"]:
            raise AssertionError(
                f"{case['id']}: expected {case['expectedState']}, got {actual}"
            )


def run_pilot() -> dict[str, Any]:
    source = TARGET.read_text(encoding="utf-8")
    started = time.perf_counter()
    results = []
    with tempfile.TemporaryDirectory(prefix="searise-mutation-") as temp_dir:
        temp_path = Path(temp_dir) / "result_state.py"
        temp_path.write_text(source, encoding="utf-8")
        _assert_fixture(_load_module(temp_path, "searise_mutation_baseline"))

        for index, mutation in enumerate(MUTATIONS):
            if source.count(mutation.before) != 1:
                raise RuntimeError(
                    f"{mutation.id}: expected one mutation target, found "
                    f"{source.count(mutation.before)}"
                )
            temp_path.write_text(
                source.replace(mutation.before, mutation.after, 1),
                encoding="utf-8",
            )
            try:
                _assert_fixture(_load_module(temp_path, f"searise_mutant_{index}"))
            except (AssertionError, ValueError) as exc:
                status = "killed"
                reason = f"{type(exc).__name__}: {exc}"
            else:
                status = "survived"
                reason = "all shared fixture cases passed"
            results.append({**asdict(mutation), "status": status, "reason": reason})

    killed = sum(result["status"] == "killed" for result in results)
    return {
        "pilotId": "pipeline-result-state-v1",
        "target": str(TARGET.relative_to(ROOT)),
        "fixture": str(FIXTURE.relative_to(ROOT)),
        "mutants": results,
        "total": len(results),
        "killed": killed,
        "scorePercent": round(100 * killed / len(results), 1),
        "survivingCriticalMutations": [
            result["id"] for result in results if result["status"] == "survived"
        ],
        "runtimeMs": round((time.perf_counter() - started) * 1000, 2),
    }


def _verify_report(actual: dict[str, Any], expected: dict[str, Any]) -> list[str]:
    stable_fields = ("pilotId", "target", "fixture", "total", "killed", "scorePercent")
    errors = [
        f"{field}: expected {expected.get(field)!r}, got {actual.get(field)!r}"
        for field in stable_fields
        if actual.get(field) != expected.get(field)
    ]
    if actual["survivingCriticalMutations"] != expected["survivingCriticalMutations"]:
        errors.append("surviving critical mutation set changed")
    if [item["id"] for item in actual["mutants"]] != [
        item["id"] for item in expected["mutants"]
    ]:
        errors.append("mutant definitions changed without updating the reviewed report")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--verify-report", type=Path, default=None)
    args = parser.parse_args()

    actual = run_pilot()
    if args.verify_report:
        expected = json.loads(args.verify_report.read_text(encoding="utf-8"))
        errors = _verify_report(actual, expected)
        if errors:
            for error in errors:
                print(f"ERROR: {error}")
            return 1
    print(json.dumps(actual, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
