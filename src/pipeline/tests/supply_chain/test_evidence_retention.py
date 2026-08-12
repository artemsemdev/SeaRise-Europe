"""Local release evidence handoffs must be exact and initially no-overwrite."""

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
from jsonschema import Draft202012Validator, ValidationError

import searise_pipeline.supply_chain.evidence_retention as retention
import searise_pipeline.supply_chain.production_evidence as publication
from searise_pipeline.candidate_completeness import CandidateContractError
from searise_pipeline.candidate_completeness import validate_candidate_root as real_byte_gate
from searise_pipeline.supply_chain import SupplyChainContractError
from searise_pipeline.supply_chain.public_readback import _verify_public_signed_subjects
from searise_pipeline.supply_chain.sigstore_verifier import (
    verify_candidate_evidence_cryptographically,
)
from tests.supply_chain.test_candidate_evidence_pair import ROOT, _load, _pair
from tests.supply_chain.test_production_evidence import _inputs as _production_inputs
from tests.supply_chain.test_sigstore_verifier import RUN_ID, _production_envelope, _tool

CLI_PATH = ROOT / "scripts/release/retain_release_evidence.py"
VALIDATOR_CLI_PATH = ROOT / "scripts/release/validate_release_evidence_retention.py"


@pytest.fixture(autouse=True)
def _structural_fixture_has_byte_gate_authority(monkeypatch: Any) -> None:
    """The compact Sigstore fixture omits large artifact bytes tested by the byte gate."""

    def validate(root: Path | int) -> Any:
        if isinstance(root, int):
            descriptor = os.open("manifest.json", os.O_RDONLY, dir_fd=root)
            try:
                raw = b""
                while chunk := os.read(descriptor, 1024 * 1024):
                    raw += chunk
            finally:
                os.close(descriptor)
        else:
            raw = (root / "manifest.json").read_bytes()
        manifest = json.loads(raw)
        return SimpleNamespace(
            candidate_id=manifest["candidateId"],
            data_release_id=manifest["dataReleaseId"],
            artifact_count=len(manifest["artifacts"]),
            manifest_sha256=hashlib.sha256(raw).hexdigest(),
        )

    monkeypatch.setattr(retention, "validate_candidate_root", validate)


def _cli(path: Path = CLI_PATH) -> Any:
    spec = importlib.util.spec_from_file_location(f"retention_cli_{path.stem}", path)
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


def test_retains_complete_schema_valid_local_handoff(tmp_path: Path) -> None:
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
    assert receipt["handoff"] == {
        "class": "local-atomic-no-overwrite",
        "initialPublicationOverwriteAllowed": False,
        "externalRetentionPolicy": "required-not-verified",
        "deletionPrevention": "not-verified",
        "coRetentionWithDataRelease": "not-verified",
    }
    assert receipt["claims"] == {
        "exactLocalEvidenceSet": True,
        "cryptographicVerificationReceiptRetained": True,
        "publicReadbackReceiptRetained": True,
        "receiptAuthorityReverified": False,
        "productionClaim": False,
        "publicationApproval": False,
        "scientificApproval": False,
    }
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
    assert retention.validate_release_evidence_retention(output) == result


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
    assert not list(output.parent.glob(".evidence-incomplete-*"))


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
        if logical == retention._RETENTION:
            raise OSError("injected staging failure")
        original(root, logical, raw)

    monkeypatch.setattr(retention, "_snapshot_fd", fail_after_some)
    with pytest.raises(SupplyChainContractError, match="local evidence handoff"):
        retention.retain_release_evidence(
            candidate, evidence, crypto, public, output, repository_root=ROOT
        )
    assert not output.exists()
    residues = list(output.parent.glob(".evidence-incomplete-*"))
    assert len(residues) == 1
    assert residues[0].is_dir() and residues[0].stat().st_mode & 0o777 == 0o700


def test_candidate_revalidation_failure_never_creates_completion_path(
    tmp_path: Path, monkeypatch: Any
) -> None:
    candidate, evidence, crypto, public, output = _inputs(tmp_path)
    original = retention.validate_candidate_root
    calls = 0

    def fail_revalidation(path: Path | int) -> Any:
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
    assert _cli(VALIDATOR_CLI_PATH).main(["--retention-root", str(output)]) == 0
    assert json.loads(capsys.readouterr().out) == line


