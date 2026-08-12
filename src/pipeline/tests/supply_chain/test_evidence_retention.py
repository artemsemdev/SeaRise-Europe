"""Release evidence retention handoff must be complete and append-only."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from jsonschema import Draft202012Validator

import searise_pipeline.supply_chain.evidence_retention as retention
from searise_pipeline.candidate_completeness import CandidateContractError
from searise_pipeline.supply_chain import SupplyChainContractError
from searise_pipeline.supply_chain.public_readback import _verify_public_signed_subjects
from searise_pipeline.supply_chain.sigstore_verifier import (
    verify_candidate_evidence_cryptographically,
)
from tests.supply_chain.test_candidate_evidence_pair import ROOT, _load, _pair
from tests.supply_chain.test_sigstore_verifier import RUN_ID, _production_envelope, _tool

CLI_PATH = ROOT / "scripts/release/retain_release_evidence.py"


@pytest.fixture(autouse=True)
def _structural_fixture_has_byte_gate_authority(monkeypatch: Any) -> None:
    """The compact Sigstore fixture omits large artifact bytes tested by the byte gate."""

    def validate(root: Path) -> Any:
        manifest = json.loads((root / "manifest.json").read_text())
        return SimpleNamespace(
            candidate_id=manifest["candidateId"],
            data_release_id=manifest["dataReleaseId"],
            artifact_count=len(manifest["artifacts"]),
        )

    monkeypatch.setattr(retention, "validate_candidate_root", validate)


def _cli() -> Any:
    spec = importlib.util.spec_from_file_location("retain_release_evidence_cli", CLI_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _inputs(tmp_path: Path) -> tuple[Path, Path, Path, Path, Path]:
    candidate, evidence = _pair(tmp_path / "pair", data_provenance_class="real-source")
    _production_envelope(evidence)
    tool, lock = _tool(tmp_path)
    lock_sha256 = hashlib.sha256(lock.read_bytes()).hexdigest()
    crypto = tmp_path / "audit" / "cryptographic.json"
    public = tmp_path / "audit" / "public-readback.json"
    crypto.parent.mkdir(mode=0o700)
    verify_candidate_evidence_cryptographically(
        candidate,
        evidence,
        repository_root=ROOT,
        controlled_build_run_id=RUN_ID,
        cosign_executable=tool,
        cosign_tool_lock=lock,
        trusted_cosign_tool_lock_sha256=lock_sha256,
        receipt_path=crypto,
    )
    roots = {"manifest.json": candidate, "provenance.intoto.jsonl": evidence}

    def exact(url: str, size: int) -> bytes:
        logical = url.rsplit("/", 1)[1]
        raw = (roots[logical] / logical).read_bytes()
        assert len(raw) == size
        return raw

    _verify_public_signed_subjects(
        candidate,
        evidence,
        repository_root=ROOT,
        controlled_build_run_id=RUN_ID,
        cosign_executable=tool,
        cosign_tool_lock=lock,
        trusted_cosign_tool_lock_sha256=lock_sha256,
        expected_origin="https://downloads.example.test",
        manifest_url="https://downloads.example.test/release/manifest.json",
        provenance_url="https://downloads.example.test/release/provenance.intoto.jsonl",
        receipt_path=public,
        fetch=exact,
        clock=lambda: datetime(2026, 8, 12, 2, 0, tzinfo=timezone.utc),
        reviewed_origins={"https://downloads.example.test"},
    )
    for directory in sorted((path for path in evidence.rglob("*") if path.is_dir()), reverse=True):
        directory.chmod(0o700)
    evidence.chmod(0o700)
    for file in (path for path in evidence.rglob("*") if path.is_file()):
        file.chmod(0o400)
    release_id = json.loads((candidate / "manifest.json").read_text())["dataReleaseId"]
    output_parent = tmp_path / "retained" / release_id
    output_parent.mkdir(parents=True, mode=0o700)
    os.chmod(output_parent, 0o700)
    return candidate, evidence, crypto, public, output_parent / "supply-chain"


def test_retains_complete_schema_valid_release_lifetime_handoff(tmp_path: Path) -> None:
    candidate, evidence, crypto, public, output = _inputs(tmp_path)
    result = retention.retain_release_evidence(
        candidate,
        evidence,
        crypto,
        public,
        output,
        repository_root=ROOT,
    )
    receipt_raw = (output / "retention-receipt.json").read_bytes()
    receipt = json.loads(receipt_raw)
    Draft202012Validator(
        _load(ROOT / "contracts/supply-chain/v1/release-evidence-retention-receipt.schema.json")
    ).validate(receipt)
    assert receipt_raw == retention._canonical(receipt)
    assert result.deterministic_identity == receipt["deterministicIdentity"]
    assert result.retained_file_count == 18
    assert len(receipt["files"]) == 17
    assert [item["path"] for item in receipt["files"]] == sorted(
        item["path"] for item in receipt["files"]
    )
    assert {item["path"] for item in receipt["files"]} == {
        "manifest.json",
        "evidence-envelope.json",
        "manifest.sigstore.json",
        "provenance.intoto.jsonl",
        "provenance.sigstore.json",
        "receipts/cryptographic-verification.json",
        "receipts/public-readback.json",
        *retention._SBOM_PATHS,
    }
    for item in receipt["files"]:
        raw = (output / item["path"]).read_bytes()
        assert len(raw) == item["byteSize"]
        assert hashlib.sha256(raw).hexdigest() == item["sha256"]
        assert (output / item["path"]).stat().st_mode & 0o777 == 0o400
    assert output.stat().st_mode & 0o777 == 0o700


def test_refuses_overwrite_and_retains_first_committed_tree(tmp_path: Path) -> None:
    candidate, evidence, crypto, public, output = _inputs(tmp_path)
    first = retention.retain_release_evidence(
        candidate, evidence, crypto, public, output, repository_root=ROOT
    )
    identity = (output.stat().st_dev, output.stat().st_ino)
    with pytest.raises(SupplyChainContractError, match="already exists"):
        retention.retain_release_evidence(
            candidate, evidence, crypto, public, output, repository_root=ROOT
        )
    assert (output.stat().st_dev, output.stat().st_ino) == identity
    assert (
        json.loads((output / "retention-receipt.json").read_text())["deterministicIdentity"]
        == first.deterministic_identity
    )


@pytest.mark.parametrize("which", ["cryptographic", "readback"])
def test_rejects_receipt_tamper_before_publication(tmp_path: Path, which: str) -> None:
    candidate, evidence, crypto, public, output = _inputs(tmp_path)
    path = crypto if which == "cryptographic" else public
    document = json.loads(path.read_text())
    document["controlledBuildRunId"] = "999"
    path.chmod(0o600)
    path.write_bytes(retention._canonical(document))
    path.chmod(0o400)
    with pytest.raises(SupplyChainContractError, match="receipt|candidate runs"):
        retention.retain_release_evidence(
            candidate, evidence, crypto, public, output, repository_root=ROOT
        )
    assert not output.exists()


def test_rejects_foreign_or_missing_finalized_evidence(tmp_path: Path) -> None:
    candidate, evidence, crypto, public, output = _inputs(tmp_path)
    foreign = evidence / "foreign.txt"
    foreign.write_text("foreign", encoding="utf-8")
    foreign.chmod(0o400)
    with pytest.raises(SupplyChainContractError, match="entry limit|foreign or missing entry"):
        retention.retain_release_evidence(
            candidate, evidence, crypto, public, output, repository_root=ROOT
        )
    assert not output.exists()


def test_rejects_output_outside_exact_release_prefix(tmp_path: Path) -> None:
    candidate, evidence, crypto, public, output = _inputs(tmp_path)
    wrong = output.parent.parent / "wrong-release" / "supply-chain"
    wrong.parent.mkdir(mode=0o700)
    with pytest.raises(SupplyChainContractError, match="dataReleaseId/supply-chain"):
        retention.retain_release_evidence(
            candidate, evidence, crypto, public, wrong, repository_root=ROOT
        )


def test_staging_failure_never_creates_completion_path(tmp_path: Path, monkeypatch: Any) -> None:
    candidate, evidence, crypto, public, output = _inputs(tmp_path)
    original = retention._snapshot_fd
    calls = 0

    def fail_after_some(root: int, logical: Any, raw: bytes) -> None:
        nonlocal calls
        calls += 1
        if calls == 4:
            raise OSError("injected staging failure")
        original(root, logical, raw)

    monkeypatch.setattr(retention, "_snapshot_fd", fail_after_some)
    with pytest.raises(OSError, match="injected staging failure"):
        retention.retain_release_evidence(
            candidate, evidence, crypto, public, output, repository_root=ROOT
        )
    assert not output.exists()


def test_candidate_revalidation_failure_never_creates_completion_path(
    tmp_path: Path, monkeypatch: Any
) -> None:
    candidate, evidence, crypto, public, output = _inputs(tmp_path)
    original = retention.validate_candidate_root
    calls = 0

    def fail_revalidation(path: Path) -> Any:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise CandidateContractError(
                "candidate-revalidation", "injected candidate revalidation failure"
            )
        return original(path)

    monkeypatch.setattr(retention, "validate_candidate_root", fail_revalidation)
    with pytest.raises(SupplyChainContractError, match="candidate revalidation failure"):
        retention.retain_release_evidence(
            candidate, evidence, crypto, public, output, repository_root=ROOT
        )
    assert not output.exists()


def test_cli_prints_only_committed_identity(tmp_path: Path, capsys: Any) -> None:
    candidate, evidence, crypto, public, output = _inputs(tmp_path)
    result = _cli().main(
        [
            "--candidate-root",
            str(candidate),
            "--evidence-root",
            str(evidence),
            "--cryptographic-receipt",
            str(crypto),
            "--public-readback-receipt",
            str(public),
            "--repository-root",
            str(ROOT),
            "--output-root",
            str(output),
        ]
    )
    assert result == 0
    line = json.loads(capsys.readouterr().out)
    assert line == {
        "candidateId": json.loads((candidate / "manifest.json").read_text())["candidateId"],
        "dataReleaseId": output.parent.name,
        "deterministicIdentity": json.loads((output / "retention-receipt.json").read_text())[
            "deterministicIdentity"
        ],
        "retainedFileCount": 18,
    }
