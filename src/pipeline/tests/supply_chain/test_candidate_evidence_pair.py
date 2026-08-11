"""Adversarial tests for the closed offline candidate/evidence pair boundary."""

from __future__ import annotations

import base64
import copy
import hashlib
import json
import os
import runpy
import shutil
from pathlib import Path
from typing import Any

import pytest

import searise_pipeline.supply_chain.candidate_evidence as pair_validation
from searise_pipeline.candidate_completeness import (
    canonical_provenance_bytes,
    generate_provenance_statement,
)
from searise_pipeline.supply_chain import (
    SupplyChainContractError,
    validate_candidate_evidence_pair,
)
from searise_pipeline.supply_chain.sbom import canonical_sbom_bytes
from tests.contracts.test_provenance_statement import _documents, _write_pair

ROOT = Path(__file__).resolve().parents[4]
INVOCATION = "https://github.com/artemsemdev/SeaRise-Europe/actions/runs/77777777777/attempts/1"
ENVELOPE = ROOT / "contracts/supply-chain/v1/fixtures/valid/evidence-envelope.json"
POLICY = ROOT / "contracts/supply-chain/v1/identity-policy.json"
SBOM_ROOT = ROOT / "contracts/supply-chain/v1/sboms"
main = runpy.run_path(str(ROOT / "scripts/release/validate_supply_chain_contract.py"))["main"]


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, document: dict[str, Any], *, canonical: bool = False) -> bytes:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (
        canonical_sbom_bytes(document)
        if canonical
        else (json.dumps(document, indent=2) + "\n").encode()
    )
    path.write_bytes(raw)
    return raw


def _b64(value: bytes) -> str:
    return base64.b64encode(value).decode()


def _pair(tmp_path: Path) -> tuple[Path, Path]:
    candidate_root, evidence_root = tmp_path / "candidate", tmp_path / "evidence"
    candidate, build = _documents()
    manifest_path, build_path = _write_pair(candidate_root, candidate, build)
    manifest_raw = manifest_path.read_bytes()

    statement = generate_provenance_statement(
        manifest_path,
        build_path,
        trusted_invocation_uri=INVOCATION,
    )
    provenance_raw = canonical_provenance_bytes(statement)
    (evidence_root / "provenance.intoto.jsonl").parent.mkdir(parents=True, exist_ok=True)
    (evidence_root / "provenance.intoto.jsonl").write_bytes(provenance_raw)

    descriptors = []
    for repository_path in sorted(SBOM_ROOT.rglob("*.cdx.json")):
        logical_path = f"sbom/{repository_path.relative_to(SBOM_ROOT).as_posix()}"
        target = evidence_root / logical_path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(repository_path, target)
        descriptors.append(
            {
                "role": "software-bill-of-materials",
                "path": logical_path,
                "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
                "mediaType": "application/vnd.cyclonedx+json",
                "bomFormat": "CycloneDX",
                "specVersion": "1.7",
            }
        )
    envelope = _load(ENVELOPE)
    for field in ("candidateId", "dataReleaseId", "dataProvenanceClass"):
        envelope[field] = candidate[field]
    envelope["identityPolicy"]["sha256"] = hashlib.sha256(POLICY.read_bytes()).hexdigest()
    envelope["candidateManifest"]["sha256"] = hashlib.sha256(manifest_raw).hexdigest()
    envelope["candidateManifest"]["byteSize"] = len(manifest_raw)
    envelope["provenance"]["sha256"] = hashlib.sha256(provenance_raw).hexdigest()
    envelope["provenance"]["byteSize"] = len(provenance_raw)
    envelope["softwareBillsOfMaterials"] = descriptors
    for signature, subject in zip(
        envelope["signatures"], (envelope["candidateManifest"], envelope["provenance"])
    ):
        signature["subjectPath"] = subject["path"]
        signature["subjectSha256"] = subject["sha256"]
        subject_raw = manifest_raw if subject["path"] == "manifest.json" else provenance_raw
        bundle = _load(ENVELOPE.parent / signature["path"])
        bundle["messageSignature"]["messageDigest"]["digest"] = _b64(
            hashlib.sha256(subject_raw).digest()
        )
        bundle_raw = _write(evidence_root / signature["path"], bundle, canonical=True)
        signature.update(sha256=hashlib.sha256(bundle_raw).hexdigest(), byteSize=len(bundle_raw))
    _write(evidence_root / "evidence-envelope.json", envelope)
    return candidate_root, evidence_root


def _validate(candidate: Path, evidence: Path, repository: Path = ROOT) -> Any:
    return validate_candidate_evidence_pair(
        candidate,
        evidence,
        repository_root=repository,
        trusted_invocation_uri=INVOCATION,
    )


