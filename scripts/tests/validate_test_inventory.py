"""Validate the test inventory, migration gates, and repository coverage."""

from __future__ import annotations

import argparse
import glob
import json
from collections.abc import Iterable
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INVENTORY = ROOT / "tests/test-inventory.json"
DEFAULT_SCHEMA = ROOT / "tests/contracts/test-inventory.schema.json"


class InventoryError(ValueError):
    """Raised when the inventory cannot safely drive test migration."""


def load_inventory(path: Path = DEFAULT_INVENTORY) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _schema_validate(inventory: dict[str, Any], schema_path: Path) -> None:
    try:
        import jsonschema
    except ModuleNotFoundError:
        required = {
            "schemaVersion",
            "updatedAt",
            "evidence",
            "suites",
            "baselineTests",
            "knownGaps",
        }
        missing = required - inventory.keys()
        if missing:
            raise InventoryError(
                f"inventory is missing required keys: {sorted(missing)}"
            )
        return

    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    try:
        jsonschema.Draft202012Validator(schema).validate(inventory)
    except jsonschema.ValidationError as exc:
        location = ".".join(str(part) for part in exc.absolute_path) or "<root>"
        raise InventoryError(f"schema violation at {location}: {exc.message}") from exc


def _matching_paths(pattern: str) -> set[str]:
    absolute_pattern = str(ROOT / pattern)
    return {
        str(Path(match).resolve().relative_to(ROOT))
        for match in glob.glob(absolute_pattern, recursive=True)
        if Path(match).is_file()
    }


def _discover_test_files() -> set[str]:
    files = {
        str(path.relative_to(ROOT))
        for path in (ROOT / "src/pipeline/tests").rglob("test_*.py")
    }
    files.update(
        str(path.relative_to(ROOT))
        for path in (ROOT / "src/frontend/src").rglob("*.test.ts")
    )
    files.update(
        str(path.relative_to(ROOT))
        for path in (ROOT / "src/frontend/src").rglob("*.test.tsx")
    )
    files.update(
        str(path.relative_to(ROOT))
        for path in (ROOT / "src/frontend/scripts").rglob("test-*.py")
    )
    files.update(
        str(path.relative_to(ROOT))
        for pattern in ("*.test.ts", "*.test.tsx")
        for path in (ROOT / "src/web/src").rglob(pattern)
    )
    files.update(
        str(path.relative_to(ROOT))
        for path in (ROOT / "src/web/scripts").rglob("*.test.mjs")
    )
    files.update(
        str(path.relative_to(ROOT))
        for path in (ROOT / "src/web/tests").rglob("*.spec.ts")
    )
    files.update(
        str(path.relative_to(ROOT))
        for path in (ROOT / "tests/harness").rglob("test_*.py")
    )
    files.update(
        str(path.relative_to(ROOT))
        for path in (ROOT / "tests/repository-removal").rglob("test_*.py")
    )
    for path in (ROOT / "src/api/SeaRise.Api.Tests").rglob("*.cs"):
        content = path.read_text(encoding="utf-8")
        if "[Fact]" in content or "[Theory]" in content:
            files.add(str(path.relative_to(ROOT)))
    compose_smoke = ROOT / "scripts/compose-smoke.sh"
    if compose_smoke.is_file():
        files.add("scripts/compose-smoke.sh")
    return files


