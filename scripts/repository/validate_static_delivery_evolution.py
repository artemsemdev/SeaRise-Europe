"""Validate the fail-closed Issue #62 static-delivery policy evolution.

This v5 authority preserves the sealed Issue #71 and Issue #61 histories. It
can authorize only the exact repository blobs pre-bound for Issue #62; it
cannot authorize an infrastructure apply, publication, data upload, secret or
GitHub-environment mutation, or any Candidate-v7/TAR access.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DIRECTORY = "contracts/repository-removal/v5/phase-3-issue-62"
SCHEMA_PATH = "contracts/repository-removal/v5/static-delivery-evolution.schema.json"
PREAPPROVAL_PATH = f"{DIRECTORY}/preapproval.json"
DECISION_PATH = f"{DIRECTORY}/owner-decision.json"
RECEIPT_PATH = f"{DIRECTORY}/application-receipt.json"
VALIDATOR_PATH = "scripts/repository/validate_static_delivery_evolution.py"
TEST_PATH = "tests/repository-removal/test_validate_static_delivery_evolution.py"
AUDITED_BASE = "df3b54f9b2566e2550ea15a408c4900c74c70102"
ISSUE61_RECEIPT_COMMIT = "c5ae8de77cef991dd21f3b7956b2b2cb23ac2918"

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
    TEST_PATH,
    "tests/test-inventory.json",
}
GOVERNED_TRANSITIONS_SHA256 = (
    "43bdc98f3bef3014548542e0d8afa2f0859a390d4aad191021f6dfb7118f1a6d"
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
EXPECTED_ISSUE71_HISTORY = {
    "preapprovalCommit": "336647a4b9bd0709e8625136ee6b4bfad83309b7",
    "preapprovalTree": "e8dfb63fec967a5158b7fea359144c8b6a6c9da7",
    "decisionCommit": "85f51b3dc6837d878675a514e57f8e205dda9a26",
    "decisionTree": "1260deb7083e26fc1f3e660e70c5070982937967",
    "appliedCommit": "f942a07b33d89247146e54d2441421ca6dabf316",
    "appliedTree": "e8d61a187facd894d610a413c39290932d15a08c",
    "receiptCommit": "fd38eddccb5dce6405df48a8f25c045e740efdca",
    "receiptTree": "84457c6d403d4b4402e862fd84395ca470396384",
    "receiptSha256": "bb962fb569218e4a8e7cf74383ece2dc3d766963cbd502637df3e2b11428b8bf",
}
EXPECTED_ISSUE61_HISTORY = {
    "preapprovalCommit": "e49398964790c949fc9d64010d8fe7416bf90ba3",
    "preapprovalTree": "1b92605c722fb91115a4740b60700b4286c3337e",
    "preapprovalSha256": "e35c90ea571f7625413775605fcf1e241173e34204b6df682a8a7a2ae7e528de",
    "decisionCommit": "b9aab46abfd18ecad3f54394e4a5b90681c6677b",
    "decisionTree": "31db7d87ac041a741a0aa74ddd4ea99ea2ae78b3",
    "decisionSha256": "40c3d176ae09bac14fa14088e6b1344fd915e5587cc2fa7ddd49fa566964f00a",
    "appliedCommit": "236ed27ad54d02b8665fee4c803329c2c88ef5e5",
    "appliedTree": "0880765fa14e2d37caa0f77926b4b98d998dff43",
    "receiptCommit": ISSUE61_RECEIPT_COMMIT,
    "receiptTree": "dfdf259332fced98bb66331873b2c201c9d5674c",
    "receiptSha256": "d73ff10e7d1818f071b2a264704d3476b765a84572057a60eb169d7cd34d2652",
}
TRUST_ROOTS = {
    "staticDeliveryEvolutionSchema": SCHEMA_PATH,
    "staticDeliveryEvolutionValidator": VALIDATOR_PATH,
}
PRIOR_IMMUTABLE_PATHS = {
    "contracts/repository-removal/v2/issue-71/preapproval.json",
    "contracts/repository-removal/v2/issue-71/owner-decision.json",
    "contracts/repository-removal/v2/issue-71/application-receipt.json",
    "contracts/repository-removal/v4/gate-policy-correction.schema.json",
    "contracts/repository-removal/v4/phase-3-issue-61/preapproval.json",
    "contracts/repository-removal/v4/phase-3-issue-61/owner-decision.json",
    "contracts/repository-removal/v4/phase-3-issue-61/application-receipt.json",
    "scripts/repository/validate_gate_policy_correction.py",
}


def _load_v4() -> Any:
    path = ROOT / "scripts/repository/validate_gate_policy_correction.py"
    spec = importlib.util.spec_from_file_location("gate_policy_correction_v4", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("v4 authority validator cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


V4 = _load_v4()
AuthorityError = V4.AuthorityError
_sha256 = V4._sha256
_git = V4._git
_json = V4._json
_blob = V4._blob
_document_at = V4._document_at
_state = V4._state
_assert_ancestor = V4._assert_ancestor
_assert_changed_paths = V4._assert_changed_paths
_assert_states = V4._assert_states
_schema_validate = V4._schema_validate
_unique_addition = V4._unique_addition
_verify_owner_comment = V4._verify_owner_comment


def _canonical_sha256(value: Any) -> str:
    return _sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode())


def _assert_immutable(root: Path, later: str, preapproval_commit: str) -> None:
    for path in EXPECTED_AUTHORITY_PATHS:
        if _state(root, preapproval_commit, path) != _state(root, later, path):
            raise AuthorityError(f"v5 authority changed after P: {path}")
    for path in PRIOR_IMMUTABLE_PATHS:
        if _state(root, AUDITED_BASE, path) != _state(root, later, path):
            raise AuthorityError(f"prior sealed history changed: {path}")


def _validate_prior_authority(
    root: Path, document: dict[str, Any], *, verify_owner_comment: bool
) -> None:
    V4.validate_application_receipt(
        root,
        ISSUE61_RECEIPT_COMMIT,
        AUDITED_BASE,
        verify_owner_comment=verify_owner_comment,
    )
    if document["phase2Issue71History"] != EXPECTED_ISSUE71_HISTORY:
        raise AuthorityError("immutable Issue #71 P/D/A/R history differs")
    if document["phase3Issue61History"] != EXPECTED_ISSUE61_HISTORY:
        raise AuthorityError("immutable Issue #61 v4 P/D/A/R history differs")
    v4_preapproval = _document_at(
        root,
        EXPECTED_ISSUE61_HISTORY["preapprovalCommit"],
        V4.PREAPPROVAL_PATH,
        "v4 preapproval",
    )
    if v4_preapproval["phase2Issue71History"] != EXPECTED_ISSUE71_HISTORY:
        raise AuthorityError("v4 does not bind the expected Issue #71 history")


def validate_preapproval_document(
    root: Path, document: dict[str, Any], *, verify_owner_comment: bool
) -> None:
    schema = _json((root / SCHEMA_PATH).read_bytes(), "v5 schema")
    _schema_validate(document, schema, "v5 preapproval")
    if document["auditedBaseCommit"] != AUDITED_BASE:
        raise AuthorityError("audited base differs from the merged Issue #61 state")
    if set(document["authorityPaths"]) != EXPECTED_AUTHORITY_PATHS:
        raise AuthorityError("v5 authority path set differs")
    if set(document["trustRootSha256"]) != set(TRUST_ROOTS):
        raise AuthorityError("v5 trust-root names differ")
    paths = [entry["path"] for entry in document["governedPaths"]]
    if paths != sorted(paths) or set(paths) != EXPECTED_GOVERNED_PATHS:
        raise AuthorityError("v5 governed path set differs")
    if len(paths) != len(set(paths)):
        raise AuthorityError("v5 governed paths are duplicated")
    if _canonical_sha256(document["governedPaths"]) != GOVERNED_TRANSITIONS_SHA256:
        raise AuthorityError("v5 future-state hash differs from the exact frozen state")
    if document["safety"] != EXPECTED_SAFETY:
        raise AuthorityError("v5 safety boundary differs")
    if document["deferredOwnership"] != EXPECTED_DEFERRED_OWNERSHIP:
        raise AuthorityError("v5 deferred ownership boundary differs")
    for name, path in TRUST_ROOTS.items():
        if _sha256((root / path).read_bytes()) != document["trustRootSha256"][name]:
            raise AuthorityError(f"v5 trust-root hash mismatch: {name}")
    _assert_states(root, AUDITED_BASE, document["governedPaths"], "before")
    for entry in document["governedPaths"]:
        if entry["before"] == entry["after"]:
            raise AuthorityError(f"v5 transition is a no-op: {entry['path']}")
        if entry["after"]["state"] != "present":
            raise AuthorityError(f"v5 cannot authorize deletion: {entry['path']}")
        lowered = entry["path"].lower()
        if "candidate-v7" in lowered or lowered.endswith((".tar", ".tar.gz")):
            raise AuthorityError(f"forbidden Candidate-v7/TAR path: {entry['path']}")
    _validate_prior_authority(root, document, verify_owner_comment=verify_owner_comment)


def validate_preapproval_commit(
    root: Path, preapproval_commit: str, *, verify_owner_comment: bool
) -> tuple[dict[str, Any], bytes]:
    _assert_ancestor(root, AUDITED_BASE, preapproval_commit)
    _assert_changed_paths(
        root, AUDITED_BASE, preapproval_commit, EXPECTED_AUTHORITY_PATHS, "B-to-P"
    )
    if _state(root, preapproval_commit, DECISION_PATH) != {"state": "absent"}:
        raise AuthorityError("v5 owner decision must be absent at P")
    if _state(root, preapproval_commit, RECEIPT_PATH) != {"state": "absent"}:
        raise AuthorityError("v5 receipt must be absent at P")
    preapproval_bytes = _blob(root, preapproval_commit, PREAPPROVAL_PATH)
    preapproval = _json(preapproval_bytes, "v5 preapproval")
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
        raise AuthorityError("v5 owner approval placeholders are not exact")
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
        root, preapproval_commit, decision_commit, {DECISION_PATH}, "P-to-D"
    )
    if (
        _unique_addition(root, preapproval_commit, decision_commit, DECISION_PATH)
        != decision_commit
    ):
        raise AuthorityError("D is not the v5 owner-decision addition commit")
    _assert_immutable(root, decision_commit, preapproval_commit)
    decision_bytes = _blob(root, decision_commit, DECISION_PATH)
    decision = _json(decision_bytes, "v5 owner decision")
    schema = _document_at(root, preapproval_commit, SCHEMA_PATH, "v5 schema")
    _schema_validate(decision, schema, "v5 owner decision")
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
            raise AuthorityError(f"v5 owner decision {field} does not match P")
    if decision["approvalSource"]["bodySha256"] != _sha256(expected_text.encode()):
        raise AuthorityError("v5 owner decision body hash differs")
    if not verify_owner_comment:
        raise AuthorityError("live v5 OWNER comment verification is required")
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
        root,
        preapproval_commit,
        decision_commit,
        verify_owner_comment=verify_owner_comment,
    )
    _assert_ancestor(root, decision_commit, applied_commit)
    _assert_changed_paths(
        root, decision_commit, applied_commit, EXPECTED_GOVERNED_PATHS, "D-to-A"
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
    receipt = _document_at(root, receipt_commit, RECEIPT_PATH, "v5 receipt")
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
        root, applied_commit, receipt_commit, {RECEIPT_PATH}, "A-to-R"
    )
    if (
        _unique_addition(root, applied_commit, receipt_commit, RECEIPT_PATH)
        != receipt_commit
    ):
        raise AuthorityError("R is not the v5 receipt addition commit")
    schema = _document_at(root, preapproval_commit, SCHEMA_PATH, "v5 schema")
    _schema_validate(receipt, schema, "v5 receipt")
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
            raise AuthorityError(f"v5 receipt {field} differs from P/D/A")
    _assert_immutable(root, head_commit, preapproval_commit)
    _assert_states(root, head_commit, preapproval["governedPaths"], "after")
    if _state(root, receipt_commit, RECEIPT_PATH) != _state(
        root, head_commit, RECEIPT_PATH
    ):
        raise AuthorityError("v5 receipt changed after R")


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
        raise AuthorityError("v5 governed paths are in a partial state")
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