def test_public_schema_and_validator_reject_forged_inventory_and_identity(tmp_path: Path) -> None:
    candidate, evidence, crypto, public, output = _inputs(tmp_path)
    result = retention.retain_release_evidence(
        candidate, evidence, crypto, public, output, repository_root=ROOT
    )
    receipt_path = output / "retention-receipt.json"
    receipt_raw = receipt_path.read_bytes()
    receipt = json.loads(receipt_raw)
    schema = _load(
        ROOT / "contracts/supply-chain/v1/release-evidence-retention-receipt.schema.json"
    )

    duplicate = json.loads(json.dumps(receipt))
    duplicate["files"] = [duplicate["files"][0]] * 17
    with pytest.raises(ValidationError):
        Draft202012Validator(schema).validate(duplicate)

    forged = json.loads(json.dumps(receipt))
    forged["deterministicIdentity"] = "f" * 64
    receipt_path.chmod(0o600)
    receipt_path.write_bytes(retention._canonical(forged))
    receipt_path.chmod(0o400)
    with pytest.raises(SupplyChainContractError, match="deterministic identity"):
        retention.validate_release_evidence_retention(output)

    descriptor_forgery = json.loads(json.dumps(receipt))
    descriptor_forgery["files"][0]["sha256"] = "0" * 64
    unsigned = dict(descriptor_forgery)
    unsigned.pop("deterministicIdentity")
    descriptor_forgery["deterministicIdentity"] = hashlib.sha256(
        retention._canonical(unsigned)
    ).hexdigest()
    receipt_path.chmod(0o600)
    receipt_path.write_bytes(retention._canonical(descriptor_forgery))
    receipt_path.chmod(0o400)
    with pytest.raises(SupplyChainContractError, match="exact retained bytes"):
        retention.validate_release_evidence_retention(output)

    receipt_path.chmod(0o600)
    receipt_path.write_bytes(receipt_raw)
    receipt_path.chmod(0o400)
    assert retention.validate_release_evidence_retention(output) == result


def test_public_validator_rejects_foreign_entries_and_mutable_modes(tmp_path: Path) -> None:
    candidate, evidence, crypto, public, output = _inputs(tmp_path)
    retention.retain_release_evidence(
        candidate, evidence, crypto, public, output, repository_root=ROOT
    )
    foreign = output / "foreign.txt"
    foreign.write_bytes(b"foreign")
    foreign.chmod(0o400)
    with pytest.raises(SupplyChainContractError, match="entry limit|foreign or missing"):
        retention.validate_release_evidence_retention(output)
    foreign.unlink()
    manifest = output / "manifest.json"
    manifest.chmod(0o600)
    with pytest.raises(SupplyChainContractError, match="private regular file"):
        retention.validate_release_evidence_retention(output)


