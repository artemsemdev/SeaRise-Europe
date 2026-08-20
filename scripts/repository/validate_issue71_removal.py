"""Run the additive issue #71 lifecycle after completed issue #70.

The reviewed v2 engine and completed issue #70 authority stay immutable. This
adapter specializes their fail-closed operations for issue #71 and binds every
new plan to the completed issue #70 receipt as a trust root.
"""

from __future__ import annotations

import copy
import importlib.util
import sys
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
_ISSUE70_PATH = REPOSITORY_ROOT / "scripts/repository/validate_issue70_removal.py"
_ISSUE70_SPEC = importlib.util.spec_from_file_location(
    "_searise_repository_removal_issue70_for_issue71", _ISSUE70_PATH
)
if _ISSUE70_SPEC is None or _ISSUE70_SPEC.loader is None:
    raise RuntimeError("issue #70 authority adapter cannot be loaded")
issue70 = importlib.util.module_from_spec(_ISSUE70_SPEC)
_ISSUE70_SPEC.loader.exec_module(issue70)


PROFILE_PATH = "contracts/repository-removal/v2/issue-71/profile.json"
VALIDATOR_PATH = "scripts/repository/validate_issue71_removal.py"
COMPLETED_ISSUE_70_ARTIFACTS = {
    "issue70ApplicationReceipt": (
        "contracts/repository-removal/v2/issue-70/application-receipt.json"
    ),
    "issue70OwnerDecision": (
        "contracts/repository-removal/v2/issue-70/owner-decision.json"
    ),
    "issue70Preapproval": "contracts/repository-removal/v2/issue-70/preapproval.json",
    "issue70Profile": "contracts/repository-removal/v2/issue-70/profile.json",
    "issue70RemovalPlan": "contracts/repository-removal/v2/issue-70/removal-plan.json",
    "issue70Validator": "scripts/repository/validate_issue70_removal.py",
}
CONTENT_AUTHORITY_HANDOFF_PATHS = {
    "src/web/scripts/check-target-content.mjs",
    "src/web/scripts/static-repository-gates.test.mjs",
}
EXPECTED_PROFILE = {
    "schemaVersion": "2.0.0",
    "profileId": "phase-2-issue-71-removal-v2",
    "issue": 71,
    "approvalIssue": 68,
    "contractDirectory": "contracts/repository-removal/v2/issue-71",
    "planId": "phase-2-issue-71-exact-removal-v2",
    "preapprovalId": "phase-2-issue-71-removal-v2",
    "receiptId": "phase-2-issue-71-removal-v2-application",
    "baseValidator": "scripts/repository/validate_removal_plan_v2.py",
    "baseSchemaDirectory": "contracts/repository-removal/v2",
    "safety": {
        "candidatePublicationAuthorized": False,
        "externalResourceMutationAuthorized": False,
    },
}


def _repository_root_from_args() -> Path:
    arguments = sys.argv[1:]
    for index, argument in enumerate(arguments):
        if argument == "--repository-root" and index + 1 < len(arguments):
            return Path(arguments[index + 1]).resolve()
        if argument.startswith("--repository-root="):
            return Path(argument.partition("=")[2]).resolve()
    return REPOSITORY_ROOT


def _specialize(value: Any) -> Any:
    if isinstance(value, dict):
        specialized = {key: _specialize(item) for key, item in value.items()}
        if specialized.get("const") == 70:
            specialized["const"] = 71
        return specialized
    if isinstance(value, list):
        return [_specialize(item) for item in value]
    if isinstance(value, str):
        return value.replace("issue-70", "issue-71")
    return value


def _issue71_schema(schema: dict[str, Any]) -> dict[str, Any]:
    return _specialize(issue70._issue70_schema(copy.deepcopy(schema)))


