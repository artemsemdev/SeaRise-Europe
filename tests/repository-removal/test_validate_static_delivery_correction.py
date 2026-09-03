from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(
    os.environ.get("SEARISE_REPOSITORY_ROOT", Path(__file__).resolve().parents[2])
).resolve()
V5_VALIDATOR = ROOT / "scripts/repository/validate_static_delivery_evolution.py"
V6_VALIDATOR = ROOT / "scripts/repository/validate_static_delivery_correction.py"
V5_PREAPPROVAL = (
    ROOT / "contracts/repository-removal/v5/phase-3-issue-62/preapproval.json"
)
V6_PREAPPROVAL = (
    ROOT / "contracts/repository-removal/v6/phase-3-issue-62/preapproval.json"
)
V5_PREAPPROVAL_COMMIT = "9934d69e4025f6dd2032375bae7e92c300b66459"
V5_OWNER_COMMENT_ID = 5416851308
V5_OWNER_COMMENT_TIME = "2026-08-25T21:11:27Z"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"{name} validator cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _v5_decision(v5) -> tuple[dict, str]:
    preapproval_bytes = V5_PREAPPROVAL.read_bytes()
    preapproval = json.loads(preapproval_bytes)
    text = v5.expected_owner_approval_text(
        preapproval,
        V5_PREAPPROVAL_COMMIT,
        hashlib.sha256(preapproval_bytes).hexdigest(),
    )
    decision = {
        "approvalSource": {
            "issue": 62,
            "commentId": V5_OWNER_COMMENT_ID,
            "commentUrl": (
                "https://github.com/artemsemdev/SeaRise-Europe/issues/62"
                f"#issuecomment-{V5_OWNER_COMMENT_ID}"
            ),
            "author": "artemsemdev",
            "authorAssociation": "OWNER",
            "bodySha256": hashlib.sha256(text.encode()).hexdigest(),
        }
    }
    return decision, text


def _issue62_comment(text: str) -> bytes:
    return json.dumps(
        {
            "id": V5_OWNER_COMMENT_ID,
            "html_url": (
                "https://github.com/artemsemdev/SeaRise-Europe/issues/62"
                f"#issuecomment-{V5_OWNER_COMMENT_ID}"
            ),
            "issue_url": (
                "https://api.github.com/repos/artemsemdev/SeaRise-Europe/issues/62"
            ),
            "body": text,
            "author_association": "OWNER",
            "user": {"login": "artemsemdev"},
            "created_at": V5_OWNER_COMMENT_TIME,
            "updated_at": V5_OWNER_COMMENT_TIME,
        }
    ).encode()


def test_v5_exact_issue62_owner_comment_is_structurally_rejected(
    monkeypatch,
) -> None:
    v5 = _load("static_delivery_evolution_v5", V5_VALIDATOR)
    decision, text = _v5_decision(v5)
    response = SimpleNamespace(stdout=_issue62_comment(text))
    monkeypatch.setattr(v5.V4.V3.subprocess, "run", lambda *a, **k: response)

    with pytest.raises(v5.AuthorityError, match="does not exactly match"):
        v5._verify_owner_comment(decision, text)


def test_v6_verifier_accepts_the_same_exact_issue62_comment(monkeypatch) -> None:
    v5 = _load("static_delivery_evolution_for_v6", V5_VALIDATOR)
    v6 = _load("static_delivery_correction_v6", V6_VALIDATOR)
    decision, text = _v5_decision(v5)
    response = SimpleNamespace(stdout=_issue62_comment(text))
    monkeypatch.setattr(v6.subprocess, "run", lambda *a, **k: response)

    v6._verify_owner_comment(decision, text)


