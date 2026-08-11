"""Tests for the private real-source pre-verification evidence boundary."""

from __future__ import annotations

import base64
import copy
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

import searise_pipeline.supply_chain.contracts as contracts
from searise_pipeline.supply_chain import SupplyChainContractError

REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
CONTRACT_ROOT = REPOSITORY_ROOT / "contracts" / "supply-chain" / "v1"
VALID_ROOT = CONTRACT_ROOT / "fixtures" / "valid"
POLICY = CONTRACT_ROOT / "identity-policy.json"
SCHEMA_URI = (
    "https://artemsemdev.github.io/SeaRise-Europe/contracts/supply-chain/v1/"
    "real-source-unverified-evidence-envelope.schema.json"
)
SIGNATURE_PATHS = ("manifest.sigstore.json", "provenance.sigstore.json")
SBOM_PATHS = (
    "sbom/build-plane.cdx.json",
    "sbom/frontend-npm.cdx.json",
    "sbom/nuget/searise-api-net8.0.cdx.json",
    "sbom/nuget/searise-application-net8.0.cdx.json",
    "sbom/nuget/searise-domain-net8.0.cdx.json",
    "sbom/nuget/searise-infrastructure-net8.0.cdx.json",
    "sbom/python-release-linux-x86-64-cp311.cdx.json",
    "sbom/python-release-macos-arm64-cp311.cdx.json",
    "sbom/python-settlement-spatial-linux-x86-64-cp311.cdx.json",
    "sbom/python-settlement-spatial-macos-arm64-cp311.cdx.json",
)
REASON = (
    "Cryptographic verification has not run; no signing, identity, environment, "
    "production, publication, or scientific approval claim is made."
)


@dataclass
class EvidenceInputs:
    envelope: bytes
    manifest: bytes
    provenance: bytes
    policy: bytes
    bundles: dict[str, bytes]
    sboms: dict[str, bytes]


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _descriptor(path: str, raw: bytes, **fields: object) -> dict[str, object]:
    return {"path": path, "sha256": _sha256(raw), "byteSize": len(raw), **fields}


def _bundle(path: str, subject: bytes) -> bytes:
    bundle = json.loads((VALID_ROOT / path).read_bytes())
    bundle["messageSignature"]["messageDigest"]["digest"] = base64.b64encode(
        hashlib.sha256(subject).digest()
    ).decode("ascii")
    return (json.dumps(bundle, separators=(",", ":")) + "\n").encode()


def _evidence_inputs(tmp_path: Path) -> EvidenceInputs:
    manifest = b'{"candidate":"real-source"}\n'
    provenance = b'{"_type":"https://in-toto.io/Statement/v1"}\n'
    policy = POLICY.read_bytes()
    bundles = {
        SIGNATURE_PATHS[0]: _bundle(SIGNATURE_PATHS[0], manifest),
        SIGNATURE_PATHS[1]: _bundle(SIGNATURE_PATHS[1], provenance),
    }
    sboms = {
        logical: (CONTRACT_ROOT / logical.replace("sbom/", "sboms/", 1)).read_bytes()
        for logical in SBOM_PATHS
    }
    signatures = [
        _descriptor(
            logical,
            bundles[logical],
            role="signature",
            mediaType="application/vnd.dev.sigstore.bundle+json;version=0.3",
            subjectPath=subject,
            subjectSha256=_sha256(manifest if index == 0 else provenance),
        )
        for index, (logical, subject) in enumerate(
            zip(SIGNATURE_PATHS, ("manifest.json", "provenance.intoto.jsonl"))
        )
    ]
    envelope = {
        "$schema": SCHEMA_URI,
        "schemaVersion": "1.0.0",
        "contractId": "phase-1-real-source-unverified-evidence-v1",
        "candidateId": "candidate-real-source-20260812-0123456789ab",
        "dataReleaseId": "searise-europe-v1.0.0-20260812-0123456789ab",
        "dataProvenanceClass": "real-source",
        "candidateManifest": _descriptor("manifest.json", manifest),
        "identityPolicy": {
            "path": "contracts/supply-chain/v1/identity-policy.json",
            "sha256": _sha256(policy),
        },
        "provenance": _descriptor(
            "provenance.intoto.jsonl",
            provenance,
            role="provenance",
            mediaType="application/vnd.in-toto+json",
            statementType="https://in-toto.io/Statement/v1",
            predicateType="https://slsa.dev/provenance/v1",
        ),
        "signatures": signatures,
        "softwareBillsOfMaterials": [
            _descriptor(
                logical,
                sboms[logical],
                role="software-bill-of-materials",
                mediaType="application/vnd.cyclonedx+json",
                bomFormat="CycloneDX",
                specVersion="1.7",
            )
            for logical in SBOM_PATHS
        ],
        "verification": {
            "status": "real-source-unverified",
            "fixtureOnly": False,
            "verified": False,
            "policySatisfied": False,
            "productionClaim": False,
            "publicationClaim": False,
            "scientificApproval": False,
            "reason": REASON,
        },
    }
    return EvidenceInputs(
        (json.dumps(envelope, separators=(",", ":")) + "\n").encode(),
        manifest,
        provenance,
        policy,
        bundles,
        sboms,
    )


