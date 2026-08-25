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
VALIDATOR = ROOT / "scripts/repository/validate_gate_policy_evolution.py"
PREAPPROVAL = (
    ROOT
    / "contracts/repository-removal/v3/phase-3-issue-61/preapproval.json"
)


def _load_validator():
    spec = importlib.util.spec_from_file_location("gate_policy_evolution", VALIDATOR)
    if spec is None or spec.loader is None:
        raise RuntimeError("gate-policy validator cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_preapproval_is_exact_and_preserves_safety_boundaries() -> None:
    validator = _load_validator()
    document = json.loads(PREAPPROVAL.read_text(encoding="utf-8"))
    validator.validate_preapproval_document(ROOT, document)
    assert document["safety"] == {
        "candidateV7BytesUsed": False,
        "tarBytesUsed": False,
        "publicationAuthorized": False,
        "externalResourceMutationAuthorized": False,
    }
    assert {entry["path"] for entry in document["governedPaths"]} == (
        validator.EXPECTED_GOVERNED_PATHS
    )


def test_preapproval_rejects_safety_or_path_expansion() -> None:
    validator = _load_validator()
    document = json.loads(PREAPPROVAL.read_text(encoding="utf-8"))
    unsafe = copy.deepcopy(document)
    unsafe["safety"]["publicationAuthorized"] = True
    with pytest.raises(validator.AuthorityError, match="safety"):
        validator.validate_preapproval_document(ROOT, unsafe)
    expanded = copy.deepcopy(document)
    expanded["governedPaths"].append(copy.deepcopy(expanded["governedPaths"][0]))
    expanded["governedPaths"][-1]["path"] = "infra/cloudflare/main.tf"
    with pytest.raises(validator.AuthorityError, match="governed path set"):
        validator.validate_preapproval_document(ROOT, expanded)


def test_issue71_history_verification_stops_at_immutable_receipt(monkeypatch) -> None:
    validator = _load_validator()
    document = json.loads(PREAPPROVAL.read_text(encoding="utf-8"))
    observed = {}

    def fake_git(_root, *arguments):
        history = document["phase2Issue71History"]
        if arguments[0] == "rev-parse":
            commit = arguments[1].split("^", 1)[0]
            kind = next(
                name for name in ("preapproval", "decision", "applied", "receipt")
                if history[f"{name}Commit"] == commit
            )
            return f"{history[f'{kind}Tree']}\n".encode()
        return (
            ROOT / "contracts/repository-removal/v2/issue-71/application-receipt.json"
        ).read_bytes()

    def fake_run(arguments, **kwargs):
        observed["arguments"] = arguments
        observed["kwargs"] = kwargs
        return type("Result", (), {"returncode": 0, "stdout": b"", "stderr": b""})()

    monkeypatch.setattr(validator, "_git", fake_git)
    monkeypatch.setattr(validator.subprocess, "run", fake_run)
    validator.validate_issue71_history(ROOT, document, verify_owner_comment=True)
    anchors = document["phase2Issue71History"]
    assert observed["arguments"][-5:] == [
        "--receipt-commit",
        anchors["receiptCommit"],
        "--head-commit",
        anchors["receiptCommit"],
        "--verify-owner-comment",
    ]


def test_issue71_history_requires_live_owner_verification() -> None:
    validator = _load_validator()
    document = json.loads(PREAPPROVAL.read_text(encoding="utf-8"))
    with pytest.raises(validator.AuthorityError, match="live OWNER"):
        validator.validate_issue71_history(ROOT, document, verify_owner_comment=False)


def test_owner_approval_text_binds_commit_and_preapproval_hash() -> None:
    validator = _load_validator()
    document = json.loads(PREAPPROVAL.read_text(encoding="utf-8"))
    commit = "a" * 40
    digest = "b" * 64
    text = validator.expected_owner_approval_text(document, commit, digest)
    assert commit in text
    assert digest in text
    assert "Candidate-v7" in text
    assert "external resource" in text
