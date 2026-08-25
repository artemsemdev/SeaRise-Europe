"""Validate the additive Phase 3 gate-policy authority lifecycle.

Issue #71 remains immutable historical evidence. This continuation replays that
P/D/A/R history at its receipt commit, then permits only owner-approved exact
blob transitions for the enumerated Phase 3 gate-policy paths.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any, Sequence


ROOT = Path(__file__).resolve().parents[2]
DIRECTORY = "contracts/repository-removal/v3/phase-3-issue-61"
SCHEMA_PATH = "contracts/repository-removal/v3/gate-policy-evolution.schema.json"
PREAPPROVAL_PATH = f"{DIRECTORY}/preapproval.json"
DECISION_PATH = f"{DIRECTORY}/owner-decision.json"
RECEIPT_PATH = f"{DIRECTORY}/application-receipt.json"
VALIDATOR_PATH = "scripts/repository/validate_gate_policy_evolution.py"
TEST_PATH = "tests/repository-removal/test_validate_gate_policy_evolution.py"

EXPECTED_AUTHORITY_PATHS = {
    "CHANGELOG.md",
    "contracts/repository-removal/README.md",
    SCHEMA_PATH,
    PREAPPROVAL_PATH,
    VALIDATOR_PATH,
}
IMMUTABLE_AUTHORITY_PATHS = {SCHEMA_PATH, PREAPPROVAL_PATH, VALIDATOR_PATH}
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
    TEST_PATH,
    "tests/test-inventory.json",
}
EXPECTED_SAFETY = {
    "candidateV7BytesUsed": False,
    "tarBytesUsed": False,
    "publicationAuthorized": False,
    "externalResourceMutationAuthorized": False,
}
EXPECTED_HISTORY = {
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
TRUST_ROOTS = {
    "gatePolicySchema": SCHEMA_PATH,
    "gatePolicyValidator": VALIDATOR_PATH,
}


class AuthorityError(RuntimeError):
    """The owner-bound continuation authority is incomplete or inconsistent."""


def _git(root: Path, *arguments: str) -> bytes:
    try:
        return subprocess.run(
            ["git", *arguments], cwd=root, check=True, capture_output=True
        ).stdout
    except (OSError, subprocess.CalledProcessError) as error:
        raise AuthorityError(f"git {' '.join(arguments)} failed") from error


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _json(content: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise AuthorityError(f"invalid {label}: {error}") from error
    if not isinstance(value, dict):
        raise AuthorityError(f"{label} must be an object")
    return value


def _blob(root: Path, commit: str, path: str) -> bytes:
    return _git(root, "show", f"{commit}:{path}")


def _state(root: Path, commit: str, path: str) -> dict[str, str]:
    output = _git(root, "ls-tree", "-z", commit, "--", path)
    if not output:
        return {"state": "absent"}
    metadata, observed_path = output[:-1].split(b"\t", 1)
    mode, object_type, object_id = metadata.decode().split()
    if observed_path.decode() != path or object_type != "blob":
        raise AuthorityError(f"authority path is not one exact blob: {path}")
    content = _git(root, "cat-file", "blob", object_id)
    return {
        "state": "present",
        "mode": mode,
        "gitBlobSha": object_id,
        "sha256": _sha256(content),
    }


def _changed_paths(root: Path, before: str, after: str) -> set[str]:
    return {
        item.decode()
        for item in _git(root, "diff", "--name-only", "-z", before, after).split(b"\0")
        if item
    }


def _assert_changed_paths(
    root: Path, before: str, after: str, expected: set[str], label: str
) -> None:
    observed = _changed_paths(root, before, after)
    if observed != expected:
        raise AuthorityError(
            f"{label} changed paths differ; extra={sorted(observed - expected)}, "
            f"missing={sorted(expected - observed)}"
        )


def _schema_validate(document: dict[str, Any], schema: dict[str, Any], label: str) -> None:
    try:
        import jsonschema

        jsonschema.Draft202012Validator.check_schema(schema)
        jsonschema.Draft202012Validator(schema).validate(document)
    except Exception as error:
        raise AuthorityError(f"{label} schema validation failed: {error}") from error


def _document_at(root: Path, commit: str, path: str, label: str) -> dict[str, Any]:
    return _json(_blob(root, commit, path), label)


def _assert_ancestor(root: Path, earlier: str, later: str) -> None:
    try:
        subprocess.run(
            ["git", "merge-base", "--is-ancestor", earlier, later],
            cwd=root,
            check=True,
            capture_output=True,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        raise AuthorityError(f"{earlier} is not an ancestor of {later}") from error


def _assert_states(
    root: Path, commit: str, entries: Sequence[dict[str, Any]], field: str
) -> None:
    for entry in entries:
        if _state(root, commit, entry["path"]) != entry[field]:
            raise AuthorityError(f"{field} state mismatch: {entry['path']}")


def validate_preapproval_document(root: Path, document: dict[str, Any]) -> None:
    schema = _json((root / SCHEMA_PATH).read_bytes(), "gate-policy schema")
    _schema_validate(document, schema, "gate-policy preapproval")
    if document["auditedBaseCommit"] != "4df5bfdeaaa66b68222519276fb72c912e457f97":
        raise AuthorityError("audited base differs from integration authority")
    if document["phase2Issue71History"] != EXPECTED_HISTORY:
        raise AuthorityError("issue #71 P/D/A/R anchors differ")
    if set(document["authorityPaths"]) != EXPECTED_AUTHORITY_PATHS:
        raise AuthorityError("preapproval authority path set differs")
    if set(document["trustRootSha256"]) != set(TRUST_ROOTS):
        raise AuthorityError("preapproval trust-root names differ")
    paths = [entry["path"] for entry in document["governedPaths"]]
    if len(paths) != len(set(paths)) or set(paths) != EXPECTED_GOVERNED_PATHS:
        raise AuthorityError("governed path set differs")
    if paths != sorted(paths):
        raise AuthorityError("governed paths must be sorted")
    if document["safety"] != EXPECTED_SAFETY:
        raise AuthorityError("gate-policy safety boundary differs")
    for name, path in TRUST_ROOTS.items():
        if _sha256((root / path).read_bytes()) != document["trustRootSha256"][name]:
            raise AuthorityError(f"trust-root hash mismatch: {name}")
    _assert_states(root, document["auditedBaseCommit"], document["governedPaths"], "before")
    for entry in document["governedPaths"]:
        if entry["before"] == entry["after"]:
            raise AuthorityError(f"governed transition is a no-op: {entry['path']}")


def expected_owner_approval_text(
    preapproval: dict[str, Any], preapproval_commit: str, preapproval_sha256: str
) -> str:
    template = preapproval["ownerApprovalTemplate"]
    if template.count("<PREAPPROVAL_COMMIT>") != 1 or template.count(
        "<PREAPPROVAL_SHA256>"
    ) != 1:
        raise AuthorityError("owner approval placeholders are not exact")
    return template.replace("<PREAPPROVAL_COMMIT>", preapproval_commit).replace(
        "<PREAPPROVAL_SHA256>", preapproval_sha256
    )


def validate_issue71_history(
    root: Path, preapproval: dict[str, Any], *, verify_owner_comment: bool
) -> None:
    if not verify_owner_comment:
        raise AuthorityError("live OWNER verification is required for issue #71 history")
    history = preapproval["phase2Issue71History"]
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


def validate_preapproval_commit(
    root: Path, preapproval_commit: str, *, verify_owner_comment: bool
) -> tuple[dict[str, Any], bytes]:
    preapproval = _document_at(root, preapproval_commit, PREAPPROVAL_PATH, "preapproval")
    base = preapproval["auditedBaseCommit"]
    _assert_ancestor(root, base, preapproval_commit)
    _assert_changed_paths(root, base, preapproval_commit, EXPECTED_AUTHORITY_PATHS, "B-to-P")
    if _state(root, preapproval_commit, DECISION_PATH)["state"] != "absent":
        raise AuthorityError("owner decision must be absent at P")
    if _state(root, preapproval_commit, RECEIPT_PATH)["state"] != "absent":
        raise AuthorityError("application receipt must be absent at P")
    validate_preapproval_document(root, preapproval)
    _assert_states(root, preapproval_commit, preapproval["governedPaths"], "before")
    validate_issue71_history(root, preapproval, verify_owner_comment=verify_owner_comment)
    return preapproval, _blob(root, preapproval_commit, PREAPPROVAL_PATH)


def _unique_addition(root: Path, start: str, head: str, path: str) -> str:
    commits = [
        line
        for line in _git(
            root, "log", "--format=%H", "--diff-filter=A", f"{start}..{head}", "--", path
        )
        .decode()
        .splitlines()
        if line
    ]
    if len(commits) != 1:
        raise AuthorityError(f"{path} must have one exact addition commit")
    return commits[0]


def _assert_immutable(root: Path, earlier: str, later: str, paths: set[str]) -> None:
    for path in paths:
        if _state(root, earlier, path) != _state(root, later, path):
            raise AuthorityError(f"authority changed after P: {path}")


def _verify_owner_comment(decision: dict[str, Any], expected_text: str) -> None:
    source = decision["approvalSource"]
    try:
        response = subprocess.run(
            [
                "gh",
                "api",
                "--method",
                "GET",
                f"repos/artemsemdev/SeaRise-Europe/issues/comments/{source['commentId']}",
            ],
            check=True,
            capture_output=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError) as error:
        raise AuthorityError("live Phase 3 OWNER comment cannot be verified") from error
    comment = _json(response, "live Phase 3 OWNER comment")
    user = comment.get("user") if isinstance(comment.get("user"), dict) else {}
    observed = {
        "id": comment.get("id"),
        "url": comment.get("html_url"),
        "issue": comment.get("issue_url"),
        "body": comment.get("body"),
        "association": comment.get("author_association"),
        "author": user.get("login"),
    }
    required = {
        "id": source["commentId"],
        "url": source["commentUrl"],
        "issue": "https://api.github.com/repos/artemsemdev/SeaRise-Europe/issues/61",
        "body": expected_text,
        "association": "OWNER",
        "author": "artemsemdev",
    }
    if observed != required:
        raise AuthorityError("live Phase 3 OWNER comment does not exactly match approval")


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
    _assert_changed_paths(root, preapproval_commit, decision_commit, {DECISION_PATH}, "P-to-D")
    if _unique_addition(root, preapproval_commit, decision_commit, DECISION_PATH) != decision_commit:
        raise AuthorityError("D is not the owner-decision addition commit")
    _assert_immutable(root, preapproval_commit, decision_commit, IMMUTABLE_AUTHORITY_PATHS)
    decision_bytes = _blob(root, decision_commit, DECISION_PATH)
    decision = _json(decision_bytes, "owner decision")
    schema = _document_at(root, preapproval_commit, SCHEMA_PATH, "gate-policy schema")
    _schema_validate(decision, schema, "gate-policy owner decision")
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
            raise AuthorityError(f"owner decision {field} does not match P")
    if decision["approvalSource"]["bodySha256"] != _sha256(expected_text.encode()):
        raise AuthorityError("owner decision body hash differs")
    if not verify_owner_comment:
        raise AuthorityError("live Phase 3 OWNER comment verification is required")
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
        root, preapproval_commit, decision_commit, verify_owner_comment=verify_owner_comment
    )
    _assert_ancestor(root, decision_commit, applied_commit)
    _assert_changed_paths(
        root, decision_commit, applied_commit, EXPECTED_GOVERNED_PATHS, "D-to-A"
    )
    _assert_immutable(root, preapproval_commit, applied_commit, IMMUTABLE_AUTHORITY_PATHS)
    _assert_states(root, applied_commit, preapproval["governedPaths"], "after")
    issue71_plan = _document_at(
        root,
        EXPECTED_HISTORY["preapprovalCommit"],
        "contracts/repository-removal/v2/issue-71/removal-plan.json",
        "issue #71 removal plan",
    )
    for entry in issue71_plan["entries"]:
        path = entry["path"]
        if path not in EXPECTED_GOVERNED_PATHS and _state(
            root, EXPECTED_HISTORY["appliedCommit"], path
        ) != _state(root, applied_commit, path):
            raise AuthorityError(f"ungoverned issue #71 post-state changed: {path}")
    return preapproval


def _governed_state_sha256(root: Path, commit: str, preapproval: dict[str, Any]) -> str:
    payload = [
        {"path": entry["path"], **_state(root, commit, entry["path"])}
        for entry in preapproval["governedPaths"]
    ]
    return _sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode())


def validate_application_receipt(
    root: Path, receipt_commit: str, head_commit: str, *, verify_owner_comment: bool
) -> None:
    receipt = _document_at(root, receipt_commit, RECEIPT_PATH, "application receipt")
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
    _assert_changed_paths(root, applied_commit, receipt_commit, {RECEIPT_PATH}, "A-to-R")
    if _unique_addition(root, applied_commit, receipt_commit, RECEIPT_PATH) != receipt_commit:
        raise AuthorityError("R is not the application-receipt addition commit")
    schema = _document_at(root, preapproval_commit, SCHEMA_PATH, "gate-policy schema")
    _schema_validate(receipt, schema, "gate-policy application receipt")
    preapproval_bytes = _blob(root, preapproval_commit, PREAPPROVAL_PATH)
    decision_bytes = _blob(root, decision_commit, DECISION_PATH)
    expected = {
        "appliedTree": _git(root, "rev-parse", f"{applied_commit}^{{tree}}").decode().strip(),
        "preapprovalSha256": _sha256(preapproval_bytes),
        "ownerDecisionSha256": _sha256(decision_bytes),
        "governedStateSha256": _governed_state_sha256(root, applied_commit, preapproval),
        "safety": EXPECTED_SAFETY,
    }
    for field, value in expected.items():
        if receipt[field] != value:
            raise AuthorityError(f"application receipt {field} differs from P/D/A")
    _assert_immutable(root, preapproval_commit, head_commit, IMMUTABLE_AUTHORITY_PATHS)
    _assert_states(root, head_commit, preapproval["governedPaths"], "after")
    if _state(root, receipt_commit, RECEIPT_PATH) != _state(root, head_commit, RECEIPT_PATH):
        raise AuthorityError("application receipt changed after R")


def validate_ci_state(root: Path, head_commit: str, *, verify_owner_comment: bool) -> None:
    preapproval_commit = _unique_addition(
        root, "4df5bfdeaaa66b68222519276fb72c912e457f97", head_commit, PREAPPROVAL_PATH
    )
    if _state(root, head_commit, DECISION_PATH)["state"] == "absent":
        preapproval, _ = validate_preapproval_commit(
            root, preapproval_commit, verify_owner_comment=verify_owner_comment
        )
        _assert_states(root, head_commit, preapproval["governedPaths"], "before")
        return
    decision_commit = _unique_addition(root, preapproval_commit, head_commit, DECISION_PATH)
    if _state(root, head_commit, RECEIPT_PATH)["state"] == "present":
        receipt_commit = _unique_addition(root, decision_commit, head_commit, RECEIPT_PATH)
        validate_application_receipt(
            root, receipt_commit, head_commit, verify_owner_comment=verify_owner_comment
        )
        return
    preapproval, _ = validate_decision_commit(
        root, preapproval_commit, decision_commit, verify_owner_comment=verify_owner_comment
    )
    states = [_state(root, head_commit, entry["path"]) for entry in preapproval["governedPaths"]]
    if states == [entry["before"] for entry in preapproval["governedPaths"]]:
        return
    if states != [entry["after"] for entry in preapproval["governedPaths"]]:
        raise AuthorityError("governed paths are in a partial or unapproved state")
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
                root,
                arguments.preapproval_commit,
                verify_owner_comment=arguments.verify_owner_comment,
            )
        else:
            validate_ci_state(
                root, arguments.head_commit, verify_owner_comment=arguments.verify_owner_comment
            )
    except (AuthorityError, KeyError, OSError, TypeError, ValueError) as error:
        print(f"ERROR: {error}")
        return 1
    print(f"validated Phase 3 gate-policy {arguments.command} authority")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
