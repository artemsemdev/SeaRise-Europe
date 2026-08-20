"""Run the additive issue #71 lifecycle after completed issue #70.

The reviewed v2 engine and completed issue #70 authority stay immutable. This
adapter specializes their fail-closed operations for issue #71 and binds every
new plan to the completed issue #70 receipt as a trust root.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import re
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
    "src/web/scripts/static-repository-gates.mjs",
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
    specialized = _specialize(issue70._issue70_schema(copy.deepcopy(schema)))
    operations = specialized.get("$defs", {}).get("operation", {}).get("oneOf")
    if isinstance(operations, list):
        operations.append(
            {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "id",
                    "kind",
                    "issue",
                    "pendingSelectorIds",
                    "inputBindings",
                ],
                "properties": {
                    "id": {"type": "string"},
                    "kind": {"const": "static-profile-multi-input-activation"},
                    "issue": {"const": 71},
                    "pendingSelectorIds": {
                        "type": "array",
                        "minItems": 1,
                        "uniqueItems": True,
                        "items": {"type": "string"},
                    },
                    "inputBindings": {
                        "type": "array",
                        "minItems": 2,
                        "maxItems": 2,
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": [
                                "componentId",
                                "inputPath",
                                "fromSha256",
                                "toSha256",
                            ],
                            "properties": {
                                "componentId": {"const": "github-actions"},
                                "inputPath": {
                                    "enum": [
                                        ".github/workflows/ci.yml",
                                        ".github/workflows/codeql.yml",
                                    ]
                                },
                                "fromSha256": {"$ref": "#/$defs/sha256"},
                                "toSha256": {"$ref": "#/$defs/sha256"},
                            },
                        },
                    },
                },
            }
        )
        for kind in (
            "pyproject-static-runtime-prune",
            "requirements-static-runtime-prune",
        ):
            operations.append(
                {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["id", "kind"],
                    "properties": {
                        "id": {"type": "string"},
                        "kind": {"const": kind},
                    },
                }
            )
    return specialized


def _activate_static_profile(
    engine: Any,
    content: bytes,
    operation: dict[str, Any],
    materialized: dict[str, bytes | None],
    *,
    verify_target: bool,
) -> bytes:
    document = engine._json_load_bytes(content, "static target profile")
    activation = document["activation"]
    issue = operation["issue"]
    if activation["blockingIssues"].count(issue) != 1:
        raise engine.PlanError("static profile blocking issue pre-state changed")
    selected = [item for item in activation["pendingSelectors"] if item["issue"] == issue]
    if sorted(item["id"] for item in selected) != sorted(operation["pendingSelectorIds"]):
        raise engine.PlanError("static profile issue selectors pre-state changed")
    bindings = operation["inputBindings"]
    paths = [binding["inputPath"] for binding in bindings]
    if sorted(paths) != [".github/workflows/ci.yml", ".github/workflows/codeql.yml"]:
        raise engine.PlanError("static profile bindings must cover both workflows")

    for binding in bindings:
        components = [
            component
            for component in document["components"]
            if component["id"] == binding["componentId"]
        ]
        inputs = [
            item
            for component in components
            for item in component["inputs"]
            if item["path"] == binding["inputPath"]
        ]
        if len(components) != 1 or len(inputs) != 1:
            raise engine.PlanError("static profile input must exist exactly once")
        if inputs[0]["sha256"] != binding["fromSha256"]:
            raise engine.PlanError("static profile input pre-state changed")
        dependency = materialized.get(binding["inputPath"])
        if dependency is None:
            raise engine.PlanError("static profile rebind dependency is absent")
        expected = engine._sha256(dependency)
        if verify_target and binding["toSha256"] != expected:
            raise engine.PlanError("static profile input post-state is not bound")
        inputs[0]["sha256"] = expected

    activation["blockingIssues"] = [
        value for value in activation["blockingIssues"] if value != issue
    ]
    activation["pendingSelectors"] = [
        item for item in activation["pendingSelectors"] if item["issue"] != issue
    ]
    if activation["pendingSelectors"] or activation["blockingIssues"]:
        raise engine.PlanError("issue #71 must be the final static profile blocker")
    if activation["status"] != "pending-legacy-removal":
        raise engine.PlanError("static profile activation status pre-state changed")
    activation["status"] = "active"

    pending = [
        component
        for component in document["components"]
        if component["id"] == "pending-legacy-python-authorities"
    ]
    contributor = [
        component
        for component in document["components"]
        if component["id"] == "pipeline-python-contributor"
    ]
    if len(pending) != 1 or len(contributor) != 1:
        raise engine.PlanError("static Python authority components changed")
    pending_inputs = pending[0]["inputs"]
    expected_paths = {
        "src/pipeline/pyproject.toml",
        "src/pipeline/requirements-pipeline.txt",
    }
    if {item["path"] for item in pending_inputs} != expected_paths:
        raise engine.PlanError("pending Python authority inputs changed")
    for item in pending_inputs:
        dependency = materialized.get(item["path"])
        if dependency is None:
            raise engine.PlanError("static Python authority dependency is absent")
        item["sha256"] = engine._sha256(dependency)
    contributor[0]["inputs"].extend(pending_inputs)
    contributor[0]["inputs"].sort(key=lambda item: item["path"])
    document["components"].remove(pending[0])
    return (json.dumps(document, indent=2) + "\n").encode("utf-8")


def _static_contributor_requirements(root: Path) -> list[str]:
    path = root / "contracts/supply-chain/v2/python/static-target-contributor-requirements.txt"
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def _prune_pyproject(engine: Any, content: bytes, root: Path) -> bytes:
    text = engine._decode(content, "issue #71 pyproject prune")
    requirements = _static_contributor_requirements(root)
    pytest_requirement = [item for item in requirements if item.casefold().startswith("pytest")]
    if len(pytest_requirement) != 1:
        raise engine.PlanError("static contributor pytest authority changed")
    dependencies = [item for item in requirements if item not in pytest_requirement]
    dependency_block = "dependencies = [\n" + "".join(
        f'    "{item}",\n' for item in dependencies
    ) + "]"
    dev_block = f'dev = [\n    "{pytest_requirement[0]}",\n]'
    text, dependency_count = re.subn(
        r"(?ms)^dependencies\s*=\s*\[.*?^\]", dependency_block, text, count=1
    )
    text, dev_count = re.subn(r"(?ms)^dev\s*=\s*\[.*?^\]", dev_block, text, count=1)
    if dependency_count != 1 or dev_count != 1:
        raise engine.PlanError("pyproject dependency authority pre-state changed")
    for line in ('    "pipeline",\n', '    "searise_pipeline.domain",\n', 'pipeline = "."\n'):
        if text.count(line) != 1:
            raise engine.PlanError("pyproject package mapping pre-state changed")
        text = text.replace(line, "", 1)
    return text.encode("utf-8")


def _prune_requirements(engine: Any, content: bytes, root: Path) -> bytes:
    text = engine._decode(content, "issue #71 requirements prune")
    for retired in ("azure-storage-blob>=12.19,<13.0", "psycopg2-binary>=2.9,<3.0"):
        if text.splitlines().count(retired) != 1:
            raise engine.PlanError("requirements dependency pre-state changed")
    return ("\n".join(_static_contributor_requirements(root)) + "\n").encode("utf-8")


def _materialize_plan(
    engine: Any,
    root: Path,
    plan: dict[str, Any],
    *,
    verify_after: bool = True,
) -> dict[str, bytes | None]:
    custom_kinds = {
        "content-authority-handoff",
        "pyproject-static-runtime-prune",
        "python-tuple-literal-value-delete",
        "requirements-static-runtime-prune",
        "static-profile-multi-input-activation",
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
        custom_only_allowed = (
            entry["path"] in CONTENT_AUTHORITY_HANDOFF_PATHS
            and len(original["operations"]) == 1
            and original["operations"][0]["kind"] == "content-authority-handoff"
        ) or (
            entry["path"] == "contracts/supply-chain/v2/static-target-profile.json"
            and len(original["operations"]) == 1
            and original["operations"][0]["kind"]
            == "static-profile-multi-input-activation"
        ) or (
            entry["path"]
            in {
                "src/pipeline/pyproject.toml",
                "src/pipeline/requirements-pipeline.txt",
            }
            and len(original["operations"]) == 1
            and original["operations"][0]["kind"]
            in {
                "pyproject-static-runtime-prune",
                "requirements-static-runtime-prune",
            }
        )
        if not entry["operations"] and not custom_only_allowed:
            raise engine.PlanError(
                "issue #71 custom operation must accompany a structural operation"
            )
    base_plan["entries"] = [entry for entry in base_plan["entries"] if entry["operations"]]
    materialized = engine._issue71_base_materialize_plan(
        root, base_plan, verify_after=False
    )

    for entry in custom_entries:
        content = materialized.get(entry["path"])
        if content is None and len(entry["operations"]) == 1 and entry["operations"][0][
            "kind"
        ] in {
            "content-authority-handoff",
            "pyproject-static-runtime-prune",
            "requirements-static-runtime-prune",
            "static-profile-multi-input-activation",
        }:
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
            elif kind == "pyproject-static-runtime-prune":
                if entry["path"] != "src/pipeline/pyproject.toml":
                    raise engine.PlanError("pyproject prune is restricted to pyproject.toml")
                content = _prune_pyproject(engine, content, root)
            elif kind == "requirements-static-runtime-prune":
                if entry["path"] != "src/pipeline/requirements-pipeline.txt":
                    raise engine.PlanError(
                        "requirements prune is restricted to requirements-pipeline.txt"
                    )
                content = _prune_requirements(engine, content, root)
            elif kind == "static-profile-multi-input-activation":
                continue
        materialized[entry["path"]] = content

    for entry in plan["entries"]:
        operations = entry["operations"]
        if (
            len(operations) == 1
            and operations[0]["kind"] == "static-profile-multi-input-activation"
        ):
            before = engine._audited_blob(root, plan["auditedCommit"], entry["path"])
            materialized[entry["path"]] = _activate_static_profile(
                engine,
                before,
                operations[0],
                materialized,
                verify_target=verify_after,
            )
            continue
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
        "src/web/scripts/static-repository-gates.mjs",
        "src/web/scripts/static-repository-gates.test.mjs",
        "tests/harness/test_changed_suites.py",
        "tests/repository-removal/test_validate_removal_plan_v2.py",
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
