"""Adversarial tests for the closed offline candidate/evidence pair boundary."""

from __future__ import annotations

import copy
import hashlib
import json
import runpy
import shutil
from pathlib import Path
from typing import Any, Callable, cast

import pytest

from searise_pipeline.candidate_completeness import (
    canonical_provenance_bytes,
    generate_provenance_statement,
)
from searise_pipeline.supply_chain import (
    SupplyChainContractError,
    validate_candidate_evidence_pair,
)
from searise_pipeline.supply_chain.sbom import canonical_sbom_bytes

ROOT = Path(__file__).resolve().parents[4]
INVOCATION = "https://github.com/artemsemdev/SeaRise-Europe/actions/runs/77777777777/attempts/1"
CANDIDATE = ROOT / "contracts/candidate-completeness/v1/fixtures/valid/engineering-candidate.json"
BUILD = ROOT / "contracts/release/v1/fixtures/valid/build-receipt.json"
SOURCE = ROOT / "contracts/release/v1/fixtures/valid/source-receipt.json"
ENVELOPE = ROOT / "contracts/supply-chain/v1/fixtures/valid/evidence-envelope.json"
POLICY = ROOT / "contracts/supply-chain/v1/identity-policy.json"
SBOMS = {
    "sbom/build-plane.cdx.json": "contracts/supply-chain/v1/sboms/build-plane.cdx.json",
    "sbom/frontend-npm.cdx.json": "contracts/supply-chain/v1/sboms/frontend-npm.cdx.json",
    "sbom/nuget/searise-api-net8.0.cdx.json": (
        "contracts/supply-chain/v1/sboms/nuget/searise-api-net8.0.cdx.json"
    ),
    "sbom/nuget/searise-application-net8.0.cdx.json": (
        "contracts/supply-chain/v1/sboms/nuget/searise-application-net8.0.cdx.json"
    ),
    "sbom/nuget/searise-domain-net8.0.cdx.json": (
        "contracts/supply-chain/v1/sboms/nuget/searise-domain-net8.0.cdx.json"
    ),
    "sbom/nuget/searise-infrastructure-net8.0.cdx.json": (
        "contracts/supply-chain/v1/sboms/nuget/searise-infrastructure-net8.0.cdx.json"
    ),
    "sbom/python-release-linux-x86-64-cp311.cdx.json": (
        "contracts/supply-chain/v1/sboms/python-release-linux-x86-64-cp311.cdx.json"
    ),
    "sbom/python-release-macos-arm64-cp311.cdx.json": (
        "contracts/supply-chain/v1/sboms/python-release-macos-arm64-cp311.cdx.json"
    ),
    "sbom/python-settlement-spatial-linux-x86-64-cp311.cdx.json": (
        "contracts/supply-chain/v1/sboms/python-settlement-spatial-linux-x86-64-cp311.cdx.json"
    ),
    "sbom/python-settlement-spatial-macos-arm64-cp311.cdx.json": (
        "contracts/supply-chain/v1/sboms/python-settlement-spatial-macos-arm64-cp311.cdx.json"
    ),
}
main = cast(
    Callable[..., int],
    runpy.run_path(str(ROOT / "scripts/release/validate_supply_chain_contract.py"))["main"],
)


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


