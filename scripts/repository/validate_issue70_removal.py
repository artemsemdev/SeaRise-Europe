"""Run an additive issue #70 lifecycle without rewriting the completed #72 chain.

The reviewed v2 engine remains byte-for-byte unchanged. This adapter loads it
in an isolated module, binds it to a separate contract directory and exact
issue identifiers, and retains the completed issue #72 artifacts as trust
roots. The adapter and profile become trust roots of every #70 preapproval.
"""

from __future__ import annotations

import ast
import copy
import importlib.util
import sys
from pathlib import Path
from typing import Any

PROFILE_PATH = "contracts/repository-removal/v2/issue-70/profile.json"
VALIDATOR_PATH = "scripts/repository/validate_issue70_removal.py"
COMPLETED_ISSUE_72_ARTIFACTS = {
    "issue72ApplicationReceipt": (
        "contracts/repository-removal/v2/application-receipt.json"
    ),
    "issue72OwnerDecision": "contracts/repository-removal/v2/owner-decision.json",
    "issue72Preapproval": "contracts/repository-removal/v2/preapproval.json",
    "issue72RemovalPlan": "contracts/repository-removal/v2/removal-plan.json",
}
CONTENT_AUTHORITY_HANDOFF_PATHS = {
    "src/web/scripts/check-target-content.mjs",
    "src/web/scripts/static-repository-gates.test.mjs",
}
EXPECTED_PROFILE = {
    "schemaVersion": "2.0.0",
    "profileId": "phase-2-issue-70-removal-v2",
    "issue": 70,
    "approvalIssue": 68,
    "contractDirectory": "contracts/repository-removal/v2/issue-70",
    "planId": "phase-2-issue-70-exact-removal-v2",
    "preapprovalId": "phase-2-issue-70-removal-v2",
    "receiptId": "phase-2-issue-70-removal-v2-application",
    "baseValidator": "scripts/repository/validate_removal_plan_v2.py",
    "baseSchemaDirectory": "contracts/repository-removal/v2",
    "safety": {
        "candidatePublicationAuthorized": False,
        "externalResourceMutationAuthorized": False,
    },
}


