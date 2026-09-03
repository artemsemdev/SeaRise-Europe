from __future__ import annotations

import copy
import importlib.util
import json
import os
from pathlib import Path

import pytest

ROOT = Path(
    os.environ.get("SEARISE_REPOSITORY_ROOT", Path(__file__).resolve().parents[2])
).resolve()
VALIDATOR = ROOT / "scripts/repository/validate_static_delivery_owner_verifier_correction.py"
PREAPPROVAL = ROOT / "contracts/repository-removal/v9/phase-3-issue-62/preapproval.json"


def _load():
    spec = importlib.util.spec_from_file_location("static_delivery_owner_verifier_v9", VALIDATOR)
    if spec is None or spec.loader is None:
        raise RuntimeError("v9 OWNER-verifier validator cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_v9_preapproval_is_exact_and_bounded(monkeypatch) -> None:
    v9 = _load()
    document = json.loads(PREAPPROVAL.read_text(encoding="utf-8"))
    monkeypatch.setattr(v9, "_validate_v8_chain", lambda *a, **k: None)
    monkeypatch.setattr(v9, "_validate_issue71_history", lambda *a, **k: None)
    v9.validate_preapproval_document(ROOT, document, verify_owner_comment=True)
    assert len(document["governedPaths"]) == 50
    assert {entry["path"] for entry in document["governedPaths"]} == v9.EXPECTED_GOVERNED_PATHS
    assert v9.NEW_GOVERNED_PATHS == {
        "tests/repository-removal/test_validate_static_delivery_owner_verifier_correction.py"
    }


def test_v9_preserves_v8_p_and_supersedes_unpublished_d_attempt() -> None:
    v9 = _load()
    document = json.loads(PREAPPROVAL.read_text(encoding="utf-8"))
    authority = document["phase3Issue62V8Authority"]
    attempt = document["supersededV8DecisionAttempt"]
    assert authority["preapprovalCommit"] == v9.V8_PREAPPROVAL
    assert authority["preapprovalMergeCommit"] == v9.AUDITED_BASE
    assert authority["repositoryDecisionIntegrated"] is False
    assert attempt["commit"] == v9.V8_DECISION_ATTEMPT
    assert attempt["tree"] == v9.V8_DECISION_ATTEMPT_TREE
    assert attempt["ownerDecisionSha256"] == v9.V8_DECISION_ATTEMPT_SHA256
    assert attempt["pullRequest"] is None
    assert attempt["published"] is False
    assert attempt["integrated"] is False


def test_v9_validates_exact_d8_attempt_through_exported_verifier(monkeypatch) -> None:
    v9 = _load()
    document = json.loads(PREAPPROVAL.read_text(encoding="utf-8"))
    observed_calls = []
    monkeypatch.setattr(v9.V8, "validate_preapproval_commit", lambda *a, **k: ({}, b""))
    monkeypatch.setattr(
        v9.V8.V7.V6,
        "_verify_owner_comment",
        lambda decision, approval: observed_calls.append((decision, approval))
        or {"createdAt": v9.V8_OWNER_COMMENT_TIME},
    )
    v9._validate_v8_chain(ROOT, document, verify_owner_comment=True)
    assert len(observed_calls) == 1
    decision, approval = observed_calls[0]
    assert decision["approvalText"] == approval
    assert decision["preapprovalCommit"] == v9.V8_PREAPPROVAL


def test_v9_executes_real_d_validation_through_existing_owner_verifier(monkeypatch) -> None:
    v9 = _load()
    preapproval = json.loads(PREAPPROVAL.read_text(encoding="utf-8"))
    approval = v9.expected_owner_approval_text(preapproval, "a" * 40, "b" * 64)
    decision = {
        "$schema": "../static-delivery-owner-verifier-correction.schema.json",
        "schemaVersion": "9.0.0",
        "documentType": "owner-decision",
        "decision": "approved",
        "approvedBy": "project-owner",
        "approvedAt": "2026-09-01T14:00:00Z",
        "preapprovalCommit": "a" * 40,
        "preapprovalSha256": "b" * 64,
        "approvalText": approval,
        "approvalSource": {
            "issue": 62,
            "commentId": 1,
            "commentUrl": "https://github.com/artemsemdev/SeaRise-Europe/issues/62#issuecomment-1",
            "author": "artemsemdev",
            "authorAssociation": "OWNER",
            "bodySha256": "c" * 64,
        },
        "safety": v9.EXPECTED_SAFETY,
    }
    observed_calls = []
    monkeypatch.setattr(v9, "validate_preapproval_commit", lambda *a, **k: (preapproval, b"p"))
    monkeypatch.setattr(v9, "_assert_ancestor", lambda *a, **k: None)
    monkeypatch.setattr(v9, "_assert_changed_paths", lambda *a, **k: None)
    monkeypatch.setattr(v9, "_unique_addition", lambda *a, **k: "d" * 40)
    monkeypatch.setattr(v9, "_assert_immutable", lambda *a, **k: None)
    monkeypatch.setattr(v9, "_blob", lambda *a, **k: json.dumps(decision).encode())
    monkeypatch.setattr(v9, "_document_at", lambda *a, **k: json.loads((ROOT / v9.SCHEMA_PATH).read_text()))
    monkeypatch.setattr(v9, "_sha256", lambda value: "b" * 64)
    monkeypatch.setattr(v9, "expected_owner_approval_text", lambda *a, **k: approval)
    monkeypatch.setattr(
        v9.V8.V7.V6,
        "_verify_owner_comment",
        lambda actual, text: observed_calls.append((actual, text))
        or {"createdAt": "2026-09-01T14:00:00Z"},
    )
    v9.validate_decision_commit(ROOT, "a" * 40, "d" * 40, verify_owner_comment=True)
    assert observed_calls == [(decision, approval)]


def test_v9_rejects_scope_and_future_tampering(monkeypatch) -> None:
    v9 = _load()
    document = json.loads(PREAPPROVAL.read_text(encoding="utf-8"))
    monkeypatch.setattr(v9, "_validate_v8_chain", lambda *a, **k: None)
    monkeypatch.setattr(v9, "_validate_issue71_history", lambda *a, **k: None)
    unsafe = copy.deepcopy(document)
    unsafe["safety"]["publicationAuthorized"] = True
    with pytest.raises(v9.AuthorityError, match="schema validation|safety"):
        v9.validate_preapproval_document(ROOT, unsafe, verify_owner_comment=True)
    changed = copy.deepcopy(document)
    changed["governedPaths"][0]["after"]["sha256"] = "0" * 64
    with pytest.raises(v9.AuthorityError, match="future-state hash|exact"):
        v9.validate_preapproval_document(ROOT, changed, verify_owner_comment=True)


def test_v9_owner_text_binds_verifier_fix_and_safety() -> None:
    v9 = _load()
    document = json.loads(PREAPPROVAL.read_text(encoding="utf-8"))
    text = v9.expected_owner_approval_text(document, "a" * 40, "b" * 64)
    assert v9.AUDITED_BASE in text
    assert v9.V8_PREAPPROVAL in text
    assert v9.V8_DECISION_ATTEMPT in text
    assert "50 governed repository paths" in text
    assert "OWNER-comment verifier" in text
    assert "no projection or bypass" in text
    assert "infrastructure apply remains unauthorized" in text


def test_v9_validator_uses_existing_exported_verifier_chain() -> None:
    v9 = _load()
    assert callable(v9.V8.V7.V6._verify_owner_comment)
    assert not hasattr(v9.V8.V7, "_verify_owner_comment")