def _validate(inputs: EvidenceInputs) -> dict[str, Any]:
    return contracts._validate_real_source_unverified_evidence(
        inputs.envelope,
        inputs.manifest,
        inputs.provenance,
        inputs.policy,
        inputs.bundles,
        inputs.sboms,
    )


def _mutate_envelope(inputs: EvidenceInputs, mutation: Any) -> None:
    document = copy.deepcopy(json.loads(inputs.envelope))
    mutation(document)
    inputs.envelope = (json.dumps(document, separators=(",", ":")) + "\n").encode()


def test_private_validator_binds_complete_real_source_preverification_bytes(
    tmp_path: Path,
) -> None:
    envelope = _validate(_evidence_inputs(tmp_path))

    assert envelope["verification"] == {
        "status": "real-source-unverified",
        "fixtureOnly": False,
        "verified": False,
        "policySatisfied": False,
        "productionClaim": False,
        "publicationClaim": False,
        "scientificApproval": False,
        "reason": REASON,
    }
    assert tuple(item["path"] for item in envelope["signatures"]) == SIGNATURE_PATHS
    assert tuple(item["path"] for item in envelope["softwareBillsOfMaterials"]) == SBOM_PATHS


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("status", "verified-production"),
        ("fixtureOnly", True),
        ("verified", True),
        ("policySatisfied", True),
        ("productionClaim", True),
        ("publicationClaim", True),
        ("scientificApproval", True),
        ("reason", "Awaiting verification."),
        ("certificateIdentity", "forbidden"),
        ("protectedEnvironment", "forbidden"),
        ("signingOutcome", "forbidden"),
    ],
)
def test_verification_claim_tampering_fails_closed(
    tmp_path: Path, field: str, value: object
) -> None:
    inputs = _evidence_inputs(tmp_path)
    _mutate_envelope(inputs, lambda document: document["verification"].update({field: value}))

    with pytest.raises(SupplyChainContractError):
        _validate(inputs)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("contractId", "phase-1-signed-candidate-evidence-v1"),
        ("dataProvenanceClass", "synthetic-fixture"),
        ("candidateId", "candidate-real-source"),
    ],
)
def test_contract_identity_tampering_fails_closed(
    tmp_path: Path, field: str, value: object
) -> None:
    inputs = _evidence_inputs(tmp_path)
    _mutate_envelope(inputs, lambda document: document.update({field: value}))

    with pytest.raises(SupplyChainContractError):
        _validate(inputs)


@pytest.mark.parametrize("mode", ["missing", "extra", "swapped"])
def test_missing_extra_or_swapped_signature_descriptors_fail_closed(
    tmp_path: Path, mode: str
) -> None:
    inputs = _evidence_inputs(tmp_path)

    def mutate(document: dict[str, Any]) -> None:
        signatures = document["signatures"]
        if mode == "missing":
            signatures.pop()
        elif mode == "extra":
            signatures.append({**signatures[-1], "path": "extra.sigstore.json"})
        else:
            signatures.reverse()

    _mutate_envelope(inputs, mutate)
    with pytest.raises(SupplyChainContractError):
        _validate(inputs)