def test_valid_pair_preserves_nonclaims_and_cli_reports_them(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    candidate, evidence = _pair(tmp_path)
    summary = _validate(candidate, evidence)
    assert summary.sbom_count == 10
    assert summary.data_provenance_class == "synthetic-fixture"
    assert (summary.cryptographic_verification, summary.production, summary.publication) == (
        False,
        False,
        False,
    )
    args = ["candidate-evidence-pair"]
    for flag, value in (
        ("candidate-root", candidate),
        ("evidence-root", evidence),
        ("repository-root", ROOT),
        ("trusted-invocation-uri", INVOCATION),
    ):
        args.extend((f"--{flag}", str(value)))
    assert main(args) == 0
    assert (
        "10 SBOMs; cryptographic verification, production, and publication not claimed"
        in capsys.readouterr().out
    )


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("candidateId",), "candidate-drift"),
        (("dataReleaseId",), "searise-europe-v1.0.0-20260811-deadbeefcafe"),
        (("dataProvenanceClass",), "real-source"),
        (("candidateManifest", "byteSize"), 1),
        (("provenance", "byteSize"), 1),
        (("candidateManifest", "byteSize"), None),
        (("provenance", "byteSize"), None),
    ],
)
def test_pair_descriptor_mismatch_fails(tmp_path: Path, path: tuple[str, ...], value: Any) -> None:
    candidate, evidence = _pair(tmp_path)
    envelope_path = evidence / "evidence-envelope.json"
    envelope = _load(envelope_path)
    target = envelope
    for field in path[:-1]:
        target = target[field]
    if value is None:
        target.pop(path[-1])
    else:
        target[path[-1]] = value
    _write(envelope_path, envelope)
    with pytest.raises(SupplyChainContractError):
        _validate(candidate, evidence)


@pytest.mark.parametrize("mutation", ["missing", "extra", "reordered"])
def test_sbom_descriptor_set_and_order_are_exact(tmp_path: Path, mutation: str) -> None:
    candidate, evidence = _pair(tmp_path)
    envelope_path = evidence / "evidence-envelope.json"
    envelope = _load(envelope_path)
    if mutation == "missing":
        envelope["softwareBillsOfMaterials"].pop()
    elif mutation == "extra":
        extra = copy.deepcopy(envelope["softwareBillsOfMaterials"][-1])
        extra["path"] = "sbom/unapproved.cdx.json"
        envelope["softwareBillsOfMaterials"].append(extra)
    else:
        envelope["softwareBillsOfMaterials"].reverse()
    _write(envelope_path, envelope)
    with pytest.raises(SupplyChainContractError, match="exact sorted ten"):
        _validate(candidate, evidence)


def test_sbom_actual_hash_and_regeneration_are_both_required(tmp_path: Path) -> None:
    candidate, evidence = _pair(tmp_path)
    logical = "sbom/frontend-npm.cdx.json"
    sbom_path = evidence / logical
    document = _load(sbom_path)
    document["version"] = 2
    changed = _write(sbom_path, document, canonical=True)
    with pytest.raises(SupplyChainContractError, match="SHA-256 mismatch"):
        _validate(candidate, evidence)
    envelope_path = evidence / "evidence-envelope.json"
    envelope = _load(envelope_path)
    next(item for item in envelope["softwareBillsOfMaterials"] if item["path"] == logical)[
        "sha256"
    ] = hashlib.sha256(changed).hexdigest()
    _write(envelope_path, envelope)
    with pytest.raises(SupplyChainContractError, match="lock authority"):
        _validate(candidate, evidence)


@pytest.mark.parametrize(
    "mutation",
    "extra duplicate wrong-target missing directory malformed hash size symlink digest".split(),
)
def test_exactly_two_unique_signature_descriptors_are_required(
    tmp_path: Path, mutation: str
) -> None:
    candidate, evidence = _pair(tmp_path)
    envelope_path = evidence / "evidence-envelope.json"
    envelope = _load(envelope_path)
    if mutation == "extra":
        extra = copy.deepcopy(envelope["signatures"][0])
        extra["path"] = "extra.sigstore.json"
        envelope["signatures"].append(extra)
    elif mutation == "duplicate":
        envelope["signatures"].append(copy.deepcopy(envelope["signatures"][0]))
    elif mutation == "wrong-target":
        envelope["signatures"][0]["subjectPath"] = "other.json"
    else:
        descriptor = envelope["signatures"][0]
        bundle_path = evidence / descriptor["path"]
        if mutation == "missing":
            bundle_path.unlink()
        elif mutation == "directory":
            bundle_path.unlink()
            bundle_path.mkdir()
        elif mutation == "hash":
            descriptor["sha256"] = "0" * 64
        elif mutation == "size":
            descriptor["byteSize"] += 1
        elif mutation == "symlink":
            outside = tmp_path / "signature-copy.json"
            shutil.copy2(bundle_path, outside)
            bundle_path.unlink()
            bundle_path.symlink_to(outside)
        else:
            bundle = _load(bundle_path)
            if mutation == "digest":
                bundle["messageSignature"]["messageDigest"]["digest"] = _b64(b"0" * 32)
            else:
                bundle["messageSignature"]["signature"] = "!"
            raw = _write(bundle_path, bundle, canonical=True)
            descriptor.update(sha256=hashlib.sha256(raw).hexdigest(), byteSize=len(raw))
    _write(envelope_path, envelope)
    with pytest.raises(SupplyChainContractError, match="signature|signed subject|symlinks"):
        _validate(candidate, evidence)


