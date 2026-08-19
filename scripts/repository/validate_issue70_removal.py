"""Run an additive issue #70 lifecycle without rewriting the completed #72 chain.

The reviewed v2 engine remains byte-for-byte unchanged. This adapter loads it
in an isolated module, binds it to a separate contract directory and exact
issue identifiers, and retains the completed issue #72 artifacts as trust
roots. The adapter and profile become trust roots of every #70 preapproval.
"""

from __future__ import annotations

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
            schema = _specialize_schema(copy.deepcopy(schema))
        base_validate(document, schema, label)

    engine._schema_validate_document = validate_specialized
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
        jsonschema.Draft202012Validator.check_schema(_specialize_schema(schema))


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
