"""Validate the immutable repository-removal approval chain.

The inventory, evidence receipt, and owner decision are read from committed Git
blobs.  Repository ownership is evaluated against the inventory's exact audited
commit, never against mutable worktree existence.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import subprocess
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from typing import Any

import jsonschema

ROOT = Path(__file__).resolve().parents[2]
CONTRACT_ROOT = ROOT / "contracts/repository-removal/v1"
DEFAULT_INVENTORY = CONTRACT_ROOT / "inventory.json"
DEFAULT_EVIDENCE = CONTRACT_ROOT / "evidence-receipt.json"
DEFAULT_DECISION = CONTRACT_ROOT / "owner-decision.json"
DEFAULT_HISTORICAL_ALLOWLIST = CONTRACT_ROOT / "historical-allowlist.json"
DEFAULT_INVENTORY_SCHEMA = CONTRACT_ROOT / "inventory.schema.json"
DEFAULT_EVIDENCE_SCHEMA = CONTRACT_ROOT / "evidence-receipt.schema.json"
DEFAULT_DECISION_SCHEMA = CONTRACT_ROOT / "owner-decision.schema.json"
DEFAULT_HISTORICAL_ALLOWLIST_SCHEMA = CONTRACT_ROOT / "historical-allowlist.schema.json"
DEFAULT_CENSUS = CONTRACT_ROOT / "census.json"
DEFAULT_CENSUS_SCHEMA = CONTRACT_ROOT / "census.schema.json"
DEFAULT_CHECK_OUTPUT_SCHEMA = CONTRACT_ROOT / "check-output.schema.json"
DEFAULT_VALIDATOR = ROOT / "scripts/repository/validate_removal_approval.py"
DEFAULT_TEST_INVENTORY = ROOT / "tests/test-inventory.json"
DEFAULT_REPLACEMENT_MATRIX = ROOT / "docs/testing/legacy-runtime-removal-matrix.md"

ACTIVE_TARGET_ROOTS = ("src/web/", "src/pipeline/searise_pipeline/")
FORBIDDEN_EVIDENCE_COMMAND = re.compile(
    r"(?:candidate[-_ ]?v7|\.tar(?:\b|\.gz\b)|"
    r"\b(?:upload|publish|destroy|delete|secret|rm|mv|cp|scp|rsync|rclone)\b|"
    r"\b(?:curl|wget|aws|az)\b|gh\s+(?:secret|variable|environment|release)|"
    r"git\s+push|docker\s+push|terraform\s+(?:apply|destroy))",
    re.IGNORECASE,
)


class RemovalApprovalError(ValueError):
    """Raised when approval inputs cannot be interpreted safely."""


def _git(repository_root: Path, *arguments: str) -> bytes:
    try:
        result = subprocess.run(
            ["git", *arguments],
            cwd=repository_root,
            check=True,
            capture_output=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        detail = ""
        if isinstance(exc, subprocess.CalledProcessError):
            detail = exc.stderr.decode("utf-8", errors="replace").strip()
        suffix = f": {detail}" if detail else ""
        raise RemovalApprovalError(
            f"git {' '.join(arguments)} failed{suffix}"
        ) from exc
    return result.stdout


def _repository_path(repository_root: Path, path: Path) -> str:
    root = repository_root.resolve()
    candidate = path if path.is_absolute() else root / path
    try:
        relative = candidate.resolve().relative_to(root)
    except ValueError as exc:
        raise RemovalApprovalError(f"input is outside repository: {path}") from exc
    return relative.as_posix()


def _committed_blob(
    repository_root: Path,
    path: Path,
    *,
    required: bool,
) -> bytes | None:
    logical_path = _repository_path(repository_root, path)
    try:
        return _git(repository_root, "show", f"HEAD:{logical_path}")
    except RemovalApprovalError:
        if required:
            raise RemovalApprovalError(
                f"required committed file is absent at HEAD: {logical_path}"
            )
        return None


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise RemovalApprovalError(f"JSON object contains duplicate key: {key}")
        result[key] = value
    return result


def _load_document(document: bytes, logical_name: str) -> dict[str, Any]:
    try:
        value = json.loads(document, object_pairs_hook=_reject_duplicate_keys)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RemovalApprovalError(f"{logical_name} is not valid UTF-8 JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise RemovalApprovalError(f"{logical_name} must be a JSON object")
    return value


def _schema_errors(
    document: dict[str, Any], schema: dict[str, Any], logical_name: str
) -> list[str]:
    try:
        jsonschema.Draft202012Validator.check_schema(schema)
    except jsonschema.SchemaError as exc:
        raise RemovalApprovalError(f"{logical_name} schema is invalid: {exc.message}") from exc
    validator = jsonschema.Draft202012Validator(
        schema,
        format_checker=jsonschema.FormatChecker(),
    )
    errors: list[str] = []
    for error in sorted(validator.iter_errors(document), key=lambda item: list(item.path)):
        location = ".".join(str(part) for part in error.absolute_path) or "<root>"
        errors.append(f"{logical_name} schema violation at {location}: {error.message}")
    return errors


def _duplicates(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    return sorted(duplicates)


def _matches_source_pattern(path: str, pattern: str) -> bool:
    """Match repository paths with slash-aware `*`, `?`, and recursive `**`."""

    expression = ""
    index = 0
    while index < len(pattern):
        if pattern.startswith("**/", index):
            expression += "(?:.*/)?"
            index += 3
        elif pattern.startswith("**", index):
            expression += ".*"
            index += 2
        elif pattern[index] == "*":
            expression += "[^/]*"
            index += 1
        elif pattern[index] == "?":
            expression += "[^/]"
            index += 1
        else:
            expression += re.escape(pattern[index])
            index += 1
    return re.fullmatch(expression, path) is not None


def _tracked_blobs(repository_root: Path, commit: str) -> dict[str, str]:
    # cat-file rejects a syntactically valid but unavailable/non-commit object.
    _git(repository_root, "cat-file", "-e", f"{commit}^{{commit}}")
    output = _git(repository_root, "ls-tree", "-r", "-z", commit)
    blobs: dict[str, str] = {}
    for entry in output.split(b"\0"):
        if not entry:
            continue
        metadata, encoded_path = entry.split(b"\t", maxsplit=1)
        _mode, object_type, object_id = metadata.decode("ascii").split(" ")
        if object_type == "blob":
            blobs[encoded_path.decode("utf-8", errors="strict")] = object_id
    return blobs


def _tree_sha(repository_root: Path, commit: str) -> str:
    return _git(repository_root, "rev-parse", f"{commit}^{{tree}}").decode().strip()


def _audited_blob(repository_root: Path, commit: str, path: str) -> bytes:
    try:
        return _git(repository_root, "show", f"{commit}:{path}")
    except RemovalApprovalError as exc:
        raise RemovalApprovalError(
            f"audited blob cannot be read at {commit}:{path}"
        ) from exc


def _workflow_job_count(source: bytes, job_id: str) -> int:
    try:
        lines = source.decode("utf-8").splitlines()
    except UnicodeDecodeError as exc:
        raise RemovalApprovalError("workflow selector source is not UTF-8") from exc
    jobs_indexes = [index for index, line in enumerate(lines) if line.rstrip() == "jobs:"]
    if len(jobs_indexes) != 1:
        raise RemovalApprovalError("workflow must contain exactly one top-level jobs mapping")
    count = 0
    child_indent: int | None = None
    for line in lines[jobs_indexes[0] + 1 :]:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip(" "))
        if indent == 0:
            break
        if child_indent is None:
            child_indent = indent
        if indent != child_indent:
            continue
        match = re.fullmatch(r"[ ]*([A-Za-z0-9_-]+):(?:[ ]*#.*)?", line)
        if match and match.group(1) == job_id:
            count += 1
    return count


def _python_assignment_count(source: bytes, name: str) -> int:
    try:
        module = ast.parse(source.decode("utf-8"))
    except (SyntaxError, UnicodeDecodeError) as exc:
        raise RemovalApprovalError("Python selector source cannot be parsed") from exc
    count = 0
    for statement in module.body:
        targets: list[ast.expr] = []
        if isinstance(statement, ast.Assign):
            targets = statement.targets
        elif isinstance(statement, ast.AnnAssign):
            targets = [statement.target]
        count += sum(isinstance(target, ast.Name) and target.id == name for target in targets)
    return count


def _python_package_count(source: bytes, package: str) -> int:
    try:
        text = source.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RemovalApprovalError("Python dependency selector source is not UTF-8") from exc
    normalized = package.lower().replace("_", "-").replace(".", "-")
    count = 0
    for raw_line in text.splitlines():
        line = raw_line.split("#", maxsplit=1)[0]
        for match in re.finditer(r"[A-Za-z0-9][A-Za-z0-9_.-]*", line):
            candidate = match.group(0).lower().replace("_", "-").replace(".", "-")
            if candidate == normalized:
                count += 1
    return count


def _toml_section(source: bytes, section: str) -> list[str]:
    try:
        lines = source.decode("utf-8").splitlines()
    except UnicodeDecodeError as exc:
        raise RemovalApprovalError("TOML selector source is not UTF-8") from exc
    header = f"[{section}]"
    indexes = [index for index, line in enumerate(lines) if line.strip() == header]
    if len(indexes) != 1:
        raise RemovalApprovalError(f"TOML must contain exactly one {header} section")
    result: list[str] = []
    for line in lines[indexes[0] + 1 :]:
        if re.fullmatch(r"\s*\[[^]]+\]\s*(?:#.*)?", line):
            break
        result.append(line.split("#", maxsplit=1)[0])
    return result


def _setuptools_package_count(source: bytes, package: str) -> int:
    section = "\n".join(_toml_section(source, "tool.setuptools"))
    matches = re.findall(
        r"(?ms)^\s*packages\s*=\s*\[(.*?)\]",
        section,
    )
    if len(matches) != 1:
        raise RemovalApprovalError("TOML must contain exactly one setuptools packages array")
    return sum(
        value == package
        for value in re.findall(r"['\"]([^'\"]+)['\"]", matches[0])
    )


def _setuptools_package_dir_count(source: bytes, package: str) -> int:
    section = _toml_section(source, "tool.setuptools.package-dir")
    key = re.escape(package)
    return sum(
        re.fullmatch(rf"\s*{key}\s*=\s*['\"][^'\"]+['\"]\s*", line) is not None
        for line in section
    )


def _selector_count(kind: str, value: str, source: bytes) -> int:
    if kind == "workflow-job":
        return _workflow_job_count(source, value)
    if kind == "python-assignment":
        return _python_assignment_count(source, value)
    if kind == "python-package":
        return _python_package_count(source, value)
    if kind == "setuptools-package":
        return _setuptools_package_count(source, value)
    if kind == "setuptools-package-dir":
        return _setuptools_package_dir_count(source, value)
    raise RemovalApprovalError(f"unsupported canonical selector kind: {kind}")


def _canonical_census(
    census: Mapping[str, Any],
    *,
    repository_root: Path,
    audited_commit: str,
    tracked: Mapping[str, str],
) -> tuple[dict[str, int], list[str]]:
    owners: dict[str, int] = {}
    errors: list[str] = []
    excluded_paths: set[str] = set()

    def assign(key: str, owner: int) -> None:
        if key in owners:
            errors.append(f"canonical census locator assigned more than once: {key}")
        else:
            owners[key] = owner

    for issue in census.get("issues", []):
        owner = issue["ownerIssue"]
        roots = issue["roots"]
        paths = issue["paths"]
        selectors = issue["selectors"]
        if paths != sorted(paths):
            errors.append(f"canonical census issue #{owner} paths must be sorted")
        selector_order = [(item["path"], item["kind"], item["value"]) for item in selectors]
        if selector_order != sorted(selector_order):
            errors.append(f"canonical census issue #{owner} selectors must be sorted")
        for root in roots:
            prefix = root["path"].rstrip("/") + "/"
            excluded = set(root["excludePaths"])
            excluded_paths.update(excluded)
            if root["excludePaths"] != sorted(excluded):
                errors.append(
                    f"canonical census root exclusions must be sorted: {root['path']}"
                )
            matched = sorted(path for path in tracked if path.startswith(prefix))
            if not matched:
                errors.append(f"canonical census root matches no audited blobs: {root['path']}")
            invalid_exclusions = sorted(
                path for path in excluded if path not in matched or not path.startswith(prefix)
            )
            if invalid_exclusions:
                errors.append(
                    f"canonical census root has invalid exclusions: {invalid_exclusions}"
                )
            for path in matched:
                if path not in excluded:
                    assign(f"{path}\0", owner)
        for path in paths:
            if path not in tracked:
                errors.append(f"canonical census path is not tracked: {path}")
            else:
                assign(f"{path}\0", owner)
        for selector in selectors:
            path = selector["path"]
            kind = selector["kind"]
            value = selector["value"]
            if path not in tracked:
                errors.append(f"canonical selector path is not tracked: {path}")
                continue
            try:
                count = _selector_count(
                    kind,
                    value,
                    _audited_blob(repository_root, audited_commit, path),
                )
            except RemovalApprovalError as exc:
                errors.append(str(exc))
                continue
            if count != 1:
                errors.append(
                    f"canonical selector must exist exactly once: {path} {kind}:{value} "
                    f"count={count}"
                )
            assign(f"{path}\0{kind}:{value}", owner)
    unassigned_exclusions = sorted(
        path for path in excluded_paths if f"{path}\0" not in owners
    )
    if unassigned_exclusions:
        errors.append(
            "canonical census exclusions must be assigned as exact paths: "
            f"{unassigned_exclusions}"
        )
    return owners, errors


def _fetch_github_owner_comment(comment_id: int) -> Mapping[str, Any]:
    try:
        output = subprocess.run(
            [
                "gh",
                "api",
                "--method",
                "GET",
                f"repos/artemsemdev/SeaRise-Europe/issues/comments/{comment_id}",
            ],
            check=True,
            capture_output=True,
        ).stdout
        comment = json.loads(output)
    except (OSError, subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        raise RemovalApprovalError("live GitHub owner comment cannot be verified") from exc
    if not isinstance(comment, dict):
        raise RemovalApprovalError("live GitHub owner comment response is malformed")
    return comment


def _sha256(document: bytes) -> str:
    return hashlib.sha256(document).hexdigest()


def expected_approval_text(
    audited_commit: str,
    inventory_sha256: str,
    evidence_sha256: str,
) -> str:
    """Return the only owner text that authorizes repository dispositions."""

    return (
        "I approve repository-removal inventory v1 for issues #70, #71, and #72 "
        f"at commit {audited_commit}, inventory SHA-256 {inventory_sha256}, and "
        f"evidence receipt SHA-256 {evidence_sha256}. This authorizes only the "
        "listed repository dispositions. It does not authorize Candidate-v7 "
        "publication/upload or deletion/mutation of any external resource, "
        "credential, GitHub environment, or secret."
    )


def validate_removal_approval(
    *,
    repository_root: Path = ROOT,
    inventory_path: Path = DEFAULT_INVENTORY,
    evidence_path: Path = DEFAULT_EVIDENCE,
    decision_path: Path = DEFAULT_DECISION,
    historical_allowlist_path: Path = DEFAULT_HISTORICAL_ALLOWLIST,
    inventory_schema_path: Path = DEFAULT_INVENTORY_SCHEMA,
    evidence_schema_path: Path = DEFAULT_EVIDENCE_SCHEMA,
    decision_schema_path: Path = DEFAULT_DECISION_SCHEMA,
    historical_allowlist_schema_path: Path = DEFAULT_HISTORICAL_ALLOWLIST_SCHEMA,
    census_path: Path = DEFAULT_CENSUS,
    census_schema_path: Path = DEFAULT_CENSUS_SCHEMA,
    check_output_schema_path: Path = DEFAULT_CHECK_OUTPUT_SCHEMA,
    validator_path: Path = DEFAULT_VALIDATOR,
    test_inventory_path: Path = DEFAULT_TEST_INVENTORY,
    replacement_matrix_path: Path = DEFAULT_REPLACEMENT_MATRIX,
    allow_unapproved: bool = False,
    verify_owner_comment: bool = False,
    owner_comment_fetcher: Callable[[int], Mapping[str, Any]] | None = None,
) -> list[str]:
    """Return every approval-chain error in deterministic order."""

    repository_root = repository_root.resolve()
    inventory_bytes = _committed_blob(repository_root, inventory_path, required=True)
    evidence_bytes = _committed_blob(repository_root, evidence_path, required=True)
    decision_bytes = _committed_blob(repository_root, decision_path, required=False)
    historical_allowlist_bytes = _committed_blob(
        repository_root, historical_allowlist_path, required=True
    )
    inventory_schema_bytes = _committed_blob(
        repository_root, inventory_schema_path, required=True
    )
    evidence_schema_bytes = _committed_blob(
        repository_root, evidence_schema_path, required=True
    )
    decision_schema_bytes = _committed_blob(
        repository_root, decision_schema_path, required=True
    )
    historical_allowlist_schema_bytes = _committed_blob(
        repository_root, historical_allowlist_schema_path, required=True
    )
    census_bytes = _committed_blob(repository_root, census_path, required=True)
    census_schema_bytes = _committed_blob(
        repository_root, census_schema_path, required=True
    )
    check_output_schema_bytes = _committed_blob(
        repository_root, check_output_schema_path, required=True
    )
    test_inventory_bytes = _committed_blob(
        repository_root, test_inventory_path, required=True
    )
    assert inventory_bytes is not None
    assert evidence_bytes is not None
    assert historical_allowlist_bytes is not None
    assert inventory_schema_bytes is not None
    assert evidence_schema_bytes is not None
    assert decision_schema_bytes is not None
    assert historical_allowlist_schema_bytes is not None
    assert census_bytes is not None
    assert census_schema_bytes is not None
    assert check_output_schema_bytes is not None
    assert test_inventory_bytes is not None

    inventory = _load_document(inventory_bytes, "inventory")
    evidence = _load_document(evidence_bytes, "evidence receipt")
    historical_allowlist = _load_document(
        historical_allowlist_bytes, "historical allowlist"
    )
    inventory_schema = _load_document(inventory_schema_bytes, "inventory schema")
    evidence_schema = _load_document(evidence_schema_bytes, "evidence receipt schema")
    decision_schema = _load_document(decision_schema_bytes, "owner decision schema")
    historical_allowlist_schema = _load_document(
        historical_allowlist_schema_bytes, "historical allowlist schema"
    )
    census = _load_document(census_bytes, "canonical census")
    census_schema = _load_document(census_schema_bytes, "canonical census schema")
    check_output_schema = _load_document(
        check_output_schema_bytes, "check output schema"
    )
    test_inventory = _load_document(test_inventory_bytes, "test inventory")
    decision = (
        _load_document(decision_bytes, "owner decision")
        if decision_bytes is not None
        else None
    )

    errors = _schema_errors(inventory, inventory_schema, "inventory")
    errors.extend(_schema_errors(evidence, evidence_schema, "evidence receipt"))
    errors.extend(
        _schema_errors(
            historical_allowlist,
            historical_allowlist_schema,
            "historical allowlist",
        )
    )
    census_schema_errors = _schema_errors(census, census_schema, "canonical census")
    errors.extend(census_schema_errors)
    if decision is not None:
        errors.extend(_schema_errors(decision, decision_schema, "owner decision"))

    # Continue semantic checks only for fields whose basic shape is available.
    items = inventory.get("items")
    audited_commit = inventory.get("auditedCommit")
    checks = evidence.get("checks")
    receipt_check_ids = (
        {
            check["id"]
            for check in checks
            if isinstance(check, dict) and isinstance(check.get("id"), str)
        }
        if isinstance(checks, list)
        else set()
    )
    receipt_checks_by_id = (
        {
            check["id"]: check
            for check in checks
            if isinstance(check, dict) and isinstance(check.get("id"), str)
        }
        if isinstance(checks, list)
        else {}
    )
    suites = test_inventory.get("suites")
    baseline_tests = test_inventory.get("baselineTests")
    suites_by_id = (
        {
            suite["id"]: suite
            for suite in suites
            if isinstance(suite, dict) and isinstance(suite.get("id"), str)
        }
        if isinstance(suites, list)
        else {}
    )
    baseline_suite_by_path = (
        {
            baseline["path"]: baseline["suite"]
            for baseline in baseline_tests
            if isinstance(baseline, dict)
            and isinstance(baseline.get("path"), str)
            and isinstance(baseline.get("suite"), str)
        }
        if isinstance(baseline_tests, list)
        else {}
    )
    tracked: dict[str, str] | None = None
    census_suite_policy_by_issue: dict[int, tuple[set[str], set[str]]] = {}
    if not census_schema_errors:
        for issue in census["issues"]:
            owner = issue["ownerIssue"]
            allowed_values = issue["allowedReplacementSuiteIds"]
            required_values = issue["requiredReplacementSuiteIds"]
            if allowed_values != sorted(allowed_values):
                errors.append(
                    f"canonical census issue #{owner} allowedReplacementSuiteIds "
                    "must be sorted"
                )
            if required_values != sorted(required_values):
                errors.append(
                    f"canonical census issue #{owner} requiredReplacementSuiteIds "
                    "must be sorted"
                )
            allowed = set(allowed_values)
            required = set(required_values)
            if not required.issubset(allowed):
                errors.append(
                    f"canonical census issue #{owner} required replacement suites "
                    "must be allowed"
                )
            census_suite_policy_by_issue[owner] = (allowed, required)
    if isinstance(items, list) and all(isinstance(item, dict) for item in items):
        item_ids = [item.get("id") for item in items]
        string_ids = [item_id for item_id in item_ids if isinstance(item_id, str)]
        duplicate_ids = _duplicates(string_ids)
        if duplicate_ids:
            errors.append(f"duplicate inventory item ids: {duplicate_ids}")
        if len(string_ids) == len(items) and string_ids != sorted(string_ids):
            errors.append("inventory items must be sorted by id")

        global_locator_keys: list[str] = []
        delete_locator_keys: list[str] = []
        delete_locator_owners: dict[str, int] = {}
        mapped_replacement_suites_by_issue: dict[int, set[str]] = {
            70: set(),
            71: set(),
            72: set(),
        }
        mapped_replacement_checks: list[str] = []
        mapped_retirement_suites: list[str] = []
        target_owner_paths: list[str] = []
        historical_inventory: dict[str, tuple[str, str]] = {}
        for item in items:
            item_id = item.get("id", "<unknown>")
            item_target_paths = item.get("targetOwnerPaths")
            if isinstance(item_target_paths, list) and all(
                isinstance(path, str) for path in item_target_paths
            ):
                if item_target_paths != sorted(item_target_paths):
                    errors.append(f"{item_id}: targetOwnerPaths must be sorted")
                target_owner_paths.extend(item_target_paths)

            locators = item.get("locators")
            if isinstance(locators, list) and all(
                isinstance(locator, dict) for locator in locators
            ):
                locator_keys = [
                    (locator.get("path"), locator.get("selector") or "")
                    for locator in locators
                    if isinstance(locator.get("path"), str)
                    and (
                        locator.get("selector") is None
                        or isinstance(locator.get("selector"), str)
                    )
                ]
                if len(locator_keys) == len(locators) and locator_keys != sorted(
                    locator_keys
                ):
                    errors.append(f"{item_id}: locators must be sorted by path and selector")
                duplicate_locators = _duplicates(
                    f"{path}\0{selector}" for path, selector in locator_keys
                )
                if duplicate_locators:
                    errors.append(f"{item_id}: duplicate locator path/selector pairs")
                global_locator_keys.extend(
                    f"{path}\0{selector}" for path, selector in locator_keys
                )
                if item.get("disposition") == "delete-phase-2":
                    owner = item.get("ownerIssue")
                    for path, selector in locator_keys:
                        key = f"{path}\0{selector}"
                        delete_locator_keys.append(key)
                        if isinstance(owner, int):
                            delete_locator_owners[key] = owner
                if item.get("disposition") == "retain-historical-evidence":
                    allowlist_id = item.get("historicalAllowlistEntry")
                    if isinstance(allowlist_id, str):
                        for locator in locators:
                            path = locator.get("path")
                            blob = locator.get("gitBlobSha")
                            if isinstance(path, str) and isinstance(blob, str):
                                if allowlist_id in historical_inventory:
                                    errors.append(
                                        f"{item_id}: historical allowlist entry must map "
                                        "to exactly one inventory locator"
                                    )
                                historical_inventory[allowlist_id] = (path, blob)

            if item.get("disposition") == "delete-phase-2":
                if not item.get("removalGate"):
                    errors.append(f"{item_id}: deletion requires a removal gate")
                if not item.get("replacementEvidence"):
                    errors.append(f"{item_id}: deletion requires replacement evidence")
                if not item.get("targetOwnerPaths"):
                    errors.append(f"{item_id}: deletion requires target owner paths")
                for field in (
                    "replacementSuiteIds",
                    "replacementCheckIds",
                    "retirementSuiteIds",
                ):
                    values = item.get(field)
                    if isinstance(values, list) and values != sorted(values):
                        errors.append(f"{item_id}: {field} must be sorted")
                replacement_suites = item.get("replacementSuiteIds")
                if isinstance(replacement_suites, list):
                    owner = item.get("ownerIssue")
                    if isinstance(owner, int):
                        mapped_replacement_suites_by_issue.setdefault(owner, set()).update(
                            replacement_suites
                        )
                        policy = census_suite_policy_by_issue.get(owner)
                        if policy is not None:
                            disallowed = sorted(set(replacement_suites) - policy[0])
                            if disallowed:
                                errors.append(
                                    f"{item_id}: replacementSuiteIds are not allowed for "
                                    f"ownerIssue #{owner}: {disallowed}"
                                )
                    missing = sorted(set(replacement_suites) - set(suites_by_id))
                    if missing:
                        errors.append(
                            f"{item_id}: replacementSuiteIds not in test inventory: {missing}"
                        )
                    non_active = sorted(
                        suite_id
                        for suite_id in replacement_suites
                        if suites_by_id.get(suite_id, {}).get("status") != "active"
                    )
                    if non_active:
                        errors.append(
                            f"{item_id}: replacement suites must be active: {non_active}"
                        )
                replacement_checks = item.get("replacementCheckIds")
                if isinstance(replacement_checks, list):
                    mapped_replacement_checks.extend(replacement_checks)
                    missing = sorted(set(replacement_checks) - receipt_check_ids)
                    if missing:
                        errors.append(
                            f"{item_id}: replacementCheckIds not in evidence receipt: {missing}"
                        )
                    selected_checks = [
                        receipt_checks_by_id[check_id]
                        for check_id in replacement_checks
                        if check_id in receipt_checks_by_id
                    ]
                    covered_suites = {
                        suite_id
                        for check in selected_checks
                        for suite_id in check.get("coveredReplacementSuiteIds", [])
                        if isinstance(suite_id, str)
                    }
                    covered_paths = {
                        path
                        for check in selected_checks
                        for path in check.get("coveredTargetOwnerPaths", [])
                        if isinstance(path, str)
                    }
                    if isinstance(replacement_suites, list) and covered_suites != set(
                        replacement_suites
                    ):
                        errors.append(
                            f"{item_id}: replacement checks do not exactly cover "
                            "replacementSuiteIds"
                        )
                    if isinstance(item_target_paths, list) and covered_paths != set(
                        item_target_paths
                    ):
                        errors.append(
                            f"{item_id}: replacement checks do not exactly cover "
                            "targetOwnerPaths"
                        )
                retirement_suites = item.get("retirementSuiteIds")
                if isinstance(retirement_suites, list):
                    mapped_retirement_suites.extend(retirement_suites)
                    missing = sorted(set(retirement_suites) - set(suites_by_id))
                    if missing:
                        errors.append(
                            f"{item_id}: retirementSuiteIds not in test inventory: {missing}"
                        )
                    owner = item.get("ownerIssue")
                    wrong_owner = sorted(
                        suite_id
                        for suite_id in retirement_suites
                        if not isinstance(
                            suites_by_id.get(suite_id, {}).get("replacementGate"),
                            dict,
                        )
                        or suites_by_id[suite_id]["replacementGate"].get("issue")
                        != owner
                    )
                    if wrong_owner:
                        errors.append(
                            f"{item_id}: retirementSuiteIds must have replacementGate.issue "
                            f"equal to ownerIssue: {wrong_owner}"
                        )
                    locator_test_suites = {
                        baseline_suite_by_path[path]
                        for path, selector in locator_keys
                        if not selector and path in baseline_suite_by_path
                    }
                    missing_mappings = sorted(locator_test_suites - set(retirement_suites))
                    if missing_mappings:
                        errors.append(
                            f"{item_id}: deleted baseline tests lack retirement mapping: "
                            f"{missing_mappings}"
                        )
                evidence_references = item.get("replacementEvidence")
                if isinstance(evidence_references, list):
                    suite_references = {
                        reference.get("reference")
                        for reference in evidence_references
                        if isinstance(reference, dict)
                        and reference.get("kind") == "test-suite"
                        and isinstance(reference.get("reference"), str)
                    }
                    if isinstance(replacement_suites, list) and set(
                        replacement_suites
                    ) != suite_references:
                        errors.append(
                            f"{item_id}: replacementEvidence test-suite references must "
                            "exactly match replacementSuiteIds"
                        )

        duplicate_locator_keys = _duplicates(global_locator_keys)
        if duplicate_locator_keys:
            errors.append("locator path/selector pairs assigned to multiple items")
        duplicate_delete_keys = _duplicates(delete_locator_keys)
        if duplicate_delete_keys:
            errors.append(
                "delete locator keys assigned to multiple items: "
                f"{duplicate_delete_keys}"
            )
        unused_receipt_checks = sorted(receipt_check_ids - set(mapped_replacement_checks))
        if unused_receipt_checks:
            errors.append(
                "evidence receipt checks are not referenced by deletion items: "
                f"{unused_receipt_checks}"
            )

        for owner, (_allowed, required) in census_suite_policy_by_issue.items():
            missing_required = sorted(
                required - mapped_replacement_suites_by_issue.get(owner, set())
            )
            if missing_required:
                errors.append(
                    f"deletion inventory lacks mandatory replacement suites for "
                    f"ownerIssue #{owner}: "
                    f"{missing_required}"
                )

        expected_retirement_suites = {
            suite_id
            for suite_id, suite in suites_by_id.items()
            if isinstance(suite.get("replacementGate"), dict)
            and suite["replacementGate"].get("issue") in {70, 71, 72}
        }
        if set(mapped_retirement_suites) != expected_retirement_suites:
            missing = sorted(expected_retirement_suites - set(mapped_retirement_suites))
            extra = sorted(set(mapped_retirement_suites) - expected_retirement_suites)
            errors.append(
                "semantic retirement suite census drifted: "
                f"missing={missing}, extra={extra}"
            )
        duplicate_retirement_suites = _duplicates(mapped_retirement_suites)
        if duplicate_retirement_suites:
            errors.append(
                "retirement suites assigned to multiple inventory items: "
                f"{duplicate_retirement_suites}"
            )

        if (
            not census_schema_errors
            and isinstance(audited_commit, str)
            and len(audited_commit) == 40
        ):
            try:
                tracked = _tracked_blobs(repository_root, audited_commit)
            except RemovalApprovalError as exc:
                errors.append(str(exc))
            else:
                canonical_owners, census_errors = _canonical_census(
                    census,
                    repository_root=repository_root,
                    audited_commit=audited_commit,
                    tracked=tracked,
                )
                errors.extend(census_errors)
                actual_delete = set(delete_locator_keys)
                expected_delete = set(canonical_owners)
                if actual_delete != expected_delete:
                    errors.append(
                        "delete inventory does not exhaust canonical census: "
                        f"missing={sorted(expected_delete - actual_delete)}, "
                        f"extra={sorted(actual_delete - expected_delete)}"
                    )
                wrong_owners = sorted(
                    key
                    for key in expected_delete & actual_delete
                    if delete_locator_owners.get(key) != canonical_owners[key]
                )
                if wrong_owners:
                    errors.append(
                        f"delete inventory ownerIssue differs from canonical census: "
                        f"{wrong_owners}"
                    )
                missing_target_paths = sorted(set(target_owner_paths) - set(tracked))
                if missing_target_paths:
                    errors.append(
                        "targetOwnerPaths not tracked at audited commit: "
                        f"{missing_target_paths}"
                    )
                for item in items:
                    item_id = item.get("id", "<unknown>")
                    locators = item.get("locators")
                    if not isinstance(locators, list):
                        continue
                    for locator in locators:
                        if not isinstance(locator, dict):
                            continue
                        path = locator.get("path")
                        expected_blob = tracked.get(path) if isinstance(path, str) else None
                        if isinstance(path, str) and expected_blob is None:
                            errors.append(
                                f"{item_id}: locator path not tracked at audited commit: {path}"
                            )
                        elif expected_blob is not None and locator.get("gitBlobSha") != expected_blob:
                            errors.append(
                                f"{item_id}: locator gitBlobSha does not match "
                                f"audited blob for {path}"
                            )

        allowlist_entries = historical_allowlist.get("entries")
        if isinstance(allowlist_entries, list) and all(
            isinstance(entry, dict) for entry in allowlist_entries
        ):
            allowlist_ids = [
                entry.get("id")
                for entry in allowlist_entries
                if isinstance(entry.get("id"), str)
            ]
            duplicate_allowlist_ids = _duplicates(allowlist_ids)
            if duplicate_allowlist_ids:
                errors.append(
                    f"duplicate historical allowlist ids: {duplicate_allowlist_ids}"
                )
            if len(allowlist_ids) == len(allowlist_entries) and allowlist_ids != sorted(
                allowlist_ids
            ):
                errors.append("historical allowlist entries must be sorted by id")
            allowlist_paths = [
                entry.get("path")
                for entry in allowlist_entries
                if isinstance(entry.get("path"), str)
            ]
            duplicate_allowlist_paths = _duplicates(allowlist_paths)
            if duplicate_allowlist_paths:
                errors.append(
                    "historical allowlist paths must be exact and globally unique: "
                    f"{duplicate_allowlist_paths}"
                )
            allowlist_by_id = {
                entry.get("id"): entry
                for entry in allowlist_entries
                if isinstance(entry.get("id"), str)
            }
            if set(allowlist_by_id) != set(historical_inventory):
                errors.append(
                    "historical allowlist entries must exactly match inventory "
                    "retain-historical-evidence cross-links"
                )
            for allowlist_id, (path, blob) in historical_inventory.items():
                entry = allowlist_by_id.get(allowlist_id)
                if entry is not None and (
                    entry.get("path") != path or entry.get("gitBlobSha") != blob
                ):
                    errors.append(
                        f"historical allowlist entry {allowlist_id} does not match "
                        "its inventory locator"
                    )
            if any(
                path.startswith(ACTIVE_TARGET_ROOTS) for path in allowlist_paths
            ):
                errors.append("historical allowlist cannot include active target roots")
            if tracked is not None:
                missing_allowlist_paths = sorted(set(allowlist_paths) - set(tracked))
                if missing_allowlist_paths:
                    errors.append(
                        "historical allowlist paths not tracked at audited commit: "
                        f"{missing_allowlist_paths}"
                    )
                for entry in allowlist_entries:
                    path = entry.get("path")
                    if isinstance(path, str) and tracked.get(path) is not None and (
                        entry.get("gitBlobSha") != tracked[path]
                    ):
                        errors.append(
                            "historical allowlist gitBlobSha does not match audited "
                            f"blob for {path}"
                        )

    inventory_sha256 = _sha256(inventory_bytes)
    evidence_sha256 = _sha256(evidence_bytes)
    if isinstance(audited_commit, str) and len(audited_commit) == 40:
        try:
            audited_tree = _tree_sha(repository_root, audited_commit)
        except RemovalApprovalError as exc:
            errors.append(str(exc))
        else:
            if inventory.get("auditedTree") != audited_tree:
                errors.append("inventory auditedTree does not match audited commit tree")
            if evidence.get("auditedTree") != audited_tree:
                errors.append("evidence receipt auditedTree does not match audited commit tree")
            if historical_allowlist.get("auditedTree") != audited_tree:
                errors.append("historical allowlist auditedTree does not match audited commit tree")
    if evidence.get("auditedCommit") != audited_commit:
        errors.append("evidence receipt auditedCommit does not match inventory")
    if evidence.get("inventorySha256") != inventory_sha256:
        errors.append("evidence receipt inventorySha256 does not match committed inventory")
    if historical_allowlist.get("auditedCommit") != audited_commit:
        errors.append("historical allowlist auditedCommit does not match inventory")
    recovery_policy = inventory.get("recoveryPolicy")
    if isinstance(recovery_policy, dict) and (
        recovery_policy.get("sourceRecoveryCommit") != audited_commit
    ):
        errors.append("recoveryPolicy sourceRecoveryCommit does not match audited commit")

    contract_hash_paths = {
        "inventorySchemaSha256": inventory_schema_path,
        "censusSha256": census_path,
        "censusSchemaSha256": census_schema_path,
        "checkOutputSchemaSha256": check_output_schema_path,
        "evidenceReceiptSchemaSha256": evidence_schema_path,
        "ownerDecisionSchemaSha256": decision_schema_path,
        "historicalAllowlistSchemaSha256": historical_allowlist_schema_path,
        "validatorSha256": validator_path,
        "testInventorySha256": test_inventory_path,
        "historicalAllowlistSha256": historical_allowlist_path,
        "replacementMatrixSha256": replacement_matrix_path,
    }
    contract_hashes = evidence.get("contractHashes")
    if isinstance(contract_hashes, dict):
        for field, path in contract_hash_paths.items():
            try:
                committed_bytes = _committed_blob(repository_root, path, required=True)
            except RemovalApprovalError as exc:
                errors.append(str(exc))
                continue
            assert committed_bytes is not None
            if contract_hashes.get(field) != _sha256(committed_bytes):
                errors.append(f"evidence receipt {field} does not match committed bytes")

    checks = evidence.get("checks")
    if isinstance(checks, list) and all(isinstance(check, dict) for check in checks):
        check_ids = [check.get("id") for check in checks]
        duplicate_check_ids = _duplicates(
            check_id for check_id in check_ids if isinstance(check_id, str)
        )
        if duplicate_check_ids:
            errors.append(f"duplicate evidence check ids: {duplicate_check_ids}")
        for check in checks:
            check_id = check.get("id", "<unknown>")
            command = check.get("command")
            if isinstance(command, str) and FORBIDDEN_EVIDENCE_COMMAND.search(command):
                errors.append(f"{check_id}: evidence command is not read-only and local-safe")
            evidence_paths = check.get("evidencePaths")
            output_path = check.get("outputPath")
            expected_output_path = f"tests/evidence/repository-removal/v1/{check_id}.json"
            if output_path != expected_output_path:
                errors.append(
                    f"{check_id}: outputPath must be the canonical check namespace: "
                    f"{expected_output_path}"
                )
            if (
                isinstance(output_path, str)
                and isinstance(evidence_paths, list)
                and output_path not in evidence_paths
            ):
                errors.append(
                    f"{check_id}: outputPath must also be listed in evidencePaths"
                )
            if tracked is not None and isinstance(evidence_paths, list):
                missing_evidence_paths = sorted(
                    path
                    for path in evidence_paths
                    if isinstance(path, str)
                    and path != output_path
                    and path not in tracked
                )
                if missing_evidence_paths:
                    errors.append(
                        f"{check_id}: evidencePaths not tracked at audited commit: "
                        f"{missing_evidence_paths}"
                    )
            covered_suites = check.get("coveredReplacementSuiteIds")
            if isinstance(covered_suites, list):
                missing_suites = sorted(set(covered_suites) - set(suites_by_id))
                if missing_suites:
                    errors.append(
                        f"{check_id}: coveredReplacementSuiteIds not in test inventory: "
                        f"{missing_suites}"
                    )
                non_active_suites = sorted(
                    suite_id
                    for suite_id in covered_suites
                    if suites_by_id.get(suite_id, {}).get("status") != "active"
                )
                if non_active_suites:
                    errors.append(
                        f"{check_id}: covered replacement suites must be active: "
                        f"{non_active_suites}"
                    )
            covered_paths = check.get("coveredTargetOwnerPaths")
            if isinstance(covered_paths, list) and isinstance(evidence_paths, list):
                missing_path_evidence = sorted(set(covered_paths) - set(evidence_paths))
                if missing_path_evidence:
                    errors.append(
                        f"{check_id}: coveredTargetOwnerPaths must be evidencePaths: "
                        f"{missing_path_evidence}"
                    )
            if isinstance(covered_suites, list) and isinstance(covered_paths, list):
                valid_covered_suites = [
                    suite_id
                    for suite_id in covered_suites
                    if suite_id in suites_by_id
                ]
                for suite_id in valid_covered_suites:
                    suite = suites_by_id[suite_id]
                    commands = suite.get("commands")
                    accepted_commands = {
                        value
                        for key in ("focused", "full")
                        if isinstance(commands, dict)
                        and isinstance((value := commands.get(key)), str)
                    }
                    if command not in accepted_commands:
                        errors.append(
                            f"{check_id}: command must exactly match {suite_id} "
                            "commands.focused or commands.full"
                        )
                    source_patterns = suite.get("sourcePaths")
                    patterns = (
                        [pattern for pattern in source_patterns if isinstance(pattern, str)]
                        if isinstance(source_patterns, list)
                        else []
                    )
                    if not any(
                        _matches_source_pattern(path, pattern)
                        for path in covered_paths
                        for pattern in patterns
                    ):
                        errors.append(
                            f"{check_id}: covered suite {suite_id} has no matching "
                            "coveredTargetOwnerPath"
                        )
                unmatched_covered_paths = sorted(
                    path
                    for path in covered_paths
                    if not any(
                        _matches_source_pattern(path, pattern)
                        for suite_id in valid_covered_suites
                        for pattern in (
                            suites_by_id[suite_id].get("sourcePaths", [])
                            if isinstance(
                                suites_by_id[suite_id].get("sourcePaths"), list
                            )
                            else []
                        )
                        if isinstance(pattern, str)
                    )
                )
                if unmatched_covered_paths:
                    errors.append(
                        f"{check_id}: coveredTargetOwnerPaths do not match covered "
                        f"suite sourcePaths: {unmatched_covered_paths}"
                    )
            if isinstance(output_path, str):
                try:
                    output_bytes = _committed_blob(
                        repository_root, Path(output_path), required=True
                    )
                except RemovalApprovalError as exc:
                    errors.append(str(exc))
                else:
                    assert output_bytes is not None
                    if check.get("outputSha256") != _sha256(output_bytes):
                        errors.append(
                            f"{check_id}: outputSha256 does not match retained "
                            f"command output: {output_path}"
                        )
                    try:
                        output_document = _load_document(
                            output_bytes, f"{check_id} check output"
                        )
                    except RemovalApprovalError as exc:
                        errors.append(str(exc))
                    else:
                        errors.extend(
                            _schema_errors(
                                output_document,
                                check_output_schema,
                                f"{check_id} check output",
                            )
                        )
                        expected_output = {
                            "schemaVersion": "1.0.0",
                            "auditedCommit": audited_commit,
                            "checkId": check_id,
                            "command": command,
                            "result": check.get("result"),
                        }
                        if output_document != expected_output:
                            errors.append(
                                f"{check_id}: committed check output does not exactly "
                                "bind auditedCommit/checkId/command/result"
                            )

    if decision is None:
        if not allow_unapproved:
            errors.append(
                "owner decision is absent; use --allow-unapproved only for "
                "pre-approval inventory validation"
            )
    else:
        if decision.get("auditedCommit") != audited_commit:
            errors.append("owner decision auditedCommit does not match inventory")
        if decision.get("inventorySha256") != inventory_sha256:
            errors.append("owner decision inventorySha256 does not match committed inventory")
        if decision.get("evidenceReceiptSha256") != evidence_sha256:
            errors.append(
                "owner decision evidenceReceiptSha256 does not match committed evidence receipt"
            )
        if (
            isinstance(audited_commit, str)
            and decision.get("approvalText")
            != expected_approval_text(audited_commit, inventory_sha256, evidence_sha256)
        ):
            errors.append("owner decision approvalText is not the exact required approval")
        approval_source = decision.get("approvalSource")
        approval_text = decision.get("approvalText")
        if isinstance(approval_source, dict) and isinstance(approval_text, str):
            if approval_source.get("issue") != 68:
                errors.append("owner decision approvalSource must reference issue 68")
            if approval_source.get("author") != "artemsemdev":
                errors.append("owner decision approvalSource author is not project owner")
            if approval_source.get("authorAssociation") != "OWNER":
                errors.append(
                    "owner decision approvalSource authorAssociation is not OWNER"
                )
            if approval_source.get("bodySha256") != _sha256(
                approval_text.encode("utf-8")
            ):
                errors.append(
                    "owner decision approvalSource bodySha256 does not match approvalText"
                )
            comment_id = approval_source.get("commentId")
            comment_url = approval_source.get("commentUrl")
            if isinstance(comment_id, int) and isinstance(comment_url, str) and not (
                comment_url.endswith(f"#issuecomment-{comment_id}")
            ):
                errors.append(
                    "owner decision approvalSource commentId does not match commentUrl"
                )
            if not verify_owner_comment:
                errors.append(
                    "live GitHub owner comment verification is required for approval"
                )
            elif isinstance(comment_id, int) and isinstance(comment_url, str):
                fetcher = owner_comment_fetcher or _fetch_github_owner_comment
                try:
                    live_comment = fetcher(comment_id)
                except (OSError, ValueError, RemovalApprovalError) as exc:
                    errors.append(f"live GitHub owner comment verification failed: {exc}")
                else:
                    live_user = live_comment.get("user")
                    live_values = {
                        "id": live_comment.get("id"),
                        "html_url": live_comment.get("html_url"),
                        "issue_url": live_comment.get("issue_url"),
                        "body": live_comment.get("body"),
                        "author_association": live_comment.get("author_association"),
                        "login": (
                            live_user.get("login")
                            if isinstance(live_user, Mapping)
                            else None
                        ),
                    }
                    expected_live = {
                        "id": comment_id,
                        "html_url": comment_url,
                        "issue_url": (
                            "https://api.github.com/repos/artemsemdev/"
                            "SeaRise-Europe/issues/68"
                        ),
                        "body": approval_text,
                        "author_association": "OWNER",
                        "login": "artemsemdev",
                    }
                    if live_values != expected_live:
                        errors.append(
                            "live GitHub owner comment does not exactly match the "
                            "recorded owner approval"
                        )

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate the committed repository-removal approval chain."
    )
    parser.add_argument("--repository-root", type=Path, default=ROOT)
    parser.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY)
    parser.add_argument("--evidence", type=Path, default=DEFAULT_EVIDENCE)
    parser.add_argument("--decision", type=Path, default=DEFAULT_DECISION)
    parser.add_argument(
        "--historical-allowlist", type=Path, default=DEFAULT_HISTORICAL_ALLOWLIST
    )
    parser.add_argument("--inventory-schema", type=Path, default=DEFAULT_INVENTORY_SCHEMA)
    parser.add_argument("--evidence-schema", type=Path, default=DEFAULT_EVIDENCE_SCHEMA)
    parser.add_argument("--decision-schema", type=Path, default=DEFAULT_DECISION_SCHEMA)
    parser.add_argument(
        "--historical-allowlist-schema",
        type=Path,
        default=DEFAULT_HISTORICAL_ALLOWLIST_SCHEMA,
    )
    parser.add_argument("--census", type=Path, default=DEFAULT_CENSUS)
    parser.add_argument("--census-schema", type=Path, default=DEFAULT_CENSUS_SCHEMA)
    parser.add_argument(
        "--check-output-schema", type=Path, default=DEFAULT_CHECK_OUTPUT_SCHEMA
    )
    parser.add_argument("--validator", type=Path, default=DEFAULT_VALIDATOR)
    parser.add_argument("--test-inventory", type=Path, default=DEFAULT_TEST_INVENTORY)
    parser.add_argument(
        "--replacement-matrix", type=Path, default=DEFAULT_REPLACEMENT_MATRIX
    )
    parser.add_argument(
        "--allow-unapproved",
        action="store_true",
        help="validate a committed pre-approval inventory when no decision exists",
    )
    parser.add_argument(
        "--verify-owner-comment",
        action="store_true",
        help="fetch and exactly verify the recorded GitHub Issue #68 OWNER comment",
    )
    args = parser.parse_args()

    try:
        errors = validate_removal_approval(
            repository_root=args.repository_root,
            inventory_path=args.inventory,
            evidence_path=args.evidence,
            decision_path=args.decision,
            historical_allowlist_path=args.historical_allowlist,
            inventory_schema_path=args.inventory_schema,
            evidence_schema_path=args.evidence_schema,
            decision_schema_path=args.decision_schema,
            historical_allowlist_schema_path=args.historical_allowlist_schema,
            census_path=args.census,
            census_schema_path=args.census_schema,
            check_output_schema_path=args.check_output_schema,
            validator_path=args.validator,
            test_inventory_path=args.test_inventory,
            replacement_matrix_path=args.replacement_matrix,
            allow_unapproved=args.allow_unapproved,
            verify_owner_comment=args.verify_owner_comment,
        )
    except RemovalApprovalError as exc:
        errors = [str(exc)]
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print("validated committed repository-removal approval chain")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