def test_semantic_validation_uses_exact_snapshots_across_root_aba(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    candidate, evidence, crypto, public, output = _inputs(tmp_path)
    original = retention._validate_candidate_evidence_pair
    displaced_candidate = candidate.with_name("candidate-held")
    displaced_evidence = evidence.with_name("evidence-held")

    def validate_snapshots(candidate_copy: Path, evidence_copy: Path, **kwargs: Any) -> Any:
        assert candidate_copy != candidate and evidence_copy != evidence
        candidate.rename(displaced_candidate)
        evidence.rename(displaced_evidence)
        candidate.mkdir(mode=0o700)
        evidence.mkdir(mode=0o700)
        try:
            return original(candidate_copy, evidence_copy, **kwargs)
        finally:
            candidate.rmdir()
            evidence.rmdir()
            displaced_candidate.rename(candidate)
            displaced_evidence.rename(evidence)

    monkeypatch.setattr(retention, "_validate_candidate_evidence_pair", validate_snapshots)
    with pytest.raises(SupplyChainContractError, match="tree.*changed|changed before"):
        retention.retain_release_evidence(
            candidate, evidence, crypto, public, output, repository_root=ROOT
        )
    assert not output.exists()


def test_receipt_path_race_fails_before_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    candidate, evidence, crypto, public, output = _inputs(tmp_path)
    original = retention._read_external
    mutated = False

    def race(path: Path, label: str, budget: Any) -> bytes:
        nonlocal mutated
        raw = original(path, label, budget)
        if path == crypto and not mutated:
            document = json.loads(raw)
            document["cosign"]["executableSha256"] = "0" * 64
            path.chmod(0o600)
            path.write_bytes(retention._canonical(document))
            path.chmod(0o400)
            mutated = True
        return raw

    monkeypatch.setattr(retention, "_read_external", race)
    with pytest.raises(SupplyChainContractError, match="changed before retention publication"):
        retention.retain_release_evidence(
            candidate, evidence, crypto, public, output, repository_root=ROOT
        )
    assert not output.exists()
    assert len(list(output.parent.glob(".evidence-incomplete-*"))) == 1


@pytest.mark.parametrize("failure", ["rename", "parent-fsync"])
def test_publication_filesystem_failures_are_normalized_and_quarantined(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    candidate, evidence, crypto, public, output = _inputs(tmp_path)
    if failure == "rename":
        monkeypatch.setattr(
            publication,
            "_rename_exclusive",
            lambda *args, **kwargs: (_ for _ in ()).throw(OSError("injected rename failure")),
        )
    else:
        real_fsync = publication.os.fsync
        parent_identity = (output.parent.stat().st_dev, output.parent.stat().st_ino)
        raised = False

        def fail_parent_fsync(descriptor: int) -> None:
            nonlocal raised
            current = os.fstat(descriptor)
            if not raised and (current.st_dev, current.st_ino) == parent_identity:
                raised = True
                raise OSError("injected parent fsync failure")
            real_fsync(descriptor)

        monkeypatch.setattr(publication.os, "fsync", fail_parent_fsync)
    with pytest.raises(SupplyChainContractError, match="publish|handoff"):
        retention.retain_release_evidence(
            candidate, evidence, crypto, public, output, repository_root=ROOT
        )
    assert not output.exists()
    assert len(list(output.parent.glob(".evidence-incomplete-*"))) == 1


def test_output_parent_displacement_is_quarantined_before_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    candidate, evidence, crypto, public, output = _inputs(tmp_path)
    original = retention._publish
    displaced = output.parent.with_name("displaced-release-parent")

    def displace(*args: Any, **kwargs: Any) -> None:
        original(*args, **kwargs)
        output.parent.rename(displaced)
        output.parent.mkdir(mode=0o700)

    monkeypatch.setattr(retention, "_publish", displace)
    with pytest.raises(SupplyChainContractError, match="output parent.*changed"):
        retention.retain_release_evidence(
            candidate, evidence, crypto, public, output, repository_root=ROOT
        )
    assert not output.exists()
    assert len(list(displaced.glob(".evidence-incomplete-*"))) == 1


def test_symlink_input_roots_and_receipts_fail_closed(tmp_path: Path) -> None:
    candidate, evidence, crypto, public, output = _inputs(tmp_path)
    candidate_link = tmp_path / "candidate-link"
    candidate_link.symlink_to(candidate, target_is_directory=True)
    with pytest.raises(SupplyChainContractError, match="without symlinks"):
        retention.retain_release_evidence(
            candidate_link, evidence, crypto, public, output, repository_root=ROOT
        )
    crypto_link = tmp_path / "cryptographic-link.json"
    crypto_link.symlink_to(crypto)
    with pytest.raises(SupplyChainContractError, match="without symlinks"):
        retention.retain_release_evidence(
            candidate, evidence, crypto_link, public, output, repository_root=ROOT
        )
    special = tmp_path / "cryptographic.fifo"
    os.mkfifo(special, 0o400)
    with pytest.raises(SupplyChainContractError, match="regular file"):
        retention.retain_release_evidence(
            candidate, evidence, special, public, output, repository_root=ROOT
        )
    assert not output.exists()


def test_clis_normalize_expected_filesystem_failures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    retain_cli = _cli()

    def fail(*args: Any, **kwargs: Any) -> Any:
        raise OSError("injected filesystem failure")

    monkeypatch.setattr(retain_cli, "retain_release_evidence", fail)
    args = [
        "--candidate-root",
        str(tmp_path / "candidate"),
        "--evidence-root",
        str(tmp_path / "evidence"),
        "--cryptographic-receipt",
        str(tmp_path / "crypto.json"),
        "--public-readback-receipt",
        str(tmp_path / "readback.json"),
        "--repository-root",
        str(ROOT),
        "--output-root",
        str(tmp_path / "release" / "supply-chain"),
    ]
    assert retain_cli.main(args) == 2
    assert capsys.readouterr().err == "error: injected filesystem failure\n"

    validator_cli = _cli(VALIDATOR_CLI_PATH)
    assert validator_cli.main(["--retention-root", str(tmp_path / "missing")]) == 2
    captured = capsys.readouterr()
    assert captured.out == "" and captured.err.startswith("error: ")


def test_real_candidate_byte_gate_authorizes_retained_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(retention, "validate_candidate_root", real_byte_gate)
    candidate, _, _ = _production_inputs(tmp_path / "real")
    descriptor = retention._open_root(candidate, "real candidate byte gate")
    try:
        summary = retention._candidate(descriptor)
    finally:
        os.close(descriptor)
    manifest_raw = (candidate / "manifest.json").read_bytes()
    assert summary.artifact_count == 53
    assert summary.manifest_sha256 == hashlib.sha256(manifest_raw).hexdigest()
