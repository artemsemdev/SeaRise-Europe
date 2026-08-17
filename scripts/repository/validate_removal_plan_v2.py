"""Validate and materialize the additive Phase 2 repository-removal v2 plan.

The v2 plan is intentionally separate from the signed v1 approval chain.  It
binds every authorized path to both its audited Git blob and its exact expected
post-removal bytes.  Structural operations are evaluated only in memory.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any


class PlanError(ValueError):
    """Raised when a removal plan is ambiguous or exceeds its authority."""


PROTECTED_V1_PREFIX = "contracts/repository-removal/v1/"
PROTECTED_PATHS = {
    "scripts/repository/validate_removal_approval.py",
}
SUPPORT_REWRITE_PATHS = {
    "tests/harness/test_changed_components.py",
    "tests/harness/test_immutable_dependencies.py",
}
CONTRACT_DIRECTORY = "contracts/repository-removal/v2"
PLAN_PATH = f"{CONTRACT_DIRECTORY}/removal-plan.json"
PREAPPROVAL_PATH = f"{CONTRACT_DIRECTORY}/preapproval.json"
DECISION_PATH = f"{CONTRACT_DIRECTORY}/owner-decision.json"
EXPECTED_TRUST_ROOTS = {
    "v1Census": "contracts/repository-removal/v1/census.json",
    "v1CensusSchema": "contracts/repository-removal/v1/census.schema.json",
    "v1CheckOutputSchema": "contracts/repository-removal/v1/check-output.schema.json",
    "v1EvidenceReceipt": "contracts/repository-removal/v1/evidence-receipt.json",
    "v1EvidenceReceiptSchema": "contracts/repository-removal/v1/evidence-receipt.schema.json",
    "v1HistoricalAllowlist": "contracts/repository-removal/v1/historical-allowlist.json",
    "v1HistoricalAllowlistPreapproval": "contracts/repository-removal/v1/historical-allowlist.preapproval.json",
    "v1HistoricalAllowlistSchema": "contracts/repository-removal/v1/historical-allowlist.schema.json",
    "v1Inventory": "contracts/repository-removal/v1/inventory.json",
    "v1InventorySchema": "contracts/repository-removal/v1/inventory.schema.json",
    "v1OwnerDecision": "contracts/repository-removal/v1/owner-decision.json",
    "v1OwnerDecisionSchema": "contracts/repository-removal/v1/owner-decision.schema.json",
    "v1Validator": "scripts/repository/validate_removal_approval.py",
    "v2OwnerDecisionSchema": f"{CONTRACT_DIRECTORY}/owner-decision.schema.json",
    "v2PlanSchema": f"{CONTRACT_DIRECTORY}/removal-plan.schema.json",
    "v2PreapprovalSchema": f"{CONTRACT_DIRECTORY}/preapproval.schema.json",
    "v2Validator": "scripts/repository/validate_removal_plan_v2.py",
}


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise PlanError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> None:
    raise PlanError(f"non-finite JSON number is forbidden: {value}")


def _json_load_bytes(content: bytes, label: str) -> dict[str, Any]:
    try:
        text = content.decode("utf-8")
        document = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_json_constant,
        )
    except UnicodeDecodeError as exc:
        raise PlanError(f"{label} is not UTF-8") from exc
    except json.JSONDecodeError as exc:
        raise PlanError(f"{label} is not strict JSON: {exc}") from exc
    if not isinstance(document, dict):
        raise PlanError(f"{label} must be a JSON object")
    return document


def _json_load_path(path: Path, label: str) -> dict[str, Any]:
    return _json_load_bytes(path.read_bytes(), label)


def _schema_validate(document: dict[str, Any], schema_path: Path, label: str) -> None:
    _schema_validate_document(
        document, _json_load_path(schema_path, f"{label} schema"), label
    )


def _schema_validate_document(
    document: dict[str, Any], schema: dict[str, Any], label: str
) -> None:
    try:
        import jsonschema
    except ModuleNotFoundError as exc:
        raise PlanError("jsonschema is required for repository-removal v2") from exc
    validator = jsonschema.Draft202012Validator(
        schema, format_checker=jsonschema.FormatChecker()
    )
    errors = sorted(validator.iter_errors(document), key=lambda error: list(error.path))
    if errors:
        error = errors[0]
        location = ".".join(str(part) for part in error.absolute_path) or "<root>"
        raise PlanError(f"{label} schema violation at {location}: {error.message}")


def _git(root: Path, *arguments: str, input_bytes: bytes | None = None) -> bytes:
    environment = os.environ.copy()
    environment["GIT_NO_REPLACE_OBJECTS"] = "1"
    environment["GIT_NO_LAZY_FETCH"] = "1"
    process = subprocess.run(
        ["git", "--no-replace-objects", *arguments],
        cwd=root,
        input=input_bytes,
        capture_output=True,
        check=False,
        env=environment,
    )
    if process.returncode:
        raise PlanError(process.stderr.decode("utf-8", errors="replace").strip())
    return process.stdout


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _git_blob_sha(content: bytes) -> str:
    header = f"blob {len(content)}\0".encode("ascii")
    return hashlib.sha1(header + content).hexdigest()


def _audited_blob(root: Path, commit: str, path: str) -> bytes:
    _, object_type, object_id = _tree_entry(root, commit, path)
    if object_type != "blob":
        raise PlanError(f"audited path is not a blob: {path}")
    return _git(root, "cat-file", "blob", object_id)


def _tree_entry(root: Path, commit: str, path: str) -> tuple[str, str, str]:
    output = _git(root, "ls-tree", "-z", commit, "--", path)
    if not output:
        raise PlanError(f"committed path is absent: {commit}:{path}")
    records = [record for record in output.split(b"\0") if record]
    if len(records) != 1:
        raise PlanError(f"committed path is ambiguous: {commit}:{path}")
    metadata, observed_path = records[0].split(b"\t", maxsplit=1)
    if observed_path.decode("utf-8") != path:
        raise PlanError(f"committed path did not resolve exactly: {commit}:{path}")
    mode, object_type, object_id = metadata.decode("ascii").split(" ")
    return mode, object_type, object_id


def _optional_tree_entry(
    root: Path, commit: str, path: str
) -> tuple[str, str, str] | None:
    output = _git(root, "ls-tree", "-z", commit, "--", path)
    if not output:
        return None
    records = [record for record in output.split(b"\0") if record]
    if len(records) != 1:
        raise PlanError(f"committed path is ambiguous: {commit}:{path}")
    metadata, observed_path = records[0].split(b"\t", maxsplit=1)
    if observed_path.decode("utf-8") != path:
        raise PlanError(f"committed path did not resolve exactly: {commit}:{path}")
    mode, object_type, object_id = metadata.decode("ascii").split(" ")
    return mode, object_type, object_id


def _regular_blob(root: Path, commit: str, path: str) -> tuple[str, str, bytes]:
    mode, object_type, object_id = _tree_entry(root, commit, path)
    if object_type != "blob" or mode not in {"100644", "100755"}:
        raise PlanError(f"committed path is not a regular file: {commit}:{path}")
    return mode, object_id, _git(root, "cat-file", "blob", object_id)


def _assert_commit(root: Path, commit: str) -> str:
    if _git(root, "rev-parse", "--is-shallow-repository").strip() != b"false":
        raise PlanError("full Git history is required")
    resolved = _git(root, "rev-parse", f"{commit}^{{commit}}").decode().strip()
    if resolved != commit:
        raise PlanError(f"commit must be one exact 40-character object id: {commit}")
    return resolved


def _assert_ancestor(root: Path, ancestor: str, descendant: str) -> None:
    process = subprocess.run(
        [
            "git",
            "--no-replace-objects",
            "merge-base",
            "--is-ancestor",
            ancestor,
            descendant,
        ],
        cwd=root,
        capture_output=True,
        env={**os.environ, "GIT_NO_REPLACE_OBJECTS": "1", "GIT_NO_LAZY_FETCH": "1"},
        check=False,
    )
    if process.returncode != 0:
        raise PlanError(f"required Git ancestry is absent: {ancestor} -> {descendant}")


def _decode(content: bytes, label: str) -> str:
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise PlanError(f"{label} is not UTF-8") from exc


def _line_indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _block_end(lines: list[str], start: int, indent: int) -> int:
    for index in range(start + 1, len(lines)):
        line = lines[index]
        if (
            line.strip()
            and not line.lstrip().startswith("#")
            and _line_indent(line) <= indent
        ):
            return index
    return len(lines)


def _mapping_key(
    lines: list[str], start: int, end: int, indent: int, key: str
) -> tuple[int, int]:
    pattern = re.compile(rf"^{' ' * indent}{re.escape(key)}:(?:\s.*)?$")
    matches = [
        index
        for index in range(start, end)
        if pattern.fullmatch(lines[index].rstrip("\n"))
    ]
    if len(matches) != 1:
        raise PlanError(
            f"workflow mapping key must exist exactly once: {key} ({len(matches)})"
        )
    index = matches[0]
    return index, _block_end(lines, index, indent)


def _workflow_job(lines: list[str], job: str) -> tuple[int, int]:
    jobs_start, jobs_end = _mapping_key(lines, 0, len(lines), 0, "jobs")
    return _mapping_key(lines, jobs_start + 1, jobs_end, 2, job)


def _delete_ranges(lines: list[str], ranges: list[tuple[int, int]]) -> list[str]:
    normalized = sorted(ranges)
    for previous, current in zip(normalized, normalized[1:]):  # noqa: RUF007
        if previous[1] > current[0]:
            raise PlanError("authorized structural operations overlap")
    result = list(lines)
    for start, end in reversed(normalized):
        del result[start:end]
    return result


def _workflow_transform(content: bytes, operations: list[dict[str, Any]]) -> bytes:
    lines = _decode(content, "workflow").splitlines(keepends=True)
    order = {
        "workflow-job-delete": 0,
        "workflow-output-delete": 1,
        "workflow-needs-edge-delete": 2,
        "workflow-step-delete": 3,
        "workflow-scalar-replace": 4,
    }
    if any(operation["kind"] not in order for operation in operations):
        raise PlanError("workflow entry contains a non-workflow operation")
    for operation in sorted(
        operations, key=lambda item: (order[item["kind"]], item["id"])
    ):
        kind = operation["kind"]
        if kind == "workflow-job-delete":
            start, end = _workflow_job(lines, operation["job"])
            lines = _delete_ranges(lines, [(start, end)])
        elif kind == "workflow-output-delete":
            job_start, job_end = _workflow_job(lines, operation["job"])
            outputs_start, outputs_end = _mapping_key(
                lines, job_start + 1, job_end, 4, "outputs"
            )
            start, end = _mapping_key(
                lines, outputs_start + 1, outputs_end, 6, operation["output"]
            )
            lines = _delete_ranges(lines, [(start, end)])
        elif kind == "workflow-needs-edge-delete":
            job_start, job_end = _workflow_job(lines, operation["consumer"])
            needs_start, needs_end = _mapping_key(
                lines, job_start + 1, job_end, 4, "needs"
            )
            pattern = re.compile(
                rf"^\s{{6}}-\s+{re.escape(operation['dependency'])}\s*$"
            )
            matches = [
                index
                for index in range(needs_start + 1, needs_end)
                if pattern.fullmatch(lines[index].rstrip("\n"))
            ]
            if len(matches) != 1:
                raise PlanError(
                    "workflow needs edge must exist exactly once: "
                    f"{operation['consumer']}.{operation['dependency']} ({len(matches)})"
                )
            lines = _delete_ranges(lines, [(matches[0], matches[0] + 1)])
        elif kind == "workflow-step-delete":
            job_start, job_end = _workflow_job(lines, operation["job"])
            steps_start, steps_end = _mapping_key(
                lines, job_start + 1, job_end, 4, "steps"
            )
            marker = f"      - name: {operation['name']}"
            matches = [
                index
                for index in range(steps_start + 1, steps_end)
                if lines[index].rstrip("\n") == marker
            ]
            if len(matches) != 1:
                raise PlanError(
                    f"workflow named step must exist exactly once: {operation['name']}"
                )
            start = matches[0]
            end = steps_end
            for index in range(start + 1, steps_end):
                if lines[index].startswith("      - "):
                    end = index
                    break
            lines = _delete_ranges(lines, [(start, end)])
        else:
            job_start, job_end = _workflow_job(lines, operation["job"])
            start, end = _mapping_key(
                lines, job_start + 1, job_end, 4, operation["field"]
            )
            if end != start + 1:
                raise PlanError("workflow scalar replacement selected a mapping block")
            expected = f"    {operation['field']}: {operation['from']}\n"
            if lines[start] != expected:
                raise PlanError(f"workflow scalar source mismatch: {operation['id']}")
            lines[start] = f"    {operation['field']}: {operation['to']}\n"
    return "".join(lines).encode("utf-8")


def _node_range(node: ast.AST) -> tuple[int, int]:
    if not hasattr(node, "lineno") or not hasattr(node, "end_lineno"):
        raise PlanError("Python AST node has no source range")
    return int(node.lineno) - 1, int(node.end_lineno)


def _module_assignment(tree: ast.Module, name: str) -> ast.Assign | ast.AnnAssign:
    matches: list[ast.Assign | ast.AnnAssign] = []
    for statement in tree.body:
        targets: list[ast.expr] = []
        if isinstance(statement, ast.Assign):
            targets = statement.targets
        elif isinstance(statement, ast.AnnAssign):
            targets = [statement.target]
        if any(
            isinstance(target, ast.Name) and target.id == name for target in targets
        ):
            matches.append(statement)
    if len(matches) != 1:
        raise PlanError(f"Python module assignment must exist exactly once: {name}")
    return matches[0]


def _function(tree: ast.Module, name: str) -> ast.FunctionDef | ast.AsyncFunctionDef:
    matches = [
        statement
        for statement in tree.body
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef))
        and statement.name == name
    ]
    if len(matches) != 1:
        raise PlanError(f"Python function must exist exactly once: {name}")
    return matches[0]


def _function_mapping_entry(
    tree: ast.Module, function_name: str, mapping_name: str, key: str
) -> tuple[ast.AST, ast.AST]:
    function = _function(tree, function_name)
    dictionaries: list[ast.Dict] = []
    for statement in function.body:
        if (
            isinstance(statement, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id == mapping_name
                for target in statement.targets
            )
            and isinstance(statement.value, ast.Dict)
        ):
            dictionaries.append(statement.value)
    if len(dictionaries) != 1:
        raise PlanError(
            f"Python mapping must exist exactly once: {function_name}.{mapping_name}"
        )
    matches: list[tuple[ast.AST, ast.AST]] = []
    for key_node, value_node in zip(dictionaries[0].keys, dictionaries[0].values):
        if isinstance(key_node, ast.Constant) and key_node.value == key:
            matches.append((key_node, value_node))
    if len(matches) != 1:
        raise PlanError(
            f"Python mapping key must exist exactly once: {mapping_name}.{key}"
        )
    return matches[0]


def _python_binding_closure_ranges(
    tree: ast.Module, operation: dict[str, Any]
) -> list[tuple[int, int]]:
    name = operation["name"]
    assignment = _module_assignment(tree, name)
    definitions = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Name)
        and isinstance(node.ctx, ast.Store)
        and node.id == name
    ]
    if len(definitions) != 1:
        raise PlanError(f"Python binding is shadowed or rebound: {name}")
    loads = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Name)
        and isinstance(node.ctx, ast.Load)
        and node.id == name
    ]
    if len(loads) != operation["expectedLoadCount"]:
        raise PlanError(
            f"Python binding load count changed: {name} ({len(loads)} != "
            f"{operation['expectedLoadCount']})"
        )
    entry_ranges: list[tuple[int, int]] = []
    covered_loads: set[int] = set()
    for container in operation["useContainers"]:
        key_node, value_node = _function_mapping_entry(
            tree, container["function"], container["mapping"], container["key"]
        )
        value_loads = [
            node
            for node in ast.walk(value_node)
            if isinstance(node, ast.Name)
            and isinstance(node.ctx, ast.Load)
            and node.id == name
        ]
        if len(value_loads) != 1:
            raise PlanError(f"Python use container does not contain one {name} load")
        covered_loads.add(id(value_loads[0]))
        entry_ranges.append((int(key_node.lineno) - 1, int(value_node.end_lineno)))
    if covered_loads != {id(node) for node in loads}:
        raise PlanError(f"Python binding has an unlisted use: {name}")
    return [_node_range(assignment), *entry_ranges]


def _python_tuple_ranges(
    tree: ast.Module, operation: dict[str, Any]
) -> list[tuple[int, int]]:
    assignment = _module_assignment(tree, operation["name"])
    value = assignment.value
    if not isinstance(value, (ast.Tuple, ast.List)):
        raise PlanError(
            f"Python sequence binding is not a literal: {operation['name']}"
        )
    ranges: list[tuple[int, int]] = []
    for selected in operation["values"]:
        matches = [
            element
            for element in value.elts
            if isinstance(element, ast.Constant) and element.value == selected
        ]
        if len(matches) != 1:
            raise PlanError(
                f"Python sequence value must exist exactly once: {operation['name']}.{selected}"
            )
        ranges.append(_node_range(matches[0]))
    return ranges


def _python_transform(content: bytes, operations: list[dict[str, Any]]) -> bytes:
    text = _decode(content, "Python router")
    binding_ops = [
        item for item in operations if item["kind"] == "python-binding-closure-delete"
    ]
    tuple_ops = [
        item for item in operations if item["kind"] == "python-tuple-literals-delete"
    ]
    function_ops = [
        item for item in operations if item["kind"] == "python-function-delete"
    ]
    if len(binding_ops) + len(tuple_ops) + len(function_ops) != len(operations):
        raise PlanError("Python entry contains a non-Python operation")

    tree = ast.parse(text)
    ranges: list[tuple[int, int]] = []
    for operation in binding_ops:
        ranges.extend(_python_binding_closure_ranges(tree, operation))
    for operation in tuple_ops:
        ranges.extend(_python_tuple_ranges(tree, operation))
    lines = _delete_ranges(text.splitlines(keepends=True), ranges)
    text = "".join(lines)

    for operation in sorted(function_ops, key=lambda item: item["name"]):
        tree = ast.parse(text)
        calls = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == operation["name"]
        ]
        if calls:
            raise PlanError(f"Python function still has calls: {operation['name']}")
        function = _function(tree, operation["name"])
        text = "".join(
            _delete_ranges(text.splitlines(keepends=True), [_node_range(function)])
        )
    ast.parse(text)
    return text.encode("utf-8")


def _object_block(lines: list[str], identifier: str) -> tuple[int, int]:
    marker = f'"id": "{identifier}"'
    matches = [index for index, line in enumerate(lines) if marker in line]
    if len(matches) != 1:
        raise PlanError(f"JSON object id must exist exactly once: {identifier}")
    marker_index = matches[0]
    start = marker_index
    while start >= 0 and "{" not in lines[start]:
        start -= 1
    if start < 0:
        raise PlanError(f"cannot locate JSON object start: {identifier}")
    depth = 0
    for index in range(start, len(lines)):
        depth += lines[index].count("{") - lines[index].count("}")
        if depth == 0:
            return start, index + 1
    raise PlanError(f"cannot locate JSON object end: {identifier}")


def _replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise PlanError(f"exact replacement must match once: {label} ({count})")
    return text.replace(old, new, 1)


def _test_inventory_transform(content: bytes, operation: dict[str, Any]) -> bytes:
    text = _decode(content, "test inventory")
    document = _json_load_bytes(content, "test inventory")
    suites = {suite["id"]: suite for suite in document["suites"]}
    evidence = operation["replacementEvidence"]
    for suite_id in operation["suiteIds"]:
        suite = suites.get(suite_id)
        if suite is None:
            raise PlanError(f"retirement suite is missing: {suite_id}")
        if (
            suite["status"] != "active"
            or suite["removalGate"] is not None
            or suite["replacementEvidence"] is not None
            or suite["replacementGate"]["issue"] != operation["issue"]
        ):
            raise PlanError(f"retirement suite pre-state changed: {suite_id}")
        lines = text.splitlines(keepends=True)
        start, end = _object_block(lines, suite_id)
        block = "".join(lines[start:end])
        block = _replace_once(
            block, '"status": "active"', '"status": "retired"', suite_id
        )
        block = _replace_once(
            block,
            '"removalGate": null',
            f'"removalGate": {operation["issue"]}',
            suite_id,
        )
        block = _replace_once(
            block,
            '"replacementEvidence": null',
            f'"replacementEvidence": {json.dumps(evidence)}',
            suite_id,
        )
        text = "".join(lines[:start]) + block + "".join(lines[end:])

    for path in operation["baselinePaths"]:
        matches = [item for item in document["baselineTests"] if item["path"] == path]
        if len(matches) != 1:
            raise PlanError(f"baseline retirement path must exist exactly once: {path}")
        item = matches[0]
        if (
            item["status"] != "active"
            or item["removalGate"] != operation["issue"]
            or item["replacementEvidence"] is not None
        ):
            raise PlanError(f"baseline retirement pre-state changed: {path}")
        baseline_lines = text.splitlines(keepends=True)
        selected = [
            index
            for index, line in enumerate(baseline_lines)
            if f'"path": "{path}"' in line
        ]
        if len(selected) != 1:
            raise PlanError(f"baseline source line must exist exactly once: {path}")
        index = selected[0]
        line = baseline_lines[index]
        line = _replace_once(line, '"status": "active"', '"status": "retired"', path)
        line = _replace_once(
            line,
            '"replacementEvidence": null',
            f'"replacementEvidence": {json.dumps(evidence)}',
            path,
        )
        baseline_lines[index] = line
        text = "".join(baseline_lines)

    text = _replace_once(
        text,
        f'"updatedAt": "{operation["fromUpdatedAt"]}"',
        f'"updatedAt": "{operation["toUpdatedAt"]}"',
        "test inventory updatedAt",
    )
    _json_load_bytes(text.encode("utf-8"), "transformed test inventory")
    return text.encode("utf-8")


def _exact_text_transform(
    content: bytes, operations: list[dict[str, Any]], path: str
) -> bytes:
    if path not in SUPPORT_REWRITE_PATHS:
        raise PlanError(f"exact text replacement is not allowed for path: {path}")
    text = _decode(content, path)
    for operation in operations:
        if operation["kind"] == "python-assertion-key-delete":
            if path != "tests/harness/test_changed_components.py":
                raise PlanError(
                    "assertion-key deletion is restricted to changed-components tests"
                )
            lines = text.splitlines(keepends=True)
            selected = [
                index
                for index, line in enumerate(lines)
                if any(f'outputs["{key}"]' in line for key in operation["keys"])
            ]
            if len(selected) != operation["expectedAssertionCount"]:
                raise PlanError("legacy route assertion count changed")
            text = "".join(
                line for index, line in enumerate(lines) if index not in set(selected)
            )
        elif operation["kind"] == "exact-text-replace":
            text = _replace_once(
                text, operation["from"], operation["to"], operation["id"]
            )
        else:
            raise PlanError("support entry contains an unsupported operation")
    return text.encode("utf-8")


def _static_profile_activation(
    content: bytes,
    operation: dict[str, Any],
    materialized: dict[str, bytes | None],
    *,
    verify_target: bool,
) -> bytes:
    dependency = materialized.get(operation["inputPath"])
    if dependency is None:
        raise PlanError(
            f"profile rebind input is absent or unplanned: {operation['inputPath']}"
        )
    text = _decode(content, "static target profile")
    document = _json_load_bytes(content, "static target profile")
    activation = document["activation"]
    issue = operation["issue"]
    if activation["blockingIssues"].count(issue) != 1:
        raise PlanError("static profile blocking issue pre-state changed")
    selected = [
        item for item in activation["pendingSelectors"] if item["issue"] == issue
    ]
    selected_ids = sorted(item["id"] for item in selected)
    if selected_ids != sorted(operation["pendingSelectorIds"]):
        raise PlanError("static profile issue selectors pre-state changed")
    components = [
        component
        for component in document["components"]
        if component["id"] == operation["componentId"]
    ]
    if len(components) != 1:
        raise PlanError("profile component must exist exactly once")
    inputs = [
        item
        for item in components[0]["inputs"]
        if item["path"] == operation["inputPath"]
    ]
    if len(inputs) != 1 or inputs[0]["sha256"] != operation["fromSha256"]:
        raise PlanError("profile input pre-state changed")
    expected = _sha256(dependency)
    if verify_target and operation["toSha256"] != expected:
        raise PlanError("profile input post-state is not bound to planned bytes")
    blocking_line = next(
        (
            line
            for line in text.splitlines(keepends=True)
            if '"blockingIssues":' in line
        ),
        None,
    )
    if blocking_line is None:
        raise PlanError("static profile blockingIssues line is missing")
    replacement_line = blocking_line.replace(
        json.dumps(activation["blockingIssues"]),
        json.dumps([value for value in activation["blockingIssues"] if value != issue]),
    )
    if replacement_line == blocking_line:
        raise PlanError("static profile blockingIssues formatting drifted")
    text = _replace_once(text, blocking_line, replacement_line, operation["id"])
    for selector in selected:
        marker = f'"id": "{selector["id"]}"'
        lines = [line for line in text.splitlines(keepends=True) if marker in line]
        if len(lines) != 1:
            raise PlanError(
                f"static profile selector formatting drifted: {selector['id']}"
            )
        text = _replace_once(text, lines[0], "", selector["id"])
    text = _replace_once(text, operation["fromSha256"], expected, operation["id"])
    transformed = _json_load_bytes(text.encode("utf-8"), "transformed static profile")
    if issue in transformed["activation"]["blockingIssues"] or any(
        item["issue"] == issue for item in transformed["activation"]["pendingSelectors"]
    ):
        raise PlanError("static profile activation transition is incomplete")
    return text.encode("utf-8")


def materialize_plan(
    root: Path, plan: dict[str, Any], *, verify_after: bool = True
) -> dict[str, bytes | None]:
    commit = plan["auditedCommit"]
    actual_tree = _git(root, "rev-parse", f"{commit}^{{tree}}").decode().strip()
    if actual_tree != plan["auditedTree"]:
        raise PlanError("audited tree does not match audited commit")
    entries = plan["entries"]
    paths = [entry["path"] for entry in entries]
    if paths != sorted(paths) or len(paths) != len(set(paths)):
        raise PlanError("plan entries must have unique sorted paths")
    for index, path in enumerate(paths):
        if any(other.startswith(f"{path}/") for other in paths[index + 1 :]):
            raise PlanError(f"plan paths overlap by ancestry: {path}")
    materialized: dict[str, bytes | None] = {}
    deferred: list[tuple[dict[str, Any], bytes]] = []
    for entry in entries:
        path = entry["path"]
        if path.startswith(PROTECTED_V1_PREFIX) or path in PROTECTED_PATHS:
            raise PlanError(f"signed v1 trust root cannot be planned: {path}")
        before_mode, before_type, _ = _tree_entry(root, commit, path)
        if before_type != "blob" or before_mode not in {"100644", "100755"}:
            raise PlanError(f"planned source is not a regular file: {path}")
        if before_mode != entry["beforeMode"]:
            raise PlanError(f"before mode mismatch: {path}")
        before = _audited_blob(root, commit, path)
        if _git_blob_sha(before) != entry["beforeGitBlobSha"]:
            raise PlanError(f"before Git blob mismatch: {path}")
        if entry["after"]["state"] == "absent":
            if entry["operations"] != [{"id": "delete-file", "kind": "file-delete"}]:
                raise PlanError(
                    f"file deletion must use the sole delete-file operation: {path}"
                )
            materialized[path] = None
            continue
        operations = entry["operations"]
        operation_ids = [operation["id"] for operation in operations]
        if operation_ids != sorted(operation_ids) or len(operation_ids) != len(
            set(operation_ids)
        ):
            raise PlanError(f"operation ids must be unique and sorted: {path}")
        kinds = {operation["kind"] for operation in operations}
        if kinds <= {
            "workflow-job-delete",
            "workflow-needs-edge-delete",
            "workflow-output-delete",
            "workflow-step-delete",
            "workflow-scalar-replace",
        }:
            after = _workflow_transform(before, operations)
        elif kinds <= {
            "python-binding-closure-delete",
            "python-tuple-literals-delete",
            "python-function-delete",
        }:
            after = _python_transform(before, operations)
        elif kinds == {"test-inventory-retire"} and len(operations) == 1:
            after = _test_inventory_transform(before, operations[0])
        elif kinds <= {"exact-text-replace", "python-assertion-key-delete"}:
            after = _exact_text_transform(before, operations, path)
        elif kinds == {"static-profile-activation-transition"} and len(operations) == 1:
            deferred.append((entry, before))
            continue
        else:
            raise PlanError(
                f"unsupported operation combination: {path} {sorted(kinds)}"
            )
        materialized[path] = after

    for entry, before in deferred:
        after = _static_profile_activation(
            before,
            entry["operations"][0],
            materialized,
            verify_target=verify_after,
        )
        materialized[entry["path"]] = after

    for entry in entries:
        after = materialized[entry["path"]]
        if after is None:
            continue
        if not verify_after:
            continue
        expected = entry["after"]
        if _git_blob_sha(after) != expected["gitBlobSha"]:
            raise PlanError(f"after Git blob mismatch: {entry['path']}")
        if _sha256(after) != expected["sha256"]:
            raise PlanError(f"after SHA-256 mismatch: {entry['path']}")
    return materialized


def _changed_paths(root: Path, before: str, after: str) -> set[str]:
    return {
        line
        for line in _git(root, "diff", "--name-only", before, after, "--")
        .decode("utf-8")
        .splitlines()
        if line
    }


def _assert_exact_changed_paths(
    root: Path, before: str, after: str, expected: set[str], label: str
) -> None:
    observed = _changed_paths(root, before, after)
    if observed != expected:
        raise PlanError(
            f"{label} changed-path set differs; "
            f"extra={sorted(observed - expected)}, missing={sorted(expected - observed)}"
        )


def _assert_authorities_unchanged(
    root: Path, preapproval_commit: str, later_commit: str, paths: set[str]
) -> None:
    for path in sorted(paths):
        if _tree_entry(root, preapproval_commit, path) != _tree_entry(
            root, later_commit, path
        ):
            raise PlanError(f"preapproval authority changed after P: {path}")


def _assert_checkout_matches_commit(root: Path, commit: str, paths: set[str]) -> None:
    for relative_path in sorted(paths):
        path = root / relative_path
        if path.is_symlink() or not path.is_file():
            raise PlanError(
                f"checked-out authority is not a regular file: {relative_path}"
            )
        _, _, expected = _regular_blob(root, commit, relative_path)
        if path.read_bytes() != expected:
            raise PlanError(
                f"checked-out authority differs from committed P: {relative_path}"
            )


def validate_framework(root: Path) -> None:
    for relative_path in (
        "contracts/repository-removal/v2/removal-plan.schema.json",
        "contracts/repository-removal/v2/preapproval.schema.json",
        "contracts/repository-removal/v2/owner-decision.schema.json",
    ):
        schema = _json_load_path(root / relative_path, relative_path)
        if schema.get("$schema") != "https://json-schema.org/draft/2020-12/schema":
            raise PlanError(
                f"v2 schema does not declare Draft 2020-12: {relative_path}"
            )


def validate_preapproval_commit(
    root: Path, preapproval_commit: str, *, checkout_commit: str | None = None
) -> tuple[dict[str, Any], dict[str, Any], bytes, bytes, set[str]]:
    _assert_commit(root, preapproval_commit)
    if _optional_tree_entry(root, preapproval_commit, DECISION_PATH) is not None:
        raise PlanError("owner decision must be absent at preapproval commit P")
    _, _, plan_bytes = _regular_blob(root, preapproval_commit, PLAN_PATH)
    _, _, preapproval_bytes = _regular_blob(root, preapproval_commit, PREAPPROVAL_PATH)
    plan = _json_load_bytes(plan_bytes, "removal plan")
    preapproval = _json_load_bytes(preapproval_bytes, "preapproval")
    _, _, plan_schema_bytes = _regular_blob(
        root, preapproval_commit, EXPECTED_TRUST_ROOTS["v2PlanSchema"]
    )
    _, _, preapproval_schema_bytes = _regular_blob(
        root, preapproval_commit, EXPECTED_TRUST_ROOTS["v2PreapprovalSchema"]
    )
    _schema_validate_document(
        plan, _json_load_bytes(plan_schema_bytes, "removal plan schema"), "removal plan"
    )
    _schema_validate_document(
        preapproval,
        _json_load_bytes(preapproval_schema_bytes, "preapproval schema"),
        "preapproval",
    )
    if preapproval["trustRoots"] != EXPECTED_TRUST_ROOTS:
        raise PlanError(
            "preapproval trustRoots do not equal the exact required mapping"
        )
    if set(preapproval["trustRootSha256"]) != set(EXPECTED_TRUST_ROOTS):
        raise PlanError("preapproval trustRootSha256 names are not exact")
    for name, path in EXPECTED_TRUST_ROOTS.items():
        _, _, content = _regular_blob(root, preapproval_commit, path)
        if _sha256(content) != preapproval["trustRootSha256"][name]:
            raise PlanError(f"preapproval trust root hash mismatch: {name}")
    if preapproval["auditedCommit"] != plan["auditedCommit"]:
        raise PlanError("preapproval audited commit does not match plan")
    if preapproval["auditedTree"] != plan["auditedTree"]:
        raise PlanError("preapproval audited tree does not match plan")
    if preapproval["removalPlanSha256"] != _sha256(plan_bytes):
        raise PlanError("preapproval removal plan hash mismatch")
    materialize_plan(root, plan)
    authority_paths = {PLAN_PATH, PREAPPROVAL_PATH, *EXPECTED_TRUST_ROOTS.values()}
    if checkout_commit is not None:
        _assert_authorities_unchanged(
            root, preapproval_commit, checkout_commit, authority_paths
        )
        _assert_checkout_matches_commit(root, preapproval_commit, authority_paths)
    return plan, preapproval, plan_bytes, preapproval_bytes, authority_paths


def expected_owner_approval_text(
    preapproval: dict[str, Any], preapproval_commit: str, preapproval_sha256: str
) -> str:
    template = preapproval["ownerApprovalTemplate"]
    if (
        template.count("<PREAPPROVAL_COMMIT>") != 1
        or template.count("<PREAPPROVAL_SHA256>") != 1
    ):
        raise PlanError("owner approval template placeholders are not exact")
    return template.replace("<PREAPPROVAL_COMMIT>", preapproval_commit).replace(
        "<PREAPPROVAL_SHA256>", preapproval_sha256
    )


def _verify_owner_comment(decision: dict[str, Any], expected_text: str) -> None:
    source = decision["approvalSource"]
    if not source["commentUrl"].endswith(f"#issuecomment-{source['commentId']}"):
        raise PlanError("v2 owner comment URL does not match comment id")
    try:
        response = subprocess.run(
            [
                "gh",
                "api",
                "--method",
                "GET",
                f"repos/artemsemdev/SeaRise-Europe/issues/comments/{source['commentId']}",
            ],
            check=True,
            capture_output=True,
        ).stdout
        comment = _json_load_bytes(response, "live GitHub owner comment")
    except (OSError, subprocess.CalledProcessError) as exc:
        raise PlanError("live GitHub v2 owner comment cannot be verified") from exc
    user = comment.get("user")
    observed = {
        "id": comment.get("id"),
        "html_url": comment.get("html_url"),
        "issue_url": comment.get("issue_url"),
        "body": comment.get("body"),
        "author_association": comment.get("author_association"),
        "login": user.get("login") if isinstance(user, dict) else None,
    }
    required = {
        "id": source["commentId"],
        "html_url": source["commentUrl"],
        "issue_url": "https://api.github.com/repos/artemsemdev/SeaRise-Europe/issues/68",
        "body": expected_text,
        "author_association": "OWNER",
        "login": "artemsemdev",
    }
    if observed != required:
        raise PlanError("live GitHub v2 owner comment does not exactly match approval")


def validate_decision_commit(
    root: Path,
    preapproval_commit: str,
    decision_commit: str,
    *,
    verify_owner_comment: bool,
    checkout_commit: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any], set[str]]:
    _assert_commit(root, decision_commit)
    _assert_ancestor(root, preapproval_commit, decision_commit)
    _assert_exact_changed_paths(
        root, preapproval_commit, decision_commit, {DECISION_PATH}, "P-to-D"
    )
    plan, preapproval, plan_bytes, preapproval_bytes, authority_paths = (
        validate_preapproval_commit(
            root, preapproval_commit, checkout_commit=checkout_commit or decision_commit
        )
    )
    _assert_authorities_unchanged(
        root, preapproval_commit, decision_commit, authority_paths
    )
    _, _, decision_bytes = _regular_blob(root, decision_commit, DECISION_PATH)
    decision = _json_load_bytes(decision_bytes, "owner decision")
    _, _, decision_schema_bytes = _regular_blob(
        root, preapproval_commit, EXPECTED_TRUST_ROOTS["v2OwnerDecisionSchema"]
    )
    _schema_validate_document(
        decision,
        _json_load_bytes(decision_schema_bytes, "owner decision schema"),
        "owner decision",
    )
    expected_text = expected_owner_approval_text(
        preapproval, preapproval_commit, _sha256(preapproval_bytes)
    )
    expected = {
        "preapprovalCommit": preapproval_commit,
        "preapprovalSha256": _sha256(preapproval_bytes),
        "removalPlanSha256": _sha256(plan_bytes),
        "approvalText": expected_text,
    }
    for field, value in expected.items():
        if decision[field] != value:
            raise PlanError(f"v2 owner decision {field} does not match committed P")
    if decision["approvalSource"]["bodySha256"] != _sha256(
        expected_text.encode("utf-8")
    ):
        raise PlanError("v2 owner decision bodySha256 does not match approval text")
    if not verify_owner_comment:
        raise PlanError("live GitHub v2 owner comment verification is required")
    _verify_owner_comment(decision, expected_text)
    return plan, decision, authority_paths


def validate_applied_commit(
    root: Path,
    preapproval_commit: str,
    decision_commit: str,
    applied_commit: str,
    *,
    verify_owner_comment: bool,
) -> None:
    _assert_commit(root, applied_commit)
    _assert_ancestor(root, decision_commit, applied_commit)
    plan, _, authority_paths = validate_decision_commit(
        root,
        preapproval_commit,
        decision_commit,
        verify_owner_comment=verify_owner_comment,
        checkout_commit=applied_commit,
    )
    _assert_authorities_unchanged(
        root, preapproval_commit, applied_commit, authority_paths
    )
    if _tree_entry(root, decision_commit, DECISION_PATH) != _tree_entry(
        root, applied_commit, DECISION_PATH
    ):
        raise PlanError("owner decision changed after D")
    materialized = materialize_plan(root, plan)
    _assert_exact_changed_paths(
        root,
        decision_commit,
        applied_commit,
        set(materialized),
        "D-to-A",
    )
    entries = {entry["path"]: entry for entry in plan["entries"]}
    for path, expected_bytes in materialized.items():
        observed = _optional_tree_entry(root, applied_commit, path)
        if expected_bytes is None:
            if observed is not None:
                raise PlanError(f"planned absent path still has a Git entry: {path}")
            continue
        if observed is None:
            raise PlanError(f"planned present path is absent: {path}")
        mode, object_type, object_id = observed
        expected = entries[path]["after"]
        if object_type != "blob" or mode != expected["mode"]:
            raise PlanError(f"planned present path has wrong type or mode: {path}")
        content = _git(root, "cat-file", "blob", object_id)
        if (
            object_id != expected["gitBlobSha"]
            or _sha256(content) != expected["sha256"]
            or content != expected_bytes
        ):
            raise PlanError(f"applied bytes do not match exact plan: {path}")


def validate_ci_state(
    root: Path,
    execution_base: str,
    applied_commit: str,
    *,
    verify_owner_comment: bool,
) -> None:
    states = {
        path: _optional_tree_entry(root, applied_commit, path) is not None
        for path in (PLAN_PATH, PREAPPROVAL_PATH, DECISION_PATH)
    }
    if not any(states.values()):
        validate_framework(root)
        return
    if not states[PLAN_PATH] or not states[PREAPPROVAL_PATH]:
        raise PlanError("repository-removal v2 artifacts are in a partial state")
    if not states[DECISION_PATH]:
        validate_preapproval_commit(
            root, applied_commit, checkout_commit=applied_commit
        )
        return
    _, _, decision_bytes = _regular_blob(root, applied_commit, DECISION_PATH)
    decision = _json_load_bytes(decision_bytes, "owner decision")
    preapproval_commit = decision.get("preapprovalCommit")
    if not isinstance(preapproval_commit, str):
        raise PlanError("owner decision does not identify preapproval commit P")
    if _optional_tree_entry(root, execution_base, DECISION_PATH) is None:
        validate_decision_commit(
            root,
            preapproval_commit,
            applied_commit,
            verify_owner_comment=verify_owner_comment,
            checkout_commit=applied_commit,
        )
    else:
        validate_applied_commit(
            root,
            preapproval_commit,
            execution_base,
            applied_commit,
            verify_owner_comment=verify_owner_comment,
        )


def _add_commit_argument(parser: argparse.ArgumentParser, name: str) -> None:
    parser.add_argument(name, required=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--repository-root", type=Path, default=Path(__file__).resolve().parents[2]
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("framework")
    preapproval = subparsers.add_parser("preapproval")
    _add_commit_argument(preapproval, "--preapproval-commit")
    decision = subparsers.add_parser("decision")
    _add_commit_argument(decision, "--preapproval-commit")
    _add_commit_argument(decision, "--decision-commit")
    decision.add_argument("--verify-owner-comment", action="store_true")
    applied = subparsers.add_parser("applied")
    _add_commit_argument(applied, "--preapproval-commit")
    _add_commit_argument(applied, "--decision-commit")
    _add_commit_argument(applied, "--applied-commit")
    applied.add_argument("--verify-owner-comment", action="store_true")
    ci = subparsers.add_parser("ci")
    _add_commit_argument(ci, "--execution-base")
    _add_commit_argument(ci, "--applied-commit")
    ci.add_argument("--verify-owner-comment", action="store_true")
    preview = subparsers.add_parser("preview")
    preview.add_argument("--plan", default=PLAN_PATH)
    preview.add_argument("--print-materialized-hashes", action="store_true")
    arguments = parser.parse_args()
    root = arguments.repository_root.resolve()
    try:
        if arguments.command == "framework":
            validate_framework(root)
        elif arguments.command == "preapproval":
            validate_preapproval_commit(
                root,
                arguments.preapproval_commit,
                checkout_commit=arguments.preapproval_commit,
            )
        elif arguments.command == "decision":
            validate_decision_commit(
                root,
                arguments.preapproval_commit,
                arguments.decision_commit,
                verify_owner_comment=arguments.verify_owner_comment,
            )
        elif arguments.command == "applied":
            validate_applied_commit(
                root,
                arguments.preapproval_commit,
                arguments.decision_commit,
                arguments.applied_commit,
                verify_owner_comment=arguments.verify_owner_comment,
            )
        elif arguments.command == "ci":
            validate_ci_state(
                root,
                arguments.execution_base,
                arguments.applied_commit,
                verify_owner_comment=arguments.verify_owner_comment,
            )
        else:
            plan = _json_load_path(root / arguments.plan, "removal plan preview")
            _schema_validate(
                plan,
                root / "contracts/repository-removal/v2/removal-plan.schema.json",
                "removal plan",
            )
            materialized = materialize_plan(root, plan, verify_after=False)
            if arguments.print_materialized_hashes:
                print(
                    json.dumps(
                        {
                            path: None
                            if content is None
                            else {
                                "gitBlobSha": _git_blob_sha(content),
                                "sha256": _sha256(content),
                            }
                            for path, content in materialized.items()
                        },
                        indent=2,
                        sort_keys=True,
                    )
                )
        print(f"validated repository-removal v2 {arguments.command}")
    except (KeyError, TypeError, ValueError, PlanError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
