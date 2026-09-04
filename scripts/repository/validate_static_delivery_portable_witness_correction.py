"""Validate the additive Issue #62 v12 portable-witness correction.

The v11 P/D authority remains immutable. The published but unmerged v11
application is superseded because clean CI cannot resolve two intentionally
unpushed diagnostic commits and the generic-host workflow lacks the Python
environment needed by the real built CLI. V12 rehydrates only exact,
authority-bound Git objects in a temporary alternate object store, then runs
the immutable historical validators. It never projects or bypasses history and
never authorizes apply, publication, upload, credentials, DNS, environments,
external mutation, Candidate-v7, or TAR use.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import importlib.util
import json
import os
import subprocess
import tempfile
from collections.abc import Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DIRECTORY = "contracts/repository-removal/v12/phase-3-issue-62"
SCHEMA_PATH = "contracts/repository-removal/v12/static-delivery-portable-witness-correction.schema.json"
PREAPPROVAL_PATH = f"{DIRECTORY}/preapproval.json"
DECISION_PATH = f"{DIRECTORY}/owner-decision.json"
RECEIPT_PATH = f"{DIRECTORY}/application-receipt.json"
VALIDATOR_PATH = "scripts/repository/validate_static_delivery_portable_witness_correction.py"
TEST_PATH = "tests/repository-removal/test_validate_static_delivery_portable_witness_correction.py"
WEB_HANDOFF_PATH = "src/web/scripts/check-target-content.mjs"
WEB_HANDOFF_TEST_PATH = "src/web/scripts/check-target-content.test.mjs"
SEALED_GATE_TEST_PATH = "src/web/scripts/static-repository-gates.test.mjs"

AUDITED_BASE = "9f1ca57cdaf4fb6617cdffd5fcd13fac1a359a71"
V11_PREAPPROVAL = "5042bf9e3c440a73a161719754f15ffa1ea9efd8"
V11_PREAPPROVAL_TREE = "24cd905433dba2917597551959ef3e7a76119782"
V11_PREAPPROVAL_SHA256 = (
    "14fe77925f870e8661a0f3a454e179e54a5683c7075ac6e42e47c77fce63d849"
)
V11_PREAPPROVAL_MERGE = "963ffa2aeb2ca43d54f2dd5868a0ba0a7abcb946"
V11_DECISION = "a328f607858cbfa368f308425a165906852d14f0"
V11_DECISION_TREE = "981a02b5c6507d2e7ddfb6360e171f4442c4cb3a"
V11_DECISION_SHA256 = (
    "865c38b0bc2a0992c6481997c4ff4dadb07fbad611caeebd43935ad70bb3de18"
)
V11_OWNER_COMMENT_ID = 5513566198
V11_OWNER_COMMENT_TIME = "2026-09-02T17:23:41Z"
V11_APPLICATION_ATTEMPT = "7819ded9bd96fcea7cb76b1c6b998918bd138f6f"
V11_APPLICATION_ATTEMPT_TREE = "e66c3259f3dcd5d922f9ba47f8cf55b2ecd7c4eb"
V11_APPLICATION_PR = 488
V11_GOVERNED_TRANSITIONS_SHA256 = (
    "8df420b1892a059869d86d87208488954d38cd0d7bd20d28e45c4766649b7041"
)
V11_GOVERNED_AFTER_SHA256 = (
    "3faf0bfee280c9811323c69fa21c698f5a8d579f6c70076d917b1730079d7a8a"
)
STATIC_REPOSITORY_GATES_PATH = "src/web/scripts/static-repository-gates.mjs"
STATIC_REPOSITORY_GATES_BLOB = "02e32cda7a01460c3055f61cccaf9f03fc0552f9"
STATIC_REPOSITORY_GATES_SHA256 = (
    "b97d051d616738dc12d24f9d364bd9fcda59d1a0ab41c705b7cdac1bc199637c"
)
GOVERNED_TRANSITIONS_SHA256 = (
    "a2b78fc78e93d12e045c7637e176b7abff7532b079a29b1d518898bec14137be"
)

EXPECTED_AUTHORITY_PATHS = {SCHEMA_PATH, PREAPPROVAL_PATH, VALIDATOR_PATH}
NEW_GOVERNED_PATHS = {
    ".github/workflows/static-quality.yml",
    TEST_PATH,
}
CORRECTED_V11_PATHS = {
    ".github/workflows/ci.yml",
    "contracts/supply-chain/v2/static-target-profile.json",
    WEB_HANDOFF_TEST_PATH,
    "src/web/scripts/static-repository-authority.mjs",
    "tests/harness/test_changed_components.py",
    "tests/harness/test_ci_gate.py",
    "tests/test-inventory.json",
    "tests/repository-removal/test_validate_static_delivery_owner_verifier_chain_correction.py",
    "tests/repository-removal/test_validate_static_delivery_owner_verifier_correction.py",
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


def _load_v11() -> Any:
    path = ROOT / "scripts/repository/validate_static_delivery_owner_verifier_chain_correction.py"
    spec = importlib.util.spec_from_file_location("static_delivery_verifier_chain_v11", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("v11 delivery validator cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


V11 = _load_v11()
AuthorityError = V11.AuthorityError
_sha256 = V11._sha256
_git = V11._git
_json = V11._json
_blob = V11._blob
_document_at = V11._document_at
_state = V11._state
_assert_ancestor = V11._assert_ancestor
_assert_changed_paths = V11._assert_changed_paths
_assert_states = V11._assert_states
_schema_validate = V11._schema_validate
_unique_addition = V11._unique_addition
EXPECTED_GOVERNED_PATHS = {*V11.EXPECTED_GOVERNED_PATHS, *NEW_GOVERNED_PATHS}
PRIOR_IMMUTABLE_PATHS = {
    *V11.PRIOR_IMMUTABLE_PATHS,
    *V11.EXPECTED_AUTHORITY_PATHS,
}
TRUST_ROOTS = {
    "staticDeliveryPortableWitnessSchema": SCHEMA_PATH,
    "staticDeliveryPortableWitnessValidator": VALIDATOR_PATH,
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
            raise AuthorityError(f"v12 authority changed after P12: {path}")
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


def _git_object_sha1(kind: str, payload: bytes) -> str:
    framed = f"{kind} {len(payload)}\0".encode() + payload
    return hashlib.sha1(framed).hexdigest()


@contextmanager
def portable_git_objects(document: dict[str, Any]):
    """Expose exact witnessed objects to immutable historical Git validators."""
    expected = {
        "v8-unpushed-owner-decision": (
            "f87a01af07eaa4c7d48c9b77df7f7603d8e0207d",
            "48b744b26cbe52c1a462853ce8c7f7ecb5c2489a",
            "57fe0f7fb367111d8a19001ddd6488ffdb3789a7",
            {
                "f87a01af07eaa4c7d48c9b77df7f7603d8e0207d",
                "57fe0f7fb367111d8a19001ddd6488ffdb3789a7",
                "7d92aec7b8abfae24dd5d5b78c95ca700c8b4955",
                "1c10841f00596e0728ae50cc2c8ef09fe9461102",
                "ba49e505e9bb734ee738ed77a9ced756a1938659",
                "227cf81e748cad7e0e3d9559f20fee30091b9dcb",
                "f22a6527cae58736a7c2803f416a00e11af709eb",
            },
        ),
        "v10-unpushed-owner-decision": (
            "6ed3ca54e5d2063d44950fe362dee5329ef71f71",
            "a264a3c15b6b00d79b10582d53c0082c145b4cc9",
            "8e95bc3b25e52d7f1659ab01345f1c9015c53347",
            {
                "6ed3ca54e5d2063d44950fe362dee5329ef71f71",
                "8e95bc3b25e52d7f1659ab01345f1c9015c53347",
                "1bf6efde1aed92656fa404e289264baa1364fb7f",
                "99788359a83ec3a66266c8383fb54a8e53908dd1",
                "e65eaecb64840991a801923f5bcd4cbca0280dc4",
                "4e2a74093a7cf678e8a50c55001041554d4ea228",
                "954274837a56d98de2a83d65111be98e70e5b35b",
            },
        ),
        "v11-published-application": (
            V11_APPLICATION_ATTEMPT,
            AUDITED_BASE,
            V11_APPLICATION_ATTEMPT_TREE,
            {V11_APPLICATION_ATTEMPT},
        ),
    }
    witnesses = document["portableGitWitnesses"]
    if {entry["name"] for entry in witnesses} != set(expected):
        raise AuthorityError("portable witness names differ")
    with tempfile.TemporaryDirectory(prefix="searise-v12-git-objects-") as temporary:
        object_root = Path(temporary) / "objects"
        object_root.mkdir()
        for witness in witnesses:
            commit, parent, tree, exact_oids = expected[witness["name"]]
            if (witness["commit"], witness["parent"], witness["tree"]) != (
                commit,
                parent,
                tree,
            ):
                raise AuthorityError(f"portable witness identity differs: {witness['name']}")
            observed_oids: set[str] = set()
            for entry in witness["objects"]:
                try:
                    payload = base64.b64decode(entry["base64"], validate=True)
                except (ValueError, TypeError) as error:
                    raise AuthorityError("portable witness base64 is invalid") from error
                if _git_object_sha1(entry["type"], payload) != entry["oid"]:
                    raise AuthorityError(f"portable Git object hash differs: {entry['oid']}")
                environment = {**os.environ, "GIT_OBJECT_DIRECTORY": str(object_root)}
                result = subprocess.run(
                    ["git", "hash-object", "-t", entry["type"], "-w", "--stdin"],
                    input=payload,
                    check=True,
                    capture_output=True,
                    env=environment,
                ).stdout.decode().strip()
                if result != entry["oid"]:
                    raise AuthorityError("rehydrated portable Git object differs")
                observed_oids.add(result)
            if observed_oids != exact_oids:
                raise AuthorityError(f"portable witness object set differs: {witness['name']}")
            commit_payload = next(
                base64.b64decode(entry["base64"])
                for entry in witness["objects"]
                if entry["oid"] == commit
            )
            if not commit_payload.startswith(f"tree {tree}\nparent {parent}\n".encode()):
                raise AuthorityError(f"portable commit parent/tree differs: {witness['name']}")
        previous = os.environ.get("GIT_ALTERNATE_OBJECT_DIRECTORIES")
        os.environ["GIT_ALTERNATE_OBJECT_DIRECTORIES"] = str(object_root)
        try:
            yield
        finally:
            if previous is None:
                os.environ.pop("GIT_ALTERNATE_OBJECT_DIRECTORIES", None)
            else:
                os.environ["GIT_ALTERNATE_OBJECT_DIRECTORIES"] = previous


def _expected_v11_authority(root: Path) -> dict[str, Any]:
    preapproval = _document_at(
        root, V11_PREAPPROVAL, V11.PREAPPROVAL_PATH, "v11 preapproval"
    )
    return {
        "preapprovalCommit": V11_PREAPPROVAL,
        "preapprovalTree": V11_PREAPPROVAL_TREE,
        "preapprovalSha256": V11_PREAPPROVAL_SHA256,
        "preapprovalMergeCommit": V11_PREAPPROVAL_MERGE,
        "ownerComment": {
            "id": V11_OWNER_COMMENT_ID,
            "url": (
                "https://github.com/artemsemdev/SeaRise-Europe/issues/62"
                f"#issuecomment-{V11_OWNER_COMMENT_ID}"
            ),
            "issueApiUrl": "https://api.github.com/repos/artemsemdev/SeaRise-Europe/issues/62",
            "author": "artemsemdev",
            "association": "OWNER",
            "createdAt": V11_OWNER_COMMENT_TIME,
            "updatedAt": V11_OWNER_COMMENT_TIME,
            "body": V11.expected_owner_approval_text(
                preapproval, V11_PREAPPROVAL, V11_PREAPPROVAL_SHA256
            ),
            "bodySha256": "4bb866a83da1c5cb89e19e8a364867fd773e239bf42edbb2239c36363bab7ee1",
        },
        "decisionCommit": V11_DECISION,
        "decisionTree": V11_DECISION_TREE,
        "ownerDecisionSha256": V11_DECISION_SHA256,
        "decisionMergeCommit": AUDITED_BASE,
        "status": "preapproval-and-decision-preserved",
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


def _expected_superseded_v11_application() -> dict[str, Any]:
    return {
        "commit": V11_APPLICATION_ATTEMPT,
        "tree": V11_APPLICATION_ATTEMPT_TREE,
        "parent": AUDITED_BASE,
        "pullRequest": V11_APPLICATION_PR,
        "governedTransitionsSha256": V11_GOVERNED_TRANSITIONS_SHA256,
        "governedAfterStateSha256": V11_GOVERNED_AFTER_SHA256,
        "status": "superseded-after-publication-before-integration",
        "published": True,
        "integrated": False,
        "reason": (
            "The exact v11 application was published only in draft PR #488 and "
            "is superseded before integration because clean CI cannot resolve "
            "the intentionally unpushed v8/v10 diagnostic objects and the "
            "generic-host job lacks its Python validator environment."
        ),
    }


def _validate_v11_chain(root: Path, document: dict[str, Any], *, verify_owner_comment: bool) -> None:
    v11_preapproval = _document_at(
        root, V11_PREAPPROVAL, V11.PREAPPROVAL_PATH, "v11 preapproval"
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
        "phase3Issue62V10Authority",
        "supersededV10DecisionAttempt",
    ):
        if document[field] != v11_preapproval[field]:
            raise AuthorityError(f"immutable v11 inherited history differs: {field}")
    with portable_git_objects(document):
        V11.validate_decision_commit(
            root,
            V11_PREAPPROVAL,
            V11_DECISION,
            verify_owner_comment=verify_owner_comment,
        )
        if _is_ancestor(root, V11_APPLICATION_ATTEMPT, AUDITED_BASE):
            raise AuthorityError("superseded v11 application reached integration")
    for commit in (V11_PREAPPROVAL, V11_PREAPPROVAL_MERGE, V11_DECISION):
        if not _is_ancestor(root, commit, AUDITED_BASE):
            raise AuthorityError("v11 P/D history is not integrated in the audited base")
    if document["phase3Issue62V11Authority"] != _expected_v11_authority(root):
        raise AuthorityError("preserved v11 P/D authority differs")
    if document["supersededV11ApplicationAttempt"] != _expected_superseded_v11_application():
        raise AuthorityError("superseded v11 application evidence differs")
    if _canonical_sha256(v11_preapproval["governedPaths"]) != V11_GOVERNED_TRANSITIONS_SHA256:
        raise AuthorityError("preserved v11 governed transition digest differs")
    if _governed_after_sha256(v11_preapproval) != V11_GOVERNED_AFTER_SHA256:
        raise AuthorityError("preserved v11 governed after-state digest differs")
    _assert_states(root, AUDITED_BASE, v11_preapproval["governedPaths"], "before")


def validate_preapproval_document(
    root: Path, document: dict[str, Any], *, verify_owner_comment: bool
) -> None:
    schema = _json((root / SCHEMA_PATH).read_bytes(), "v12 verifier schema")
    _schema_validate(document, schema, "v12 verifier preapproval")
    if document["auditedBaseCommit"] != AUDITED_BASE:
        raise AuthorityError("audited base differs from merged v11 decision")
    if set(document["authorityPaths"]) != EXPECTED_AUTHORITY_PATHS:
        raise AuthorityError("v12 authority path set differs")
    if set(document["trustRootSha256"]) != set(TRUST_ROOTS):
        raise AuthorityError("v12 trust-root names differ")
    paths = [entry["path"] for entry in document["governedPaths"]]
    if paths != sorted(paths) or set(paths) != EXPECTED_GOVERNED_PATHS:
        raise AuthorityError("v12 governed path set differs")
    if len(paths) != len(set(paths)):
        raise AuthorityError("v12 governed paths are duplicated")
    if _canonical_sha256(document["governedPaths"]) != GOVERNED_TRANSITIONS_SHA256:
        raise AuthorityError("v12 future-state hash differs from the exact corrected state")
    if document["safety"] != EXPECTED_SAFETY:
        raise AuthorityError("v12 safety boundary differs")
    if document["deferredOwnership"] != EXPECTED_DEFERRED_OWNERSHIP:
        raise AuthorityError("v12 deferred ownership boundary differs")
    if document["phase2Issue71History"] != V11.V10.V9.V8.V7.V6.EXPECTED_ISSUE71_HISTORY:
        raise AuthorityError("immutable Issue #71 P/D/A/R history differs")
    if document["phase3Issue61History"] != V11.V10.V9.V8.V7.V6.EXPECTED_ISSUE61_HISTORY:
        raise AuthorityError("immutable Issue #61 v4 P/D/A/R history differs")
    expected_hashes = {
        "staticDeliveryPortableWitnessSchema": _sha256((root / SCHEMA_PATH).read_bytes()),
        "staticDeliveryPortableWitnessValidator": _sha256((root / VALIDATOR_PATH).read_bytes()),
        "staticRepositoryGates": STATIC_REPOSITORY_GATES_SHA256,
    }
    if document["trustRootSha256"] != expected_hashes:
        raise AuthorityError("v12 trust-root hash differs")
    if document["trustRootSha256"]["staticRepositoryGates"] != STATIC_REPOSITORY_GATES_SHA256:
        raise AuthorityError("Issue #71 static-repository gate trust blob differs")
    _assert_states(root, AUDITED_BASE, document["governedPaths"], "before")
    for entry in document["governedPaths"]:
        if entry["before"] == entry["after"]:
            raise AuthorityError(f"v12 transition is a no-op: {entry['path']}")
        if entry["after"]["state"] != "present":
            raise AuthorityError(f"v12 cannot authorize deletion: {entry['path']}")
        lowered = entry["path"].lower()
        if "candidate-v7" in lowered or lowered.endswith((".tar", ".tar.gz")):
            raise AuthorityError(f"forbidden Candidate-v7/TAR path: {entry['path']}")

    v11 = _document_at(root, V11_PREAPPROVAL, V11.PREAPPROVAL_PATH, "v11 preapproval")
    v11_after = {entry["path"]: entry["after"] for entry in v11["governedPaths"]}
    v12_after = {entry["path"]: entry["after"] for entry in document["governedPaths"]}
    if set(v12_after) != set(v11_after) | NEW_GOVERNED_PATHS:
        raise AuthorityError("v12 does not cover the complete v11 future state and CI fix")
    changed = {path for path in v11_after if v12_after[path] != v11_after[path]}
    if changed != CORRECTED_V11_PATHS:
        raise AuthorityError("v12 differs from v11 outside the bounded portable-witness/CI fix")
    _validate_issue71_history(root, document, verify_owner_comment=verify_owner_comment)
    _validate_v11_chain(root, document, verify_owner_comment=verify_owner_comment)


def validate_preapproval_commit(
    root: Path, preapproval_commit: str, *, verify_owner_comment: bool
) -> tuple[dict[str, Any], bytes]:
    _assert_ancestor(root, AUDITED_BASE, preapproval_commit)
    _assert_changed_paths(root, AUDITED_BASE, preapproval_commit, EXPECTED_AUTHORITY_PATHS, "B12-to-P12")
    if _state(root, preapproval_commit, DECISION_PATH) != {"state": "absent"}:
        raise AuthorityError("v12 owner decision must be absent at P12")
    if _state(root, preapproval_commit, RECEIPT_PATH) != {"state": "absent"}:
        raise AuthorityError("v12 receipt must be absent at P12")
    preapproval_bytes = _blob(root, preapproval_commit, PREAPPROVAL_PATH)
    preapproval = _json(preapproval_bytes, "v12 verifier preapproval")
    validate_preapproval_document(root, preapproval, verify_owner_comment=verify_owner_comment)
    return preapproval, preapproval_bytes


def expected_owner_approval_text(
    preapproval: dict[str, Any], preapproval_commit: str, preapproval_sha256: str
) -> str:
    template = preapproval["ownerApprovalTemplate"]
    placeholders = ("<PREAPPROVAL_COMMIT>", "<PREAPPROVAL_SHA256>")
    if any(template.count(placeholder) != 1 for placeholder in placeholders):
        raise AuthorityError("v12 approval placeholders are not exact")
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
    _assert_changed_paths(root, preapproval_commit, decision_commit, {DECISION_PATH}, "P12-to-D12")
    if _unique_addition(root, preapproval_commit, decision_commit, DECISION_PATH) != decision_commit:
        raise AuthorityError("D12 is not the v12 owner-decision addition commit")
    _assert_immutable(root, decision_commit, preapproval_commit)
    decision = _json(_blob(root, decision_commit, DECISION_PATH), "v12 owner decision")
    schema = _document_at(root, preapproval_commit, SCHEMA_PATH, "v12 verifier schema")
    _schema_validate(decision, schema, "v12 owner decision")
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
            raise AuthorityError(f"v12 owner decision {field} differs from P12")
    if not verify_owner_comment:
        raise AuthorityError("live v12 OWNER comment verification is required")
    observed = V11.V10.V9.V8.V7.V6._verify_owner_comment(decision, approval)
    if decision["approvedAt"] != observed["createdAt"]:
        raise AuthorityError("v12 owner decision timestamp differs from live comment")
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
    _assert_changed_paths(root, decision_commit, applied_commit, EXPECTED_GOVERNED_PATHS, "D12-to-A12")
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
    receipt = _document_at(root, receipt_commit, RECEIPT_PATH, "v12 application receipt")
    preapproval = validate_applied_commit(
        root,
        receipt["preapprovalCommit"],
        receipt["decisionCommit"],
        receipt["appliedCommit"],
        verify_owner_comment=verify_owner_comment,
    )
    _assert_ancestor(root, receipt["appliedCommit"], receipt_commit)
    _assert_ancestor(root, receipt_commit, head_commit)
    _assert_changed_paths(root, receipt["appliedCommit"], receipt_commit, {RECEIPT_PATH}, "A12-to-R12")
    if _unique_addition(root, receipt["appliedCommit"], receipt_commit, RECEIPT_PATH) != receipt_commit:
        raise AuthorityError("R12 is not the v12 receipt addition commit")
    schema = _document_at(root, receipt["preapprovalCommit"], SCHEMA_PATH, "v12 verifier schema")
    _schema_validate(receipt, schema, "v12 application receipt")
    expected = {
        "appliedTree": _git(root, "rev-parse", f"{receipt['appliedCommit']}^{{tree}}").decode().strip(),
        "preapprovalSha256": _sha256(_blob(root, receipt["preapprovalCommit"], PREAPPROVAL_PATH)),
        "ownerDecisionSha256": _sha256(_blob(root, receipt["decisionCommit"], DECISION_PATH)),
        "governedStateSha256": _governed_state_sha256(root, receipt["appliedCommit"], preapproval),
        "safety": EXPECTED_SAFETY,
    }
    for field, value in expected.items():
        if receipt[field] != value:
            raise AuthorityError(f"v12 receipt {field} differs from P12/D12/A12")
    _assert_immutable(root, head_commit, receipt["preapprovalCommit"])
    _assert_states(root, head_commit, preapproval["governedPaths"], "after")
    if _state(root, receipt_commit, RECEIPT_PATH) != _state(root, head_commit, RECEIPT_PATH):
        raise AuthorityError("v12 receipt changed after R12")


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
        raise AuthorityError("v12 governed paths are in a partial state")
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
