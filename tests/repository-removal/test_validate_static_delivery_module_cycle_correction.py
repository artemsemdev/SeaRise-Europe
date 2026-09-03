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
VALIDATOR = ROOT / "scripts/repository/validate_static_delivery_module_cycle_correction.py"
PREAPPROVAL = ROOT / "contracts/repository-removal/v10/phase-3-issue-62/preapproval.json"


def _load():
    spec = importlib.util.spec_from_file_location("static_delivery_module_cycle_v10", VALIDATOR)
    if spec is None or spec.loader is None:
        raise RuntimeError("v10 module-cycle validator cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_v10_preapproval_is_exact_and_bounded(monkeypatch) -> None:
    v10 = _load()
    document = json.loads(PREAPPROVAL.read_text(encoding="utf-8"))
    monkeypatch.setattr(v10, "_validate_v9_chain", lambda *a, **k: None)
    monkeypatch.setattr(v10, "_validate_issue71_history", lambda *a, **k: None)
    v10.validate_preapproval_document(ROOT, document, verify_owner_comment=True)
    assert len(document["governedPaths"]) == 52
    assert {entry["path"] for entry in document["governedPaths"]} == v10.EXPECTED_GOVERNED_PATHS
    assert v10.NEW_GOVERNED_PATHS == {
        "src/web/scripts/static-repository-authority.mjs",
        "tests/repository-removal/test_validate_static_delivery_module_cycle_correction.py",
    }


def test_v10_preserves_integrated_v9_pd_and_supersedes_only_uncommitted_a() -> None:
    v10 = _load()
    document = json.loads(PREAPPROVAL.read_text(encoding="utf-8"))
    authority = document["phase3Issue62V9Authority"]
    proposed = document["supersededV9ProposedApplication"]
    assert authority["preapprovalCommit"] == v10.V9_PREAPPROVAL
    assert authority["decisionCommit"] == v10.V9_DECISION
    assert authority["repositoryDecisionIntegrated"] is True
    assert authority["integratedApplicationCommit"] is None
    assert proposed["commit"] is None
    assert proposed["tree"] is None
    assert proposed["pullRequest"] is None
    assert proposed["governedPathCount"] == 50
    assert proposed["governedTransitionsSha256"] == v10.V9_GOVERNED_TRANSITIONS_SHA256
    assert proposed["governedStateIntegrated"] is False


def test_v10_validates_real_integrated_v9_decision(monkeypatch) -> None:
    v10 = _load()
    document = json.loads(PREAPPROVAL.read_text(encoding="utf-8"))
    calls = []
    monkeypatch.setattr(
        v10.V9,
        "validate_decision_commit",
        lambda root, p, d, **kwargs: calls.append((root, p, d, kwargs)) or ({}, {}),
    )
    monkeypatch.setattr(v10, "_is_ancestor", lambda *a, **k: True)
    monkeypatch.setattr(v10, "_assert_states", lambda *a, **k: None)
    v10._validate_v9_chain(ROOT, document, verify_owner_comment=True)
    assert calls == [(ROOT, v10.V9_PREAPPROVAL, v10.V9_DECISION, {"verify_owner_comment": True})]


def test_v10_rejects_scope_and_future_tampering(monkeypatch) -> None:
    v10 = _load()
    document = json.loads(PREAPPROVAL.read_text(encoding="utf-8"))
    monkeypatch.setattr(v10, "_validate_v9_chain", lambda *a, **k: None)
    monkeypatch.setattr(v10, "_validate_issue71_history", lambda *a, **k: None)
    unsafe = copy.deepcopy(document)
    unsafe["safety"]["publicationAuthorized"] = True
    with pytest.raises(v10.AuthorityError, match="schema validation|safety"):
        v10.validate_preapproval_document(ROOT, unsafe, verify_owner_comment=True)
    changed = copy.deepcopy(document)
    changed["governedPaths"][0]["after"]["sha256"] = "0" * 64
    with pytest.raises(v10.AuthorityError, match="future-state hash|exact"):
        v10.validate_preapproval_document(ROOT, changed, verify_owner_comment=True)


def test_v10_owner_text_binds_cycle_fix_and_safety() -> None:
    v10 = _load()
    document = json.loads(PREAPPROVAL.read_text(encoding="utf-8"))
    text = v10.expected_owner_approval_text(document, "a" * 40, "b" * 64)
    assert v10.AUDITED_BASE in text
    assert v10.V9_PREAPPROVAL in text
    assert v10.V9_DECISION in text
    assert "52 governed repository paths" in text
    assert "circular import" in text
    assert "source and built Node CLI" in text
    assert "no projection, bypass adapter" in text
    assert "infrastructure apply remains unauthorized" in text


def test_v10_module_ownership_has_no_cycle_or_bypass() -> None:
    gate = (ROOT / "src/web/scripts/static-repository-gates.mjs").read_text(encoding="utf-8")
    launcher = (ROOT / "src/web/scripts/check-target-content.mjs").read_text(encoding="utf-8")
    authority = (ROOT / "src/web/scripts/static-repository-authority.mjs").read_text(encoding="utf-8")
    assert 'from "./static-repository-authority.mjs"' in gate
    assert 'from "./check-target-content.mjs"' not in gate
    assert 'from "./static-repository-authority.mjs"' in launcher
    assert "loadHistoricalAllowlist" in authority
    assert "projection adapter" not in authority.lower()
    assert "bypass adapter" not in authority.lower()
