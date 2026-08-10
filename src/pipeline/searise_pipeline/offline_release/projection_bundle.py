"""Fail-closed reuse of the owner-approved Phase 0R projection bundle."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, NoReturn

from ..release import (
    RegionalReleaseSource,
    load_release_contract,
    load_source_fixture,
    validate_analysis_cog,
    validate_geoparquet,
    validate_lookup_goldens,
)
from ..release.evidence import (
    binding_sha256,
    safe_candidate_path,
    sha256,
    validate_build_receipt,
)
from ..science import ScienceContractError

_CONTRACT = Path("src/pipeline/science/ar6-regional-release.json")
_SOURCE_FIXTURE = Path("src/pipeline/fixtures/ar6-regional-release/source-fixture.json.gz")
_SOURCE_RECEIPT = Path(
    "src/pipeline/fixtures/ar6-regional-release/source-fixture-receipt.json"
)
_GOLDENS = Path("src/pipeline/science/evidence/ar6-lookup-goldens.json")
_MAC_EVIDENCE = Path("src/pipeline/evidence/ar6-regional-release/macos-arm64-cp311")
_OWNER_EVIDENCE = Path("src/pipeline/evidence/ar6-regional-release/owner-promotion")


@dataclass(frozen=True)
class ReviewedProjectionEvidence:
    """Strictly validated Phase 0R authority and artifact identity evidence."""

    contract: Mapping[str, Any]
    source: RegionalReleaseSource
    binding: Mapping[str, Any]
    delivery_trace: Mapping[str, Any]


def load_reviewed_projection_evidence(
    repository_root: Path,
) -> ReviewedProjectionEvidence:
    """Validate the complete owner chain once for all Phase 1 consumers."""
    contract = load_release_contract(repository_root / _CONTRACT)
    receipt = _read_json(repository_root / _SOURCE_RECEIPT)
    source = load_source_fixture(
        repository_root / _SOURCE_FIXTURE,
        receipt=receipt,
        release_contract=contract,
    )
    binding = _read_json(repository_root / _MAC_EVIDENCE / "candidate-binding.json")
    final_gate = _validate_approved_evidence(
        repository_root,
        binding=binding,
        contract=contract,
        contract_sha256=source.contract_sha256,
    )
    trace_path = repository_root / _MAC_EVIDENCE / "browser-trace-macos-arm64.json"
    trace = _read_json(trace_path)
    evidence_bindings = final_gate.get("evidenceBindings")
    candidate = trace.get("candidate")
    binding_hashes = binding.get("artifactHashes")
    if (
        not isinstance(evidence_bindings, dict)
        or evidence_bindings.get("deliveryTraceSha256") != sha256(trace_path)
        or not isinstance(candidate, dict)
        or candidate.get("releaseId") != binding.get("releaseId")
        or candidate.get("manifestSha256") != binding.get("manifestSha256")
        or not isinstance(binding_hashes, dict)
        or candidate.get("artifactHashes") != binding_hashes
    ):
        _fail("reviewed projection delivery trace changed identity")
    sizes = candidate.get("artifactByteSizes")
    if (
        not isinstance(sizes, dict)
        or set(sizes) != set(binding_hashes)
        or any(type(size) is not int or size <= 0 for size in sizes.values())
    ):
        _fail("reviewed projection delivery sizes are invalid")
    return ReviewedProjectionEvidence(contract, source, binding, trace)


def validate_reviewed_projection_bundle(
    bundle_root: Path,
    *,
    repository_root: Path,
) -> dict[str, Any]:
    """Revalidate exact projection semantics before derive-stage promotion."""
    evidence = load_reviewed_projection_evidence(repository_root)
    contract = evidence.contract
    source = evidence.source
    binding = evidence.binding

    matrix = {(layer.scenario, layer.horizon): layer for layer in source.layers}
    cog_paths = {
        f"analysis/{scenario}/{horizon}.tif"
        for scenario, horizon in matrix
    }
    pmtiles_paths = {
        f"layers/{scenario}/{horizon}.pmtiles"
        for scenario, horizon in matrix
    }
    geoparquet_path = "analysis/projections.parquet"
    expected_paths = cog_paths | pmtiles_paths | {geoparquet_path}
    hashes = binding.get("artifactHashes")
    if not isinstance(hashes, dict) or not expected_paths.issubset(hashes):
        _fail("reviewed #110 projection inventory is incomplete")

    manifest = _read_json(bundle_root / "manifest.json")
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list):
        _fail("projection bundle manifest artifact inventory is invalid")
    projection_roles = {
        "projection-analysis-cog",
        "projection-geoparquet",
        "projection-visual-pmtiles",
    }
    projection_artifacts = [
        item
        for item in artifacts
        if isinstance(item, dict) and item.get("role") in projection_roles
    ]
    by_path = {
        item.get("path"): item
        for item in projection_artifacts
        if item.get("path") in expected_paths
    }
    if len(projection_artifacts) != len(expected_paths) or set(by_path) != expected_paths:
        _fail("projection bundle does not contain the exact 3 x 3 artifact matrix")

    expected_roles = {
        **{path: ("projection-analysis-cog", "exact-lookup") for path in cog_paths},
        **{
            path: ("projection-visual-pmtiles", "visual-only")
            for path in pmtiles_paths
        },
        geoparquet_path: ("projection-geoparquet", "exact-analytics"),
    }
    for relative in sorted(expected_paths):
        artifact = by_path[relative]
        path = _regular_bundle_file(bundle_root, relative)
        observed_hash = sha256(path)
        role, scientific_use = expected_roles[relative]
        if (
            observed_hash != hashes[relative]
            or artifact.get("sha256") != observed_hash
            or artifact.get("byteSize") != path.stat().st_size
            or artifact.get("role") != role
            or artifact.get("scientificUse") != scientific_use
        ):
            _fail(f"projection artifact differs from reviewed #110 identity: {relative}")

    for (scenario, horizon), layer in sorted(matrix.items()):
        validate_analysis_cog(
            bundle_root / f"analysis/{scenario}/{horizon}.tif",
            layer,
            contract=contract,
        )
    validate_geoparquet(
        bundle_root / geoparquet_path,
        source,
        contract=contract,
    )
    validate_lookup_goldens(source, repository_root / _GOLDENS)
    return {
        "reviewedProjectionArtifactCount": len(expected_paths),
        "reviewedProjectionCogsValidated": len(cog_paths),
        "reviewedProjectionGeoparquetValidated": True,
        "reviewedProjectionPmtilesDecodedParity": "approved-byte-identical",
        "reviewedProjectionGoldenParity": True,
    }


def _validate_approved_evidence(
    repository_root: Path,
    *,
    binding: Mapping[str, Any],
    contract: Mapping[str, Any],
    contract_sha256: str,
) -> Mapping[str, Any]:
    mac_root = repository_root / _MAC_EVIDENCE
    owner_root = repository_root / _OWNER_EVIDENCE
    final_gate = _read_json(owner_root / "final-gate.json")
    promotion = _read_json(owner_root / "promotion.json")
    owner = _read_json(owner_root / "owner-attestation.json")
    build_receipt = _read_json(mac_root / "build-receipt.json")
    binding_digest = binding_sha256(binding)
    required_checks = {
        "artifactBudgets",
        "cogStructureAndValues",
        "completeScenarioHorizonMatrix",
        "crossArtifactSemanticParity",
        "crossEnvironmentReproducibility",
        "deliveryMeasurements",
        "geoparquetSchemaAndValues",
        "licenceAndAttribution",
        "lookupGoldenParity",
        "nonAllNodataLayers",
        "pmtilesStructureAndProperties",
        "sourceArchiveAndMembersVerified",
        "sourceContentSeal",
        "sourceGridIdentity",
    }
    checks = final_gate.get("checks")
    evidence_bindings = final_gate.get("evidenceBindings")
    promotion_evidence = final_gate.get("promotionEvidence")
    if (
        final_gate.get("issue") != 110
        or final_gate.get("automatedValidation") != "passed"
        or final_gate.get("blockingChecks") != []
        or final_gate.get("ownerDecision") != "approved"
        or final_gate.get("releaseDisposition") != "approved"
        or final_gate.get("phase1Unlocked") is not True
        or final_gate.get("scientificDisposition") != "projection-only"
        or not isinstance(checks, dict)
        or set(checks) != required_checks
        or any(checks.get(name) is not True for name in required_checks)
        or not isinstance(evidence_bindings, dict)
        or evidence_bindings.get("candidateBindingSha256") != binding_digest
        or owner.get("decision") != "approved"
        or owner.get("candidateBindingSha256") != binding_digest
        or promotion.get("macCandidateBindingSha256") != binding_digest
    ):
        _fail("reviewed projection evidence is not owner-approved")

    validated_profile = validate_build_receipt(
        build_receipt,
        manifest={"releaseId": binding.get("releaseId")},
        contract=contract,
    )
    if (
        binding.get("releaseId") != final_gate.get("releaseId")
        or binding.get("releaseContractId") != contract.get("releaseContractId")
        or binding.get("sourceRevision") != build_receipt.get("sourceRevision")
        or binding.get("environmentIdentity") != build_receipt.get("environmentIdentity")
        or binding.get("validatedEnvironmentProfile") != validated_profile
        or binding.get("buildReceiptSha256") != sha256(mac_root / "build-receipt.json")
        or promotion.get("releaseContractSha256") != contract_sha256
        or promotion.get("ownerEvidenceSha256")
        != sha256(owner_root / "owner-attestation.json")
        or not isinstance(promotion_evidence, dict)
        or promotion_evidence.get("ownerEvidenceSha256") != promotion.get("ownerEvidenceSha256")
        or promotion.get("integrationMergeEvidenceSha256")
        != sha256(owner_root / "integration-merge.json")
        or promotion_evidence.get("integrationMergeEvidenceSha256")
        != promotion.get("integrationMergeEvidenceSha256")
        or promotion_evidence.get("promotionSha256") != sha256(owner_root / "promotion.json")
    ):
        _fail("reviewed projection source, tool, or build identity changed")
    _validate_owner_checksums(owner_root)
    return final_gate


def _validate_owner_checksums(root: Path) -> None:
    expected_names = (
        "owner-attestation.json",
        "integration-merge.json",
        "promotion.json",
        "final-gate.json",
    )
    try:
        lines = (root / "checksums.txt").read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ScienceContractError("Cannot read approved projection checksums") from exc
    expected = [f"{sha256(root / name)}  {name}" for name in expected_names]
    if lines != expected:
        _fail("reviewed projection owner evidence checksum inventory changed")


def _regular_bundle_file(root: Path, relative: str) -> Path:
    path = safe_candidate_path(root, relative)
    if root.is_symlink() or not path.is_file():
        _fail(f"projection artifact is absent or unsafe: {relative}")
    return path


def _read_json(path: Path) -> dict[str, Any]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ScienceContractError(f"Cannot read reviewed projection evidence: {path}") from exc
    if not isinstance(document, dict):
        _fail("reviewed projection evidence must be a JSON object")
    return document


def _fail(message: str) -> NoReturn:
    raise ScienceContractError(message)