def test_correction_preapproval_is_exact_and_supersedes_v5_before_d_a(
    monkeypatch,
) -> None:
    v6 = _load("static_delivery_correction_document", V6_VALIDATOR)
    document = json.loads(V6_PREAPPROVAL.read_text(encoding="utf-8"))
    monkeypatch.setattr(v6, "_validate_superseded_authority", lambda *a, **k: None)

    v6.validate_preapproval_document(ROOT, document, verify_owner_comment=True)

    assert document["supersededAuthority"]["status"] == (
        "superseded-before-decision-and-application"
    )
    assert document["supersededAuthority"]["decisionCommit"] is None
    assert document["supersededAuthority"]["appliedCommit"] is None
    assert document["supersededAuthority"]["receiptCommit"] is None
    assert document["supersededAuthority"]["ownerComment"]["id"] == (
        V5_OWNER_COMMENT_ID
    )
    assert {entry["path"] for entry in document["governedPaths"]} == (
        v6.EXPECTED_GOVERNED_PATHS
    )


def test_correction_rejects_safety_path_or_future_state_expansion(
    monkeypatch,
) -> None:
    v6 = _load("static_delivery_correction_safety", V6_VALIDATOR)
    document = json.loads(V6_PREAPPROVAL.read_text(encoding="utf-8"))
    monkeypatch.setattr(v6, "_validate_superseded_authority", lambda *a, **k: None)

    unsafe = copy.deepcopy(document)
    unsafe["safety"]["infrastructureApplyAuthorized"] = True
    with pytest.raises(v6.AuthorityError, match="schema validation|safety"):
        v6.validate_preapproval_document(ROOT, unsafe, verify_owner_comment=True)

    expanded = copy.deepcopy(document)
    expanded["governedPaths"].append(copy.deepcopy(expanded["governedPaths"][0]))
    expanded["governedPaths"][-1]["path"] = "infra/cloudflare/secrets.auto.tfvars"
    with pytest.raises(v6.AuthorityError, match="governed path set"):
        v6.validate_preapproval_document(ROOT, expanded, verify_owner_comment=True)

    changed = copy.deepcopy(document)
    changed["governedPaths"][0]["after"]["sha256"] = "0" * 64
    with pytest.raises(v6.AuthorityError, match="future-state hash|exact"):
        v6.validate_preapproval_document(ROOT, changed, verify_owner_comment=True)


def test_correction_owner_text_binds_superseded_comment_and_scope() -> None:
    v6 = _load("static_delivery_correction_text", V6_VALIDATOR)
    document = json.loads(V6_PREAPPROVAL.read_text(encoding="utf-8"))
    text = v6.expected_owner_approval_text(document, "a" * 40, "b" * 64)

    assert "a" * 40 in text
    assert "b" * 64 in text
    assert V5_PREAPPROVAL_COMMIT in text
    assert str(V5_OWNER_COMMENT_ID) in text
    assert "superseded before decision and application" in text
    assert "infrastructure apply" in text
    assert "Issue #74" in text


def test_correction_ci_rejects_partial_governed_state(monkeypatch) -> None:
    v6 = _load("static_delivery_correction_ci", V6_VALIDATOR)
    document = json.loads(V6_PREAPPROVAL.read_text(encoding="utf-8"))
    states = [copy.deepcopy(entry["before"]) for entry in document["governedPaths"]]
    states[0] = copy.deepcopy(document["governedPaths"][0]["after"])
    monkeypatch.setattr(v6, "_unique_addition", lambda *a, **k: "c" * 40)

    def fake_state(_root, _commit, path):
        if path == v6.DECISION_PATH:
            return {"state": "present"}
        if path == v6.RECEIPT_PATH:
            return {"state": "absent"}
        index = next(
            index
            for index, entry in enumerate(document["governedPaths"])
            if entry["path"] == path
        )
        return states[index]

    monkeypatch.setattr(v6, "_state", fake_state)
    monkeypatch.setattr(
        v6,
        "validate_decision_commit",
        lambda *a, **k: (document, {"decision": "approved"}),
    )

    with pytest.raises(v6.AuthorityError, match="partial"):
        v6.validate_ci_state(ROOT, "d" * 40, verify_owner_comment=True)
