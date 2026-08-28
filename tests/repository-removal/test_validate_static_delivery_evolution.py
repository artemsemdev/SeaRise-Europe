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
VALIDATOR = ROOT / "scripts/repository/validate_static_delivery_evolution.py"
PREAPPROVAL = (
    ROOT
    / "contracts/repository-removal/v5/phase-3-issue-62/preapproval.json"
)


def _load_validator():
    spec = importlib.util.spec_from_file_location(
        "static_delivery_evolution", VALIDATOR
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("static-delivery evolution validator cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _document() -> dict:
    return json.loads(PREAPPROVAL.read_text(encoding="utf-8"))


def test_preapproval_binds_complete_delivery_state_and_prior_history(
    monkeypatch,
) -> None:
    validator = _load_validator()
    document = _document()
    monkeypatch.setattr(validator, "_validate_prior_authority", lambda *a, **k: None)

    validator.validate_preapproval_document(
        ROOT, document, verify_owner_comment=True
    )

    assert {entry["path"] for entry in document["governedPaths"]} == (
        validator.EXPECTED_GOVERNED_PATHS
    )
    assert document["phase2Issue71History"] == validator.EXPECTED_ISSUE71_HISTORY
    assert document["phase3Issue61History"] == validator.EXPECTED_ISSUE61_HISTORY
    assert document["safety"] == validator.EXPECTED_SAFETY


def test_preapproval_rejects_safety_path_or_state_expansion(monkeypatch) -> None:
    validator = _load_validator()
    document = _document()
    monkeypatch.setattr(validator, "_validate_prior_authority", lambda *a, **k: None)

    unsafe = copy.deepcopy(document)
    unsafe["safety"]["infrastructureApplyAuthorized"] = True
    with pytest.raises(validator.AuthorityError, match="schema validation|safety"):
        validator.validate_preapproval_document(
            ROOT, unsafe, verify_owner_comment=True
        )

    expanded = copy.deepcopy(document)
    expanded["governedPaths"].append(copy.deepcopy(expanded["governedPaths"][0]))
    expanded["governedPaths"][-1]["path"] = "infra/cloudflare/secrets.auto.tfvars"
    with pytest.raises(validator.AuthorityError, match="governed path set"):
        validator.validate_preapproval_document(
            ROOT, expanded, verify_owner_comment=True
        )

    changed = copy.deepcopy(document)
    changed["governedPaths"][0]["after"]["sha256"] = "0" * 64
    with pytest.raises(validator.AuthorityError, match="future-state hash|exact"):
        validator.validate_preapproval_document(
            ROOT, changed, verify_owner_comment=True
        )


def test_owner_approval_text_binds_delivery_scope_and_prior_receipt() -> None:
    validator = _load_validator()
    text = validator.expected_owner_approval_text(_document(), "a" * 40, "b" * 64)

    assert "a" * 40 in text
    assert "b" * 64 in text
    assert validator.ISSUE61_RECEIPT_COMMIT in text
    assert validator.AUDITED_BASE in text
    assert "Candidate-v7" in text
    assert "infrastructure apply" in text
    assert "publication" in text
    assert "Issue #74" in text


def test_ci_rejects_partial_delivery_state(monkeypatch) -> None:
    validator = _load_validator()
    document = _document()
    states = [copy.deepcopy(entry["before"]) for entry in document["governedPaths"]]
    states[0] = copy.deepcopy(document["governedPaths"][0]["after"])

    monkeypatch.setattr(validator, "_unique_addition", lambda *a, **k: "c" * 40)

    def fake_state(_root, _commit, path):
        if path == validator.DECISION_PATH:
            return {"state": "present"}
        if path == validator.RECEIPT_PATH:
            return {"state": "absent"}
        index = next(
            index
            for index, entry in enumerate(document["governedPaths"])
            if entry["path"] == path
        )
        return states[index]

    monkeypatch.setattr(validator, "_state", fake_state)
    monkeypatch.setattr(
        validator,
        "validate_decision_commit",
        lambda *a, **k: (document, {"decision": "approved"}),
    )

    with pytest.raises(validator.AuthorityError, match="partial"):
        validator.validate_ci_state(ROOT, "d" * 40, verify_owner_comment=True)
