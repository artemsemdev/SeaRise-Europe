from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest

import scripts.repository.validate_removal_plan_v2 as validator
from scripts.repository.validate_removal_plan_v2 import (
    DECISION_PATH,
    EXPECTED_TRUST_ROOTS,
    PLAN_PATH,
    PREAPPROVAL_PATH,
    PlanError,
    _json_load_bytes,
    _schema_validate_document,
    _sha256,
    _static_profile_activation,
    materialize_plan,
    validate_applied_commit,
    validate_decision_commit,
    validate_framework,
    validate_preapproval_commit,
)

ROOT = Path(__file__).resolve().parents[2]
V2 = ROOT / "contracts/repository-removal/v2"


def _run(repo: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", *arguments],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _write(repo: Path, relative_path: str, content: bytes) -> None:
    path = repo / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def _commit(repo: Path, message: str) -> str:
    _run(repo, "add", "-A")
    _run(repo, "commit", "-m", message)
    return _run(repo, "rev-parse", "HEAD")


def _blob(repo: Path, commit: str, path: str) -> str:
    return _run(repo, "rev-parse", f"{commit}:{path}")


def _lifecycle(tmp_path: Path) -> tuple[Path, str, str, str]:
    repo = tmp_path / "repository"
    repo.mkdir()
    _run(repo, "init")
    _run(repo, "config", "user.name", "Framework Test")
    _run(repo, "config", "user.email", "framework@example.invalid")

    for relative_path in sorted(set(EXPECTED_TRUST_ROOTS.values())):
        _write(repo, relative_path, (ROOT / relative_path).read_bytes())
    _write(repo, "retire.txt", b"legacy runtime\n")
    base = _commit(repo, "base")
    tree = _run(repo, "rev-parse", f"{base}^{{tree}}")

    plan = {
        "$schema": "./removal-plan.schema.json",
        "schemaVersion": "2.0.0",
        "planId": "phase-2-issue-72-exact-removal-v2",
        "issue": 72,
        "auditedCommit": base,
        "auditedTree": tree,
        "entries": [
            {
                "path": "retire.txt",
                "beforeMode": "100644",
                "beforeGitBlobSha": _blob(repo, base, "retire.txt"),
                "after": {"state": "absent"},
                "operations": [{"id": "delete-file", "kind": "file-delete"}],
            }
        ],
        "safety": {
            "candidateV7BytesUsed": False,
            "tarBytesUsed": False,
            "publicationAuthorized": False,
            "externalResourceMutationAuthorized": False,
        },
    }
    plan_bytes = (json.dumps(plan, indent=2) + "\n").encode()
    _write(repo, PLAN_PATH, plan_bytes)
    trust_hashes = {
        name: _sha256((repo / path).read_bytes())
        for name, path in EXPECTED_TRUST_ROOTS.items()
    }
    template = (
        "I approve issue #72 at <PREAPPROVAL_COMMIT> with preapproval "
        "<PREAPPROVAL_SHA256>. Candidate-v7 and TAR remain private; external "
        "resource mutation is not authorized."
    )
    preapproval = {
        "$schema": "./preapproval.schema.json",
        "schemaVersion": "2.0.0",
        "preapprovalId": "phase-2-issue-72-removal-v2",
        "decisionState": "owner-approval-required",
        "auditedCommit": base,
        "auditedTree": tree,
        "removalPlanSha256": _sha256(plan_bytes),
        "trustRoots": EXPECTED_TRUST_ROOTS,
        "trustRootSha256": trust_hashes,
        "ownerApprovalTemplate": template,
        "safety": {
            "candidatePublicationAuthorized": False,
            "externalResourceMutationAuthorized": False,
        },
    }
    preapproval_bytes = (json.dumps(preapproval, indent=2) + "\n").encode()
    _write(repo, PREAPPROVAL_PATH, preapproval_bytes)
    preapproval_commit = _commit(repo, "preapproval")

    approval_text = template.replace(
        "<PREAPPROVAL_COMMIT>", preapproval_commit
    ).replace("<PREAPPROVAL_SHA256>", _sha256(preapproval_bytes))
    decision = {
        "$schema": "./owner-decision.schema.json",
        "schemaVersion": "2.0.0",
        "decision": "approved",
        "approvedBy": "project-owner",
        "approvedAt": "2026-08-17T12:00:00Z",
        "preapprovalCommit": preapproval_commit,
        "preapprovalSha256": _sha256(preapproval_bytes),
        "removalPlanSha256": _sha256(plan_bytes),
        "approvalText": approval_text,
        "approvalSource": {
            "issue": 68,
            "commentId": 123,
            "commentUrl": "https://github.com/artemsemdev/SeaRise-Europe/issues/68#issuecomment-123",
            "author": "artemsemdev",
            "authorAssociation": "OWNER",
            "bodySha256": _sha256(approval_text.encode()),
        },
        "candidatePublicationAuthorized": False,
        "externalResourceMutationAuthorized": False,
    }
    _write(repo, DECISION_PATH, (json.dumps(decision, indent=2) + "\n").encode())
    decision_commit = _commit(repo, "decision")
    (repo / "retire.txt").unlink()
    applied_commit = _commit(repo, "applied")
    return repo, preapproval_commit, decision_commit, applied_commit


def test_framework_contains_schemas_but_no_concrete_authority() -> None:
    validate_framework(ROOT)
    assert (V2 / "removal-plan.schema.json").is_file()
    assert (V2 / "preapproval.schema.json").is_file()
    assert (V2 / "owner-decision.schema.json").is_file()
    assert not (V2 / "removal-plan.json").exists()
    assert not (V2 / "preapproval.json").exists()
    assert not (V2 / "owner-decision.json").exists()


@pytest.mark.parametrize(
    "content, message",
    [
        (b'{"outer":{"value":1,"value":2}}', "duplicate JSON key"),
        (b'{"value":NaN}', "non-finite JSON number"),
        (b"[]", "must be a JSON object"),
    ],
)
def test_strict_json_rejects_ambiguous_documents(content: bytes, message: str) -> None:
    with pytest.raises(PlanError, match=message):
        _json_load_bytes(content, "adversarial")


def test_real_git_preapproval_decision_applied_lifecycle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, preapproval, decision, applied = _lifecycle(tmp_path)
    monkeypatch.setattr(validator, "_verify_owner_comment", lambda *_: None)

    validate_preapproval_commit(repo, preapproval, checkout_commit=applied)
    validate_decision_commit(
        repo,
        preapproval,
        decision,
        verify_owner_comment=True,
        checkout_commit=applied,
    )
    validate_applied_commit(
        repo,
        preapproval,
        decision,
        applied,
        verify_owner_comment=True,
    )


def test_preapproval_and_execution_base_cannot_be_conflated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, preapproval, decision, applied = _lifecycle(tmp_path)
    monkeypatch.setattr(validator, "_verify_owner_comment", lambda *_: None)

    with pytest.raises(PlanError, match="P-to-D changed-path set differs"):
        validate_decision_commit(repo, decision, decision, verify_owner_comment=True)
    with pytest.raises(PlanError, match="P-to-D changed-path set differs"):
        validate_applied_commit(
            repo,
            preapproval,
            preapproval,
            applied,
            verify_owner_comment=True,
        )


def test_applied_diff_rejects_extra_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, preapproval, decision, _ = _lifecycle(tmp_path)
    _run(repo, "reset", "--hard", decision)
    (repo / "retire.txt").unlink()
    _write(repo, "extra.txt", b"unauthorized\n")
    applied = _commit(repo, "applied with extra path")
    monkeypatch.setattr(validator, "_verify_owner_comment", lambda *_: None)

    with pytest.raises(PlanError, match=r"extra=\['extra.txt'\]"):
        validate_applied_commit(
            repo, preapproval, decision, applied, verify_owner_comment=True
        )


def test_applied_diff_rejects_missing_planned_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, preapproval, decision, _ = _lifecycle(tmp_path)
    _run(repo, "reset", "--hard", decision)
    monkeypatch.setattr(validator, "_verify_owner_comment", lambda *_: None)
    with pytest.raises(PlanError, match=r"missing=\['retire.txt'\]"):
        validate_applied_commit(
            repo, preapproval, decision, decision, verify_owner_comment=True
        )


def test_absent_path_rejects_symlink_substitution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, preapproval, decision, _ = _lifecycle(tmp_path)
    _run(repo, "reset", "--hard", decision)
    (repo / "retire.txt").unlink()
    os.symlink("missing-target", repo / "retire.txt")
    applied = _commit(repo, "replace deletion with symlink")
    monkeypatch.setattr(validator, "_verify_owner_comment", lambda *_: None)

    with pytest.raises(PlanError, match="planned absent path still has a Git entry"):
        validate_applied_commit(
            repo, preapproval, decision, applied, verify_owner_comment=True
        )


def test_decision_requires_live_owner_verification(tmp_path: Path) -> None:
    repo, preapproval, decision, _ = _lifecycle(tmp_path)
    with pytest.raises(PlanError, match="live GitHub"):
        validate_decision_commit(
            repo, preapproval, decision, verify_owner_comment=False
        )


def test_authority_mutation_after_preapproval_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, preapproval, _, _ = _lifecycle(tmp_path)
    _run(repo, "reset", "--hard", preapproval)
    path = repo / EXPECTED_TRUST_ROOTS["v1Inventory"]
    path.write_bytes(path.read_bytes() + b"\n")
    _write(repo, DECISION_PATH, b"{}\n")
    mutated = _commit(repo, "mutate authority")
    monkeypatch.setattr(validator, "_verify_owner_comment", lambda *_: None)
    with pytest.raises(PlanError, match="P-to-D changed-path set differs"):
        validate_decision_commit(repo, preapproval, mutated, verify_owner_comment=True)


def test_exact_trust_root_mapping_rejects_missing_name(tmp_path: Path) -> None:
    repo, preapproval, _, _ = _lifecycle(tmp_path)
    _run(repo, "reset", "--hard", preapproval)
    path = repo / PREAPPROVAL_PATH
    document = json.loads(path.read_bytes())
    document["trustRoots"].pop("v1Census")
    path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    corrupt = _commit(repo, "remove required trust root")
    with pytest.raises(PlanError, match="exact required mapping"):
        validate_preapproval_commit(repo, corrupt, checkout_commit=corrupt)


def test_decision_symlink_is_not_a_signed_json_blob(tmp_path: Path) -> None:
    repo, preapproval, _, _ = _lifecycle(tmp_path)
    _run(repo, "reset", "--hard", preapproval)
    os.symlink("missing-decision", repo / DECISION_PATH)
    decision = _commit(repo, "symlink decision")
    with pytest.raises(PlanError, match="not a regular file"):
        validate_decision_commit(repo, preapproval, decision, verify_owner_comment=True)


def test_nonancestor_applied_commit_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, preapproval, decision, _ = _lifecycle(tmp_path)
    unrelated = _run(
        repo,
        "commit-tree",
        _run(repo, "rev-parse", f"{decision}^{{tree}}"),
        "-m",
        "unrelated",
    )
    monkeypatch.setattr(validator, "_verify_owner_comment", lambda *_: None)
    with pytest.raises(PlanError, match="required Git ancestry is absent"):
        validate_applied_commit(
            repo, preapproval, decision, unrelated, verify_owner_comment=True
        )


def test_git_replace_ref_cannot_change_committed_preapproval(tmp_path: Path) -> None:
    repo, preapproval, _, _ = _lifecycle(tmp_path)
    base = _run(repo, "rev-parse", f"{preapproval}~1")
    _run(repo, "replace", preapproval, base)
    validate_preapproval_commit(repo, preapproval)


def test_plan_rejects_protected_v1_and_path_ancestry_collisions(
    tmp_path: Path,
) -> None:
    repo, preapproval, _, _ = _lifecycle(tmp_path)
    plan = _json_load_bytes(
        subprocess.run(
            ["git", "show", f"{preapproval}:{PLAN_PATH}"],
            cwd=repo,
            check=True,
            capture_output=True,
        ).stdout,
        "plan",
    )
    protected = json.loads(json.dumps(plan))
    protected["entries"][0]["path"] = EXPECTED_TRUST_ROOTS["v1Inventory"]
    with pytest.raises(PlanError, match="signed v1 trust root cannot be planned"):
        materialize_plan(repo, protected, verify_after=False)

    collision = json.loads(json.dumps(plan))
    collision["entries"] = [
        {**collision["entries"][0], "path": "retire.txt"},
        {**collision["entries"][0], "path": "retire.txt/child"},
    ]
    with pytest.raises(PlanError, match="overlap by ancestry"):
        materialize_plan(repo, collision, verify_after=False)


def test_schema_rejects_candidate_tar_publication_and_external_authority(
    tmp_path: Path,
) -> None:
    repo, preapproval, _, _ = _lifecycle(tmp_path)
    plan_bytes = subprocess.run(
        ["git", "show", f"{preapproval}:{PLAN_PATH}"],
        cwd=repo,
        check=True,
        capture_output=True,
    ).stdout
    schema = _json_load_bytes(
        (
            ROOT / "contracts/repository-removal/v2/removal-plan.schema.json"
        ).read_bytes(),
        "schema",
    )
    for field in (
        "candidateV7BytesUsed",
        "tarBytesUsed",
        "publicationAuthorized",
        "externalResourceMutationAuthorized",
    ):
        plan = _json_load_bytes(plan_bytes, "plan")
        plan["safety"][field] = True
        with pytest.raises(PlanError, match="schema violation"):
            _schema_validate_document(plan, schema, "plan")


def _activation_operation(workflow: bytes) -> dict:
    return {
        "id": "activate-issue-72-profile",
        "kind": "static-profile-activation-transition",
        "issue": 72,
        "pendingSelectorIds": [
            "ci-legacy-compose-smoke",
            "ci-legacy-docker-api",
            "ci-legacy-docker-frontend",
            "legacy-api-dockerfile",
            "legacy-compose-file",
            "legacy-compose-smoke",
            "legacy-frontend-dockerfile",
        ],
        "componentId": "github-actions",
        "inputPath": ".github/workflows/ci.yml",
        "fromSha256": "6129f323d1c6bc52837936e89a437cae42213fa8f76bd9e3d5ee3d2756757d18",
        "toSha256": hashlib.sha256(workflow).hexdigest(),
    }


def test_static_profile_activation_removes_all_issue_72_state_and_rebinds_ci() -> None:
    profile = (
        ROOT / "contracts/supply-chain/v2/static-target-profile.json"
    ).read_bytes()
    workflow = b"planned workflow\n"
    transformed = _static_profile_activation(
        profile,
        _activation_operation(workflow),
        {".github/workflows/ci.yml": workflow},
        verify_target=True,
    )
    document = json.loads(transformed)
    assert 72 not in document["activation"]["blockingIssues"]
    assert all(
        selector["issue"] != 72
        for selector in document["activation"]["pendingSelectors"]
    )
    github = next(
        item for item in document["components"] if item["id"] == "github-actions"
    )
    ci_input = next(
        item for item in github["inputs"] if item["path"] == ".github/workflows/ci.yml"
    )
    assert ci_input["sha256"] == hashlib.sha256(workflow).hexdigest()


def test_static_profile_activation_rejects_confirmed_selector_drift() -> None:
    profile = (
        ROOT / "contracts/supply-chain/v2/static-target-profile.json"
    ).read_bytes()
    workflow = b"planned workflow\n"
    operation = _activation_operation(workflow)
    operation["pendingSelectorIds"] = operation["pendingSelectorIds"][:-1]
    with pytest.raises(PlanError, match="selectors pre-state changed"):
        _static_profile_activation(
            profile,
            operation,
            {".github/workflows/ci.yml": workflow},
            verify_target=True,
        )


def test_candidate_and_tar_paths_are_never_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, preapproval, _, _ = _lifecycle(tmp_path)
    original = Path.read_bytes

    def guarded_read(path: Path) -> bytes:
        try:
            lowered = str(path.relative_to(repo)).lower()
        except ValueError:
            lowered = str(path).lower()
        if "candidate" in lowered or lowered.endswith(".tar"):
            raise AssertionError(f"forbidden local artifact read: {path}")
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", guarded_read)
    validate_preapproval_commit(repo, preapproval, checkout_commit=preapproval)
    lowered = " ".join(EXPECTED_TRUST_ROOTS.values()).lower()
    assert "candidate" not in lowered
    assert ".tar" not in lowered