def _duplicates(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    return sorted(duplicates)


def validate_inventory(
    inventory: dict[str, Any],
    schema_path: Path = DEFAULT_SCHEMA,
    *,
    now: datetime | None = None,
) -> list[str]:
    _schema_validate(inventory, schema_path)
    errors: list[str] = []
    suites = inventory["suites"]
    evidence = inventory["evidence"]
    current_time = now or datetime.now(timezone.utc)
    if current_time.tzinfo is None:
        raise InventoryError("inventory validation time must include a timezone")
    for evidence_id, record in evidence.items():
        try:
            observed_at = datetime.fromisoformat(
                record["observedAt"].replace("Z", "+00:00")
            )
        except (TypeError, ValueError):
            errors.append(
                f"{evidence_id}: observedAt is not a valid timezone-aware timestamp"
            )
            continue
        if observed_at.tzinfo is None:
            errors.append(f"{evidence_id}: observedAt must include a timezone")
        elif observed_at > current_time + timedelta(minutes=5):
            errors.append(f"{evidence_id}: observedAt is in the future")

    duplicate_ids = _duplicates(suite["id"] for suite in suites)
    if duplicate_ids:
        errors.append(f"duplicate suite ids: {duplicate_ids}")

    covered: set[str] = set()
    for suite in suites:
        suite_id = suite["id"]
        status = suite["status"]
        matched: set[str] = set()
        for pattern in suite["sourcePaths"]:
            matches = _matching_paths(pattern)
            if status == "active" and not matches:
                errors.append(
                    f"{suite_id}: sourcePaths pattern matches no files: {pattern}"
                )
            matched.update(matches)
        if status == "active":
            covered.update(matched)

        if status == "retired":
            if suite["removalGate"] is None or suite["replacementEvidence"] is None:
                errors.append(f"{suite_id}: retired suite requires gate and evidence")
        elif (
            suite["removalGate"] is not None or suite["replacementEvidence"] is not None
        ):
            errors.append(f"{suite_id}: active suite cannot carry retirement metadata")

        if suite["cost"]["evidenceRef"] not in evidence:
            errors.append(f"{suite_id}: cost evidenceRef does not exist")
        if suite["disposition"] == "keep-permanently":
            if suite["replacementGate"]["issue"] is not None:
                errors.append(
                    f"{suite_id}: permanent suite must not have a deletion issue"
                )
        elif suite["replacementGate"]["issue"] is None:
            errors.append(f"{suite_id}: migratable suite requires a replacement issue")

        execution = suite["execution"]
        if (
            execution["tier"] == "fast"
            and not execution["requiresDocker"]
            and not execution["requiresCredentials"]
            and suite["commands"]["focused"] is None
        ):
            errors.append(
                f"{suite_id}: credential-free fast suite requires a focused command"
            )

        flake = suite["flakiness"]
        if flake["status"] == "quarantined":
            if flake["issue"] is None or flake["expiresAt"] is None:
                errors.append(f"{suite_id}: quarantine requires issue and expiry")
            elif date.fromisoformat(flake["expiresAt"]) <= date.fromisoformat(
                inventory["updatedAt"]
            ):
                errors.append(f"{suite_id}: quarantine is expired at inventory update")
        elif flake["issue"] is not None or flake["expiresAt"] is not None:
            errors.append(
                f"{suite_id}: non-quarantined suite cannot carry quarantine metadata"
            )

    discovered = _discover_test_files()
    uncovered = sorted(discovered - covered)
    if uncovered:
        errors.append(f"test files missing from inventory: {uncovered}")

    suite_by_id = {suite["id"]: suite for suite in suites}
    suite_ids = set(suite_by_id)
    baseline = inventory["baselineTests"]
    duplicate_paths = _duplicates(item["path"] for item in baseline)
    if duplicate_paths:
        errors.append(f"duplicate baseline test paths: {duplicate_paths}")
    active_paths = {item["path"] for item in baseline if item["status"] == "active"}
    if active_paths != discovered:
        missing = sorted(discovered - active_paths)
        removed = sorted(active_paths - discovered)
        if missing:
            errors.append(f"new tests require an inventory baseline entry: {missing}")
        if removed:
            errors.append(
                f"baseline tests removed without retirement evidence: {removed}"
            )
    for item in baseline:
        if item["suite"] not in suite_ids:
            errors.append(f"{item['path']}: unknown suite {item['suite']}")
        elif (
            item["status"] == "active"
            and suite_by_id[item["suite"]]["status"] == "retired"
        ):
            errors.append(f"{item['path']}: active baseline is owned by retired suite")
        if item["status"] == "retired":
            if item["removalGate"] is None or item["replacementEvidence"] is None:
                errors.append(
                    f"{item['path']}: retired test requires gate and evidence"
                )
            if item["path"] in discovered:
                errors.append(
                    f"{item['path']}: on-disk test cannot be declared retired"
                )
        elif item["replacementEvidence"] is not None:
            errors.append(
                f"{item['path']}: active test cannot claim replacement evidence"
            )
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY)
    parser.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA)
    args = parser.parse_args()

    inventory = load_inventory(args.inventory)
    errors = validate_inventory(inventory, args.schema)
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print(f"validated {len(inventory['suites'])} inventoried suites")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
