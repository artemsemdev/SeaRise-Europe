"""Validate the additive Issue #62 v7 static-delivery authority handoff.

The v6 preapproval and OWNER decision remain immutable authority.  Its first
application attempt is retained only as an unmerged diagnostic because the
static Web gate still dispatched to the older Issue #61 validator.  A v7
decision may authorize only the exact corrected repository blobs pre-bound by
this module.  It never authorizes infrastructure apply, publication, upload,
credentials, DNS, environments, external mutation, Candidate-v7, or TAR use.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
from collections.abc import Sequence
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DIRECTORY = "contracts/repository-removal/v7/phase-3-issue-62"
SCHEMA_PATH = "contracts/repository-removal/v7/static-delivery-handoff-correction.schema.json"
PREAPPROVAL_PATH = f"{DIRECTORY}/preapproval.json"
DECISION_PATH = f"{DIRECTORY}/owner-decision.json"
RECEIPT_PATH = f"{DIRECTORY}/application-receipt.json"
VALIDATOR_PATH = "scripts/repository/validate_static_delivery_handoff_correction.py"
TEST_PATH = "tests/repository-removal/test_validate_static_delivery_handoff_correction.py"
WEB_HANDOFF_PATH = "src/web/scripts/check-target-content.mjs"
WEB_HANDOFF_TEST_PATH = "src/web/scripts/check-target-content.test.mjs"
SEALED_GATE_TEST_PATH = "src/web/scripts/static-repository-gates.test.mjs"

AUDITED_BASE = "eb2c3709410e6873929a810b89214222f4b6cd1b"
V6_PREAPPROVAL = "cb53ae73732114ad00856c5b29c1ffb5c7560167"
V6_PREAPPROVAL_TREE = "8ba49f074641dccb4757b69b16e9e8ff570ce341"
V6_PREAPPROVAL_SHA256 = (
    "f4145b8d022f88bba2a22e487aa0a9d454a95cff06e40b53d1b2ebd2929e016d"
)
V6_DECISION = "4689320af62061ab0cba31863cb7ace8e4974dd8"
V6_DECISION_TREE = "bc5a2eeec761714ee9da7df4c9931ceac3d92267"
V6_DECISION_SHA256 = (
    "747f5ee5de26cde96acb3e8d2fdcb935413c6e6fda6f52e59e472d98676a0ac0"
)
V6_OWNER_COMMENT_ID = 5457178200
V6_OWNER_COMMENT_TIME = "2026-08-28T20:01:30Z"
V6_APPLICATION_ATTEMPT = "72e239e98d38e4fb2ece2fd2a9ce6a167b151220"
V6_APPLICATION_ATTEMPT_TREE = "5b79283a32ab5b4967bc817a08d13aadbac45fd6"
V6_APPLICATION_PR = 479
V6_APPLICATION_PR_URL = "https://github.com/artemsemdev/SeaRise-Europe/pull/479"
STATIC_REPOSITORY_GATES_PATH = "src/web/scripts/static-repository-gates.mjs"
STATIC_REPOSITORY_GATES_BLOB = "02e32cda7a01460c3055f61cccaf9f03fc0552f9"
STATIC_REPOSITORY_GATES_SHA256 = (
    "b97d051d616738dc12d24f9d364bd9fcda59d1a0ab41c705b7cdac1bc199637c"
)
GOVERNED_TRANSITIONS_SHA256 = (
    "807fadfb3d0503cc0d408a1c6cc0fe0ad221db6086cf1018317c725a285433fb"
)

EXPECTED_AUTHORITY_PATHS = {SCHEMA_PATH, PREAPPROVAL_PATH, VALIDATOR_PATH}
NEW_GOVERNED_PATHS = {
    STATIC_REPOSITORY_GATES_PATH,
    TEST_PATH,
    WEB_HANDOFF_PATH,
    WEB_HANDOFF_TEST_PATH,
    SEALED_GATE_TEST_PATH,
}
CORRECTED_V6_PATHS = {
    ".github/workflows/ci.yml",
    "contracts/supply-chain/v2/static-target-profile.json",
    "tests/harness/test_changed_components.py",
    "tests/harness/test_ci_gate.py",
    "tests/test-inventory.json",
}
EXPECTED_SAFETY = {
    "candidateV7BytesUsed": False,
    "tarBytesUsed": False,
    "publicationAuthorized": False,
    "infrastructureApplyAuthorized": False,
    "externalResourceMutationAuthorized": False,
    "externalDeletionAuthorized": False,
    "credentialMutationAuthorized": False,
    "githubEnvironmentMutationAuthorized": False,
}
EXPECTED_DEFERRED_OWNERSHIP = {
    "issue64PublicationGateRequired": True,
    "issue74ManagedControlsRequired": True,
    "liveCloudflareEvidenceClaimed": False,
}


def _load_v6() -> Any:
    path = ROOT / "scripts/repository/validate_static_delivery_correction.py"
    spec = importlib.util.spec_from_file_location("static_delivery_correction_v6", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("v6 delivery validator cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


V6 = _load_v6()
AuthorityError = V6.AuthorityError
_sha256 = V6._sha256
_git = V6._git
_json = V6._json
_blob = V6._blob
_document_at = V6._document_at
_state = V6._state
_assert_ancestor = V6._assert_ancestor
_assert_changed_paths = V6._assert_changed_paths
_assert_states = V6._assert_states
_schema_validate = V6._schema_validate
_unique_addition = V6._unique_addition
EXPECTED_GOVERNED_PATHS = {*V6.EXPECTED_GOVERNED_PATHS, *NEW_GOVERNED_PATHS}
PRIOR_IMMUTABLE_PATHS = {
    *V6.PRIOR_IMMUTABLE_PATHS,
    *V6.EXPECTED_AUTHORITY_PATHS,
    V6.DECISION_PATH,
}
TRUST_ROOTS = {
    "staticDeliveryHandoffSchema": SCHEMA_PATH,
    "staticDeliveryHandoffValidator": VALIDATOR_PATH,
    "staticRepositoryGates": STATIC_REPOSITORY_GATES_PATH,
}


def _canonical_sha256(value: Any) -> str:
    return _sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode())


def _is_ancestor(root: Path, ancestor: str, descendant: str) -> bool:
    result = subprocess.run(
        ["git", "merge-base", "--is-ancestor", ancestor, descendant],
        cwd=root,
        check=False,
        capture_output=True,
    )
    if result.returncode not in (0, 1):
        raise AuthorityError("cannot prove rejected v6 application ancestry")
    return result.returncode == 0


def _assert_immutable(root: Path, later: str, preapproval_commit: str) -> None:
    for path in EXPECTED_AUTHORITY_PATHS:
        if _state(root, preapproval_commit, path) != _state(root, later, path):
            raise AuthorityError(f"v7 authority changed after P7: {path}")
    for path in PRIOR_IMMUTABLE_PATHS:
        if _state(root, AUDITED_BASE, path) != _state(root, later, path):
            raise AuthorityError(f"prior sealed authority changed: {path}")


def _validate_issue71_history(
    root: Path, document: dict[str, Any], *, verify_owner_comment: bool
) -> None:
    if not verify_owner_comment:
        raise AuthorityError("live OWNER verification is required for issue #71 history")
    history = document["phase2Issue71History"]
    for kind in ("preapproval", "decision", "applied", "receipt"):
        commit = history[f"{kind}Commit"]
        tree = _git(root, "rev-parse", f"{commit}^{{tree}}").decode().strip()
        if tree != history[f"{kind}Tree"]:
            raise AuthorityError(f"issue #71 historical {kind} tree differs")
    receipt = _blob(
        root,
        history["receiptCommit"],
        "contracts/repository-removal/v2/issue-71/application-receipt.json",
    )
    if _sha256(receipt) != history["receiptSha256"]:
        raise AuthorityError("issue #71 historical receipt bytes differ")
    historical_gate = {
        "state": "present",
        "mode": "100644",
        "gitBlobSha": STATIC_REPOSITORY_GATES_BLOB,
        "sha256": STATIC_REPOSITORY_GATES_SHA256,
    }
    for commit in (history["receiptCommit"], AUDITED_BASE):
        if _state(root, commit, STATIC_REPOSITORY_GATES_PATH) != historical_gate:
            raise AuthorityError("historical Issue #71 static-repository gate differs")
    command = [
        "python3",
        str(root / "scripts/repository/validate_issue71_removal.py"),
        "--repository-root",
        str(root),
        "post-application",
        "--receipt-commit",
        history["receiptCommit"],
        "--head-commit",
        history["receiptCommit"],
        "--verify-owner-comment",
    ]
    try:
        subprocess.run(command, cwd=root, check=True, capture_output=True)
    except (OSError, subprocess.CalledProcessError) as error:
        detail = getattr(error, "stderr", b"").decode(errors="replace").strip()
        raise AuthorityError(
            f"immutable issue #71 P/D/A/R validation failed{': ' + detail if detail else ''}"
        ) from error


def _expected_v6_authority(root: Path) -> dict[str, Any]:
    decision = _document_at(root, V6_DECISION, V6.DECISION_PATH, "v6 decision")
    return {
        "preapprovalCommit": V6_PREAPPROVAL,
        "preapprovalTree": V6_PREAPPROVAL_TREE,
        "preapprovalSha256": V6_PREAPPROVAL_SHA256,
        "decisionCommit": V6_DECISION,
        "decisionTree": V6_DECISION_TREE,
        "decisionSha256": V6_DECISION_SHA256,
        "ownerComment": {
            "id": V6_OWNER_COMMENT_ID,
            "url": decision["approvalSource"]["commentUrl"],
            "issueApiUrl": "https://api.github.com/repos/artemsemdev/SeaRise-Europe/issues/62",
            "author": "artemsemdev",
            "association": "OWNER",
            "createdAt": V6_OWNER_COMMENT_TIME,
            "updatedAt": V6_OWNER_COMMENT_TIME,
            "body": decision["approvalText"],
            "bodySha256": decision["approvalSource"]["bodySha256"],
        },
        "status": "decision-preserved-application-superseded",
        "governedStateAuthorized": True,
        "integratedApplicationCommit": None,
        "receiptCommit": None,
    }


def _expected_superseded_application() -> dict[str, Any]:
    return {
        "commit": V6_APPLICATION_ATTEMPT,
        "tree": V6_APPLICATION_ATTEMPT_TREE,
        "pullRequest": V6_APPLICATION_PR,
        "pullRequestUrl": V6_APPLICATION_PR_URL,
        "status": "superseded-after-decision-before-application-and-integration",
        "ancestorOfAuditedBase": False,
        "governedStateIntegrated": False,
        "reason": (
            "The v6 application attempt left check-target-content.mjs dispatching "
            "to the Issue #61 v4 validator, so Static Web rejected the Issue #62 "
            "CI state. The exact attempt remains an unmerged diagnostic and is "
            "superseded before repository application or integration."
        ),
    }


def _validate_v6_chain(root: Path, document: dict[str, Any], *, verify_owner_comment: bool) -> None:
    v6_preapproval = _document_at(
        root, V6_PREAPPROVAL, V6.PREAPPROVAL_PATH, "v6 preapproval"
    )
    if (
        document["phase3Issue62V5SupersededAuthority"]
        != v6_preapproval["supersededAuthority"]
    ):
        raise AuthorityError("immutable superseded v5 authority differs")
    V6.validate_decision_commit(
        root,
        V6_PREAPPROVAL,
        V6_DECISION,
        verify_owner_comment=verify_owner_comment,
    )
    if document["phase3Issue62V6Authority"] != _expected_v6_authority(root):
        raise AuthorityError("preserved v6 P/D authority differs")
    if document["supersededV6Application"] != _expected_superseded_application():
        raise AuthorityError("superseded v6 application evidence differs")
    if not _is_ancestor(root, V6_DECISION, V6_APPLICATION_ATTEMPT):
        raise AuthorityError("v6 application attempt does not descend from its decision")
    if _is_ancestor(root, V6_APPLICATION_ATTEMPT, AUDITED_BASE):
        raise AuthorityError("rejected v6 application is integrated into the audited base")
    if _git(root, "rev-parse", f"{V6_APPLICATION_ATTEMPT}^{{tree}}").decode().strip() != V6_APPLICATION_ATTEMPT_TREE:
        raise AuthorityError("rejected v6 application tree differs")
    V6.validate_applied_commit(
        root,
        V6_PREAPPROVAL,
        V6_DECISION,
        V6_APPLICATION_ATTEMPT,
        verify_owner_comment=verify_owner_comment,
    )
    _assert_states(root, AUDITED_BASE, v6_preapproval["governedPaths"], "before")


def validate_preapproval_document(
    root: Path, document: dict[str, Any], *, verify_owner_comment: bool
) -> None:
    schema = _json((root / SCHEMA_PATH).read_bytes(), "v7 handoff schema")
    _schema_validate(document, schema, "v7 handoff preapproval")
    if document["auditedBaseCommit"] != AUDITED_BASE:
        raise AuthorityError("audited base differs from merged v6 P/D authority")
    if set(document["authorityPaths"]) != EXPECTED_AUTHORITY_PATHS:
        raise AuthorityError("v7 authority path set differs")
    if set(document["trustRootSha256"]) != set(TRUST_ROOTS):
        raise AuthorityError("v7 trust-root names differ")
    paths = [entry["path"] for entry in document["governedPaths"]]
    if paths != sorted(paths) or set(paths) != EXPECTED_GOVERNED_PATHS:
        raise AuthorityError("v7 governed path set differs")
    if len(paths) != len(set(paths)):
        raise AuthorityError("v7 governed paths are duplicated")
    if _canonical_sha256(document["governedPaths"]) != GOVERNED_TRANSITIONS_SHA256:
        raise AuthorityError("v7 future-state hash differs from the exact corrected state")
    if document["safety"] != EXPECTED_SAFETY:
        raise AuthorityError("v7 safety boundary differs")
    if document["deferredOwnership"] != EXPECTED_DEFERRED_OWNERSHIP:
        raise AuthorityError("v7 deferred ownership boundary differs")
    if document["phase2Issue71History"] != V6.EXPECTED_ISSUE71_HISTORY:
        raise AuthorityError("immutable Issue #71 P/D/A/R history differs")
    if document["phase3Issue61History"] != V6.EXPECTED_ISSUE61_HISTORY:
        raise AuthorityError("immutable Issue #61 v4 P/D/A/R history differs")
    expected_hashes = {
        "staticDeliveryHandoffSchema": _sha256((root / SCHEMA_PATH).read_bytes()),
        "staticDeliveryHandoffValidator": _sha256((root / VALIDATOR_PATH).read_bytes()),
        "staticRepositoryGates": STATIC_REPOSITORY_GATES_SHA256,
    }
    if document["trustRootSha256"] != expected_hashes:
        raise AuthorityError("v7 trust-root hash differs")
    if document["trustRootSha256"]["staticRepositoryGates"] != STATIC_REPOSITORY_GATES_SHA256:
        raise AuthorityError("Issue #71 static-repository gate trust blob differs")
    _assert_states(root, AUDITED_BASE, document["governedPaths"], "before")
    for entry in document["governedPaths"]:
        if entry["before"] == entry["after"]:
            raise AuthorityError(f"v7 transition is a no-op: {entry['path']}")
        if entry["after"]["state"] != "present":
            raise AuthorityError(f"v7 cannot authorize deletion: {entry['path']}")
        lowered = entry["path"].lower()
        if "candidate-v7" in lowered or lowered.endswith((".tar", ".tar.gz")):
            raise AuthorityError(f"forbidden Candidate-v7/TAR path: {entry['path']}")

    v6 = _document_at(root, V6_PREAPPROVAL, V6.PREAPPROVAL_PATH, "v6 preapproval")
    v6_after = {entry["path"]: entry["after"] for entry in v6["governedPaths"]}
    v7_after = {entry["path"]: entry["after"] for entry in document["governedPaths"]}
    if set(v7_after) != set(v6_after) | NEW_GOVERNED_PATHS:
        raise AuthorityError("v7 does not cover the complete v6 future state and handoff")
    changed = {path for path in v6_after if v7_after[path] != v6_after[path]}
    if changed != CORRECTED_V6_PATHS:
        raise AuthorityError("v7 differs from v6 outside the bounded handoff fix")
    _validate_issue71_history(root, document, verify_owner_comment=verify_owner_comment)
    _validate_v6_chain(root, document, verify_owner_comment=verify_owner_comment)


def validate_preapproval_commit(
    root: Path, preapproval_commit: str, *, verify_owner_comment: bool
) -> tuple[dict[str, Any], bytes]:
    _assert_ancestor(root, AUDITED_BASE, preapproval_commit)
    _assert_changed_paths(root, AUDITED_BASE, preapproval_commit, EXPECTED_AUTHORITY_PATHS, "B7-to-P7")
    if _state(root, preapproval_commit, DECISION_PATH) != {"state": "absent"}:
        raise AuthorityError("v7 owner decision must be absent at P7")
    if _state(root, preapproval_commit, RECEIPT_PATH) != {"state": "absent"}:
        raise AuthorityError("v7 receipt must be absent at P7")
    preapproval_bytes = _blob(root, preapproval_commit, PREAPPROVAL_PATH)
    preapproval = _json(preapproval_bytes, "v7 handoff preapproval")
    validate_preapproval_document(root, preapproval, verify_owner_comment=verify_owner_comment)
    return preapproval, preapproval_bytes


def expected_owner_approval_text(
    preapproval: dict[str, Any], preapproval_commit: str, preapproval_sha256: str
) -> str:
    template = preapproval["ownerApprovalTemplate"]
    placeholders = ("<PREAPPROVAL_COMMIT>", "<PREAPPROVAL_SHA256>")
    if any(template.count(placeholder) != 1 for placeholder in placeholders):
        raise AuthorityError("v7 approval placeholders are not exact")
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
    _assert_changed_paths(root, preapproval_commit, decision_commit, {DECISION_PATH}, "P7-to-D7")
    if _unique_addition(root, preapproval_commit, decision_commit, DECISION_PATH) != decision_commit:
        raise AuthorityError("D7 is not the v7 owner-decision addition commit")
    _assert_immutable(root, decision_commit, preapproval_commit)
    decision = _json(_blob(root, decision_commit, DECISION_PATH), "v7 owner decision")
    schema = _document_at(root, preapproval_commit, SCHEMA_PATH, "v7 handoff schema")
    _schema_validate(decision, schema, "v7 owner decision")
    approval = expected_owner_approval_text(
        preapproval, preapproval_commit, _sha256(preapproval_bytes)
    )
    expected = {
        "preapprovalCommit": preapproval_commit,
        "preapprovalSha256": _sha256(preapproval_bytes),
        "approvalText": approval,
        "safety": EXPECTED_SAFETY,
    }
    for field, value in expected.items():
        if decision[field] != value:
            raise AuthorityError(f"v7 owner decision {field} differs from P7")
    if not verify_owner_comment:
        raise AuthorityError("live v7 OWNER comment verification is required")
    observed = V6._verify_owner_comment(decision, approval)
    if decision["approvedAt"] != observed["createdAt"]:
        raise AuthorityError("v7 owner decision timestamp differs from live comment")
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
        root, preapproval_commit, decision_commit, verify_owner_comment=verify_owner_comment
    )
    _assert_ancestor(root, decision_commit, applied_commit)
    _assert_changed_paths(root, decision_commit, applied_commit, EXPECTED_GOVERNED_PATHS, "D7-to-A7")
    _assert_immutable(root, applied_commit, preapproval_commit)
    _assert_states(root, applied_commit, preapproval["governedPaths"], "after")
    return preapproval


def _governed_state_sha256(root: Path, commit: str, preapproval: dict[str, Any]) -> str:
    payload = [
        {"path": entry["path"], **_state(root, commit, entry["path"])}
        for entry in preapproval["governedPaths"]
    ]
    return _canonical_sha256(payload)


def validate_application_receipt(
    root: Path, receipt_commit: str, head_commit: str, *, verify_owner_comment: bool
) -> None:
    receipt = _document_at(root, receipt_commit, RECEIPT_PATH, "v7 application receipt")
    preapproval = validate_applied_commit(
        root,
        receipt["preapprovalCommit"],
        receipt["decisionCommit"],
        receipt["appliedCommit"],
        verify_owner_comment=verify_owner_comment,
    )
    _assert_ancestor(root, receipt["appliedCommit"], receipt_commit)
    _assert_ancestor(root, receipt_commit, head_commit)
    _assert_changed_paths(root, receipt["appliedCommit"], receipt_commit, {RECEIPT_PATH}, "A7-to-R7")
    if _unique_addition(root, receipt["appliedCommit"], receipt_commit, RECEIPT_PATH) != receipt_commit:
        raise AuthorityError("R7 is not the v7 receipt addition commit")
    schema = _document_at(root, receipt["preapprovalCommit"], SCHEMA_PATH, "v7 handoff schema")
    _schema_validate(receipt, schema, "v7 application receipt")
    expected = {
        "appliedTree": _git(root, "rev-parse", f"{receipt['appliedCommit']}^{{tree}}").decode().strip(),
        "preapprovalSha256": _sha256(_blob(root, receipt["preapprovalCommit"], PREAPPROVAL_PATH)),
        "ownerDecisionSha256": _sha256(_blob(root, receipt["decisionCommit"], DECISION_PATH)),
        "governedStateSha256": _governed_state_sha256(root, receipt["appliedCommit"], preapproval),
        "safety": EXPECTED_SAFETY,
    }
    for field, value in expected.items():
        if receipt[field] != value:
            raise AuthorityError(f"v7 receipt {field} differs from P7/D7/A7")
    _assert_immutable(root, head_commit, receipt["preapprovalCommit"])
    _assert_states(root, head_commit, preapproval["governedPaths"], "after")
    if _state(root, receipt_commit, RECEIPT_PATH) != _state(root, head_commit, RECEIPT_PATH):
        raise AuthorityError("v7 receipt changed after R7")


def validate_ci_state(root: Path, head_commit: str, *, verify_owner_comment: bool) -> None:
    preapproval_commit = _unique_addition(root, AUDITED_BASE, head_commit, PREAPPROVAL_PATH)
    if _state(root, head_commit, DECISION_PATH) == {"state": "absent"}:
        preapproval, _ = validate_preapproval_commit(
            root, preapproval_commit, verify_owner_comment=verify_owner_comment
        )
        _assert_states(root, head_commit, preapproval["governedPaths"], "before")
        return
    decision_commit = _unique_addition(root, preapproval_commit, head_commit, DECISION_PATH)
    if _state(root, head_commit, RECEIPT_PATH) != {"state": "absent"}:
        receipt_commit = _unique_addition(root, decision_commit, head_commit, RECEIPT_PATH)
        validate_application_receipt(root, receipt_commit, head_commit, verify_owner_comment=verify_owner_comment)
        return
    preapproval, _ = validate_decision_commit(
        root, preapproval_commit, decision_commit, verify_owner_comment=verify_owner_comment
    )
    states = [_state(root, head_commit, entry["path"]) for entry in preapproval["governedPaths"]]
    before = [entry["before"] for entry in preapproval["governedPaths"]]
    after = [entry["after"] for entry in preapproval["governedPaths"]]
    if states == before:
        return
    if states != after:
        raise AuthorityError("v7 governed paths are in a partial state")
    validate_applied_commit(
        root, preapproval_commit, decision_commit, head_commit, verify_owner_comment=verify_owner_comment
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
                root, arguments.preapproval_commit, verify_owner_comment=arguments.verify_owner_comment
            )
        else:
            validate_ci_state(root, arguments.head_commit, verify_owner_comment=arguments.verify_owner_comment)
    except AuthorityError as error:
        print(f"ERROR: {error}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
