from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path

import pytest


ROOT = Path(
    os.environ.get("SEARISE_REPOSITORY_ROOT", Path(__file__).resolve().parents[2])
).resolve()
VALIDATOR = ROOT / "scripts/repository/validate_static_delivery_handoff_correction.py"
PREAPPROVAL = (
    ROOT / "contracts/repository-removal/v7/phase-3-issue-62/preapproval.json"
)


def _load():
    spec = importlib.util.spec_from_file_location("static_delivery_handoff_v7", VALIDATOR)
    if spec is None or spec.loader is None:
        raise RuntimeError("v7 handoff validator cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_v7_preapproval_is_exact_and_bounded(monkeypatch) -> None:
    v7 = _load()
    document = json.loads(PREAPPROVAL.read_text(encoding="utf-8"))
    monkeypatch.setattr(v7, "_validate_v6_chain", lambda *a, **k: None)
    monkeypatch.setattr(v7, "_validate_issue71_history", lambda *a, **k: None)

    v7.validate_preapproval_document(ROOT, document, verify_owner_comment=True)

    assert len(document["governedPaths"]) == 48
    assert {entry["path"] for entry in document["governedPaths"]} == (
        v7.EXPECTED_GOVERNED_PATHS
    )
    assert v7.NEW_GOVERNED_PATHS == {
        "src/web/scripts/static-repository-gates.mjs",
        "src/web/scripts/check-target-content.mjs",
        "src/web/scripts/check-target-content.test.mjs",
        "src/web/scripts/static-repository-gates.test.mjs",
        "tests/repository-removal/test_validate_static_delivery_handoff_correction.py",
    }


def test_v7_preserves_v6_decision_and_supersedes_only_unmerged_application() -> None:
    v7 = _load()
    document = json.loads(PREAPPROVAL.read_text(encoding="utf-8"))

    authority = document["phase3Issue62V6Authority"]
    attempt = document["supersededV6Application"]
    assert authority["preapprovalCommit"] == v7.V6_PREAPPROVAL
    assert authority["decisionCommit"] == v7.V6_DECISION
    assert authority["governedStateAuthorized"] is True
    assert authority["integratedApplicationCommit"] is None
    assert attempt["commit"] == v7.V6_APPLICATION_ATTEMPT
    assert attempt["pullRequest"] == 479
    assert attempt["ancestorOfAuditedBase"] is False
    assert attempt["governedStateIntegrated"] is False
    assert v7._is_ancestor(ROOT, v7.V6_APPLICATION_ATTEMPT, v7.AUDITED_BASE) is False


def test_v7_binds_the_historical_issue71_gate_before_exact_evolution() -> None:
    v7 = _load()
    document = json.loads(PREAPPROVAL.read_text(encoding="utf-8"))
    state = v7._state(ROOT, v7.AUDITED_BASE, v7.STATIC_REPOSITORY_GATES_PATH)

    assert state["gitBlobSha"] == v7.STATIC_REPOSITORY_GATES_BLOB
    assert state["sha256"] == v7.STATIC_REPOSITORY_GATES_SHA256
    assert document["trustRootSha256"]["staticRepositoryGates"] == state["sha256"]
    transition = next(
        entry for entry in document["governedPaths"]
        if entry["path"] == v7.STATIC_REPOSITORY_GATES_PATH
    )
    assert transition["before"] == state
    assert transition["after"] != state


def test_v7_rejects_safety_scope_and_future_state_tampering(monkeypatch) -> None:
    v7 = _load()
    document = json.loads(PREAPPROVAL.read_text(encoding="utf-8"))
    monkeypatch.setattr(v7, "_validate_v6_chain", lambda *a, **k: None)
    monkeypatch.setattr(v7, "_validate_issue71_history", lambda *a, **k: None)

    unsafe = copy.deepcopy(document)
    unsafe["safety"]["publicationAuthorized"] = True
    with pytest.raises(v7.AuthorityError, match="schema validation|safety"):
        v7.validate_preapproval_document(ROOT, unsafe, verify_owner_comment=True)

    expanded = copy.deepcopy(document)
    expanded["governedPaths"].append(copy.deepcopy(expanded["governedPaths"][0]))
    expanded["governedPaths"][-1]["path"] = "infra/cloudflare/secrets.auto.tfvars"
    with pytest.raises(v7.AuthorityError, match="schema validation|governed path set"):
        v7.validate_preapproval_document(ROOT, expanded, verify_owner_comment=True)

    changed = copy.deepcopy(document)
    changed["governedPaths"][0]["after"]["sha256"] = "0" * 64
    with pytest.raises(v7.AuthorityError, match="future-state hash|exact"):
        v7.validate_preapproval_document(ROOT, changed, verify_owner_comment=True)


def test_v7_owner_text_binds_handoff_history_and_safety() -> None:
    v7 = _load()
    document = json.loads(PREAPPROVAL.read_text(encoding="utf-8"))
    text = v7.expected_owner_approval_text(document, "a" * 40, "b" * 64)

    assert "a" * 40 in text
    assert "b" * 64 in text
    assert v7.AUDITED_BASE in text
    assert v7.V6_PREAPPROVAL in text
    assert v7.V6_DECISION in text
    assert v7.V6_APPLICATION_ATTEMPT in text
    assert "PR #479" in text
    assert "48 governed repository paths" in text
    assert "static-repository-gates.mjs" in text
    assert "infrastructure apply remains unauthorized" in text
    assert "Issue #64" in text
    assert "Issue #74" in text


def test_v7_preapproval_blob_has_stable_sha256() -> None:
    document = PREAPPROVAL.read_bytes()
    assert len(hashlib.sha256(document).hexdigest()) == 64