def _load_base_engine(repository_root: Path) -> Any:
    validator = repository_root / EXPECTED_PROFILE["baseValidator"]
    if validator.is_symlink() or not validator.is_file():
        raise RuntimeError("issue #70 base validator must be a regular file")
    spec = importlib.util.spec_from_file_location(
        "_searise_repository_removal_v2_issue70_base",
        validator,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("issue #70 base validator cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _repository_root_from_args() -> Path:
    default = Path(__file__).resolve().parents[2]
    arguments = sys.argv[1:]
    for index, argument in enumerate(arguments):
        if argument == "--repository-root" and index + 1 < len(arguments):
            return Path(arguments[index + 1]).resolve()
        if argument.startswith("--repository-root="):
            return Path(argument.partition("=")[2]).resolve()
    return default


def _specialize_schema(value: Any) -> Any:
    if isinstance(value, dict):
        specialized = {key: _specialize_schema(item) for key, item in value.items()}
        if specialized.get("const") == 72:
            specialized["const"] = 70
        return specialized
    if isinstance(value, list):
        return [_specialize_schema(item) for item in value]
    if isinstance(value, str):
        return value.replace("issue-72", "issue-70")
    return value


def _issue70_schema(schema: dict[str, Any]) -> dict[str, Any]:
    specialized = _specialize_schema(copy.deepcopy(schema))
    operations = specialized.get("$defs", {}).get("operation", {}).get("oneOf")
    if isinstance(operations, list):
        operations.append(
            {
                "type": "object",
                "additionalProperties": False,
                "required": ["id", "kind", "job", "name", "from", "to"],
                "properties": {
                    "id": {"type": "string"},
                    "kind": {"const": "workflow-step-run-replace"},
                    "job": {"type": "string", "minLength": 1},
                    "name": {"type": "string", "minLength": 1},
                    "from": {"type": "string", "minLength": 1},
                    "to": {"type": "string", "minLength": 1},
                },
            }
        )
        operations.append(
            {
                "type": "object",
                "additionalProperties": False,
                "required": ["id", "kind", "from", "to"],
                "properties": {
                    "id": {"type": "string"},
                    "kind": {"const": "content-authority-handoff"},
                    "from": {"type": "string", "minLength": 1},
                    "to": {"type": "string", "minLength": 1},
                },
            }
        )
        operations.append(
            {
                "type": "object",
                "additionalProperties": False,
                "required": ["id", "kind", "name", "values"],
                "properties": {
                    "id": {"type": "string"},
                    "kind": {"const": "python-tuple-literal-value-delete"},
                    "name": {"type": "string", "minLength": 1},
                    "values": {
                        "type": "array",
                        "minItems": 1,
                        "uniqueItems": True,
                        "items": {"type": "string", "minLength": 1},
                    },
                },
            }
        )
    return specialized


def _replace_workflow_step_run(
    engine: Any,
    content: bytes,
    operation: dict[str, Any],
) -> bytes:
    lines = content.decode("utf-8").splitlines(keepends=True)
    job_start, job_end = engine._workflow_job(lines, operation["job"])
    steps_start, steps_end = engine._mapping_key(
        lines, job_start + 1, job_end, 4, "steps"
    )
    marker = f"      - name: {operation['name']}"
    matches = [
        index
        for index in range(steps_start + 1, steps_end)
        if lines[index].rstrip("\n") == marker
    ]
    if len(matches) != 1:
        raise engine.PlanError(
            f"workflow step must exist exactly once: {operation['name']}"
        )
    start = matches[0]
    end = steps_end
    for index in range(start + 1, steps_end):
        if lines[index].startswith("      - "):
            end = index
            break
    step = "".join(lines[start:end])
    if step.count(operation["from"]) != 1:
        raise engine.PlanError(
            f"workflow step run source must match once: {operation['name']}"
        )
    lines[start:end] = [step.replace(operation["from"], operation["to"], 1)]
    return "".join(lines).encode("utf-8")


def _delete_python_tuple_literal_values(
    engine: Any,
    content: bytes,
    operation: dict[str, Any],
) -> bytes:
    text = content.decode("utf-8")
    tree = ast.parse(text)
    assignment = engine._module_assignment(tree, operation["name"])
    value = assignment.value
    if not isinstance(value, ast.Tuple):
        raise engine.PlanError(
            f"Python binding is not a literal tuple: {operation['name']}"
        )
    literals: list[str] = []
    for element in value.elts:
        if not isinstance(element, ast.Constant) or not isinstance(element.value, str):
            raise engine.PlanError(
                f"Python tuple contains a non-string literal: {operation['name']}"
            )
        literals.append(element.value)
    selected = operation["values"]
    selected_set = set(selected)
    for selected_value in selected:
        if literals.count(selected_value) != 1:
            raise engine.PlanError(
                "Python tuple value must exist exactly once: "
                f"{operation['name']}.{selected_value}"
            )
    remaining = [item for item in literals if item not in selected_set]
    if not remaining:
        raise engine.PlanError(
            f"Python tuple deletion would empty binding: {operation['name']}"
        )
    if assignment.col_offset != 0:
        raise engine.PlanError(
            f"Python tuple binding must be module-scoped: {operation['name']}"
        )
    lines = text.splitlines(keepends=True)
    replacement = [f"{operation['name']} = (\n"]
    replacement.extend(f"    {item!r},\n" for item in remaining)
    replacement.append(")\n")
    lines[assignment.lineno - 1 : assignment.end_lineno] = replacement
    transformed = "".join(lines)
    ast.parse(transformed)
    return transformed.encode("utf-8")


def _issue70_materialize_plan(
    engine: Any,
    root: Path,
    plan: dict[str, Any],
    *,
    verify_after: bool = True,
) -> dict[str, bytes | None]:
    custom_kinds = {
        "content-authority-handoff",
        "python-tuple-literal-value-delete",
        "workflow-step-run-replace",
    }
    custom_entries = [
        entry
        for entry in plan["entries"]
        if any(operation["kind"] in custom_kinds for operation in entry["operations"])
    ]
    if not custom_entries:
        return engine._issue70_base_materialize_plan(
            root, plan, verify_after=verify_after
        )

    base_plan = copy.deepcopy(plan)
    for entry, original_entry in zip(base_plan["entries"], plan["entries"]):
        entry["operations"] = [
            operation
            for operation in entry["operations"]
            if operation["kind"] not in custom_kinds
        ]
        if not entry["operations"] and not (
            entry["path"] in CONTENT_AUTHORITY_HANDOFF_PATHS
            and len(original_entry["operations"]) == 1
            and original_entry["operations"][0]["kind"] == "content-authority-handoff"
        ):
            raise engine.PlanError(
                "issue #70 custom operation must accompany a structural operation"
            )
    base_plan["entries"] = [entry for entry in base_plan["entries"] if entry["operations"]]
    materialized = engine._issue70_base_materialize_plan(
        root, base_plan, verify_after=False
    )

    for entry in custom_entries:
        content = materialized.get(entry["path"])
        if content is None and all(
            operation["kind"] == "content-authority-handoff"
            for operation in entry["operations"]
        ):
            content = engine._audited_blob(
                root, plan["auditedCommit"], entry["path"]
            )
        if content is None:
            raise engine.PlanError("issue #70 custom operation target is absent")
        for operation in entry["operations"]:
            if operation["kind"] == "content-authority-handoff":
                if entry["path"] not in CONTENT_AUTHORITY_HANDOFF_PATHS:
                    raise engine.PlanError(
                        "content authority handoff is restricted to the content checker"
                    )
                source = operation["from"].encode("utf-8")
                if content.count(source) != 1:
                    raise engine.PlanError(
                        "content authority handoff source must match exactly once"
                    )
                content = content.replace(source, operation["to"].encode("utf-8"), 1)
            elif operation["kind"] == "workflow-step-run-replace":
                if entry["path"] != ".github/workflows/ci.yml":
                    raise engine.PlanError("workflow step handoff is restricted to CI")
                content = _replace_workflow_step_run(engine, content, operation)
            elif operation["kind"] == "python-tuple-literal-value-delete":
                if entry["path"] != "scripts/ci/changed_components.py":
                    raise engine.PlanError(
                        "Python tuple deletion is restricted to the CI router"
                    )
                content = _delete_python_tuple_literal_values(
                    engine, content, operation
                )
        materialized[entry["path"]] = content

    for entry in plan["entries"]:
        operations = entry["operations"]
        if (
            len(operations) != 1
            or operations[0]["kind"] != "static-profile-activation-transition"
        ):
            continue
        before = engine._audited_blob(root, plan["auditedCommit"], entry["path"])
        materialized[entry["path"]] = engine._static_profile_activation(
            before,
            operations[0],
            materialized,
            verify_target=verify_after,
        )

    if verify_after:
        for entry in plan["entries"]:
            after = materialized[entry["path"]]
            if after is None:
                continue
            expected = entry["after"]
            if engine._git_blob_sha(after) != expected["gitBlobSha"]:
                raise engine.PlanError(f"after Git blob mismatch: {entry['path']}")
            if engine._sha256(after) != expected["sha256"]:
                raise engine.PlanError(f"after SHA-256 mismatch: {entry['path']}")
    return materialized


def _issue70_test_inventory_transform(
    engine: Any,
    content: bytes,
    operation: dict[str, Any],
) -> bytes:
    """Promote only exact-plan baselines owned by selected issue #70 suites."""

    document = engine._json_load_bytes(content, "issue #70 test inventory")
    selected_suites = set(operation["suiteIds"])
    suites = {suite["id"]: suite for suite in document["suites"]}
    text = content.decode("utf-8")

    for path in operation["baselinePaths"]:
        matches = [item for item in document["baselineTests"] if item["path"] == path]
        if len(matches) != 1:
            raise engine.PlanError(
                f"baseline retirement path must exist exactly once: {path}"
            )
        item = matches[0]
        suite = suites.get(item["suite"])
        if (
            item["status"] != "active"
            or item["replacementEvidence"] is not None
            or item["suite"] not in selected_suites
            or suite is None
            or suite["replacementGate"]["issue"] != 70
        ):
            raise engine.PlanError(f"issue #70 baseline authority mismatch: {path}")
        if item["removalGate"] not in {None, 70}:
            raise engine.PlanError(f"issue #70 baseline gate differs: {path}")
        if item["removalGate"] is None:
            lines = text.splitlines(keepends=True)
            selected = [
                index for index, line in enumerate(lines) if f'"path": "{path}"' in line
            ]
            if len(selected) != 1:
                raise engine.PlanError(
                    f"issue #70 baseline formatting drifted: {path}"
                )
            index = selected[0]
            if lines[index].count('"removalGate": null') != 1:
                raise engine.PlanError(f"issue #70 baseline gate drifted: {path}")
            lines[index] = lines[index].replace(
                '"removalGate": null', '"removalGate": 70', 1
            )
            text = "".join(lines)

    return engine._issue70_base_test_inventory_transform(
        text.encode("utf-8"), operation
    )


def configure_engine(repository_root: Path) -> Any:
    engine = _load_base_engine(repository_root)
    profile = engine._json_load_path(repository_root / PROFILE_PATH, "issue #70 profile")
    if profile != EXPECTED_PROFILE:
        raise engine.PlanError("issue #70 profile differs from its exact contract")

    contract_directory = profile["contractDirectory"]
    engine.CONTRACT_DIRECTORY = contract_directory
    engine.PLAN_PATH = f"{contract_directory}/removal-plan.json"
    engine.PREAPPROVAL_PATH = f"{contract_directory}/preapproval.json"
    engine.DECISION_PATH = f"{contract_directory}/owner-decision.json"
    engine.RECEIPT_PATH = f"{contract_directory}/application-receipt.json"
    engine.EXPECTED_TRUST_ROOTS = {
        **engine.EXPECTED_TRUST_ROOTS,
        **COMPLETED_ISSUE_72_ARTIFACTS,
        "issue70Profile": PROFILE_PATH,
        "issue70Validator": VALIDATOR_PATH,
    }

    base_validate = engine._schema_validate_document

    def validate_specialized(
        document: dict[str, Any],
        schema: dict[str, Any],
        label: str,
    ) -> None:
        if label in {
            "removal plan",
            "preapproval",
            "owner decision",
            "application receipt",
        }:
            schema = _issue70_schema(schema)
        base_validate(document, schema, label)

    engine._schema_validate_document = validate_specialized
    engine._issue70_base_test_inventory_transform = engine._test_inventory_transform
    engine._test_inventory_transform = lambda content, operation: (
        _issue70_test_inventory_transform(engine, content, operation)
    )
    engine._issue70_base_materialize_plan = engine.materialize_plan
    engine.materialize_plan = lambda root, plan, verify_after=True: (
        _issue70_materialize_plan(
            engine,
            root,
            plan,
            verify_after=verify_after,
        )
    )
    return engine


def validate_framework(repository_root: Path) -> None:
    try:
        import jsonschema
    except ModuleNotFoundError as exc:
        raise RuntimeError("jsonschema is required for issue #70 authority") from exc

    engine = configure_engine(repository_root)
    engine.validate_framework(repository_root)
    for relative_path in (
        PROFILE_PATH,
        VALIDATOR_PATH,
        *COMPLETED_ISSUE_72_ARTIFACTS.values(),
    ):
        path = repository_root / relative_path
        if path.is_symlink() or not path.is_file():
            raise engine.PlanError(
                f"issue #70 authority must be a regular file: {relative_path}"
            )
    for schema_name in (
        "removal-plan.schema.json",
        "preapproval.schema.json",
        "owner-decision.schema.json",
        "application-receipt.schema.json",
    ):
        schema = engine._json_load_path(
            repository_root / EXPECTED_PROFILE["baseSchemaDirectory"] / schema_name,
            schema_name,
        )
        jsonschema.Draft202012Validator.check_schema(_issue70_schema(schema))


def main() -> int:
    repository_root = _repository_root_from_args()
    try:
        if "framework" in sys.argv[1:]:
            validate_framework(repository_root)
            print("validated repository-removal v2 issue-70 framework")
            return 0
        engine = configure_engine(repository_root)
        return engine.main()
    except (KeyError, TypeError, ValueError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
