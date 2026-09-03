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
VALIDATOR = (
    ROOT / "scripts/repository/validate_static_delivery_trust_handoff_correction.py"
)
PREAPPROVAL = (
    ROOT / "contracts/repository-removal/v8/phase-3-issue-62/preapproval.json"
)


def _load():
    spec = importlib.util.spec_from_file_location(
        "static_delivery_trust_handoff_v8", VALIDATOR
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("v8 trust-handoff validator cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_v8_preapproval_is_exact_and_bounded(monkeypatch) -> None:
    v8 = _load()
    document = json.loads(PREAPPROVAL.read_text(encoding="utf-8"))
    monkeypatch.setattr(v8, "_validate_v7_chain", lambda *a, **k: None)
    monkeypatch.setattr(v8, "_validate_issue71_history", lambda *a, **k: None)

    v8.validate_preapproval_document(ROOT, document, verify_owner_comment=True)

    assert len(document["governedPaths"]) == 49
    assert {entry["path"] for entry in document["governedPaths"]} == (
        v8.EXPECTED_GOVERNED_PATHS
    )
    assert v8.NEW_GOVERNED_PATHS == {
        "tests/repository-removal/"
        "test_validate_static_delivery_trust_handoff_correction.py"
    }


def test_v8_preserves_v7_decision_and_supersedes_uncommitted_future() -> None:
    v8 = _load()
    document = json.loads(PREAPPROVAL.read_text(encoding="utf-8"))

    authority = document["phase3Issue62V7Authority"]
    proposal = document["supersededV7ProposedApplication"]
    assert authority["preapprovalCommit"] == v8.V7_PREAPPROVAL
    assert authority["decisionCommit"] == v8.V7_DECISION
    assert authority["governedStateAuthorized"] is True
    assert authority["integratedApplicationCommit"] is None
    assert proposal["commit"] is None
    assert proposal["tree"] is None
    assert proposal["pullRequest"] is None
    assert proposal["governedPathCount"] == 48
    assert proposal["governedTransitionsSha256"] == (
        v8.V7_GOVERNED_TRANSITIONS_SHA256
    )
    assert proposal["governedStateIntegrated"] is False


def test_v8_binds_historical_issue71_gate_to_exact_evolved_blob() -> None:
    v8 = _load()
    document = json.loads(PREAPPROVAL.read_text(encoding="utf-8"))
    transition = next(
        entry
        for entry in document["governedPaths"]
        if entry["path"] == v8.STATIC_REPOSITORY_GATES_PATH
    )
    historical = v8._state(
        ROOT, v8.AUDITED_BASE, v8.STATIC_REPOSITORY_GATES_PATH
    )

    assert historical["gitBlobSha"] == v8.STATIC_REPOSITORY_GATES_BLOB
    assert historical["sha256"] == v8.STATIC_REPOSITORY_GATES_SHA256
    assert transition["before"] == historical
    assert transition["after"] != historical


def test_v8_rejects_scope_future_and_supersession_tampering(monkeypatch) -> None:
    v8 = _load()
    document = json.loads(PREAPPROVAL.read_text(encoding="utf-8"))
    monkeypatch.setattr(v8, "_validate_v7_chain", lambda *a, **k: None)
    monkeypatch.setattr(v8, "_validate_issue71_history", lambda *a, **k: None)

    unsafe = copy.deepcopy(document)
    unsafe["safety"]["publicationAuthorized"] = True
    with pytest.raises(v8.AuthorityError, match="schema validation|safety"):
        v8.validate_preapproval_document(ROOT, unsafe, verify_owner_comment=True)

    changed = copy.deepcopy(document)
    changed["governedPaths"][0]["after"]["sha256"] = "0" * 64
    with pytest.raises(v8.AuthorityError, match="future-state hash|exact"):
        v8.validate_preapproval_document(ROOT, changed, verify_owner_comment=True)

    supersession = copy.deepcopy(document)
    supersession["supersededV7ProposedApplication"][
        "governedAfterStateSha256"
    ] = "0" * 64
    monkeypatch.undo()
    monkeypatch.setattr(v8.V7, "validate_decision_commit", lambda *a, **k: ({}, {}))
    with pytest.raises(v8.AuthorityError, match="superseded uncommitted"):
        v8._validate_v7_chain(ROOT, supersession, verify_owner_comment=True)


def test_v8_owner_text_binds_history_handoff_and_safety() -> None:
    v8 = _load()
    document = json.loads(PREAPPROVAL.read_text(encoding="utf-8"))
    text = v8.expected_owner_approval_text(document, "a" * 40, "b" * 64)

    assert "a" * 40 in text
    assert "b" * 64 in text
    assert v8.AUDITED_BASE in text
    assert v8.V7_PREAPPROVAL in text
    assert v8.V7_DECISION in text
    assert "49 governed repository paths" in text
    assert "uncommitted" in text
    assert "Issue #71" in text
    assert "no projection or bypass" in text
    assert "infrastructure apply remains unauthorized" in text
    assert "Issue #64" in text
    assert "Issue #74" in text


def test_v8_preapproval_blob_has_stable_sha256() -> None:
    document = PREAPPROVAL.read_bytes()
    assert len(hashlib.sha256(document).hexdigest()) == 64