def _pair(tmp_path: Path) -> tuple[Path, Path]:
    candidate_root, evidence_root = tmp_path / "candidate", tmp_path / "evidence"
    candidate = _load(CANDIDATE)
    build = _load(BUILD)
    build["dataReleaseId"] = candidate["dataReleaseId"]
    build["dataProvenanceClass"] = candidate["dataProvenanceClass"]
    build["sourceReceipts"] = [
        {"path": item["path"], "sha256": item["sha256"]}
        for item in candidate["artifacts"]
        if item["role"] == "source-receipt"
    ]
    output_roles = {"projection-geoparquet", "projection-analysis-cog", "projection-visual-pmtiles"}
    build["outputs"] = [
        {key: item[key] for key in ("path", "role", "mediaType", "byteSize", "sha256")}
        for item in candidate["artifacts"]
        if item["role"] in output_roles
    ]
    artifacts = {item["path"]: item for item in candidate["artifacts"]}
    checksums = {item["path"]: item for item in candidate["checksumInventory"]["subjects"]}
    for index, item in enumerate(build["sourceReceipts"]):
        receipt = _load(SOURCE)
        receipt.update(
            dataReleaseId=candidate["dataReleaseId"],
            dataProvenanceClass=candidate["dataProvenanceClass"],
            receiptId=f"source-fixture-{index:012x}",
            sourceId=f"fixture/source-{index}",
            sourceVersion=f"fixture-{index}",
            sourceUrl=f"https://fixtures.searise.invalid/source-{index}.bin",
            byteSize=index + 1,
            sha256=f"{index + 1:064x}",
            attributionId=artifacts[item["path"]]["rights"]["attributionIds"][0],
        )
        receipt["cache"]["key"] = f"sha256/{receipt['sha256']}"
        raw = canonical_provenance_bytes(receipt)
        source_path = candidate_root / item["path"]
        source_path.parent.mkdir(parents=True, exist_ok=True)
        source_path.write_bytes(raw)
        item["sha256"] = hashlib.sha256(raw).hexdigest()
        artifacts[item["path"]].update(sha256=item["sha256"], byteSize=len(raw))
        checksums[item["path"]]["sha256"] = item["sha256"]
    build_raw = _write(candidate_root / "receipts/build.json", build)
    build_artifact = next(
        item for item in candidate["artifacts"] if item["role"] == "build-receipt"
    )
    build_artifact["byteSize"] = len(build_raw)
    build_artifact["sha256"] = hashlib.sha256(build_raw).hexdigest()
    next(
        item
        for item in candidate["checksumInventory"]["subjects"]
        if item["path"] == build_artifact["path"]
    )["sha256"] = build_artifact["sha256"]
    manifest_raw = _write(candidate_root / "manifest.json", candidate)

    statement = generate_provenance_statement(
        candidate_root / "manifest.json",
        candidate_root / "receipts/build.json",
        trusted_invocation_uri=INVOCATION,
    )
    provenance_raw = canonical_provenance_bytes(statement)
    (evidence_root / "provenance.intoto.jsonl").parent.mkdir(parents=True, exist_ok=True)
    (evidence_root / "provenance.intoto.jsonl").write_bytes(provenance_raw)

    descriptors = []
    for logical_path, repository_path in sorted(SBOMS.items()):
        target = evidence_root / logical_path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / repository_path, target)
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
    envelope.update(
        {
            field: candidate[field]
            for field in ("candidateId", "dataReleaseId", "dataProvenanceClass")
        }
    )
    envelope["identityPolicy"]["sha256"] = hashlib.sha256(POLICY.read_bytes()).hexdigest()
    envelope["candidateManifest"]["sha256"] = hashlib.sha256(manifest_raw).hexdigest()
    envelope["provenance"]["sha256"] = hashlib.sha256(provenance_raw).hexdigest()
    envelope["softwareBillsOfMaterials"] = descriptors
    for signature, subject in zip(
        envelope["signatures"], (envelope["candidateManifest"], envelope["provenance"])
    ):
        signature["subjectPath"] = subject["path"]
        signature["subjectSha256"] = subject["sha256"]
    _write(evidence_root / "evidence-envelope.json", envelope)
    return candidate_root, evidence_root


def _validate(candidate: Path, evidence: Path) -> None:
    validate_candidate_evidence_pair(
        candidate,
        evidence,
        repository_root=ROOT,
        trusted_invocation_uri=INVOCATION,
    )


def test_valid_pair_preserves_nonclaims_and_cli_reports_them(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    candidate, evidence = _pair(tmp_path)

    summary = validate_candidate_evidence_pair(
        candidate, evidence, repository_root=ROOT, trusted_invocation_uri=INVOCATION
    )

    assert summary.sbom_count == 10
    assert summary.data_provenance_class == "synthetic-fixture"
    assert (
        not summary.cryptographic_verification
        and not summary.production
        and not summary.publication
    )
    assert (
        main(
            [
                "candidate-evidence-pair",
                "--candidate-root",
                str(candidate),
                "--evidence-root",
                str(evidence),
                "--repository-root",
                str(ROOT),
                "--trusted-invocation-uri",
                INVOCATION,
            ]
        )
        == 0
    )
    assert (
        "10 SBOMs; cryptographic verification, production, and publication not claimed"
        in capsys.readouterr().out
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("candidateId", "candidate-drift"),
        ("dataReleaseId", "searise-europe-v1.0.0-20260811-deadbeefcafe"),
        ("dataProvenanceClass", "real-source"),
    ],
)
def test_pair_identity_mismatch_fails(tmp_path: Path, field: str, value: str) -> None:
    candidate, evidence = _pair(tmp_path)
    envelope_path = evidence / "evidence-envelope.json"
    envelope = _load(envelope_path)
    envelope[field] = value
    _write(envelope_path, envelope)

    with pytest.raises(SupplyChainContractError, match=field):
        _validate(candidate, evidence)


@pytest.mark.parametrize("relative", ["manifest.json", "provenance.intoto.jsonl"])
def test_actual_pair_byte_tampering_fails(tmp_path: Path, relative: str) -> None:
    candidate, evidence = _pair(tmp_path)
    target = candidate / relative if relative == "manifest.json" else evidence / relative
    target.write_bytes(target.read_bytes() + b" ")

    with pytest.raises(SupplyChainContractError, match="manifest|provenance"):
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


@pytest.mark.parametrize("mutation", ["extra", "duplicate", "wrong-target"])
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
    else:
        envelope["signatures"][0]["subjectPath"] = "other.json"
    _write(envelope_path, envelope)

    with pytest.raises(SupplyChainContractError, match="signature|signed subject"):
        _validate(candidate, evidence)


@pytest.mark.parametrize("invalid", ["duplicate", "nan"])
def test_envelope_requires_strict_json(tmp_path: Path, invalid: str) -> None:
    candidate, evidence = _pair(tmp_path)
    envelope_path = evidence / "evidence-envelope.json"
    raw = envelope_path.read_bytes()
    if invalid == "duplicate":
        raw = raw.replace(
            b'{\n  "$schema"', b'{\n  "candidateId": "candidate-duplicate",\n  "$schema"'
        )
    else:
        raw = raw.replace(b'"fixtureOnly": true', b'"fixtureOnly": NaN')
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
