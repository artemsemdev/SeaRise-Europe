"""Validate the fail-closed correction of the Phase 3 gate-policy authority.

The v3 P/D evidence and Issue #71 P/D/A/R history remain immutable. This
authority records that the inconsistent v3 governed state was superseded
before application, then permits only a newly approved exact corrected state.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
from typing import Any, Sequence


ROOT = Path(__file__).resolve().parents[2]
DIRECTORY = "contracts/repository-removal/v4/phase-3-issue-61"
SCHEMA_PATH = "contracts/repository-removal/v4/gate-policy-correction.schema.json"
PREAPPROVAL_PATH = f"{DIRECTORY}/preapproval.json"
DECISION_PATH = f"{DIRECTORY}/owner-decision.json"
RECEIPT_PATH = f"{DIRECTORY}/application-receipt.json"
VALIDATOR_PATH = "scripts/repository/validate_gate_policy_correction.py"
TEST_PATH = "tests/repository-removal/test_validate_gate_policy_correction.py"
AUDITED_BASE = "1813f33ff71b04d88ba6b3390d5abb2d05a053cf"
OLD_PREAPPROVAL = "3d6eca009edeb9c961ff4aa727d7e34758904750"
OLD_DECISION = "c62b7870b0798daaf24fdca3d11ba4c2d8c34b4f"
OLD_RECEIPT_PATH = (
    "contracts/repository-removal/v3/phase-3-issue-61/application-receipt.json"
)

EXPECTED_AUTHORITY_PATHS = {SCHEMA_PATH, PREAPPROVAL_PATH, VALIDATOR_PATH}
IMMUTABLE_AUTHORITY_PATHS = EXPECTED_AUTHORITY_PATHS
EXPECTED_GOVERNED_PATHS = {
    ".github/workflows/ci.yml",
    ".github/workflows/codeql.yml",
    "contracts/ci/v1/architecture-fitness.json",
    "contracts/supply-chain/v2/static-target-profile.json",
    "scripts/ci/changed_components.py",
    "scripts/ci/validate_markdown.py",
    "scripts/ci/verify_ci_gate.py",
    "src/web/scripts/check-target-content.mjs",
    "tests/harness/test_changed_components.py",
    "tests/harness/test_ci_gate.py",
    "tests/harness/test_immutable_dependencies.py",
    "tests/harness/test_validate_markdown.py",
    "tests/repository-removal/test_validate_gate_policy_evolution.py",
    TEST_PATH,
    "tests/test-inventory.json",
}
CORRECTED_OLD_PATHS = {
    ".github/workflows/ci.yml",
    "contracts/supply-chain/v2/static-target-profile.json",
    "src/web/scripts/check-target-content.mjs",
    "tests/harness/test_changed_components.py",
    "tests/test-inventory.json",
}
EXPECTED_SAFETY = {
    "candidateV7BytesUsed": False,
    "tarBytesUsed": False,
    "publicationAuthorized": False,
    "externalResourceMutationAuthorized": False,
}
TRUST_ROOTS = {
    "gatePolicyCorrectionSchema": SCHEMA_PATH,
    "gatePolicyCorrectionValidator": VALIDATOR_PATH,
}


def _load_v3() -> Any:
    path = ROOT / "scripts/repository/validate_gate_policy_evolution.py"
    spec = importlib.util.spec_from_file_location("gate_policy_evolution_v3", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("v3 authority validator cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


V3 = _load_v3()
AuthorityError = V3.AuthorityError
_sha256 = V3._sha256
_git = V3._git
_json = V3._json
_blob = V3._blob
_document_at = V3._document_at
_state = V3._state
_assert_ancestor = V3._assert_ancestor
_assert_changed_paths = V3._assert_changed_paths
_assert_states = V3._assert_states
_schema_validate = V3._schema_validate
_unique_addition = V3._unique_addition
_verify_owner_comment = V3._verify_owner_comment


def _assert_immutable(root: Path, earlier: str, later: str) -> None:
    for authority_path in IMMUTABLE_AUTHORITY_PATHS:
        if _state(root, earlier, authority_path) != _state(
            root, later, authority_path
        ):
            raise AuthorityError(
                f"correction authority changed after P2: {authority_path}"
            )


def _validate_superseded_authority(
    root: Path, preapproval: dict[str, Any], *, verify_owner_comment: bool
) -> None:
    old = preapproval["supersededAuthority"]
    v3 = V3
    v3.validate_decision_commit(
        root, OLD_PREAPPROVAL, OLD_DECISION,
        verify_owner_comment=verify_owner_comment,
    )
    expected = {
        "preapprovalCommit": OLD_PREAPPROVAL,
        "preapprovalTree": _git(
            root, "rev-parse", f"{OLD_PREAPPROVAL}^{{tree}}"
        ).decode().strip(),
        "preapprovalSha256": _sha256(
            _blob(root, OLD_PREAPPROVAL, v3.PREAPPROVAL_PATH)
        ),
        "decisionCommit": OLD_DECISION,
        "decisionTree": _git(
            root, "rev-parse", f"{OLD_DECISION}^{{tree}}"
        ).decode().strip(),
        "decisionSha256": _sha256(_blob(root, OLD_DECISION, v3.DECISION_PATH)),
        "status": "superseded-before-application",
        "appliedCommit": None,
        "receiptCommit": None,
    }
    for field, value in expected.items():
        if old[field] != value:
            raise AuthorityError(f"superseded v3 authority {field} differs")
    if _state(root, preapproval["auditedBaseCommit"], OLD_RECEIPT_PATH) != {
        "state": "absent"
    }:
        raise AuthorityError("v3 receipt exists despite before-application supersession")
    old_preapproval = _document_at(
        root, OLD_PREAPPROVAL, v3.PREAPPROVAL_PATH, "v3 preapproval"
    )
    _assert_states(
        root, preapproval["auditedBaseCommit"], old_preapproval["governedPaths"], "before"
    )


def validate_preapproval_document(
    root: Path, document: dict[str, Any], *, verify_owner_comment: bool
) -> None:
    schema = _json((root / SCHEMA_PATH).read_bytes(), "correction schema")
    _schema_validate(document, schema, "correction preapproval")
    if document["auditedBaseCommit"] != AUDITED_BASE:
        raise AuthorityError("audited base differs from merged v3 D authority")
    if set(document["authorityPaths"]) != EXPECTED_AUTHORITY_PATHS:
        raise AuthorityError("correction authority path set differs")
    if set(document["trustRootSha256"]) != set(TRUST_ROOTS):
        raise AuthorityError("correction trust-root names differ")
    paths = [entry["path"] for entry in document["governedPaths"]]
    if paths != sorted(paths) or set(paths) != EXPECTED_GOVERNED_PATHS:
        raise AuthorityError("corrected governed path set differs")
    if len(paths) != len(set(paths)):
        raise AuthorityError("corrected governed paths are duplicated")
    if document["safety"] != EXPECTED_SAFETY:
        raise AuthorityError("correction safety boundary differs")
    for name, path in TRUST_ROOTS.items():
        if _sha256((root / path).read_bytes()) != document["trustRootSha256"][name]:
            raise AuthorityError(f"correction trust-root hash mismatch: {name}")
    _assert_states(root, AUDITED_BASE, document["governedPaths"], "before")
    for entry in document["governedPaths"]:
        if entry["before"] == entry["after"]:
            raise AuthorityError(f"corrected transition is a no-op: {entry['path']}")

    v3 = V3
    old_document = _document_at(
        root, OLD_PREAPPROVAL, v3.PREAPPROVAL_PATH, "v3 preapproval"
    )
    if document["phase2Issue71History"] != old_document["phase2Issue71History"]:
        raise AuthorityError("immutable Issue #71 P/D/A/R history differs")
    old_after = {entry["path"]: entry["after"] for entry in old_document["governedPaths"]}
    corrected_after = {entry["path"]: entry["after"] for entry in document["governedPaths"]}
    if set(corrected_after) != set(old_after) | {TEST_PATH}:
        raise AuthorityError("correction does not cover the complete superseded state")
    changed = {
        path for path in old_after if corrected_after[path] != old_after[path]
    }
    if changed != CORRECTED_OLD_PATHS:
        raise AuthorityError("correction differs from v3 outside the bounded fix set")
    if corrected_after[TEST_PATH]["state"] != "present":
        raise AuthorityError("correction validator test is not pre-bound")
    _validate_superseded_authority(
        root, document, verify_owner_comment=verify_owner_comment
    )


def validate_preapproval_commit(
    root: Path, preapproval_commit: str, *, verify_owner_comment: bool
) -> tuple[dict[str, Any], bytes]:
    _assert_ancestor(root, AUDITED_BASE, preapproval_commit)
    _assert_changed_paths(
        root, AUDITED_BASE, preapproval_commit, EXPECTED_AUTHORITY_PATHS, "B2-to-P2"
    )
    if _state(root, preapproval_commit, DECISION_PATH) != {"state": "absent"}:
        raise AuthorityError("correction owner decision must be absent at P2")
    if _state(root, preapproval_commit, RECEIPT_PATH) != {"state": "absent"}:
        raise AuthorityError("correction receipt must be absent at P2")
    preapproval_bytes = _blob(root, preapproval_commit, PREAPPROVAL_PATH)
    preapproval = _json(preapproval_bytes, "correction preapproval")
    validate_preapproval_document(
        root, preapproval, verify_owner_comment=verify_owner_comment
    )
    return preapproval, preapproval_bytes


def expected_owner_approval_text(
    preapproval: dict[str, Any], preapproval_commit: str, preapproval_sha256: str
) -> str:
    template = preapproval["ownerApprovalTemplate"]
    if template.count("<PREAPPROVAL_COMMIT>") != 1 or template.count(
        "<PREAPPROVAL_SHA256>"
    ) != 1:
        raise AuthorityError("correction owner approval placeholders are not exact")
    return template.replace("<PREAPPROVAL_COMMIT>", preapproval_commit).replace(
        "<PREAPPROVAL_SHA256>", preapproval_sha256
    )


def validate_decision_commit(
    root: Path,
    preapproval_commit: str,
    decision_commit: str,
    *,
    verify_owner_comment: bool,
) -> tuple[dict[str, Any], dict[str, Any]]:
    preapproval, preapproval_bytes = validate_preapproval_commit(
        root, preapproval_commit, verify_owner_comment=verify_owner_comment
    )
    _assert_ancestor(root, preapproval_commit, decision_commit)
    _assert_changed_paths(
        root, preapproval_commit, decision_commit, {DECISION_PATH}, "P2-to-D2"
    )
    if _unique_addition(
        root, preapproval_commit, decision_commit, DECISION_PATH
    ) != decision_commit:
        raise AuthorityError("D2 is not the correction owner-decision addition commit")
    _assert_immutable(root, preapproval_commit, decision_commit)
    decision_bytes = _blob(root, decision_commit, DECISION_PATH)
    decision = _json(decision_bytes, "correction owner decision")
    schema = _document_at(root, preapproval_commit, SCHEMA_PATH, "correction schema")
    _schema_validate(decision, schema, "correction owner decision")
    expected_text = expected_owner_approval_text(
        preapproval, preapproval_commit, _sha256(preapproval_bytes)
    )
    expected = {
        "preapprovalCommit": preapproval_commit,
        "preapprovalSha256": _sha256(preapproval_bytes),
        "approvalText": expected_text,
        "safety": EXPECTED_SAFETY,
    }
    for field, value in expected.items():
        if decision[field] != value:
            raise AuthorityError(f"correction owner decision {field} does not match P2")
    if decision["approvalSource"]["bodySha256"] != _sha256(expected_text.encode()):
        raise AuthorityError("correction owner decision body hash differs")
    if not verify_owner_comment:
        raise AuthorityError("live correction OWNER comment verification is required")
    _verify_owner_comment(decision, expected_text)
    return preapproval, decision


def validate_applied_commit(
    root: Path,
    preapproval_commit: str,
    decision_commit: str,
    applied_commit: str,
    *,
    verify_owner_comment: bool,
) -> dict[str, Any]:
    preapproval, _ = validate_decision_commit(
        root, preapproval_commit, decision_commit,
        verify_owner_comment=verify_owner_comment,
    )
    _assert_ancestor(root, decision_commit, applied_commit)
    _assert_changed_paths(
        root, decision_commit, applied_commit, EXPECTED_GOVERNED_PATHS, "D2-to-A2"
    )
    _assert_immutable(root, preapproval_commit, applied_commit)
    _assert_states(root, applied_commit, preapproval["governedPaths"], "after")
    if _state(root, applied_commit, OLD_RECEIPT_PATH) != {"state": "absent"}:
        raise AuthorityError("superseded v3 receipt appeared during correction")
    return preapproval


def _governed_state_sha256(
    root: Path, commit: str, preapproval: dict[str, Any]
) -> str:
    payload = [
        {"path": entry["path"], **_state(root, commit, entry["path"])}
        for entry in preapproval["governedPaths"]
    ]
    return _sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    )


def validate_application_receipt(
    root: Path,
    receipt_commit: str,
    head_commit: str,
    *,
    verify_owner_comment: bool,
) -> None:
    receipt = _document_at(root, receipt_commit, RECEIPT_PATH, "correction receipt")
    preapproval_commit = receipt["preapprovalCommit"]
    decision_commit = receipt["decisionCommit"]
    applied_commit = receipt["appliedCommit"]
    preapproval = validate_applied_commit(
        root,
        preapproval_commit,
        decision_commit,
        applied_commit,
        verify_owner_comment=verify_owner_comment,
    )
    _assert_ancestor(root, applied_commit, receipt_commit)
    _assert_ancestor(root, receipt_commit, head_commit)
    _assert_changed_paths(
        root, applied_commit, receipt_commit, {RECEIPT_PATH}, "A2-to-R2"
    )
    if _unique_addition(
        root, applied_commit, receipt_commit, RECEIPT_PATH
    ) != receipt_commit:
        raise AuthorityError("R2 is not the correction receipt addition commit")
    schema = _document_at(root, preapproval_commit, SCHEMA_PATH, "correction schema")
    _schema_validate(receipt, schema, "correction receipt")
    expected = {
        "appliedTree": _git(
            root, "rev-parse", f"{applied_commit}^{{tree}}"
        ).decode().strip(),
        "preapprovalSha256": _sha256(
            _blob(root, preapproval_commit, PREAPPROVAL_PATH)
        ),
        "ownerDecisionSha256": _sha256(
            _blob(root, decision_commit, DECISION_PATH)
        ),
        "governedStateSha256": _governed_state_sha256(
            root, applied_commit, preapproval
        ),
        "safety": EXPECTED_SAFETY,
    }
    for field, value in expected.items():
        if receipt[field] != value:
            raise AuthorityError(f"correction receipt {field} differs from P2/D2/A2")
    _assert_immutable(root, preapproval_commit, head_commit)
    _assert_states(root, head_commit, preapproval["governedPaths"], "after")
    if _state(root, receipt_commit, RECEIPT_PATH) != _state(
        root, head_commit, RECEIPT_PATH
    ):
        raise AuthorityError("correction receipt changed after R2")


def validate_ci_state(root: Path, head_commit: str, *, verify_owner_comment: bool) -> None:
    preapproval_commit = _unique_addition(
        root, AUDITED_BASE, head_commit, PREAPPROVAL_PATH
    )
    if _state(root, head_commit, DECISION_PATH) == {"state": "absent"}:
        preapproval, _ = validate_preapproval_commit(
            root, preapproval_commit, verify_owner_comment=verify_owner_comment
        )
        _assert_states(root, head_commit, preapproval["governedPaths"], "before")
        return
    decision_commit = _unique_addition(
        root, preapproval_commit, head_commit, DECISION_PATH
    )
    if _state(root, head_commit, RECEIPT_PATH) != {"state": "absent"}:
        receipt_commit = _unique_addition(
            root, decision_commit, head_commit, RECEIPT_PATH
        )
        validate_application_receipt(
            root,
            receipt_commit,
            head_commit,
            verify_owner_comment=verify_owner_comment,
        )
        return
    preapproval, _ = validate_decision_commit(
        root, preapproval_commit, decision_commit,
        verify_owner_comment=verify_owner_comment,
    )
    states = [_state(root, head_commit, entry["path"]) for entry in preapproval["governedPaths"]]
    before = [entry["before"] for entry in preapproval["governedPaths"]]
    after = [entry["after"] for entry in preapproval["governedPaths"]]
    if states == before:
        return
    if states != after:
        raise AuthorityError("governed paths are in a partial or superseded state")
    validate_applied_commit(
        root, preapproval_commit, decision_commit, head_commit,
        verify_owner_comment=verify_owner_comment,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository-root", type=Path, default=ROOT)
    commands = parser.add_subparsers(dest="command", required=True)
    preapproval = commands.add_parser("preapproval")
    preapproval.add_argument("--preapproval-commit", required=True)
    ci = commands.add_parser("ci")
    ci.add_argument("--head-commit", required=True)
    for command in (preapproval, ci):
        command.add_argument("--verify-owner-comment", action="store_true")
    arguments = parser.parse_args(argv)
    root = arguments.repository_root.resolve()
    try:
        if arguments.command == "preapproval":
            validate_preapproval_commit(
                root, arguments.preapproval_commit,
                verify_owner_comment=arguments.verify_owner_comment,
            )
        else:
            validate_ci_state(
                root, arguments.head_commit,
                verify_owner_comment=arguments.verify_owner_comment,
            )
    except AuthorityError as error:
        print(f"ERROR: {error}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