def test_tlog_entry_is_the_exact_hashedrekord_subset() -> None:
    cases = [
        (("kindVersion", "kind"), "rekord"),
        (("kindVersion", "version"), "1"),
        (("kindVersion", "extra"), 0),
        (("inclusionPromise", "extra"), "x"),
        (("logId", "extra"), "x"),
        (("inclusionPromise",), []),
        (("inclusionProof",), {}),
    ]
    cases += [
        ((field,), value)
        for field in ("integratedTime", "logIndex")
        for value in (None, True, "1", -1)
    ]
    subject = b"subject"
    bundle = _load(ENVELOPE.parent / "manifest.sigstore.json")
    bundle["messageSignature"]["messageDigest"]["digest"] = _b64(hashlib.sha256(subject).digest())
    for path, value in cases:
        mutated = copy.deepcopy(bundle)
        target = mutated["verificationMaterial"]["tlogEntries"][0]
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = value
        with pytest.raises(SupplyChainContractError, match="hashedrekord subset"):
            pair_validation._validate_bundle(mutated, subject, "signature")


@pytest.mark.parametrize("invalid", ["duplicate", "nan", "surrogate", "deep"])
def test_envelope_requires_strict_json(tmp_path: Path, invalid: str) -> None:
    candidate, evidence = _pair(tmp_path)
    envelope_path = evidence / "evidence-envelope.json"
    raw = envelope_path.read_bytes()
    if invalid == "duplicate":
        raw = raw.replace(
            b'{\n  "$schema"', b'{\n  "candidateId": "candidate-duplicate",\n  "$schema"'
        )
    elif invalid == "nan":
        raw = raw.replace(b'"fixtureOnly": true', b'"fixtureOnly": NaN')
    elif invalid == "surrogate":
        raw = raw.replace(b'"reason": "', b'"reason": "\\ud800')
    else:
        raw = b'{"nested":' + (b"[" * 2000) + b"0" + (b"]" * 2000) + b"}"
    envelope_path.write_bytes(raw)
    with pytest.raises(SupplyChainContractError, match="strict UTF-8 JSON"):
        _validate(candidate, evidence)


@pytest.mark.parametrize("target", ["root", "nested"])
def test_candidate_and_evidence_paths_reject_symlinks(tmp_path: Path, target: str) -> None:
    candidate, evidence = _pair(tmp_path / "real")
    if target == "root":
        linked = tmp_path / "candidate-link"
        linked.symlink_to(candidate, target_is_directory=True)
        candidate = linked
    else:
        provenance = evidence / "provenance.intoto.jsonl"
        outside = tmp_path / "provenance-copy.jsonl"
        shutil.copy2(provenance, outside)
        provenance.unlink()
        provenance.symlink_to(outside)
    with pytest.raises(SupplyChainContractError, match="without symlinks"):
        _validate(candidate, evidence)


@pytest.mark.parametrize("mutation", ["symlink", "swap"])
def test_identity_policy_is_descriptor_safe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation: str
) -> None:
    candidate, evidence = _pair(tmp_path / "pair")
    repository = tmp_path / "repository"
    policy = repository / POLICY.relative_to(ROOT)
    policy.parent.mkdir(parents=True)
    shutil.copy2(POLICY, policy)
    replacement = tmp_path / "identity-policy-copy.json"
    shutil.copy2(POLICY, replacement)
    if mutation == "symlink":
        policy.unlink()
        policy.symlink_to(replacement)
    else:
        real_read = os.read
        inode = policy.stat().st_ino
        swapped = False

        def swap(descriptor: int, count: int) -> bytes:
            nonlocal swapped
            raw = real_read(descriptor, count)
            if not swapped and os.fstat(descriptor).st_ino == inode:
                replacement.replace(policy)
                swapped = True
            return raw

        monkeypatch.setattr(pair_validation.os, "read", swap)
    with pytest.raises(SupplyChainContractError, match="identity policy.*(symlinks|changed)"):
        _validate(candidate, evidence, repository)
