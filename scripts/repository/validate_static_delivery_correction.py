"""Validate the fail-closed correction of Issue #62 delivery authority.

The approved v5 preapproval and its OWNER comment remain immutable evidence,
but v5 is superseded before decision or application because its inherited
live-comment verifier hard-codes Issue #61. This v6 authority can permit only
the exact corrected repository state after a new, exact OWNER approval.
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
DIRECTORY = "contracts/repository-removal/v6/phase-3-issue-62"
SCHEMA_PATH = "contracts/repository-removal/v6/static-delivery-correction.schema.json"
PREAPPROVAL_PATH = f"{DIRECTORY}/preapproval.json"
DECISION_PATH = f"{DIRECTORY}/owner-decision.json"
RECEIPT_PATH = f"{DIRECTORY}/application-receipt.json"
VALIDATOR_PATH = "scripts/repository/validate_static_delivery_correction.py"
TEST_PATH = "tests/repository-removal/test_validate_static_delivery_correction.py"
AUDITED_BASE = "499414227b92eead387551e8f5f78ccc9f21815d"
OLD_PREAPPROVAL = "9934d69e4025f6dd2032375bae7e92c300b66459"
OLD_PREAPPROVAL_TREE = "d0f82b22fde8ac5fe5f91cf73f6ad54e99d5a567"
OLD_PREAPPROVAL_SHA256 = (
    "99837823dc003aaa516ff9842c38dbb1ccdad3e744195765f9f165baa070410f"
)
OLD_OWNER_COMMENT_ID = 5416851308
OLD_OWNER_COMMENT_TIME = "2026-08-25T21:11:27Z"
OLD_OWNER_COMMENT_BODY_SHA256 = (
    "6281fb8316237c9bca7949e2d36710aab47c98bdbc26062e217a7715496d9016"
)
SUPERSESSION_REASON = (
    "The v5 validator aliases the Issue #61 live-comment verifier, whose exact "
    "comparison hard-codes the Issue #61 API URL. It therefore rejects the "
    "approved byte-exact Issue #62 OWNER comment. No v5 decision or governed "
    "state was committed, so v5 is superseded before decision and application."
)

EXPECTED_AUTHORITY_PATHS = {SCHEMA_PATH, PREAPPROVAL_PATH, VALIDATOR_PATH}
EXPECTED_GOVERNED_PATHS = {
    ".github/workflows/ci.yml",
    ".github/workflows/static-delivery-apply.yml",
    ".github/workflows/static-delivery-plan.yml",
    "CHANGELOG.md",
    "contracts/ci/v1/architecture-fitness.json",
    "contracts/supply-chain/v2/static-target-profile.json",
    "contracts/supply-chain/v2/static-target-profile.schema.json",
    "docs/architecture/08-deployment-topology.md",
    "docs/delivery/README.md",
    "docs/delivery/cloudflare-static-delivery.md",
    "docs/evidence/phase-3/issue-62-cloudflare-delivery.md",
    "docs/operations/static-target-supply-chain.md",
    "docs/testing/static-target-content-contract.md",
    "infra/cloudflare/.opentofu-version",
    "infra/cloudflare/.terraform.lock.hcl",
    "infra/cloudflare/backends/fixture.s3.tfbackend.example",
    "infra/cloudflare/backends/production.s3.tfbackend.example",
    "infra/cloudflare/backends/staging.s3.tfbackend.example",
    "infra/cloudflare/delivery-contract.json",
    "infra/cloudflare/environments/fixture.tfvars",
    "infra/cloudflare/environments/production.tfvars",
    "infra/cloudflare/environments/staging.tfvars",
    "infra/cloudflare/fixtures/plan/.terraform.lock.hcl",
    "infra/cloudflare/fixtures/plan/main.tf",
    "infra/cloudflare/fixtures/static-site/index.html",
    "infra/cloudflare/main.tf",
    "infra/cloudflare/outputs.tf",
    "infra/cloudflare/static-assets.headers",
    "infra/cloudflare/variables.tf",
    "infra/cloudflare/versions.tf",
    "scripts/ci/changed_components.py",
    "scripts/ci/verify_ci_gate.py",
    "scripts/infra/validate_cloudflare_delivery.py",
    "scripts/infra/verify_http_delivery.py",
    "scripts/tests/validate_test_inventory.py",
    "src/pipeline/searise_pipeline/supply_chain/static_profile.py",
    "src/pipeline/tests/supply_chain/test_static_target_profile.py",
    "tests/harness/test_changed_components.py",
    "tests/harness/test_ci_gate.py",
    "tests/infra/test_cloudflare_delivery.py",
    "tests/repository-removal/test_validate_static_delivery_evolution.py",
    TEST_PATH,
    "tests/test-inventory.json",
}
CORRECTED_OLD_PATHS = {
    ".github/workflows/ci.yml",
    "contracts/supply-chain/v2/static-target-profile.json",
    "tests/harness/test_changed_components.py",
    "tests/harness/test_ci_gate.py",
    "tests/test-inventory.json",
}
GOVERNED_TRANSITIONS_SHA256 = (
    "4cb3c86995721d29a3fb2ed5d04d35d5a94bd80f3921bbc85cecb20964f0999f"
)
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
TRUST_ROOTS = {
    "staticDeliveryCorrectionSchema": SCHEMA_PATH,
    "staticDeliveryCorrectionValidator": VALIDATOR_PATH,
}


def _load_v5() -> Any:
    path = ROOT / "scripts/repository/validate_static_delivery_evolution.py"
    spec = importlib.util.spec_from_file_location("static_delivery_evolution_v5", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("v5 delivery validator cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


V5 = _load_v5()
AuthorityError = V5.AuthorityError
_sha256 = V5._sha256
_git = V5._git
_json = V5._json
_blob = V5._blob
_document_at = V5._document_at
_state = V5._state
_assert_ancestor = V5._assert_ancestor
_assert_changed_paths = V5._assert_changed_paths
_assert_states = V5._assert_states
_schema_validate = V5._schema_validate
_unique_addition = V5._unique_addition
EXPECTED_ISSUE71_HISTORY = V5.EXPECTED_ISSUE71_HISTORY
EXPECTED_ISSUE61_HISTORY = V5.EXPECTED_ISSUE61_HISTORY
PRIOR_IMMUTABLE_PATHS = {
    *V5.PRIOR_IMMUTABLE_PATHS,
    *V5.EXPECTED_AUTHORITY_PATHS,
    V5.DECISION_PATH,
    V5.RECEIPT_PATH,
}


def _canonical_sha256(value: Any) -> str:
    return _sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode())


def _fetch_owner_comment(comment_id: int) -> dict[str, Any]:
    try:
        response = subprocess.run(
            [
                "gh",
                "api",
                "--method",
                "GET",
                f"repos/artemsemdev/SeaRise-Europe/issues/comments/{comment_id}",
            ],
            check=True,
            capture_output=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError) as error:
        raise AuthorityError(
            "live Issue #62 OWNER comment cannot be verified"
        ) from error
    comment = _json(response, "live Issue #62 OWNER comment")
    user = comment.get("user") if isinstance(comment.get("user"), dict) else {}
    return {
        "id": comment.get("id"),
        "url": comment.get("html_url"),
        "issueApiUrl": comment.get("issue_url"),
        "author": user.get("login"),
        "association": comment.get("author_association"),
        "createdAt": comment.get("created_at"),
        "updatedAt": comment.get("updated_at"),
        "body": comment.get("body"),
    }


def _verify_owner_comment(
    decision: dict[str, Any], expected_text: str
) -> dict[str, Any]:
    source = decision["approvalSource"]
    expected_source = {
        "issue": 62,
        "commentUrl": (
            "https://github.com/artemsemdev/SeaRise-Europe/issues/62"
            f"#issuecomment-{source['commentId']}"
        ),
        "author": "artemsemdev",
        "authorAssociation": "OWNER",
        "bodySha256": _sha256(expected_text.encode()),
    }
    for field, value in expected_source.items():
        if source.get(field) != value:
            raise AuthorityError(f"Issue #62 owner-decision source {field} differs")
    observed = _fetch_owner_comment(source["commentId"])
    expected = {
        "id": source["commentId"],
        "url": source["commentUrl"],
        "issueApiUrl": "https://api.github.com/repos/artemsemdev/SeaRise-Europe/issues/62",
        "author": "artemsemdev",
        "association": "OWNER",
        "body": expected_text,
    }
    for field, value in expected.items():
        if observed[field] != value:
            raise AuthorityError(f"live Issue #62 OWNER comment {field} differs")
    if observed["createdAt"] != observed["updatedAt"]:
        raise AuthorityError("live Issue #62 OWNER comment was edited")
    return observed


def _assert_immutable(root: Path, later: str, preapproval_commit: str) -> None:
    for path in EXPECTED_AUTHORITY_PATHS:
        if _state(root, preapproval_commit, path) != _state(root, later, path):
            raise AuthorityError(f"v6 authority changed after P2: {path}")
    for path in PRIOR_IMMUTABLE_PATHS:
        if _state(root, AUDITED_BASE, path) != _state(root, later, path):
            raise AuthorityError(f"prior sealed authority changed: {path}")


def _expected_old_comment(root: Path) -> tuple[dict[str, Any], str]:
    preapproval_bytes = _blob(root, OLD_PREAPPROVAL, V5.PREAPPROVAL_PATH)
    preapproval = _json(preapproval_bytes, "v5 preapproval")
    body = V5.expected_owner_approval_text(
        preapproval, OLD_PREAPPROVAL, _sha256(preapproval_bytes)
    )
    expected = {
        "id": OLD_OWNER_COMMENT_ID,
        "url": (
            "https://github.com/artemsemdev/SeaRise-Europe/issues/62"
            f"#issuecomment-{OLD_OWNER_COMMENT_ID}"
        ),
        "issueApiUrl": "https://api.github.com/repos/artemsemdev/SeaRise-Europe/issues/62",
        "author": "artemsemdev",
        "association": "OWNER",
        "createdAt": OLD_OWNER_COMMENT_TIME,
        "updatedAt": OLD_OWNER_COMMENT_TIME,
        "body": body,
        "bodySha256": _sha256(body.encode()),
    }
    return expected, body


def _validate_superseded_authority(
    root: Path, preapproval: dict[str, Any], *, verify_owner_comment: bool
) -> None:
    V5.validate_preapproval_commit(
        root, OLD_PREAPPROVAL, verify_owner_comment=verify_owner_comment
    )
    old = preapproval["supersededAuthority"]
    expected_comment, body = _expected_old_comment(root)
    expected = {
        "preapprovalCommit": OLD_PREAPPROVAL,
        "preapprovalTree": OLD_PREAPPROVAL_TREE,
        "preapprovalSha256": OLD_PREAPPROVAL_SHA256,
        "ownerComment": expected_comment,
        "status": "superseded-before-decision-and-application",
        "governedStateAuthorized": False,
        "decisionCommit": None,
        "appliedCommit": None,
        "receiptCommit": None,
        "reason": SUPERSESSION_REASON,
    }
    if old != expected:
        raise AuthorityError("superseded v5 authority evidence differs")
    if _state(root, AUDITED_BASE, V5.DECISION_PATH) != {"state": "absent"}:
        raise AuthorityError("v5 decision exists despite before-decision supersession")
    if _state(root, AUDITED_BASE, V5.RECEIPT_PATH) != {"state": "absent"}:
        raise AuthorityError(
            "v5 receipt exists despite before-application supersession"
        )
    v5 = _document_at(root, OLD_PREAPPROVAL, V5.PREAPPROVAL_PATH, "v5 preapproval")
    _assert_states(root, AUDITED_BASE, v5["governedPaths"], "before")
    if not verify_owner_comment:
        raise AuthorityError(
            "live superseded v5 OWNER comment verification is required"
        )
    observed = _fetch_owner_comment(OLD_OWNER_COMMENT_ID)
    if observed != {
        key: value for key, value in expected_comment.items() if key != "bodySha256"
    }:
        raise AuthorityError("live superseded v5 OWNER comment differs")
    if _sha256(body.encode()) != OLD_OWNER_COMMENT_BODY_SHA256:
        raise AuthorityError("superseded v5 OWNER body hash differs")


def validate_preapproval_document(
    root: Path, document: dict[str, Any], *, verify_owner_comment: bool
) -> None:
    schema = _json((root / SCHEMA_PATH).read_bytes(), "v6 correction schema")
    _schema_validate(document, schema, "v6 correction preapproval")
    if document["auditedBaseCommit"] != AUDITED_BASE:
        raise AuthorityError("audited base differs from merged v5 P authority")
    if set(document["authorityPaths"]) != EXPECTED_AUTHORITY_PATHS:
        raise AuthorityError("v6 correction authority path set differs")
    if set(document["trustRootSha256"]) != set(TRUST_ROOTS):
        raise AuthorityError("v6 correction trust-root names differ")
    paths = [entry["path"] for entry in document["governedPaths"]]
    if paths != sorted(paths) or set(paths) != EXPECTED_GOVERNED_PATHS:
        raise AuthorityError("v6 corrected governed path set differs")
    if len(paths) != len(set(paths)):
        raise AuthorityError("v6 corrected governed paths are duplicated")
    if _canonical_sha256(document["governedPaths"]) != GOVERNED_TRANSITIONS_SHA256:
        raise AuthorityError(
            "v6 future-state hash differs from the exact corrected state"
        )
    if document["safety"] != EXPECTED_SAFETY:
        raise AuthorityError("v6 correction safety boundary differs")
    if document["deferredOwnership"] != EXPECTED_DEFERRED_OWNERSHIP:
        raise AuthorityError("v6 correction deferred ownership boundary differs")
    if document["phase2Issue71History"] != EXPECTED_ISSUE71_HISTORY:
        raise AuthorityError("immutable Issue #71 P/D/A/R history differs")
    if document["phase3Issue61History"] != EXPECTED_ISSUE61_HISTORY:
        raise AuthorityError("immutable Issue #61 v4 P/D/A/R history differs")
    for name, path in TRUST_ROOTS.items():
        if _sha256((root / path).read_bytes()) != document["trustRootSha256"][name]:
            raise AuthorityError(f"v6 correction trust-root hash mismatch: {name}")
    _assert_states(root, AUDITED_BASE, document["governedPaths"], "before")
    for entry in document["governedPaths"]:
        if entry["before"] == entry["after"]:
            raise AuthorityError(f"v6 corrected transition is a no-op: {entry['path']}")
        if entry["after"]["state"] != "present":
            raise AuthorityError(f"v6 cannot authorize deletion: {entry['path']}")
        lowered = entry["path"].lower()
        if "candidate-v7" in lowered or lowered.endswith((".tar", ".tar.gz")):
            raise AuthorityError(f"forbidden Candidate-v7/TAR path: {entry['path']}")

    old_document = _document_at(
        root, OLD_PREAPPROVAL, V5.PREAPPROVAL_PATH, "v5 preapproval"
    )
    old_after = {
        entry["path"]: entry["after"] for entry in old_document["governedPaths"]
    }
    corrected_after = {
        entry["path"]: entry["after"] for entry in document["governedPaths"]
    }
    if set(corrected_after) != set(old_after) | {TEST_PATH}:
        raise AuthorityError(
            "v6 correction does not cover the complete v5 future state"
        )
    changed = {path for path in old_after if corrected_after[path] != old_after[path]}
    if changed != CORRECTED_OLD_PATHS:
        raise AuthorityError("v6 correction differs outside the bounded fix set")
    if corrected_after[TEST_PATH]["state"] != "present":
        raise AuthorityError("v6 correction validator test is not pre-bound")
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
        raise AuthorityError("v6 owner decision must be absent at P2")
    if _state(root, preapproval_commit, RECEIPT_PATH) != {"state": "absent"}:
        raise AuthorityError("v6 receipt must be absent at P2")
    preapproval_bytes = _blob(root, preapproval_commit, PREAPPROVAL_PATH)
    preapproval = _json(preapproval_bytes, "v6 correction preapproval")
    validate_preapproval_document(
        root, preapproval, verify_owner_comment=verify_owner_comment
    )
    return preapproval, preapproval_bytes


def expected_owner_approval_text(
    preapproval: dict[str, Any], preapproval_commit: str, preapproval_sha256: str
) -> str:
    template = preapproval["ownerApprovalTemplate"]
    placeholders = ("<PREAPPROVAL_COMMIT>", "<PREAPPROVAL_SHA256>")
    if any(template.count(placeholder) != 1 for placeholder in placeholders):
        raise AuthorityError("v6 correction approval placeholders are not exact")
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
    if (
        _unique_addition(root, preapproval_commit, decision_commit, DECISION_PATH)
        != decision_commit
    ):
        raise AuthorityError("D2 is not the v6 owner-decision addition commit")
    _assert_immutable(root, decision_commit, preapproval_commit)
    decision_bytes = _blob(root, decision_commit, DECISION_PATH)
    decision = _json(decision_bytes, "v6 correction owner decision")
    schema = _document_at(root, preapproval_commit, SCHEMA_PATH, "v6 correction schema")
    _schema_validate(decision, schema, "v6 correction owner decision")
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
            raise AuthorityError(f"v6 owner decision {field} does not match P2")
    if not verify_owner_comment:
        raise AuthorityError("live v6 OWNER comment verification is required")
    observed = _verify_owner_comment(decision, expected_text)
    if decision["approvedAt"] != observed["createdAt"]:
        raise AuthorityError("v6 owner decision timestamp differs from live comment")
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
        root,
        preapproval_commit,
        decision_commit,
        verify_owner_comment=verify_owner_comment,
    )
    _assert_ancestor(root, decision_commit, applied_commit)
    _assert_changed_paths(
        root, decision_commit, applied_commit, EXPECTED_GOVERNED_PATHS, "D2-to-A2"
    )
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
    root: Path,
    receipt_commit: str,
    head_commit: str,
    *,
    verify_owner_comment: bool,
) -> None:
    receipt = _document_at(root, receipt_commit, RECEIPT_PATH, "v6 correction receipt")
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
    if (
        _unique_addition(root, applied_commit, receipt_commit, RECEIPT_PATH)
        != receipt_commit
    ):
        raise AuthorityError("R2 is not the v6 correction receipt addition commit")
    schema = _document_at(root, preapproval_commit, SCHEMA_PATH, "v6 correction schema")
    _schema_validate(receipt, schema, "v6 correction receipt")
    expected = {
        "appliedTree": _git(root, "rev-parse", f"{applied_commit}^{{tree}}")
        .decode()
        .strip(),
        "preapprovalSha256": _sha256(_blob(root, preapproval_commit, PREAPPROVAL_PATH)),
        "ownerDecisionSha256": _sha256(_blob(root, decision_commit, DECISION_PATH)),
        "governedStateSha256": _governed_state_sha256(
            root, applied_commit, preapproval
        ),
        "safety": EXPECTED_SAFETY,
    }
    for field, value in expected.items():
        if receipt[field] != value:
            raise AuthorityError(f"v6 correction receipt {field} differs from P2/D2/A2")
    _assert_immutable(root, head_commit, preapproval_commit)
    _assert_states(root, head_commit, preapproval["governedPaths"], "after")
    if _state(root, receipt_commit, RECEIPT_PATH) != _state(
        root, head_commit, RECEIPT_PATH
    ):
        raise AuthorityError("v6 correction receipt changed after R2")


def validate_ci_state(
    root: Path, head_commit: str, *, verify_owner_comment: bool
) -> None:
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
            root, receipt_commit, head_commit, verify_owner_comment=verify_owner_comment
        )
        return
    preapproval, _ = validate_decision_commit(
        root,
        preapproval_commit,
        decision_commit,
        verify_owner_comment=verify_owner_comment,
    )
    states = [
        _state(root, head_commit, entry["path"])
        for entry in preapproval["governedPaths"]
    ]
    before = [entry["before"] for entry in preapproval["governedPaths"]]
    after = [entry["after"] for entry in preapproval["governedPaths"]]
    if states == before:
        return
    if states != after:
        raise AuthorityError("v6 governed paths are in a partial state")
    validate_applied_commit(
        root,
        preapproval_commit,
        decision_commit,
        head_commit,
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
                root,
                arguments.preapproval_commit,
                verify_owner_comment=arguments.verify_owner_comment,
            )
        else:
            validate_ci_state(
                root,
                arguments.head_commit,
                verify_owner_comment=arguments.verify_owner_comment,
            )
    except AuthorityError as error:
        print(f"ERROR: {error}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
