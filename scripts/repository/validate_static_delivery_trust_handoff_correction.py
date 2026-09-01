"""Validate the additive Issue #62 v8 static-delivery trust-root handoff.

The v7 preapproval and OWNER decision remain immutable authority. Its exact
48-path future was prepared but never committed or integrated and is
superseded before application because its Web handoff did not prove the
historical Issue #71 gate blob before trusting the evolved gate. A v8 decision
may authorize only the exact corrected repository blobs pre-bound here. It
never authorizes infrastructure apply, publication, upload, credentials, DNS,
environments, external mutation, Candidate-v7, or TAR use.
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
DIRECTORY = "contracts/repository-removal/v8/phase-3-issue-62"
SCHEMA_PATH = "contracts/repository-removal/v8/static-delivery-trust-handoff-correction.schema.json"
PREAPPROVAL_PATH = f"{DIRECTORY}/preapproval.json"
DECISION_PATH = f"{DIRECTORY}/owner-decision.json"
RECEIPT_PATH = f"{DIRECTORY}/application-receipt.json"
VALIDATOR_PATH = "scripts/repository/validate_static_delivery_trust_handoff_correction.py"
TEST_PATH = "tests/repository-removal/test_validate_static_delivery_trust_handoff_correction.py"
WEB_HANDOFF_PATH = "src/web/scripts/check-target-content.mjs"
WEB_HANDOFF_TEST_PATH = "src/web/scripts/check-target-content.test.mjs"
SEALED_GATE_TEST_PATH = "src/web/scripts/static-repository-gates.test.mjs"

AUDITED_BASE = "caa161e5a53014b73f30bd43b78c1026c24e9c98"
V7_PREAPPROVAL = "caa49ae8eaf4dcf06107f45cd72d104f88386544"
V7_PREAPPROVAL_TREE = "0d68e787cc6b3f92ee5bde288808388c09be2cc0"
V7_PREAPPROVAL_SHA256 = (
    "26aea62dab0093c262bc5caa34bea3e4edf3ab506f491d766b769e33cb1e448b"
)
V7_DECISION = "82ef074298f362e32163d140f81d403776f5a3d6"
V7_DECISION_TREE = "acf98632762eceaec70616287abc76da29c23979"
V7_DECISION_SHA256 = (
    "6fb4b42389e223ac08351549e75a8aef6b8d0e5ee4a118613602868b4ede70d3"
)
V7_OWNER_COMMENT_ID = 5493019624
V7_OWNER_COMMENT_TIME = "2026-09-01T11:09:32Z"
STATIC_REPOSITORY_GATES_PATH = "src/web/scripts/static-repository-gates.mjs"
STATIC_REPOSITORY_GATES_BLOB = "02e32cda7a01460c3055f61cccaf9f03fc0552f9"
STATIC_REPOSITORY_GATES_SHA256 = (
    "b97d051d616738dc12d24f9d364bd9fcda59d1a0ab41c705b7cdac1bc199637c"
)
V7_GOVERNED_TRANSITIONS_SHA256 = (
    "807fadfb3d0503cc0d408a1c6cc0fe0ad221db6086cf1018317c725a285433fb"
)
GOVERNED_TRANSITIONS_SHA256 = (
    "cd4ed890afad960c6f6b3e71b80724c8163fc0f6b8950a6aeb4398edbc05addf"
)

EXPECTED_AUTHORITY_PATHS = {SCHEMA_PATH, PREAPPROVAL_PATH, VALIDATOR_PATH}
NEW_GOVERNED_PATHS = {
    TEST_PATH,
}
CORRECTED_V7_PATHS = {
    ".github/workflows/ci.yml",
    "contracts/supply-chain/v2/static-target-profile.json",
    WEB_HANDOFF_PATH,
    WEB_HANDOFF_TEST_PATH,
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


def _load_v7() -> Any:
    path = ROOT / "scripts/repository/validate_static_delivery_handoff_correction.py"
    spec = importlib.util.spec_from_file_location("static_delivery_handoff_v7", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("v7 delivery validator cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


V7 = _load_v7()
AuthorityError = V7.AuthorityError
_sha256 = V7._sha256
_git = V7._git
_json = V7._json
_blob = V7._blob
_document_at = V7._document_at
_state = V7._state
_assert_ancestor = V7._assert_ancestor
_assert_changed_paths = V7._assert_changed_paths
_assert_states = V7._assert_states
_schema_validate = V7._schema_validate
_unique_addition = V7._unique_addition
EXPECTED_GOVERNED_PATHS = {*V7.EXPECTED_GOVERNED_PATHS, *NEW_GOVERNED_PATHS}
PRIOR_IMMUTABLE_PATHS = {
    *V7.PRIOR_IMMUTABLE_PATHS,
    *V7.EXPECTED_AUTHORITY_PATHS,
    V7.DECISION_PATH,
}
TRUST_ROOTS = {
    "staticDeliveryTrustHandoffSchema": SCHEMA_PATH,
    "staticDeliveryTrustHandoffValidator": VALIDATOR_PATH,
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
        raise AuthorityError("cannot prove repository history ancestry")
    return result.returncode == 0


def _assert_immutable(root: Path, later: str, preapproval_commit: str) -> None:
    for path in EXPECTED_AUTHORITY_PATHS:
        if _state(root, preapproval_commit, path) != _state(root, later, path):
            raise AuthorityError(f"v8 authority changed after P8: {path}")
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


def _expected_v7_authority(root: Path) -> dict[str, Any]:
    decision = _document_at(root, V7_DECISION, V7.DECISION_PATH, "v7 decision")
    return {
        "preapprovalCommit": V7_PREAPPROVAL,
        "preapprovalTree": V7_PREAPPROVAL_TREE,
        "preapprovalSha256": V7_PREAPPROVAL_SHA256,
        "decisionCommit": V7_DECISION,
        "decisionTree": V7_DECISION_TREE,
        "decisionSha256": V7_DECISION_SHA256,
        "ownerComment": {
            "id": V7_OWNER_COMMENT_ID,
            "url": decision["approvalSource"]["commentUrl"],
            "issueApiUrl": "https://api.github.com/repos/artemsemdev/SeaRise-Europe/issues/62",
            "author": "artemsemdev",
            "association": "OWNER",
            "createdAt": V7_OWNER_COMMENT_TIME,
            "updatedAt": V7_OWNER_COMMENT_TIME,
            "body": decision["approvalText"],
            "bodySha256": decision["approvalSource"]["bodySha256"],
        },
        "status": "decision-preserved-uncommitted-application-superseded",
        "governedStateAuthorized": True,
        "integratedApplicationCommit": None,
        "receiptCommit": None,
    }


def _governed_after_sha256(preapproval: dict[str, Any]) -> str:
    payload = [
        {"path": entry["path"], **entry["after"]}
        for entry in preapproval["governedPaths"]
    ]
    return _canonical_sha256(payload)


def _expected_superseded_v7_proposed_application(
    v7_preapproval: dict[str, Any],
) -> dict[str, Any]:
    return {
        "commit": None,
        "tree": None,
        "pullRequest": None,
        "status": "superseded-before-application-commit-and-integration",
        "governedPathCount": 48,
        "governedTransitionsSha256": V7_GOVERNED_TRANSITIONS_SHA256,
        "governedAfterStateSha256": _governed_after_sha256(v7_preapproval),
        "governedStateIntegrated": False,
        "reason": (
            "The exact 48-path v7 after-state was prepared only in an uncommitted "
            "worktree and never became a Git commit, pull request, repository "
            "application, or integration state. Review found that its Web handoff "
            "selected the evolved static-repository gate without first proving "
            "that the transition began at the exact historical Issue #71 gate "
            "blob. The proposal is therefore superseded before application; its "
            "exact transitions and after-state remain bound only as diagnostic "
            "evidence and authorize no governed repository state."
        ),
    }


def _validate_v7_chain(root: Path, document: dict[str, Any], *, verify_owner_comment: bool) -> None:
    v7_preapproval = _document_at(
        root, V7_PREAPPROVAL, V7.PREAPPROVAL_PATH, "v7 preapproval"
    )
    for field in (
        "phase2Issue71History",
        "phase3Issue61History",
        "phase3Issue62V5SupersededAuthority",
        "phase3Issue62V6Authority",
        "supersededV6Application",
    ):
        if document[field] != v7_preapproval[field]:
            raise AuthorityError(f"immutable v7 inherited history differs: {field}")
    V7.validate_decision_commit(
        root,
        V7_PREAPPROVAL,
        V7_DECISION,
        verify_owner_comment=verify_owner_comment,
    )
    if document["phase3Issue62V7Authority"] != _expected_v7_authority(root):
        raise AuthorityError("preserved v7 P/D authority differs")
    expected_proposal = _expected_superseded_v7_proposed_application(v7_preapproval)
    if document["supersededV7ProposedApplication"] != expected_proposal:
        raise AuthorityError("superseded uncommitted v7 application evidence differs")
    _assert_states(root, AUDITED_BASE, v7_preapproval["governedPaths"], "before")


def validate_preapproval_document(
    root: Path, document: dict[str, Any], *, verify_owner_comment: bool
) -> None:
    schema = _json((root / SCHEMA_PATH).read_bytes(), "v8 handoff schema")
    _schema_validate(document, schema, "v8 handoff preapproval")
    if document["auditedBaseCommit"] != AUDITED_BASE:
        raise AuthorityError("audited base differs from merged v7 P/D authority")
    if set(document["authorityPaths"]) != EXPECTED_AUTHORITY_PATHS:
        raise AuthorityError("v8 authority path set differs")
    if set(document["trustRootSha256"]) != set(TRUST_ROOTS):
        raise AuthorityError("v8 trust-root names differ")
    paths = [entry["path"] for entry in document["governedPaths"]]
    if paths != sorted(paths) or set(paths) != EXPECTED_GOVERNED_PATHS:
        raise AuthorityError("v8 governed path set differs")
    if len(paths) != len(set(paths)):
        raise AuthorityError("v8 governed paths are duplicated")
    if _canonical_sha256(document["governedPaths"]) != GOVERNED_TRANSITIONS_SHA256:
        raise AuthorityError("v8 future-state hash differs from the exact corrected state")
    if document["safety"] != EXPECTED_SAFETY:
        raise AuthorityError("v8 safety boundary differs")
    if document["deferredOwnership"] != EXPECTED_DEFERRED_OWNERSHIP:
        raise AuthorityError("v8 deferred ownership boundary differs")
    if document["phase2Issue71History"] != V7.V6.EXPECTED_ISSUE71_HISTORY:
        raise AuthorityError("immutable Issue #71 P/D/A/R history differs")
    if document["phase3Issue61History"] != V7.V6.EXPECTED_ISSUE61_HISTORY:
        raise AuthorityError("immutable Issue #61 v4 P/D/A/R history differs")
    expected_hashes = {
        "staticDeliveryTrustHandoffSchema": _sha256((root / SCHEMA_PATH).read_bytes()),
        "staticDeliveryTrustHandoffValidator": _sha256((root / VALIDATOR_PATH).read_bytes()),
        "staticRepositoryGates": STATIC_REPOSITORY_GATES_SHA256,
    }
    if document["trustRootSha256"] != expected_hashes:
        raise AuthorityError("v8 trust-root hash differs")
    if document["trustRootSha256"]["staticRepositoryGates"] != STATIC_REPOSITORY_GATES_SHA256:
        raise AuthorityError("Issue #71 static-repository gate trust blob differs")
    _assert_states(root, AUDITED_BASE, document["governedPaths"], "before")
    for entry in document["governedPaths"]:
        if entry["before"] == entry["after"]:
            raise AuthorityError(f"v8 transition is a no-op: {entry['path']}")
        if entry["after"]["state"] != "present":
            raise AuthorityError(f"v8 cannot authorize deletion: {entry['path']}")
        lowered = entry["path"].lower()
        if "candidate-v7" in lowered or lowered.endswith((".tar", ".tar.gz")):
            raise AuthorityError(f"forbidden Candidate-v7/TAR path: {entry['path']}")

    v7 = _document_at(root, V7_PREAPPROVAL, V7.PREAPPROVAL_PATH, "v7 preapproval")
    v7_after = {entry["path"]: entry["after"] for entry in v7["governedPaths"]}
    v8_after = {entry["path"]: entry["after"] for entry in document["governedPaths"]}
    if set(v8_after) != set(v7_after) | NEW_GOVERNED_PATHS:
        raise AuthorityError("v8 does not cover the complete v7 future state and handoff")
    changed = {path for path in v7_after if v8_after[path] != v7_after[path]}
    if changed != CORRECTED_V7_PATHS:
        raise AuthorityError("v8 differs from v7 outside the bounded handoff fix")
    _validate_issue71_history(root, document, verify_owner_comment=verify_owner_comment)
    _validate_v7_chain(root, document, verify_owner_comment=verify_owner_comment)


def validate_preapproval_commit(
    root: Path, preapproval_commit: str, *, verify_owner_comment: bool
) -> tuple[dict[str, Any], bytes]:
    _assert_ancestor(root, AUDITED_BASE, preapproval_commit)
    _assert_changed_paths(root, AUDITED_BASE, preapproval_commit, EXPECTED_AUTHORITY_PATHS, "B8-to-P8")
    if _state(root, preapproval_commit, DECISION_PATH) != {"state": "absent"}:
        raise AuthorityError("v8 owner decision must be absent at P8")
    if _state(root, preapproval_commit, RECEIPT_PATH) != {"state": "absent"}:
        raise AuthorityError("v8 receipt must be absent at P8")
    preapproval_bytes = _blob(root, preapproval_commit, PREAPPROVAL_PATH)
    preapproval = _json(preapproval_bytes, "v8 handoff preapproval")
    validate_preapproval_document(root, preapproval, verify_owner_comment=verify_owner_comment)
    return preapproval, preapproval_bytes


def expected_owner_approval_text(
    preapproval: dict[str, Any], preapproval_commit: str, preapproval_sha256: str
) -> str:
    template = preapproval["ownerApprovalTemplate"]
    placeholders = ("<PREAPPROVAL_COMMIT>", "<PREAPPROVAL_SHA256>")
    if any(template.count(placeholder) != 1 for placeholder in placeholders):
        raise AuthorityError("v8 approval placeholders are not exact")
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
    _assert_changed_paths(root, preapproval_commit, decision_commit, {DECISION_PATH}, "P8-to-D8")
    if _unique_addition(root, preapproval_commit, decision_commit, DECISION_PATH) != decision_commit:
        raise AuthorityError("D8 is not the v8 owner-decision addition commit")
    _assert_immutable(root, decision_commit, preapproval_commit)
    decision = _json(_blob(root, decision_commit, DECISION_PATH), "v8 owner decision")
    schema = _document_at(root, preapproval_commit, SCHEMA_PATH, "v8 handoff schema")
    _schema_validate(decision, schema, "v8 owner decision")
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
            raise AuthorityError(f"v8 owner decision {field} differs from P8")
    if not verify_owner_comment:
        raise AuthorityError("live v8 OWNER comment verification is required")
    observed = V7._verify_owner_comment(decision, approval)
    if decision["approvedAt"] != observed["createdAt"]:
        raise AuthorityError("v8 owner decision timestamp differs from live comment")
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
    _assert_changed_paths(root, decision_commit, applied_commit, EXPECTED_GOVERNED_PATHS, "D8-to-A8")
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
    receipt = _document_at(root, receipt_commit, RECEIPT_PATH, "v8 application receipt")
    preapproval = validate_applied_commit(
        root,
        receipt["preapprovalCommit"],
        receipt["decisionCommit"],
        receipt["appliedCommit"],
        verify_owner_comment=verify_owner_comment,
    )
    _assert_ancestor(root, receipt["appliedCommit"], receipt_commit)
    _assert_ancestor(root, receipt_commit, head_commit)
    _assert_changed_paths(root, receipt["appliedCommit"], receipt_commit, {RECEIPT_PATH}, "A8-to-R8")
    if _unique_addition(root, receipt["appliedCommit"], receipt_commit, RECEIPT_PATH) != receipt_commit:
        raise AuthorityError("R8 is not the v8 receipt addition commit")
    schema = _document_at(root, receipt["preapprovalCommit"], SCHEMA_PATH, "v8 handoff schema")
    _schema_validate(receipt, schema, "v8 application receipt")
    expected = {
        "appliedTree": _git(root, "rev-parse", f"{receipt['appliedCommit']}^{{tree}}").decode().strip(),
        "preapprovalSha256": _sha256(_blob(root, receipt["preapprovalCommit"], PREAPPROVAL_PATH)),
        "ownerDecisionSha256": _sha256(_blob(root, receipt["decisionCommit"], DECISION_PATH)),
        "governedStateSha256": _governed_state_sha256(root, receipt["appliedCommit"], preapproval),
        "safety": EXPECTED_SAFETY,
    }
    for field, value in expected.items():
        if receipt[field] != value:
            raise AuthorityError(f"v8 receipt {field} differs from P8/D8/A8")
    _assert_immutable(root, head_commit, receipt["preapprovalCommit"])
    _assert_states(root, head_commit, preapproval["governedPaths"], "after")
    if _state(root, receipt_commit, RECEIPT_PATH) != _state(root, head_commit, RECEIPT_PATH):
        raise AuthorityError("v8 receipt changed after R8")


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
        raise AuthorityError("v8 governed paths are in a partial state")
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
