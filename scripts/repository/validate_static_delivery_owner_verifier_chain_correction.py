"""Validate the additive Issue #62 v11 static-delivery OWNER-verifier handoff.

The v10 preapproval remains immutable authority. Its exact OWNER decision was
committed only in an unpushed diagnostic branch and is superseded before
publication or integration because the v10 validator calls a symbol the v7
module does not expose. A v11 decision may authorize only the exact corrected
repository blobs pre-bound here. It
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
DIRECTORY = "contracts/repository-removal/v11/phase-3-issue-62"
SCHEMA_PATH = "contracts/repository-removal/v11/static-delivery-owner-verifier-chain-correction.schema.json"
PREAPPROVAL_PATH = f"{DIRECTORY}/preapproval.json"
DECISION_PATH = f"{DIRECTORY}/owner-decision.json"
RECEIPT_PATH = f"{DIRECTORY}/application-receipt.json"
VALIDATOR_PATH = "scripts/repository/validate_static_delivery_owner_verifier_chain_correction.py"
TEST_PATH = "tests/repository-removal/test_validate_static_delivery_owner_verifier_chain_correction.py"
WEB_HANDOFF_PATH = "src/web/scripts/check-target-content.mjs"
WEB_HANDOFF_TEST_PATH = "src/web/scripts/check-target-content.test.mjs"
SEALED_GATE_TEST_PATH = "src/web/scripts/static-repository-gates.test.mjs"

AUDITED_BASE = "a264a3c15b6b00d79b10582d53c0082c145b4cc9"
V10_PREAPPROVAL = "45c9e855c904bf93f2cb9e5b79497114827a63aa"
V10_PREAPPROVAL_TREE = "b0fad8c1480a2a38827a09c63f1991e30d63f561"
V10_PREAPPROVAL_SHA256 = (
    "90d2c6faa4f389f405e3087a37e56ae1fe9373ca0941bc948428bb9fbd4a42c2"
)
V10_PREAPPROVAL_MERGE = AUDITED_BASE
V10_DECISION_ATTEMPT = "6ed3ca54e5d2063d44950fe362dee5329ef71f71"
V10_DECISION_ATTEMPT_TREE = "8e95bc3b25e52d7f1659ab01345f1c9015c53347"
V10_DECISION_ATTEMPT_SHA256 = (
    "d42ae6d5880e15ca5658e2fe8e455c9013608460d02c791c5d98720c6ebff7b9"
)
V10_OWNER_COMMENT_ID = 5498258726
V10_OWNER_COMMENT_TIME = "2026-09-01T18:06:49Z"
STATIC_REPOSITORY_GATES_PATH = "src/web/scripts/static-repository-gates.mjs"
STATIC_REPOSITORY_GATES_BLOB = "02e32cda7a01460c3055f61cccaf9f03fc0552f9"
STATIC_REPOSITORY_GATES_SHA256 = (
    "b97d051d616738dc12d24f9d364bd9fcda59d1a0ab41c705b7cdac1bc199637c"
)
V10_GOVERNED_TRANSITIONS_SHA256 = (
    "fe6ea3cea9e51f2dcda7216fe0e194c991bb19b40a15a4c7ab46dc91399f17fb"
)
GOVERNED_TRANSITIONS_SHA256 = (
    "8df420b1892a059869d86d87208488954d38cd0d7bd20d28e45c4766649b7041"
)

EXPECTED_AUTHORITY_PATHS = {SCHEMA_PATH, PREAPPROVAL_PATH, VALIDATOR_PATH}
NEW_GOVERNED_PATHS = {
    TEST_PATH,
}
CORRECTED_V10_PATHS = {
    ".github/workflows/ci.yml",
    "contracts/supply-chain/v2/static-target-profile.json",
    WEB_HANDOFF_TEST_PATH,
    "src/web/scripts/static-repository-authority.mjs",
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


def _load_v10() -> Any:
    path = ROOT / "scripts/repository/validate_static_delivery_module_cycle_correction.py"
    spec = importlib.util.spec_from_file_location("static_delivery_module_cycle_v10", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("v10 delivery validator cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


V10 = _load_v10()
AuthorityError = V10.AuthorityError
_sha256 = V10._sha256
_git = V10._git
_json = V10._json
_blob = V10._blob
_document_at = V10._document_at
_state = V10._state
_assert_ancestor = V10._assert_ancestor
_assert_changed_paths = V10._assert_changed_paths
_assert_states = V10._assert_states
_schema_validate = V10._schema_validate
_unique_addition = V10._unique_addition
EXPECTED_GOVERNED_PATHS = {*V10.EXPECTED_GOVERNED_PATHS, *NEW_GOVERNED_PATHS}
PRIOR_IMMUTABLE_PATHS = {
    *V10.PRIOR_IMMUTABLE_PATHS,
    *V10.EXPECTED_AUTHORITY_PATHS,
}
TRUST_ROOTS = {
    "staticDeliveryOwnerVerifierChainSchema": SCHEMA_PATH,
    "staticDeliveryOwnerVerifierChainValidator": VALIDATOR_PATH,
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
            raise AuthorityError(f"v11 authority changed after P11: {path}")
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


def _expected_v10_authority(root: Path) -> dict[str, Any]:
    preapproval = _document_at(
        root, V10_PREAPPROVAL, V10.PREAPPROVAL_PATH, "v10 preapproval"
    )
    return {
        "preapprovalCommit": V10_PREAPPROVAL,
        "preapprovalTree": V10_PREAPPROVAL_TREE,
        "preapprovalSha256": V10_PREAPPROVAL_SHA256,
        "preapprovalMergeCommit": V10_PREAPPROVAL_MERGE,
        "ownerComment": {
            "id": V10_OWNER_COMMENT_ID,
            "url": (
                "https://github.com/artemsemdev/SeaRise-Europe/issues/62"
                f"#issuecomment-{V10_OWNER_COMMENT_ID}"
            ),
            "issueApiUrl": "https://api.github.com/repos/artemsemdev/SeaRise-Europe/issues/62",
            "author": "artemsemdev",
            "association": "OWNER",
            "createdAt": V10_OWNER_COMMENT_TIME,
            "updatedAt": V10_OWNER_COMMENT_TIME,
            "body": V10.expected_owner_approval_text(
                preapproval, V10_PREAPPROVAL, V10_PREAPPROVAL_SHA256
            ),
            "bodySha256": "9254010c32c5b2a6112ea0549e471fe2b8a4868c835354df4270cf46a55c022f",
        },
        "status": "preapproval-preserved-decision-attempt-superseded",
        "ownerApprovalRecorded": True,
        "repositoryDecisionIntegrated": False,
        "integratedApplicationCommit": None,
        "receiptCommit": None,
    }


def _governed_after_sha256(preapproval: dict[str, Any]) -> str:
    payload = [
        {"path": entry["path"], **entry["after"]}
        for entry in preapproval["governedPaths"]
    ]
    return _canonical_sha256(payload)


def _expected_superseded_v10_decision_attempt(root: Path) -> dict[str, Any]:
    decision = _document_at(
        root, V10_DECISION_ATTEMPT, V10.DECISION_PATH, "v10 decision attempt"
    )
    _assert_changed_paths(
        root,
        AUDITED_BASE,
        V10_DECISION_ATTEMPT,
        {V10.DECISION_PATH},
        "B11-to-superseded-D10",
    )
    if _unique_addition(
        root, AUDITED_BASE, V10_DECISION_ATTEMPT, V10.DECISION_PATH
    ) != V10_DECISION_ATTEMPT:
        raise AuthorityError("superseded D10 is not one exact decision addition")
    v10_schema = _document_at(
        root, V10_PREAPPROVAL, V10.SCHEMA_PATH, "v10 module-cycle schema"
    )
    _schema_validate(decision, v10_schema, "superseded v10 owner decision")
    return {
        "commit": V10_DECISION_ATTEMPT,
        "tree": V10_DECISION_ATTEMPT_TREE,
        "ownerDecisionSha256": V10_DECISION_ATTEMPT_SHA256,
        "pullRequest": None,
        "status": "superseded-before-publication-and-integration",
        "published": False,
        "integrated": False,
        "approvalSource": decision["approvalSource"],
        "reason": (
            "The exact v10 owner-decision JSON was committed only on a local, "
            "unpushed diagnostic branch. Live D validation proved that the v10 "
            "validator calls V9.V7.V6._verify_owner_comment even though the v9 "
            "module exposes v8 rather than v7. The attempt is superseded before publication or "
            "integration and authorizes no applied governed repository state."
        ),
    }


def _validate_v10_chain(root: Path, document: dict[str, Any], *, verify_owner_comment: bool) -> None:
    v10_preapproval = _document_at(
        root, V10_PREAPPROVAL, V10.PREAPPROVAL_PATH, "v10 preapproval"
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
        "phase3Issue62V9Authority",
        "supersededV9ProposedApplication",
    ):
        if document[field] != v10_preapproval[field]:
            raise AuthorityError(f"immutable v10 inherited history differs: {field}")
    V10.validate_preapproval_commit(
        root, V10_PREAPPROVAL, verify_owner_comment=verify_owner_comment
    )
    if not _is_ancestor(root, V10_PREAPPROVAL, AUDITED_BASE):
        raise AuthorityError("v10 preapproval is not integrated in the audited base")
    if _git(root, "rev-parse", f"{V10_PREAPPROVAL_MERGE}^{{tree}}").decode().strip() != (
        _git(root, "rev-parse", f"{AUDITED_BASE}^{{tree}}").decode().strip()
    ):
        raise AuthorityError("v10 preapproval merge differs from audited base")
    if _is_ancestor(root, V10_DECISION_ATTEMPT, AUDITED_BASE):
        raise AuthorityError("superseded v10 decision attempt reached integration")
    decision = _document_at(
        root, V10_DECISION_ATTEMPT, V10.DECISION_PATH, "v10 decision attempt"
    )
    approval = V10.expected_owner_approval_text(
        v10_preapproval, V10_PREAPPROVAL, V10_PREAPPROVAL_SHA256
    )
    if decision["approvalText"] != approval:
        raise AuthorityError("superseded v10 decision approval text differs")
    if not verify_owner_comment:
        raise AuthorityError("live v10 OWNER comment verification is required")
    observed = V10.V9.V8.V7.V6._verify_owner_comment(decision, approval)
    if decision["approvedAt"] != observed["createdAt"]:
        raise AuthorityError("v10 decision attempt timestamp differs from live comment")
    if document["phase3Issue62V10Authority"] != _expected_v10_authority(root):
        raise AuthorityError("preserved v10 preapproval authority differs")
    expected_attempt = _expected_superseded_v10_decision_attempt(root)
    if document["supersededV10DecisionAttempt"] != expected_attempt:
        raise AuthorityError("superseded v10 decision attempt evidence differs")
    _assert_states(root, AUDITED_BASE, v10_preapproval["governedPaths"], "before")


def validate_preapproval_document(
    root: Path, document: dict[str, Any], *, verify_owner_comment: bool
) -> None:
    schema = _json((root / SCHEMA_PATH).read_bytes(), "v11 verifier schema")
    _schema_validate(document, schema, "v11 verifier preapproval")
    if document["auditedBaseCommit"] != AUDITED_BASE:
        raise AuthorityError("audited base differs from merged v10 preapproval")
    if set(document["authorityPaths"]) != EXPECTED_AUTHORITY_PATHS:
        raise AuthorityError("v11 authority path set differs")
    if set(document["trustRootSha256"]) != set(TRUST_ROOTS):
        raise AuthorityError("v11 trust-root names differ")
    paths = [entry["path"] for entry in document["governedPaths"]]
    if paths != sorted(paths) or set(paths) != EXPECTED_GOVERNED_PATHS:
        raise AuthorityError("v11 governed path set differs")
    if len(paths) != len(set(paths)):
        raise AuthorityError("v11 governed paths are duplicated")
    if _canonical_sha256(document["governedPaths"]) != GOVERNED_TRANSITIONS_SHA256:
        raise AuthorityError("v11 future-state hash differs from the exact corrected state")
    if document["safety"] != EXPECTED_SAFETY:
        raise AuthorityError("v11 safety boundary differs")
    if document["deferredOwnership"] != EXPECTED_DEFERRED_OWNERSHIP:
        raise AuthorityError("v11 deferred ownership boundary differs")
    if document["phase2Issue71History"] != V10.V9.V8.V7.V6.EXPECTED_ISSUE71_HISTORY:
        raise AuthorityError("immutable Issue #71 P/D/A/R history differs")
    if document["phase3Issue61History"] != V10.V9.V8.V7.V6.EXPECTED_ISSUE61_HISTORY:
        raise AuthorityError("immutable Issue #61 v4 P/D/A/R history differs")
    expected_hashes = {
        "staticDeliveryOwnerVerifierChainSchema": _sha256((root / SCHEMA_PATH).read_bytes()),
        "staticDeliveryOwnerVerifierChainValidator": _sha256((root / VALIDATOR_PATH).read_bytes()),
        "staticRepositoryGates": STATIC_REPOSITORY_GATES_SHA256,
    }
    if document["trustRootSha256"] != expected_hashes:
        raise AuthorityError("v11 trust-root hash differs")
    if document["trustRootSha256"]["staticRepositoryGates"] != STATIC_REPOSITORY_GATES_SHA256:
        raise AuthorityError("Issue #71 static-repository gate trust blob differs")
    _assert_states(root, AUDITED_BASE, document["governedPaths"], "before")
    for entry in document["governedPaths"]:
        if entry["before"] == entry["after"]:
            raise AuthorityError(f"v11 transition is a no-op: {entry['path']}")
        if entry["after"]["state"] != "present":
            raise AuthorityError(f"v11 cannot authorize deletion: {entry['path']}")
        lowered = entry["path"].lower()
        if "candidate-v7" in lowered or lowered.endswith((".tar", ".tar.gz")):
            raise AuthorityError(f"forbidden Candidate-v7/TAR path: {entry['path']}")

    v10 = _document_at(root, V10_PREAPPROVAL, V10.PREAPPROVAL_PATH, "v10 preapproval")
    v10_after = {entry["path"]: entry["after"] for entry in v10["governedPaths"]}
    v11_after = {entry["path"]: entry["after"] for entry in document["governedPaths"]}
    if set(v11_after) != set(v10_after) | NEW_GOVERNED_PATHS:
        raise AuthorityError("v11 does not cover the complete v10 future state and verifier fix")
    changed = {path for path in v10_after if v11_after[path] != v10_after[path]}
    if changed != CORRECTED_V10_PATHS:
        raise AuthorityError("v11 differs from v10 outside the bounded verifier fix")
    _validate_issue71_history(root, document, verify_owner_comment=verify_owner_comment)
    _validate_v10_chain(root, document, verify_owner_comment=verify_owner_comment)


def validate_preapproval_commit(
    root: Path, preapproval_commit: str, *, verify_owner_comment: bool
) -> tuple[dict[str, Any], bytes]:
    _assert_ancestor(root, AUDITED_BASE, preapproval_commit)
    _assert_changed_paths(root, AUDITED_BASE, preapproval_commit, EXPECTED_AUTHORITY_PATHS, "B11-to-P11")
    if _state(root, preapproval_commit, DECISION_PATH) != {"state": "absent"}:
        raise AuthorityError("v11 owner decision must be absent at P11")
    if _state(root, preapproval_commit, RECEIPT_PATH) != {"state": "absent"}:
        raise AuthorityError("v11 receipt must be absent at P11")
    preapproval_bytes = _blob(root, preapproval_commit, PREAPPROVAL_PATH)
    preapproval = _json(preapproval_bytes, "v11 verifier preapproval")
    validate_preapproval_document(root, preapproval, verify_owner_comment=verify_owner_comment)
    return preapproval, preapproval_bytes


def expected_owner_approval_text(
    preapproval: dict[str, Any], preapproval_commit: str, preapproval_sha256: str
) -> str:
    template = preapproval["ownerApprovalTemplate"]
    placeholders = ("<PREAPPROVAL_COMMIT>", "<PREAPPROVAL_SHA256>")
    if any(template.count(placeholder) != 1 for placeholder in placeholders):
        raise AuthorityError("v11 approval placeholders are not exact")
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
    _assert_changed_paths(root, preapproval_commit, decision_commit, {DECISION_PATH}, "P11-to-D11")
    if _unique_addition(root, preapproval_commit, decision_commit, DECISION_PATH) != decision_commit:
        raise AuthorityError("D11 is not the v11 owner-decision addition commit")
    _assert_immutable(root, decision_commit, preapproval_commit)
    decision = _json(_blob(root, decision_commit, DECISION_PATH), "v11 owner decision")
    schema = _document_at(root, preapproval_commit, SCHEMA_PATH, "v11 verifier schema")
    _schema_validate(decision, schema, "v11 owner decision")
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
            raise AuthorityError(f"v11 owner decision {field} differs from P11")
    if not verify_owner_comment:
        raise AuthorityError("live v11 OWNER comment verification is required")
    observed = V10.V9.V8.V7.V6._verify_owner_comment(decision, approval)
    if decision["approvedAt"] != observed["createdAt"]:
        raise AuthorityError("v11 owner decision timestamp differs from live comment")
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
    _assert_changed_paths(root, decision_commit, applied_commit, EXPECTED_GOVERNED_PATHS, "D11-to-A11")
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
    receipt = _document_at(root, receipt_commit, RECEIPT_PATH, "v11 application receipt")
    preapproval = validate_applied_commit(
        root,
        receipt["preapprovalCommit"],
        receipt["decisionCommit"],
        receipt["appliedCommit"],
        verify_owner_comment=verify_owner_comment,
    )
    _assert_ancestor(root, receipt["appliedCommit"], receipt_commit)
    _assert_ancestor(root, receipt_commit, head_commit)
    _assert_changed_paths(root, receipt["appliedCommit"], receipt_commit, {RECEIPT_PATH}, "A11-to-R11")
    if _unique_addition(root, receipt["appliedCommit"], receipt_commit, RECEIPT_PATH) != receipt_commit:
        raise AuthorityError("R11 is not the v11 receipt addition commit")
    schema = _document_at(root, receipt["preapprovalCommit"], SCHEMA_PATH, "v11 verifier schema")
    _schema_validate(receipt, schema, "v11 application receipt")
    expected = {
        "appliedTree": _git(root, "rev-parse", f"{receipt['appliedCommit']}^{{tree}}").decode().strip(),
        "preapprovalSha256": _sha256(_blob(root, receipt["preapprovalCommit"], PREAPPROVAL_PATH)),
        "ownerDecisionSha256": _sha256(_blob(root, receipt["decisionCommit"], DECISION_PATH)),
        "governedStateSha256": _governed_state_sha256(root, receipt["appliedCommit"], preapproval),
        "safety": EXPECTED_SAFETY,
    }
    for field, value in expected.items():
        if receipt[field] != value:
            raise AuthorityError(f"v11 receipt {field} differs from P11/D11/A11")
    _assert_immutable(root, head_commit, receipt["preapprovalCommit"])
    _assert_states(root, head_commit, preapproval["governedPaths"], "after")
    if _state(root, receipt_commit, RECEIPT_PATH) != _state(root, head_commit, RECEIPT_PATH):
        raise AuthorityError("v11 receipt changed after R11")


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
        raise AuthorityError("v11 governed paths are in a partial state")
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
