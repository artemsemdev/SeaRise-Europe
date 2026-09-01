"""Validate the additive Issue #62 v9 static-delivery OWNER-verifier handoff.

The v8 preapproval remains immutable authority. Its exact OWNER decision was
committed only in an unpushed diagnostic branch and is superseded before
publication or integration because the v8 validator calls a symbol the v7
module does not expose. A v9 decision may authorize only the exact corrected
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
DIRECTORY = "contracts/repository-removal/v9/phase-3-issue-62"
SCHEMA_PATH = "contracts/repository-removal/v9/static-delivery-owner-verifier-correction.schema.json"
PREAPPROVAL_PATH = f"{DIRECTORY}/preapproval.json"
DECISION_PATH = f"{DIRECTORY}/owner-decision.json"
RECEIPT_PATH = f"{DIRECTORY}/application-receipt.json"
VALIDATOR_PATH = "scripts/repository/validate_static_delivery_owner_verifier_correction.py"
TEST_PATH = "tests/repository-removal/test_validate_static_delivery_owner_verifier_correction.py"
WEB_HANDOFF_PATH = "src/web/scripts/check-target-content.mjs"
WEB_HANDOFF_TEST_PATH = "src/web/scripts/check-target-content.test.mjs"
SEALED_GATE_TEST_PATH = "src/web/scripts/static-repository-gates.test.mjs"

AUDITED_BASE = "48b744b26cbe52c1a462853ce8c7f7ecb5c2489a"
V8_PREAPPROVAL = "4d0c8191c53816592223476e2f969b707d9db35a"
V8_PREAPPROVAL_TREE = "260038379eb411081251ec95a053287e36594273"
V8_PREAPPROVAL_SHA256 = (
    "fa2b7087225b93ca49044467f07d46618f90287bded7442acfa7ed4afc702a94"
)
V8_PREAPPROVAL_MERGE = AUDITED_BASE
V8_DECISION_ATTEMPT = "f87a01af07eaa4c7d48c9b77df7f7603d8e0207d"
V8_DECISION_ATTEMPT_TREE = "57fe0f7fb367111d8a19001ddd6488ffdb3789a7"
V8_DECISION_ATTEMPT_SHA256 = (
    "233c2913bfdee6516b9bec984d1844636ac2b06b5653406a297a864a1442bac9"
)
V8_OWNER_COMMENT_ID = 5494452061
V8_OWNER_COMMENT_TIME = "2026-09-01T13:10:23Z"
STATIC_REPOSITORY_GATES_PATH = "src/web/scripts/static-repository-gates.mjs"
STATIC_REPOSITORY_GATES_BLOB = "02e32cda7a01460c3055f61cccaf9f03fc0552f9"
STATIC_REPOSITORY_GATES_SHA256 = (
    "b97d051d616738dc12d24f9d364bd9fcda59d1a0ab41c705b7cdac1bc199637c"
)
V8_GOVERNED_TRANSITIONS_SHA256 = (
    "cd4ed890afad960c6f6b3e71b80724c8163fc0f6b8950a6aeb4398edbc05addf"
)
GOVERNED_TRANSITIONS_SHA256 = (
    "e2aecd26242e91e02f724a240cbc1687c620c8b115ce3af77b0966c57d25ea7c"
)

EXPECTED_AUTHORITY_PATHS = {SCHEMA_PATH, PREAPPROVAL_PATH, VALIDATOR_PATH}
NEW_GOVERNED_PATHS = {
    TEST_PATH,
}
CORRECTED_V8_PATHS = {
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


def _load_v8() -> Any:
    path = ROOT / "scripts/repository/validate_static_delivery_trust_handoff_correction.py"
    spec = importlib.util.spec_from_file_location("static_delivery_trust_handoff_v8", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("v8 delivery validator cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


V8 = _load_v8()
AuthorityError = V8.AuthorityError
_sha256 = V8._sha256
_git = V8._git
_json = V8._json
_blob = V8._blob
_document_at = V8._document_at
_state = V8._state
_assert_ancestor = V8._assert_ancestor
_assert_changed_paths = V8._assert_changed_paths
_assert_states = V8._assert_states
_schema_validate = V8._schema_validate
_unique_addition = V8._unique_addition
EXPECTED_GOVERNED_PATHS = {*V8.EXPECTED_GOVERNED_PATHS, *NEW_GOVERNED_PATHS}
PRIOR_IMMUTABLE_PATHS = {
    *V8.PRIOR_IMMUTABLE_PATHS,
    *V8.EXPECTED_AUTHORITY_PATHS,
}
TRUST_ROOTS = {
    "staticDeliveryOwnerVerifierSchema": SCHEMA_PATH,
    "staticDeliveryOwnerVerifierValidator": VALIDATOR_PATH,
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


def _expected_v8_authority(root: Path) -> dict[str, Any]:
    preapproval = _document_at(
        root, V8_PREAPPROVAL, V8.PREAPPROVAL_PATH, "v8 preapproval"
    )
    return {
        "preapprovalCommit": V8_PREAPPROVAL,
        "preapprovalTree": V8_PREAPPROVAL_TREE,
        "preapprovalSha256": V8_PREAPPROVAL_SHA256,
        "preapprovalMergeCommit": V8_PREAPPROVAL_MERGE,
        "ownerComment": {
            "id": V8_OWNER_COMMENT_ID,
            "url": (
                "https://github.com/artemsemdev/SeaRise-Europe/issues/62"
                f"#issuecomment-{V8_OWNER_COMMENT_ID}"
            ),
            "issueApiUrl": "https://api.github.com/repos/artemsemdev/SeaRise-Europe/issues/62",
            "author": "artemsemdev",
            "association": "OWNER",
            "createdAt": V8_OWNER_COMMENT_TIME,
            "updatedAt": V8_OWNER_COMMENT_TIME,
            "body": V8.expected_owner_approval_text(
                preapproval, V8_PREAPPROVAL, V8_PREAPPROVAL_SHA256
            ),
            "bodySha256": "7a6ac23e73a895899eae50d4dff85e944f55350effe39afd377bd02f58d2cebd",
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


def _expected_superseded_v8_decision_attempt(root: Path) -> dict[str, Any]:
    decision = _document_at(
        root, V8_DECISION_ATTEMPT, V8.DECISION_PATH, "v8 decision attempt"
    )
    _assert_changed_paths(
        root,
        AUDITED_BASE,
        V8_DECISION_ATTEMPT,
        {V8.DECISION_PATH},
        "B9-to-superseded-D8",
    )
    if _unique_addition(
        root, AUDITED_BASE, V8_DECISION_ATTEMPT, V8.DECISION_PATH
    ) != V8_DECISION_ATTEMPT:
        raise AuthorityError("superseded D8 is not one exact decision addition")
    v8_schema = _document_at(
        root, V8_PREAPPROVAL, V8.SCHEMA_PATH, "v8 trust-handoff schema"
    )
    _schema_validate(decision, v8_schema, "superseded v8 owner decision")
    return {
        "commit": V8_DECISION_ATTEMPT,
        "tree": V8_DECISION_ATTEMPT_TREE,
        "ownerDecisionSha256": V8_DECISION_ATTEMPT_SHA256,
        "pullRequest": None,
        "status": "superseded-before-publication-and-integration",
        "published": False,
        "integrated": False,
        "approvalSource": decision["approvalSource"],
        "reason": (
            "The exact v8 owner-decision JSON was committed only on a local, "
            "unpushed diagnostic branch. Live D validation proved that the v8 "
            "validator calls V7._verify_owner_comment, a symbol the v7 module "
            "does not expose. The attempt is superseded before publication or "
            "integration and authorizes no applied governed repository state."
        ),
    }


def _validate_v8_chain(root: Path, document: dict[str, Any], *, verify_owner_comment: bool) -> None:
    v8_preapproval = _document_at(
        root, V8_PREAPPROVAL, V8.PREAPPROVAL_PATH, "v8 preapproval"
    )
    for field in (
        "phase2Issue71History",
        "phase3Issue61History",
        "phase3Issue62V5SupersededAuthority",
        "phase3Issue62V6Authority",
        "supersededV6Application",
        "phase3Issue62V7Authority",
        "supersededV7ProposedApplication",
    ):
        if document[field] != v8_preapproval[field]:
            raise AuthorityError(f"immutable v8 inherited history differs: {field}")
    V8.validate_preapproval_commit(
        root, V8_PREAPPROVAL, verify_owner_comment=verify_owner_comment
    )
    if not _is_ancestor(root, V8_PREAPPROVAL, AUDITED_BASE):
        raise AuthorityError("v8 preapproval is not integrated in the audited base")
    if _git(root, "rev-parse", f"{V8_PREAPPROVAL_MERGE}^{{tree}}").decode().strip() != (
        _git(root, "rev-parse", f"{AUDITED_BASE}^{{tree}}").decode().strip()
    ):
        raise AuthorityError("v8 preapproval merge differs from audited base")
    if _is_ancestor(root, V8_DECISION_ATTEMPT, AUDITED_BASE):
        raise AuthorityError("superseded v8 decision attempt reached integration")
    decision = _document_at(
        root, V8_DECISION_ATTEMPT, V8.DECISION_PATH, "v8 decision attempt"
    )
    approval = V8.expected_owner_approval_text(
        v8_preapproval, V8_PREAPPROVAL, V8_PREAPPROVAL_SHA256
    )
    if decision["approvalText"] != approval:
        raise AuthorityError("superseded v8 decision approval text differs")
    if not verify_owner_comment:
        raise AuthorityError("live v8 OWNER comment verification is required")
    observed = V8.V7.V6._verify_owner_comment(decision, approval)
    if decision["approvedAt"] != observed["createdAt"]:
        raise AuthorityError("v8 decision attempt timestamp differs from live comment")
    if document["phase3Issue62V8Authority"] != _expected_v8_authority(root):
        raise AuthorityError("preserved v8 preapproval authority differs")
    expected_attempt = _expected_superseded_v8_decision_attempt(root)
    if document["supersededV8DecisionAttempt"] != expected_attempt:
        raise AuthorityError("superseded v8 decision attempt evidence differs")
    _assert_states(root, AUDITED_BASE, v8_preapproval["governedPaths"], "before")


def validate_preapproval_document(
    root: Path, document: dict[str, Any], *, verify_owner_comment: bool
) -> None:
    schema = _json((root / SCHEMA_PATH).read_bytes(), "v9 verifier schema")
    _schema_validate(document, schema, "v9 verifier preapproval")
    if document["auditedBaseCommit"] != AUDITED_BASE:
        raise AuthorityError("audited base differs from merged v8 preapproval")
    if set(document["authorityPaths"]) != EXPECTED_AUTHORITY_PATHS:
        raise AuthorityError("v9 authority path set differs")
    if set(document["trustRootSha256"]) != set(TRUST_ROOTS):
        raise AuthorityError("v9 trust-root names differ")
    paths = [entry["path"] for entry in document["governedPaths"]]
    if paths != sorted(paths) or set(paths) != EXPECTED_GOVERNED_PATHS:
        raise AuthorityError("v9 governed path set differs")
    if len(paths) != len(set(paths)):
        raise AuthorityError("v9 governed paths are duplicated")
    if _canonical_sha256(document["governedPaths"]) != GOVERNED_TRANSITIONS_SHA256:
        raise AuthorityError("v9 future-state hash differs from the exact corrected state")
    if document["safety"] != EXPECTED_SAFETY:
        raise AuthorityError("v9 safety boundary differs")
    if document["deferredOwnership"] != EXPECTED_DEFERRED_OWNERSHIP:
        raise AuthorityError("v9 deferred ownership boundary differs")
    if document["phase2Issue71History"] != V8.V7.V6.EXPECTED_ISSUE71_HISTORY:
        raise AuthorityError("immutable Issue #71 P/D/A/R history differs")
    if document["phase3Issue61History"] != V8.V7.V6.EXPECTED_ISSUE61_HISTORY:
        raise AuthorityError("immutable Issue #61 v4 P/D/A/R history differs")
    expected_hashes = {
        "staticDeliveryOwnerVerifierSchema": _sha256((root / SCHEMA_PATH).read_bytes()),
        "staticDeliveryOwnerVerifierValidator": _sha256((root / VALIDATOR_PATH).read_bytes()),
        "staticRepositoryGates": STATIC_REPOSITORY_GATES_SHA256,
    }
    if document["trustRootSha256"] != expected_hashes:
        raise AuthorityError("v9 trust-root hash differs")
    if document["trustRootSha256"]["staticRepositoryGates"] != STATIC_REPOSITORY_GATES_SHA256:
        raise AuthorityError("Issue #71 static-repository gate trust blob differs")
    _assert_states(root, AUDITED_BASE, document["governedPaths"], "before")
    for entry in document["governedPaths"]:
        if entry["before"] == entry["after"]:
            raise AuthorityError(f"v9 transition is a no-op: {entry['path']}")
        if entry["after"]["state"] != "present":
            raise AuthorityError(f"v9 cannot authorize deletion: {entry['path']}")
        lowered = entry["path"].lower()
        if "candidate-v7" in lowered or lowered.endswith((".tar", ".tar.gz")):
            raise AuthorityError(f"forbidden Candidate-v7/TAR path: {entry['path']}")

    v8 = _document_at(root, V8_PREAPPROVAL, V8.PREAPPROVAL_PATH, "v8 preapproval")
    v8_after = {entry["path"]: entry["after"] for entry in v8["governedPaths"]}
    v9_after = {entry["path"]: entry["after"] for entry in document["governedPaths"]}
    if set(v9_after) != set(v8_after) | NEW_GOVERNED_PATHS:
        raise AuthorityError("v9 does not cover the complete v8 future state and verifier fix")
    changed = {path for path in v8_after if v9_after[path] != v8_after[path]}
    if changed != CORRECTED_V8_PATHS:
        raise AuthorityError("v9 differs from v8 outside the bounded verifier fix")
    _validate_issue71_history(root, document, verify_owner_comment=verify_owner_comment)
    _validate_v8_chain(root, document, verify_owner_comment=verify_owner_comment)


def validate_preapproval_commit(
    root: Path, preapproval_commit: str, *, verify_owner_comment: bool
) -> tuple[dict[str, Any], bytes]:
    _assert_ancestor(root, AUDITED_BASE, preapproval_commit)
    _assert_changed_paths(root, AUDITED_BASE, preapproval_commit, EXPECTED_AUTHORITY_PATHS, "B9-to-P9")
    if _state(root, preapproval_commit, DECISION_PATH) != {"state": "absent"}:
        raise AuthorityError("v9 owner decision must be absent at P9")
    if _state(root, preapproval_commit, RECEIPT_PATH) != {"state": "absent"}:
        raise AuthorityError("v9 receipt must be absent at P9")
    preapproval_bytes = _blob(root, preapproval_commit, PREAPPROVAL_PATH)
    preapproval = _json(preapproval_bytes, "v9 verifier preapproval")
    validate_preapproval_document(root, preapproval, verify_owner_comment=verify_owner_comment)
    return preapproval, preapproval_bytes


def expected_owner_approval_text(
    preapproval: dict[str, Any], preapproval_commit: str, preapproval_sha256: str
) -> str:
    template = preapproval["ownerApprovalTemplate"]
    placeholders = ("<PREAPPROVAL_COMMIT>", "<PREAPPROVAL_SHA256>")
    if any(template.count(placeholder) != 1 for placeholder in placeholders):
        raise AuthorityError("v9 approval placeholders are not exact")
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
    _assert_changed_paths(root, preapproval_commit, decision_commit, {DECISION_PATH}, "P9-to-D9")
    if _unique_addition(root, preapproval_commit, decision_commit, DECISION_PATH) != decision_commit:
        raise AuthorityError("D9 is not the v9 owner-decision addition commit")
    _assert_immutable(root, decision_commit, preapproval_commit)
    decision = _json(_blob(root, decision_commit, DECISION_PATH), "v9 owner decision")
    schema = _document_at(root, preapproval_commit, SCHEMA_PATH, "v9 verifier schema")
    _schema_validate(decision, schema, "v9 owner decision")
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
            raise AuthorityError(f"v9 owner decision {field} differs from P9")
    if not verify_owner_comment:
        raise AuthorityError("live v9 OWNER comment verification is required")
    observed = V8.V7.V6._verify_owner_comment(decision, approval)
    if decision["approvedAt"] != observed["createdAt"]:
        raise AuthorityError("v9 owner decision timestamp differs from live comment")
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
    _assert_changed_paths(root, decision_commit, applied_commit, EXPECTED_GOVERNED_PATHS, "D9-to-A9")
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
    receipt = _document_at(root, receipt_commit, RECEIPT_PATH, "v9 application receipt")
    preapproval = validate_applied_commit(
        root,
        receipt["preapprovalCommit"],
        receipt["decisionCommit"],
        receipt["appliedCommit"],
        verify_owner_comment=verify_owner_comment,
    )
    _assert_ancestor(root, receipt["appliedCommit"], receipt_commit)
    _assert_ancestor(root, receipt_commit, head_commit)
    _assert_changed_paths(root, receipt["appliedCommit"], receipt_commit, {RECEIPT_PATH}, "A9-to-R9")
    if _unique_addition(root, receipt["appliedCommit"], receipt_commit, RECEIPT_PATH) != receipt_commit:
        raise AuthorityError("R9 is not the v9 receipt addition commit")
    schema = _document_at(root, receipt["preapprovalCommit"], SCHEMA_PATH, "v9 verifier schema")
    _schema_validate(receipt, schema, "v9 application receipt")
    expected = {
        "appliedTree": _git(root, "rev-parse", f"{receipt['appliedCommit']}^{{tree}}").decode().strip(),
        "preapprovalSha256": _sha256(_blob(root, receipt["preapprovalCommit"], PREAPPROVAL_PATH)),
        "ownerDecisionSha256": _sha256(_blob(root, receipt["decisionCommit"], DECISION_PATH)),
        "governedStateSha256": _governed_state_sha256(root, receipt["appliedCommit"], preapproval),
        "safety": EXPECTED_SAFETY,
    }
    for field, value in expected.items():
        if receipt[field] != value:
            raise AuthorityError(f"v9 receipt {field} differs from P9/D9/A9")
    _assert_immutable(root, head_commit, receipt["preapprovalCommit"])
    _assert_states(root, head_commit, preapproval["governedPaths"], "after")
    if _state(root, receipt_commit, RECEIPT_PATH) != _state(root, head_commit, RECEIPT_PATH):
        raise AuthorityError("v9 receipt changed after R9")


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
        raise AuthorityError("v9 governed paths are in a partial state")
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
