"""Tamper matrix for identity-bound cryptographic candidate verification."""

from __future__ import annotations

import hashlib
import inspect
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator, ValidationError

import searise_pipeline.supply_chain as supply_chain
import searise_pipeline.supply_chain.sigstore_verifier as verifier
from searise_pipeline.supply_chain import (
    SupplyChainContractError,
    validate_candidate_evidence_pair,
    verify_candidate_evidence_cryptographically,
)
from tests.supply_chain.test_candidate_evidence_pair import ROOT, _load, _pair, _write

RUN_ID = "77777777777"


def _tool(tmp_path: Path, mode: str = "ok") -> tuple[Path, Path]:
    executable = tmp_path / "reviewed-cosign"
    behavior = {
        "ok": 'print("Verified OK")',
        "nonzero": 'print("rejected", file=sys.stderr); raise SystemExit(1)',
        "second-nonzero": 'p=pathlib.Path(os.environ["HOME"])/"calls"; n=int(p.read_text()) if p.exists() else 0; p.parent.mkdir(exist_ok=True); p.write_text(str(n+1)); print("Verified OK") if n == 0 else sys.exit(1)',  # noqa: E501
        "malformed": 'print("verification maybe succeeded")',
    }[mode]
    script = f"""#!{Path(sys.executable).resolve()}
import os, pathlib, sys
expected = [
    "verify-blob", "--bundle", sys.argv[3],
    "--certificate-identity", {verifier._IDENTITY!r},
    "--certificate-oidc-issuer", {verifier._ISSUER!r}, sys.argv[-1],
]
if sys.argv[1:] != expected:
    raise SystemExit(9)
{behavior}
""".encode()
    executable.write_bytes(script)
    executable.chmod(0o700)
    lock = tmp_path / "cosign-tool-lock.json"
    lock.write_text(
        json.dumps(
            {
                "$schema": "https://artemsemdev.github.io/SeaRise-Europe/contracts/supply-chain/v1/cosign-tool-lock.schema.json",
                "schemaVersion": "1.0.0",
                "contractId": "phase-1-cosign-linux-amd64-v1",
                "tool": "cosign",
                "version": "3.0.6",
                "platform": "linux-amd64",
                "releaseUrl": "https://github.com/sigstore/cosign/releases/tag/v3.0.6",
                "executable": {
                    "name": "cosign-linux-amd64",
                    "url": "https://github.com/sigstore/cosign/releases/download/v3.0.6/cosign-linux-amd64",
                    "sha256": hashlib.sha256(script).hexdigest(),
                    "byteSize": len(script),
                },
                "checksumEvidence": {
                    "name": "cosign_checksums.txt",
                    "url": "https://github.com/sigstore/cosign/releases/download/v3.0.6/cosign_checksums.txt",
                    "sha256": "0" * 64,
                    "byteSize": 1,
                    "entry": f"{hashlib.sha256(script).hexdigest()}  cosign-linux-amd64",
                },
            },
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    )
    return executable, lock


def _verify(
    candidate: Path,
    evidence: Path,
    tool: Path,
    lock: Path,
    *,
    run_id: str = RUN_ID,
    receipt_path: Path | None = None,
) -> Any:
    return verify_candidate_evidence_cryptographically(
        candidate,
        evidence,
        repository_root=ROOT,
        controlled_build_run_id=run_id,
        cosign_executable=tool,
        cosign_tool_lock=lock,
        trusted_cosign_tool_lock_sha256=hashlib.sha256(lock.read_bytes()).hexdigest(),
        receipt_path=receipt_path,
    )


def _production_envelope(evidence: Path) -> None:
    path = evidence / "evidence-envelope.json"
    envelope = _load(path)
    envelope["verification"].update(
        status="verified-production",
        fixtureOnly=False,
        verified=True,
        policySatisfied=True,
        productionClaim=True,
        reason=None,
    )
    _write(path, envelope)


def test_exact_pair_atomically_publishes_canonical_receipt(tmp_path: Path) -> None:
    candidate, evidence = _pair(tmp_path / "pair")
    _production_envelope(evidence)
    tool, lock = _tool(tmp_path)
    with pytest.raises(SupplyChainContractError, match="separate cryptographic verifier"):
        validate_candidate_evidence_pair(
            candidate,
            evidence,
            repository_root=ROOT,
            trusted_invocation_uri=f"https://github.com/artemsemdev/SeaRise-Europe/actions/runs/{RUN_ID}/attempts/1",
        )
    receipt_path = tmp_path / "verification.json"
    verification = _verify(candidate, evidence, tool, lock, receipt_path=receipt_path)
    receipt = verification.receipt
    receipt_schema = _load(
        ROOT / "contracts/supply-chain/v1/cryptographic-verification-receipt.schema.json"
    )
    Draft202012Validator(receipt_schema).validate(receipt)
    duplicate = json.loads(json.dumps(receipt))
    duplicate["subjects"][1] = duplicate["subjects"][0]
    with pytest.raises(ValidationError):
        Draft202012Validator(receipt_schema).validate(duplicate)
    assert (
        verification.receipt_bytes
        == (
            json.dumps(receipt, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n"
        ).encode()
    )
    assert receipt["trustedInvocationUri"].endswith(f"/runs/{RUN_ID}/attempts/1")
    assert [item["path"] for item in receipt["subjects"]] == [
        "manifest.json",
        "provenance.intoto.jsonl",
    ]
    assert receipt["claims"] == json.loads(
        '{"certificateWorkflowIdentityVerified":true,"oidcIssuerVerified":true,"protectedEnvironmentVerified":false,"subjectDigestsVerified":true,"productionClaim":false,"publicationClaim":false,"scientificApproval":false}'
    )  # noqa: E501
    assert receipt_path.read_bytes() == verification.receipt_bytes


def test_real_source_candidate_reaches_cryptographic_verifier(tmp_path: Path) -> None:
    candidate, evidence = _pair(tmp_path / "pair", data_provenance_class="real-source")
    _production_envelope(evidence)
    tool, lock = _tool(tmp_path)

    verification = _verify(candidate, evidence, tool, lock)

    assert verification.receipt["dataProvenanceClass"] == "real-source"
    assert verification.receipt["claims"] == {
        "certificateWorkflowIdentityVerified": True,
        "oidcIssuerVerified": True,
        "protectedEnvironmentVerified": False,
        "subjectDigestsVerified": True,
        "productionClaim": False,
        "publicationClaim": False,
        "scientificApproval": False,
    }


@pytest.mark.parametrize("field", ["protectedEnvironment", "bundleMediaType"])
def test_entire_identity_policy_is_authoritative(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, field: str
) -> None:
    candidate, evidence = _pair(tmp_path / "pair")
    tool, lock = _tool(tmp_path)
    strict_json = verifier._strict_json

    def mutate(raw: bytes, label: str) -> dict[str, Any]:
        document = strict_json(raw, label)
        if label == "identity policy":
            document[field] = "unreviewed"
        return document

    monkeypatch.setattr(verifier, "_strict_json", mutate)
    with pytest.raises(SupplyChainContractError, match="exact production signing identity"):
        _verify(candidate, evidence, tool, lock)


@pytest.mark.parametrize("mode", ["nonzero", "second-nonzero", "malformed"])
def test_cosign_failure_and_unexpected_output_fail_closed(tmp_path: Path, mode: str) -> None:
    candidate, evidence = _pair(tmp_path / "pair")
    _production_envelope(evidence)
    tool, lock = _tool(tmp_path, mode)
    receipt_path = tmp_path / "verification.json"
    with pytest.raises(SupplyChainContractError, match="Cosign (rejected|returned)"):
        _verify(candidate, evidence, tool, lock, receipt_path=receipt_path)
    assert not receipt_path.exists()


def test_schema_valid_forged_receipt_has_no_publication_api(tmp_path: Path) -> None:
    candidate, evidence = _pair(tmp_path / "pair")
    tool, lock = _tool(tmp_path)
    verification = _verify(candidate, evidence, tool, lock)
    forged = json.loads(json.dumps(verification.receipt))
    forged["subjects"][0]["sha256"] = "0" * 64
    receipt_schema = _load(
        ROOT / "contracts/supply-chain/v1/cryptographic-verification-receipt.schema.json"
    )
    Draft202012Validator(receipt_schema).validate(forged)
    assert verifier._strict_json(verifier._canonical(forged), "forged receipt") == forged
    assert not hasattr(supply_chain, "CryptographicVerification")
    assert not hasattr(supply_chain, "publish_cryptographic_verification_receipt")
    assert (
        "receipt_bytes"
        not in inspect.signature(verify_candidate_evidence_cryptographically).parameters
    )


def test_root_generation_swap_fails_after_snapshot_validation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    candidate, evidence = _pair(tmp_path / "active")
    replacement_candidate, replacement_evidence = _pair(tmp_path / "replacement")
    tool, lock = _tool(tmp_path)
    structural = verifier._validate_candidate_evidence_pair

    def swap(*args: Any, **kwargs: Any) -> Any:
        summary = structural(*args, **kwargs)
        candidate.rename(tmp_path / "retired-candidate")
        replacement_candidate.rename(candidate)
        evidence.rename(tmp_path / "retired-evidence")
        replacement_evidence.rename(evidence)
        return summary

    monkeypatch.setattr(verifier, "_validate_candidate_evidence_pair", swap)
    with pytest.raises(SupplyChainContractError, match="root generation changed"):
        _verify(candidate, evidence, tool, lock)


def test_cosign_symlink_and_read_swap_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    candidate, evidence = _pair(tmp_path / "pair")
    tool, lock = _tool(tmp_path)
    real_tool = tmp_path / "real-cosign"
    tool.replace(real_tool)
    tool.symlink_to(real_tool)
    with pytest.raises(SupplyChainContractError, match="without symlinks"):
        _verify(candidate, evidence, tool, lock)

    tool.unlink()
    shutil.copy2(real_tool, tool)
    replacement = tmp_path / "replacement-cosign"
    shutil.copy2(real_tool, replacement)
    inode = tool.stat().st_ino
    swapped = False
    real_read = os.read

    def swap(descriptor: int, count: int) -> bytes:
        nonlocal swapped
        raw = real_read(descriptor, count)
        if not swapped and os.fstat(descriptor).st_ino == inode:
            replacement.replace(tool)
            swapped = True
        return raw

    monkeypatch.setattr(verifier.os, "read", swap)
    with pytest.raises(SupplyChainContractError, match="changed while it was read"):
        _verify(candidate, evidence, tool, lock)