@pytest.mark.parametrize("mode", ["missing", "extra", "swapped"])
def test_missing_extra_or_swapped_signature_bundle_bytes_fail_closed(
    tmp_path: Path, mode: str
) -> None:
    inputs = _evidence_inputs(tmp_path)
    if mode == "missing":
        inputs.bundles.pop(SIGNATURE_PATHS[-1])
    elif mode == "extra":
        inputs.bundles["extra.sigstore.json"] = b"extra"
    else:
        first, second = SIGNATURE_PATHS
        inputs.bundles[first], inputs.bundles[second] = (
            inputs.bundles[second],
            inputs.bundles[first],
        )

    with pytest.raises(SupplyChainContractError, match="signature"):
        _validate(inputs)


def test_signature_subject_digest_mismatch_fails_closed(tmp_path: Path) -> None:
    inputs = _evidence_inputs(tmp_path)
    _mutate_envelope(
        inputs,
        lambda document: document["signatures"][0].update({"subjectSha256": "f" * 64}),
    )

    with pytest.raises(SupplyChainContractError, match="signature subject mismatch"):
        _validate(inputs)


def test_self_consistent_descriptor_rejects_malformed_sigstore_bundle(tmp_path: Path) -> None:
    inputs = _evidence_inputs(tmp_path)
    logical = SIGNATURE_PATHS[0]
    malformed = b'{"mediaType":"application/vnd.dev.sigstore.bundle.v0.3+json"}\n'
    inputs.bundles[logical] = malformed
    _mutate_envelope(
        inputs,
        lambda document: document["signatures"][0].update(
            {"sha256": _sha256(malformed), "byteSize": len(malformed)}
        ),
    )

    with pytest.raises(SupplyChainContractError, match="structure is malformed"):
        _validate(inputs)


@pytest.mark.parametrize("mode", ["missing", "extra", "wrong"])
def test_missing_extra_or_wrong_sbom_descriptor_path_fails_closed(
    tmp_path: Path, mode: str
) -> None:
    inputs = _evidence_inputs(tmp_path)

    def mutate(document: dict[str, Any]) -> None:
        descriptors = document["softwareBillsOfMaterials"]
        if mode == "missing":
            descriptors.pop()
        elif mode == "extra":
            descriptors.append({**descriptors[-1], "path": "sbom/extra.cdx.json"})
        else:
            descriptors[0]["path"] = "sbom/wrong.cdx.json"

    _mutate_envelope(inputs, mutate)
    with pytest.raises(SupplyChainContractError):
        _validate(inputs)


@pytest.mark.parametrize("mode", ["missing", "extra", "wrong"])
def test_missing_extra_or_wrong_sbom_input_path_fails_closed(tmp_path: Path, mode: str) -> None:
    inputs = _evidence_inputs(tmp_path)
    raw = inputs.sboms.pop(SBOM_PATHS[-1])
    if mode == "extra":
        inputs.sboms[SBOM_PATHS[-1]] = raw
        inputs.sboms["sbom/extra.cdx.json"] = raw
    elif mode == "wrong":
        inputs.sboms["sbom/wrong.cdx.json"] = raw

    with pytest.raises(SupplyChainContractError, match="SBOM paths"):
        _validate(inputs)


@pytest.mark.parametrize("artifact", ["manifest", "provenance", "signature", "sbom"])
def test_bound_artifact_byte_tampering_fails_closed(tmp_path: Path, artifact: str) -> None:
    inputs = _evidence_inputs(tmp_path)
    if artifact == "manifest":
        inputs.manifest += b"tamper"
    elif artifact == "provenance":
        inputs.provenance += b"tamper"
    elif artifact == "signature":
        inputs.bundles[SIGNATURE_PATHS[0]] += b"tamper"
    else:
        inputs.sboms[SBOM_PATHS[0]] += b"tamper"

    with pytest.raises(SupplyChainContractError, match="SHA-256"):
        _validate(inputs)


def test_public_structural_validator_remains_synthetic_only(tmp_path: Path) -> None:
    inputs = _evidence_inputs(tmp_path)
    envelope_path = tmp_path / "evidence-envelope.json"
    envelope_path.write_bytes(inputs.envelope)
    physical_sboms = {
        logical: CONTRACT_ROOT / logical.replace("sbom/", "sboms/", 1) for logical in SBOM_PATHS
    }

    with pytest.raises(SupplyChainContractError, match="schema|contractId"):
        contracts.validate_evidence_files(envelope_path, POLICY, physical_sboms)
