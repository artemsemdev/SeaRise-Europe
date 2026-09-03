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
VALIDATOR = ROOT / "scripts/repository/validate_static_delivery_owner_verifier_chain_correction.py"
PREAPPROVAL = ROOT / "contracts/repository-removal/v11/phase-3-issue-62/preapproval.json"


def _load():
    spec = importlib.util.spec_from_file_location(
        "static_delivery_owner_verifier_chain_v11", VALIDATOR
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("v11 OWNER-verifier-chain validator cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_v11_preapproval_is_exact_and_bounded(monkeypatch) -> None:
    v11 = _load()
    document = json.loads(PREAPPROVAL.read_text(encoding="utf-8"))
    monkeypatch.setattr(v11, "_validate_v10_chain", lambda *a, **k: None)
    monkeypatch.setattr(v11, "_validate_issue71_history", lambda *a, **k: None)
    v11.validate_preapproval_document(ROOT, document, verify_owner_comment=True)
    assert len(document["governedPaths"]) == 53
    assert {entry["path"] for entry in document["governedPaths"]} == v11.EXPECTED_GOVERNED_PATHS
    assert v11.NEW_GOVERNED_PATHS == {
        "tests/repository-removal/test_validate_static_delivery_owner_verifier_chain_correction.py"
    }


def test_v11_preserves_v10_p_and_supersedes_unpublished_d_attempt() -> None:
    v11 = _load()
    document = json.loads(PREAPPROVAL.read_text(encoding="utf-8"))
    authority = document["phase3Issue62V10Authority"]
    attempt = document["supersededV10DecisionAttempt"]
    assert authority["preapprovalCommit"] == v11.V10_PREAPPROVAL
    assert authority["preapprovalMergeCommit"] == v11.AUDITED_BASE
    assert authority["repositoryDecisionIntegrated"] is False
    assert attempt["commit"] == v11.V10_DECISION_ATTEMPT
    assert attempt["tree"] == v11.V10_DECISION_ATTEMPT_TREE
    assert attempt["ownerDecisionSha256"] == v11.V10_DECISION_ATTEMPT_SHA256
    assert attempt["pullRequest"] is None
    assert attempt["published"] is False
    assert attempt["integrated"] is False


def test_v11_executes_real_v10_d_attempt_through_correct_verifier_chain(monkeypatch) -> None:
    v11 = _load()
    document = json.loads(PREAPPROVAL.read_text(encoding="utf-8"))
    calls = []
    monkeypatch.setattr(v11.V10, "validate_preapproval_commit", lambda *a, **k: ({}, b""))
    monkeypatch.setattr(v11, "_assert_states", lambda *a, **k: None)
    monkeypatch.setattr(
        v11.V10.V9.V8.V7.V6,
        "_verify_owner_comment",
        lambda decision, approval: calls.append((decision, approval))
        or {"createdAt": v11.V10_OWNER_COMMENT_TIME},
    )
    v11._validate_v10_chain(ROOT, document, verify_owner_comment=True)
    assert len(calls) == 1
    decision, approval = calls[0]
    assert decision["preapprovalCommit"] == v11.V10_PREAPPROVAL
    assert decision["approvalText"] == approval


def test_v11_rejects_scope_and_future_tampering(monkeypatch) -> None:
    v11 = _load()
    document = json.loads(PREAPPROVAL.read_text(encoding="utf-8"))
    monkeypatch.setattr(v11, "_validate_v10_chain", lambda *a, **k: None)
    monkeypatch.setattr(v11, "_validate_issue71_history", lambda *a, **k: None)
    unsafe = copy.deepcopy(document)
    unsafe["safety"]["publicationAuthorized"] = True
    with pytest.raises(v11.AuthorityError, match="schema validation|safety"):
        v11.validate_preapproval_document(ROOT, unsafe, verify_owner_comment=True)
    changed = copy.deepcopy(document)
    changed["governedPaths"][0]["after"]["sha256"] = "0" * 64
    with pytest.raises(v11.AuthorityError, match="future-state hash|exact"):
        v11.validate_preapproval_document(ROOT, changed, verify_owner_comment=True)


def test_v11_owner_text_binds_verifier_chain_fix_and_safety() -> None:
    v11 = _load()
    document = json.loads(PREAPPROVAL.read_text(encoding="utf-8"))
    text = v11.expected_owner_approval_text(document, "a" * 40, "b" * 64)
    assert v11.AUDITED_BASE in text
    assert v11.V10_PREAPPROVAL in text
    assert v11.V10_DECISION_ATTEMPT in text
    assert "53 governed repository paths" in text
    assert "V9.V8.V7.V6._verify_owner_comment" in text
    assert "no projection or bypass" in text
    assert "infrastructure apply remains unauthorized" in text


def test_v11_validator_uses_complete_exported_verifier_chain() -> None:
    v11 = _load()
    source = VALIDATOR.read_text(encoding="utf-8")
    assert callable(v11.V10.V9.V8.V7.V6._verify_owner_comment)
    assert not hasattr(v11.V10.V9, "V7")
    assert "V10.V9.V7.V6._verify_owner_comment" not in source
    assert source.count("V10.V9.V8.V7.V6._verify_owner_comment") == 2
