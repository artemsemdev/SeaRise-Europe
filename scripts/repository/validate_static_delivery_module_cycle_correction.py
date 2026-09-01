"""Validate the additive Issue #62 v10 static-delivery module-cycle handoff.

The v9 preapproval and OWNER decision remain immutable integrated authority.
Its exact 50-file application state was materialized only in an uncommitted
diagnostic worktree and is superseded before application or integration because
the target-content launcher and repository gate form a circular top-level-await
module graph that exits with status 13. A v10 decision may authorize only the
exact corrected repository blobs pre-bound here. It
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
DIRECTORY = "contracts/repository-removal/v10/phase-3-issue-62"
SCHEMA_PATH = "contracts/repository-removal/v10/static-delivery-module-cycle-correction.schema.json"
PREAPPROVAL_PATH = f"{DIRECTORY}/preapproval.json"
DECISION_PATH = f"{DIRECTORY}/owner-decision.json"
RECEIPT_PATH = f"{DIRECTORY}/application-receipt.json"
VALIDATOR_PATH = "scripts/repository/validate_static_delivery_module_cycle_correction.py"
TEST_PATH = "tests/repository-removal/test_validate_static_delivery_module_cycle_correction.py"
WEB_HANDOFF_PATH = "src/web/scripts/check-target-content.mjs"
WEB_HANDOFF_TEST_PATH = "src/web/scripts/check-target-content.test.mjs"
SEALED_GATE_TEST_PATH = "src/web/scripts/static-repository-gates.test.mjs"

AUDITED_BASE = "a083c06747e6d1a0860171db926f528ab54ecefa"
V9_PREAPPROVAL = "6d14058acdc18e06f1e7023e85e254f584c499b4"
V9_PREAPPROVAL_TREE = "09871d4456666e3a2c94d9e4d5a58bdf78fefa22"
V9_PREAPPROVAL_SHA256 = (
    "43f62d66dae8b0939645be92c564e84487032cfee09d0a21dcc0be8b52d7ff58"
)
V9_PREAPPROVAL_MERGE = "a53e8f4bec8df248713b2013e25996744952023e"
V9_DECISION = "e2dcb08ae70a7c665b02600c8cc1c758e052b1b4"
V9_DECISION_TREE = "ecb519cfab0f5802c3fbf8ec287448accc856a39"
V9_DECISION_SHA256 = (
    "49db66844fee59edf3be08c9bc7be4917865e298411693cf64e0a592a7786964"
)
V9_DECISION_MERGE = AUDITED_BASE
V9_OWNER_COMMENT_ID = 5496247462
V9_OWNER_COMMENT_TIME = "2026-09-01T15:22:39Z"
STATIC_REPOSITORY_GATES_PATH = "src/web/scripts/static-repository-gates.mjs"
STATIC_REPOSITORY_GATES_BLOB = "02e32cda7a01460c3055f61cccaf9f03fc0552f9"
STATIC_REPOSITORY_GATES_SHA256 = (
    "b97d051d616738dc12d24f9d364bd9fcda59d1a0ab41c705b7cdac1bc199637c"
)
V9_GOVERNED_TRANSITIONS_SHA256 = (
    "e2aecd26242e91e02f724a240cbc1687c620c8b115ce3af77b0966c57d25ea7c"
)
V9_GOVERNED_AFTER_STATE_SHA256 = (
    "103b3d6f1fc238d523edb45af2d3af654a3fca09deb9c1d9080f74969058c9f4"
)
GOVERNED_TRANSITIONS_SHA256 = (
    "fe6ea3cea9e51f2dcda7216fe0e194c991bb19b40a15a4c7ab46dc91399f17fb"
)

EXPECTED_AUTHORITY_PATHS = {SCHEMA_PATH, PREAPPROVAL_PATH, VALIDATOR_PATH}
NEW_GOVERNED_PATHS = {
    TEST_PATH,
    "src/web/scripts/static-repository-authority.mjs",
}
CORRECTED_V9_PATHS = {
    ".github/workflows/ci.yml",
    "contracts/supply-chain/v2/static-target-profile.json",
    WEB_HANDOFF_PATH,
    WEB_HANDOFF_TEST_PATH,
    "src/web/scripts/static-repository-gates.mjs",
    SEALED_GATE_TEST_PATH,
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


def _load_v9() -> Any:
    path = ROOT / "scripts/repository/validate_static_delivery_owner_verifier_correction.py"
    spec = importlib.util.spec_from_file_location("static_delivery_owner_verifier_v9", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("v9 delivery validator cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


V9 = _load_v9()
AuthorityError = V9.AuthorityError
_sha256 = V9._sha256
_git = V9._git
_json = V9._json
_blob = V9._blob
_document_at = V9._document_at
_state = V9._state
_assert_ancestor = V9._assert_ancestor
_assert_changed_paths = V9._assert_changed_paths
_assert_states = V9._assert_states
_schema_validate = V9._schema_validate
_unique_addition = V9._unique_addition
EXPECTED_GOVERNED_PATHS = {*V9.EXPECTED_GOVERNED_PATHS, *NEW_GOVERNED_PATHS}
PRIOR_IMMUTABLE_PATHS = {
    *V9.PRIOR_IMMUTABLE_PATHS,
    *V9.EXPECTED_AUTHORITY_PATHS,
}
TRUST_ROOTS = {
    "staticDeliveryModuleCycleSchema": SCHEMA_PATH,
    "staticDeliveryModuleCycleValidator": VALIDATOR_PATH,
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
            raise AuthorityError(f"v10 authority changed after P10: {path}")
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


def _expected_v9_authority(root: Path) -> dict[str, Any]:
    preapproval = _document_at(
        root, V9_PREAPPROVAL, V9.PREAPPROVAL_PATH, "v9 preapproval"
    )
    return {
        "preapprovalCommit": V9_PREAPPROVAL,
        "preapprovalTree": V9_PREAPPROVAL_TREE,
        "preapprovalSha256": V9_PREAPPROVAL_SHA256,
        "preapprovalMergeCommit": V9_PREAPPROVAL_MERGE,
        "decisionCommit": V9_DECISION,
        "decisionTree": V9_DECISION_TREE,
        "ownerDecisionSha256": V9_DECISION_SHA256,
        "decisionMergeCommit": V9_DECISION_MERGE,
        "ownerComment": {
            "id": V9_OWNER_COMMENT_ID,
            "url": (
                "https://github.com/artemsemdev/SeaRise-Europe/issues/62"
                f"#issuecomment-{V9_OWNER_COMMENT_ID}"
            ),
            "issueApiUrl": "https://api.github.com/repos/artemsemdev/SeaRise-Europe/issues/62",
            "author": "artemsemdev",
            "association": "OWNER",
            "createdAt": V9_OWNER_COMMENT_TIME,
            "updatedAt": V9_OWNER_COMMENT_TIME,
            "body": V9.expected_owner_approval_text(
                preapproval, V9_PREAPPROVAL, V9_PREAPPROVAL_SHA256
            ),
            "bodySha256": "a07b12804a9f63ee0f27f90262e7fbd459d3dbda1a8d2795942c8d7e02714e00",
        },
        "status": "decision-preserved-application-superseded",
        "ownerApprovalRecorded": True,
        "repositoryDecisionIntegrated": True,
        "integratedApplicationCommit": None,
        "receiptCommit": None,
    }


def _governed_after_sha256(preapproval: dict[str, Any]) -> str:
    payload = [
        {"path": entry["path"], **entry["after"]}
        for entry in preapproval["governedPaths"]
    ]
    return _canonical_sha256(payload)


def _expected_superseded_v9_application(root: Path) -> dict[str, Any]:
    preapproval = _document_at(root, V9_PREAPPROVAL, V9.PREAPPROVAL_PATH, "v9 preapproval")
    if _canonical_sha256(preapproval["governedPaths"]) != V9_GOVERNED_TRANSITIONS_SHA256:
        raise AuthorityError("superseded v9 application transitions differ")
    if _governed_after_sha256(preapproval) != V9_GOVERNED_AFTER_STATE_SHA256:
        raise AuthorityError("superseded v9 application after state differs")
    return {
        "commit": None,
        "tree": None,
        "pullRequest": None,
        "status": "superseded-before-application-commit-and-integration",
        "governedPathCount": 50,
        "governedTransitionsSha256": V9_GOVERNED_TRANSITIONS_SHA256,
        "governedAfterStateSha256": V9_GOVERNED_AFTER_STATE_SHA256,
        "governedStateIntegrated": False,
        "reason": (
            "The exact v9 50-file after state was materialized only in an uncommitted "
            "diagnostic worktree. Real source and built Node CLI execution exposed a "
            "circular top-level-await module graph between check-target-content.mjs "
            "and static-repository-gates.mjs, exiting with status 13. No v9 application "
            "commit, pull request, integration, receipt, deployment, publication, "
            "upload, or external mutation exists."
        ),
    }


def _validate_v9_chain(root: Path, document: dict[str, Any], *, verify_owner_comment: bool) -> None:
    v9_preapproval = _document_at(
        root, V9_PREAPPROVAL, V9.PREAPPROVAL_PATH, "v9 preapproval"
    )
    for field in (
        "phase2Issue71History",
        "phase3Issue61History",
        "phase3Issue62V5SupersededAuthority",
        "phase3Issue62V6Authority",
        "supersededV6Application",
        "phase3Issue62V7Authority",
        "supersededV7ProposedApplication",
        "phase3Issue62V8Authority",
        "supersededV8DecisionAttempt",
    ):
        if document[field] != v9_preapproval[field]:
            raise AuthorityError(f"immutable v9 inherited history differs: {field}")
    V9.validate_decision_commit(
        root, V9_PREAPPROVAL, V9_DECISION, verify_owner_comment=verify_owner_comment
    )
    if not _is_ancestor(root, V9_PREAPPROVAL, AUDITED_BASE):
        raise AuthorityError("v9 preapproval is not integrated in the audited base")
    if not _is_ancestor(root, V9_DECISION, AUDITED_BASE):
        raise AuthorityError("v9 decision is not integrated in the audited base")
    for merged, topic, label in (
        (V9_PREAPPROVAL_MERGE, V9_PREAPPROVAL, "preapproval"),
        (V9_DECISION_MERGE, V9_DECISION, "decision"),
    ):
        if not _is_ancestor(root, merged, AUDITED_BASE):
            raise AuthorityError(f"v9 {label} merge is not in the audited base")
        if _git(root, "rev-parse", f"{merged}^{{tree}}").decode().strip() != (
            _git(root, "rev-parse", f"{topic}^{{tree}}").decode().strip()
        ):
            raise AuthorityError(f"v9 {label} merge tree differs from reviewed topic")
    if document["phase3Issue62V9Authority"] != _expected_v9_authority(root):
        raise AuthorityError("preserved v9 P/D authority differs")
    expected_application = _expected_superseded_v9_application(root)
    if document["supersededV9ProposedApplication"] != expected_application:
        raise AuthorityError("superseded v9 application evidence differs")
    _assert_states(root, AUDITED_BASE, v9_preapproval["governedPaths"], "before")


def validate_preapproval_document(
    root: Path, document: dict[str, Any], *, verify_owner_comment: bool
) -> None:
    schema = _json((root / SCHEMA_PATH).read_bytes(), "v10 verifier schema")
    _schema_validate(document, schema, "v10 verifier preapproval")
    if document["auditedBaseCommit"] != AUDITED_BASE:
        raise AuthorityError("audited base differs from merged v9 preapproval")
    if set(document["authorityPaths"]) != EXPECTED_AUTHORITY_PATHS:
        raise AuthorityError("v10 authority path set differs")
    if set(document["trustRootSha256"]) != set(TRUST_ROOTS):
        raise AuthorityError("v10 trust-root names differ")
    paths = [entry["path"] for entry in document["governedPaths"]]
    if paths != sorted(paths) or set(paths) != EXPECTED_GOVERNED_PATHS:
        raise AuthorityError("v10 governed path set differs")
    if len(paths) != len(set(paths)):
        raise AuthorityError("v10 governed paths are duplicated")
    if _canonical_sha256(document["governedPaths"]) != GOVERNED_TRANSITIONS_SHA256:
        raise AuthorityError("v10 future-state hash differs from the exact corrected state")
    if document["safety"] != EXPECTED_SAFETY:
        raise AuthorityError("v10 safety boundary differs")
    if document["deferredOwnership"] != EXPECTED_DEFERRED_OWNERSHIP:
        raise AuthorityError("v10 deferred ownership boundary differs")
    if document["phase2Issue71History"] != V9.V8.V7.V6.EXPECTED_ISSUE71_HISTORY:
        raise AuthorityError("immutable Issue #71 P/D/A/R history differs")
    if document["phase3Issue61History"] != V9.V8.V7.V6.EXPECTED_ISSUE61_HISTORY:
        raise AuthorityError("immutable Issue #61 v4 P/D/A/R history differs")
    expected_hashes = {
        "staticDeliveryModuleCycleSchema": _sha256((root / SCHEMA_PATH).read_bytes()),
        "staticDeliveryModuleCycleValidator": _sha256((root / VALIDATOR_PATH).read_bytes()),
        "staticRepositoryGates": STATIC_REPOSITORY_GATES_SHA256,
    }
    if document["trustRootSha256"] != expected_hashes:
        raise AuthorityError("v10 trust-root hash differs")
    if document["trustRootSha256"]["staticRepositoryGates"] != STATIC_REPOSITORY_GATES_SHA256:
        raise AuthorityError("Issue #71 static-repository gate trust blob differs")
    _assert_states(root, AUDITED_BASE, document["governedPaths"], "before")
    for entry in document["governedPaths"]:
        if entry["before"] == entry["after"]:
            raise AuthorityError(f"v10 transition is a no-op: {entry['path']}")
        if entry["after"]["state"] != "present":
            raise AuthorityError(f"v10 cannot authorize deletion: {entry['path']}")
        lowered = entry["path"].lower()
        if "candidate-v7" in lowered or lowered.endswith((".tar", ".tar.gz")):
            raise AuthorityError(f"forbidden Candidate-v7/TAR path: {entry['path']}")

    v9 = _document_at(root, V9_PREAPPROVAL, V9.PREAPPROVAL_PATH, "v9 preapproval")
    v9_after = {entry["path"]: entry["after"] for entry in v9["governedPaths"]}
    v10_after = {entry["path"]: entry["after"] for entry in document["governedPaths"]}
    if set(v10_after) != set(v9_after) | NEW_GOVERNED_PATHS:
        raise AuthorityError("v10 does not cover the complete v9 future state and verifier fix")
    changed = {path for path in v9_after if v10_after[path] != v9_after[path]}
    if changed != CORRECTED_V9_PATHS:
        raise AuthorityError("v10 differs from v9 outside the bounded verifier fix")
    _validate_issue71_history(root, document, verify_owner_comment=verify_owner_comment)
    _validate_v9_chain(root, document, verify_owner_comment=verify_owner_comment)


def validate_preapproval_commit(
    root: Path, preapproval_commit: str, *, verify_owner_comment: bool
) -> tuple[dict[str, Any], bytes]:
    _assert_ancestor(root, AUDITED_BASE, preapproval_commit)
    _assert_changed_paths(root, AUDITED_BASE, preapproval_commit, EXPECTED_AUTHORITY_PATHS, "B10-to-P10")
    if _state(root, preapproval_commit, DECISION_PATH) != {"state": "absent"}:
        raise AuthorityError("v10 owner decision must be absent at P10")
    if _state(root, preapproval_commit, RECEIPT_PATH) != {"state": "absent"}:
        raise AuthorityError("v10 receipt must be absent at P10")
    preapproval_bytes = _blob(root, preapproval_commit, PREAPPROVAL_PATH)
    preapproval = _json(preapproval_bytes, "v10 verifier preapproval")
    validate_preapproval_document(root, preapproval, verify_owner_comment=verify_owner_comment)
    return preapproval, preapproval_bytes


def expected_owner_approval_text(
    preapproval: dict[str, Any], preapproval_commit: str, preapproval_sha256: str
) -> str:
    template = preapproval["ownerApprovalTemplate"]
    placeholders = ("<PREAPPROVAL_COMMIT>", "<PREAPPROVAL_SHA256>")
    if any(template.count(placeholder) != 1 for placeholder in placeholders):
        raise AuthorityError("v10 approval placeholders are not exact")
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
    _assert_changed_paths(root, preapproval_commit, decision_commit, {DECISION_PATH}, "P10-to-D10")
    if _unique_addition(root, preapproval_commit, decision_commit, DECISION_PATH) != decision_commit:
        raise AuthorityError("D10 is not the v10 owner-decision addition commit")
    _assert_immutable(root, decision_commit, preapproval_commit)
    decision = _json(_blob(root, decision_commit, DECISION_PATH), "v10 owner decision")
    schema = _document_at(root, preapproval_commit, SCHEMA_PATH, "v10 verifier schema")
    _schema_validate(decision, schema, "v10 owner decision")
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
            raise AuthorityError(f"v10 owner decision {field} differs from P10")
    if not verify_owner_comment:
        raise AuthorityError("live v10 OWNER comment verification is required")
    observed = V9.V7.V6._verify_owner_comment(decision, approval)
    if decision["approvedAt"] != observed["createdAt"]:
        raise AuthorityError("v10 owner decision timestamp differs from live comment")
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
    _assert_changed_paths(root, decision_commit, applied_commit, EXPECTED_GOVERNED_PATHS, "D10-to-A10")
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
    receipt = _document_at(root, receipt_commit, RECEIPT_PATH, "v10 application receipt")
    preapproval = validate_applied_commit(
        root,
        receipt["preapprovalCommit"],
        receipt["decisionCommit"],
        receipt["appliedCommit"],
        verify_owner_comment=verify_owner_comment,
    )
    _assert_ancestor(root, receipt["appliedCommit"], receipt_commit)
    _assert_ancestor(root, receipt_commit, head_commit)
    _assert_changed_paths(root, receipt["appliedCommit"], receipt_commit, {RECEIPT_PATH}, "A10-to-R10")
    if _unique_addition(root, receipt["appliedCommit"], receipt_commit, RECEIPT_PATH) != receipt_commit:
        raise AuthorityError("R10 is not the v10 receipt addition commit")
    schema = _document_at(root, receipt["preapprovalCommit"], SCHEMA_PATH, "v10 verifier schema")
    _schema_validate(receipt, schema, "v10 application receipt")
    expected = {
        "appliedTree": _git(root, "rev-parse", f"{receipt['appliedCommit']}^{{tree}}").decode().strip(),
        "preapprovalSha256": _sha256(_blob(root, receipt["preapprovalCommit"], PREAPPROVAL_PATH)),
        "ownerDecisionSha256": _sha256(_blob(root, receipt["decisionCommit"], DECISION_PATH)),
        "governedStateSha256": _governed_state_sha256(root, receipt["appliedCommit"], preapproval),
        "safety": EXPECTED_SAFETY,
    }
    for field, value in expected.items():
        if receipt[field] != value:
            raise AuthorityError(f"v10 receipt {field} differs from P10/D10/A10")
    _assert_immutable(root, head_commit, receipt["preapprovalCommit"])
    _assert_states(root, head_commit, preapproval["governedPaths"], "after")
    if _state(root, receipt_commit, RECEIPT_PATH) != _state(root, head_commit, RECEIPT_PATH):
        raise AuthorityError("v10 receipt changed after R10")


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
        raise AuthorityError("v10 governed paths are in a partial state")
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
