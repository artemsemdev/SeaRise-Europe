"""Validate the immutable repository-removal approval chain.

The inventory, evidence receipt, and owner decision are read from committed Git
blobs.  Repository ownership is evaluated against the inventory's exact audited
commit, never against mutable worktree existence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from collections.abc import Iterable
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
DEFAULT_VALIDATOR = ROOT / "scripts/repository/validate_removal_approval.py"
DEFAULT_TEST_INVENTORY = ROOT / "tests/test-inventory.json"
DEFAULT_REPLACEMENT_MATRIX = ROOT / "docs/testing/legacy-frontend-removal-inventory.md"

ACTIVE_TARGET_ROOTS = ("src/web/", "src/pipeline/searise_pipeline/")
FORBIDDEN_EVIDENCE_COMMAND = re.compile(
    r"(?:candidate[-_ ]?v7|\.tar(?:\s|$)|\b(?:upload|publish|destroy|delete|secret)\b|"
    r"gh\s+(?:secret|variable|environment)|terraform\s+(?:apply|destroy))",
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
    validator_path: Path = DEFAULT_VALIDATOR,
    test_inventory_path: Path = DEFAULT_TEST_INVENTORY,
    replacement_matrix_path: Path = DEFAULT_REPLACEMENT_MATRIX,
    allow_unapproved: bool = False,
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
    assert inventory_bytes is not None
    assert evidence_bytes is not None
    assert historical_allowlist_bytes is not None
    assert inventory_schema_bytes is not None
    assert evidence_schema_bytes is not None
    assert decision_schema_bytes is not None
    assert historical_allowlist_schema_bytes is not None

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
    if decision is not None:
        errors.extend(_schema_errors(decision, decision_schema, "owner decision"))

    # Continue semantic checks only for fields whose basic shape is available.
    items = inventory.get("items")
    audited_commit = inventory.get("auditedCommit")
    tracked: dict[str, str] | None = None
    if isinstance(items, list) and all(isinstance(item, dict) for item in items):
        item_ids = [item.get("id") for item in items]
        string_ids = [item_id for item_id in item_ids if isinstance(item_id, str)]
        duplicate_ids = _duplicates(string_ids)
        if duplicate_ids:
            errors.append(f"duplicate inventory item ids: {duplicate_ids}")
        if len(string_ids) == len(items) and string_ids != sorted(string_ids):
            errors.append("inventory items must be sorted by id")

        global_locator_keys: list[str] = []
        delete_locator_paths: list[str] = []
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
                locator_paths = [path for path, _selector in locator_keys]
                if item.get("disposition") == "delete-phase-2":
                    delete_locator_paths.extend(locator_paths)
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

        duplicate_locator_keys = _duplicates(global_locator_keys)
        if duplicate_locator_keys:
            errors.append("locator path/selector pairs assigned to multiple items")
        duplicate_delete_paths = _duplicates(delete_locator_paths)
        if duplicate_delete_paths:
            errors.append(
                "delete locator paths assigned to multiple items: "
                f"{duplicate_delete_paths}"
            )

        if isinstance(audited_commit, str) and len(audited_commit) == 40:
            try:
                tracked = _tracked_blobs(repository_root, audited_commit)
            except RemovalApprovalError as exc:
                errors.append(str(exc))
            else:
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
            if tracked is not None and isinstance(evidence_paths, list):
                missing_evidence_paths = sorted(
                    path
                    for path in evidence_paths
                    if isinstance(path, str) and path not in tracked
                )
                if missing_evidence_paths:
                    errors.append(
                        f"{check_id}: evidencePaths not tracked at audited commit: "
                        f"{missing_evidence_paths}"
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
            validator_path=args.validator,
            test_inventory_path=args.test_inventory,
            replacement_matrix_path=args.replacement_matrix,
            allow_unapproved=args.allow_unapproved,
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