def _materialize_plan(
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
    base_plan = copy.deepcopy(plan)
    for entry, original in zip(base_plan["entries"], plan["entries"]):
        entry["operations"] = [
            operation
            for operation in entry["operations"]
            if operation["kind"] not in custom_kinds
        ]
        if not entry["operations"] and not (
            entry["path"] in CONTENT_AUTHORITY_HANDOFF_PATHS
            and len(original["operations"]) == 1
            and original["operations"][0]["kind"] == "content-authority-handoff"
        ):
            raise engine.PlanError(
                "issue #71 custom operation must accompany a structural operation"
            )
    base_plan["entries"] = [entry for entry in base_plan["entries"] if entry["operations"]]
    materialized = engine._issue71_base_materialize_plan(
        root, base_plan, verify_after=False
    )

    for entry in custom_entries:
        content = materialized.get(entry["path"])
        if content is None and all(
            operation["kind"] == "content-authority-handoff"
            for operation in entry["operations"]
        ):
            content = engine._audited_blob(root, plan["auditedCommit"], entry["path"])
        if content is None:
            raise engine.PlanError("issue #71 custom operation target is absent")
        for operation in entry["operations"]:
            kind = operation["kind"]
            if kind == "content-authority-handoff":
                if entry["path"] not in CONTENT_AUTHORITY_HANDOFF_PATHS:
                    raise engine.PlanError(
                        "content authority handoff is restricted to content gates"
                    )
                source = operation["from"].encode("utf-8")
                if content.count(source) != 1:
                    raise engine.PlanError(
                        "content authority handoff source must match exactly once"
                    )
                content = content.replace(source, operation["to"].encode("utf-8"), 1)
            elif kind == "workflow-step-run-replace":
                if entry["path"] != ".github/workflows/ci.yml":
                    raise engine.PlanError("workflow step handoff is restricted to CI")
                content = issue70._replace_workflow_step_run(engine, content, operation)
            elif kind == "python-tuple-literal-value-delete":
                if entry["path"] != "scripts/ci/changed_components.py":
                    raise engine.PlanError(
                        "Python tuple deletion is restricted to the CI router"
                    )
                content = issue70._delete_python_tuple_literal_values(
                    engine, content, operation
                )
        materialized[entry["path"]] = content

    for entry in plan["entries"]:
        operations = entry["operations"]
        if (
            len(operations) == 1
            and operations[0]["kind"] == "static-profile-activation-transition"
        ):
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
            if engine._git_blob_sha(after) != entry["after"]["gitBlobSha"]:
                raise engine.PlanError(f"after Git blob mismatch: {entry['path']}")
            if engine._sha256(after) != entry["after"]["sha256"]:
                raise engine.PlanError(f"after SHA-256 mismatch: {entry['path']}")
    return materialized


def configure_engine(repository_root: Path) -> Any:
    engine = issue70._load_base_engine(repository_root)
    profile = engine._json_load_path(repository_root / PROFILE_PATH, "issue #71 profile")
    if profile != EXPECTED_PROFILE:
        raise engine.PlanError("issue #71 profile differs from its exact contract")
    contract_directory = profile["contractDirectory"]
    engine.CONTRACT_DIRECTORY = contract_directory
    engine.PLAN_PATH = f"{contract_directory}/removal-plan.json"
    engine.PREAPPROVAL_PATH = f"{contract_directory}/preapproval.json"
    engine.DECISION_PATH = f"{contract_directory}/owner-decision.json"
    engine.RECEIPT_PATH = f"{contract_directory}/application-receipt.json"
    engine.SUPPORT_REWRITE_PATHS = {
        *engine.SUPPORT_REWRITE_PATHS,
        "src/pipeline/tests/supply_chain/test_static_target_profile.py",
        "src/web/scripts/static-repository-gates.test.mjs",
    }
    engine.EXPECTED_TRUST_ROOTS = {
        **engine.EXPECTED_TRUST_ROOTS,
        **COMPLETED_ISSUE_70_ARTIFACTS,
        "issue71Profile": PROFILE_PATH,
        "issue71Validator": VALIDATOR_PATH,
    }
    base_validate = engine._schema_validate_document

    def validate_specialized(
        document: dict[str, Any], schema: dict[str, Any], label: str
    ) -> None:
        if label in {
            "removal plan",
            "preapproval",
            "owner decision",
            "application receipt",
        }:
            schema = _issue71_schema(schema)
        base_validate(document, schema, label)

    engine._schema_validate_document = validate_specialized
    engine._issue71_base_materialize_plan = engine.materialize_plan
    engine.materialize_plan = lambda root, plan, verify_after=True: _materialize_plan(
        engine, root, plan, verify_after=verify_after
    )
    return engine


def validate_framework(repository_root: Path) -> None:
    import jsonschema

    engine = configure_engine(repository_root)
    engine.validate_framework(repository_root)
    for relative_path in (
        PROFILE_PATH,
        VALIDATOR_PATH,
        *COMPLETED_ISSUE_70_ARTIFACTS.values(),
    ):
        path = repository_root / relative_path
        if path.is_symlink() or not path.is_file():
            raise engine.PlanError(
                f"issue #71 authority must be a regular file: {relative_path}"
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
        jsonschema.Draft202012Validator.check_schema(_issue71_schema(schema))


def main() -> int:
    repository_root = _repository_root_from_args()
    try:
        if "framework" in sys.argv[1:]:
            validate_framework(repository_root)
            print("validated repository-removal v2 issue-71 framework")
            return 0
        return configure_engine(repository_root).main()
    except (KeyError, TypeError, ValueError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
