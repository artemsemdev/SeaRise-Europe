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
VALIDATOR = ROOT / "scripts/repository/validate_gate_policy_correction.py"
PREAPPROVAL = (
    ROOT
    / "contracts/repository-removal/v4/phase-3-issue-61/preapproval.json"
)


def _load_validator():
    spec = importlib.util.spec_from_file_location("gate_policy_correction", VALIDATOR)
    if spec is None or spec.loader is None:
        raise RuntimeError("gate-policy correction validator cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _document() -> dict:
    return json.loads(PREAPPROVAL.read_text(encoding="utf-8"))


def test_correction_preapproval_is_exact_and_supersedes_v3_before_application(
    monkeypatch,
) -> None:
    validator = _load_validator()
    document = _document()
    monkeypatch.setattr(validator, "_validate_superseded_authority", lambda *a, **k: None)

    validator.validate_preapproval_document(
        ROOT, document, verify_owner_comment=True
    )

    assert document["supersededAuthority"]["status"] == (
        "superseded-before-application"
    )
    assert document["supersededAuthority"]["appliedCommit"] is None
    assert document["supersededAuthority"]["receiptCommit"] is None
    assert {entry["path"] for entry in document["governedPaths"]} == (
        validator.EXPECTED_GOVERNED_PATHS
    )
    assert document["safety"] == validator.EXPECTED_SAFETY


def test_correction_rejects_safety_path_or_scope_expansion(monkeypatch) -> None:
    validator = _load_validator()
    document = _document()
    monkeypatch.setattr(validator, "_validate_superseded_authority", lambda *a, **k: None)

    unsafe = copy.deepcopy(document)
    unsafe["safety"]["publicationAuthorized"] = True
    with pytest.raises(validator.AuthorityError, match="schema validation|safety"):
        validator.validate_preapproval_document(
            ROOT, unsafe, verify_owner_comment=True
        )

    expanded = copy.deepcopy(document)
    expanded["governedPaths"].append(copy.deepcopy(expanded["governedPaths"][0]))
    expanded["governedPaths"][-1]["path"] = "infra/cloudflare/main.tf"
    with pytest.raises(validator.AuthorityError, match="governed path set"):
        validator.validate_preapproval_document(
            ROOT, expanded, verify_owner_comment=True
        )

    broadened = copy.deepcopy(document)
    unchanged_path = next(
        path
        for path in validator.EXPECTED_GOVERNED_PATHS
        if path not in validator.CORRECTED_OLD_PATHS
        and path != validator.TEST_PATH
    )
    entry = next(
        item for item in broadened["governedPaths"] if item["path"] == unchanged_path
    )
    entry["after"] = copy.deepcopy(entry["before"])
    with pytest.raises(validator.AuthorityError, match="no-op|bounded fix set"):
        validator.validate_preapproval_document(
            ROOT, broadened, verify_owner_comment=True
        )


def test_owner_approval_text_binds_correction_and_supersession() -> None:
    validator = _load_validator()
    text = validator.expected_owner_approval_text(_document(), "a" * 40, "b" * 64)

    assert "a" * 40 in text
    assert "b" * 64 in text
    assert validator.OLD_PREAPPROVAL in text
    assert validator.OLD_DECISION in text
    assert "superseded before application" in text
    assert "Candidate-v7" in text
    assert "external resource" in text


def test_ci_rejects_partial_or_superseded_governed_state(monkeypatch) -> None:
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

    with pytest.raises(validator.AuthorityError, match="partial or superseded"):
        validator.validate_ci_state(
            ROOT, "d" * 40, verify_owner_comment=True
        )
