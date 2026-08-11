"""Fail-closed Phase 1 engineering candidate completeness validation."""

from __future__ import annotations

import json
import posixpath
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, NoReturn, Sequence

from jsonschema import Draft202012Validator, FormatChecker  # type: ignore[import-untyped]


class CandidateCompletenessError(ValueError):
    """Raised with a stable cross-runtime completeness failure code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class CandidateCompletenessSummary:
    """Stable successful validation result for CI and later assembly wiring."""

    artifact_count: int
    dataset_count: int
    manifest_written_last: bool


def _fail(code: str, message: str) -> NoReturn:
    raise CandidateCompletenessError(code, message)


def _safe_path(value: object) -> bool:
    if not isinstance(value, str) or not value or "\\" in value or "//" in value:
        return False
    path = PurePosixPath(value)
    return not path.is_absolute() and all(part not in ("", ".", "..") for part in path.parts)


def _resolve_href(source_path: str, href: object) -> str:
    if (
        not isinstance(href, str)
        or not href
        or href.startswith("/")
        or ":" in href.split("/", 1)[0]
        or "\\" in href
        or any(part in ("", ".") for part in href.split("/"))
    ):
        _fail("unsafe-reference", f"unsafe STAC href: {href}")
    resolved = posixpath.normpath(posixpath.join(posixpath.dirname(source_path), href))
    if resolved == ".." or resolved.startswith("../") or "/releases/" in f"/{resolved}/":
        _fail("unsafe-reference", f"STAC href escapes or crosses a release: {href}")
    return resolved


def _schema_validate(candidate: Mapping[str, Any], schema_path: Path) -> None:
    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        _fail("candidate-schema", f"cannot read candidate schema: {exc}")
    errors = sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(candidate),
        key=lambda error: list(error.absolute_path),
    )
    if errors:
        error = errors[0]
        location = ".".join(str(part) for part in error.absolute_path) or "$"
        _fail("candidate-schema", f"candidate schema rejected {location}: {error.message}")


def _required(candidate: Mapping[str, Any], *names: str) -> None:
    missing = [name for name in names if name not in candidate]
    if missing:
        _fail("candidate-schema", f"candidate is missing: {', '.join(missing)}")


def _validate_geometry_policy(candidate: Mapping[str, Any]) -> None:
    expected = {
        "status": "selected-scope-approximation",
        "purpose": "product-eligibility-only",
        "canonical": False,
        "production": False,
        "publicationEligible": False,
        "hazardExtentClaim": False,
    }
    if candidate["geometryPolicy"] != expected or candidate["publicationClaim"] is not False:
        _fail("geometry-policy", "non-canonical geometry cannot carry a publication claim")


def _validate_artifacts(
    candidate: Mapping[str, Any], contract: Mapping[str, Any]
) -> Sequence[Mapping[str, Any]]:
    raw_artifacts = candidate["artifacts"]
    if not isinstance(raw_artifacts, list) or not all(
        isinstance(artifact, dict) for artifact in raw_artifacts
    ):
        _fail("candidate-schema", "candidate artifacts must be objects")
    artifacts: list[Mapping[str, Any]] = raw_artifacts
    forbidden = set(contract["forbiddenDeferredRoles"])
    if any(artifact.get("role") in forbidden for artifact in artifacts):
        _fail("premature-supply-chain", "signing, provenance, and SBOM belong to issue #53")
    for artifact in artifacts:
        if not _safe_path(artifact.get("path")):
            _fail("unsafe-reference", f"unsafe artifact path: {artifact.get('path')}")
        if artifact.get("dataReleaseId") != candidate["dataReleaseId"]:
            _fail("cross-release-reference", "artifact release ID differs from candidate")
        if artifact.get("immutable") is not True:
            _fail("artifact-immutable", f"artifact is mutable: {artifact.get('artifactId')}")
        if (
            artifact.get("sha256") != artifact.get("observedSha256")
            or artifact.get("byteSize") != artifact.get("observedByteSize")
        ):
            _fail("artifact-integrity", f"artifact bytes differ: {artifact.get('artifactId')}")

    ids = [artifact.get("artifactId") for artifact in artifacts]
    paths = [artifact.get("path") for artifact in artifacts]
    if len(set(ids)) != len(ids) or len(set(paths)) != len(paths):
        _fail("artifact-duplicate", "artifact IDs and paths must be unique")

    required = contract["requiredArtifacts"]
    expected_by_id = {artifact["artifactId"]: artifact for artifact in required}
    actual_by_id = {artifact["artifactId"]: artifact for artifact in artifacts}
    extra = set(actual_by_id) - set(expected_by_id)
    if extra:
        _fail("artifact-extra", f"unexpected artifacts: {', '.join(sorted(extra))}")
    missing = set(expected_by_id) - set(actual_by_id)
    if missing or len(artifacts) != contract["artifactCount"]:
        _fail("artifact-inventory", f"missing artifacts: {', '.join(sorted(missing))}")

    registry_values = candidate["attributionRegistry"]
    if registry_values != contract.get("attributionRegistry"):
        _fail("artifact-rights", "attribution registry differs from the exact contract")
    registry = set(registry_values)
    identity_fields = ("path", "role", "mediaType", "contentEncoding")
    for artifact_id, expected in expected_by_id.items():
        actual = actual_by_id[artifact_id]
        if any(actual.get(field) != expected[field] for field in identity_fields):
            _fail("artifact-inventory", f"artifact contract differs: {artifact_id}")
        rights = actual.get("rights")
        if not isinstance(rights, dict):
            _fail("artifact-rights", f"artifact rights are malformed: {artifact_id}")
        attribution_ids = rights.get("attributionIds", [])
        if (
            attribution_ids != [expected["attributionId"]]
            or any(attribution_id not in registry for attribution_id in attribution_ids)
            or rights.get("redistribution") != "allowed"
        ):
            _fail("artifact-rights", f"artifact rights are incomplete: {artifact_id}")
    return artifacts


def _validate_stac(candidate: Mapping[str, Any], contract: Mapping[str, Any]) -> int:
    release_id = candidate["dataReleaseId"]
    stac = candidate["stac"]
    catalog = stac["catalog"]
    collection = stac["collection"]
    if catalog.get("path") != "stac/catalog.json" or _resolve_href(
        catalog["path"], catalog.get("collectionHref")
    ) != "stac/collection.json":
        _fail("stac-reference", "STAC catalog does not resolve to its collection")

    expected_pairs = [
        (scenario, horizon)
        for scenario in contract["scenarios"]
        for horizon in contract["horizons"]
    ]
    expected_item_paths = {
        f"stac/items/{scenario}-{horizon}.json" for scenario, horizon in expected_pairs
    }
    item_hrefs = collection.get("itemHrefs", [])
    resolved_items = {
        _resolve_href(collection["path"], href) for href in item_hrefs
    }
    if (
        collection.get("path") != "stac/collection.json"
        or len(item_hrefs) != len(resolved_items)
        or resolved_items != expected_item_paths
    ):
        _fail("stac-reference", "STAC collection item links differ from the 3 x 3 matrix")

    items = stac["items"]
    pairs = [(item.get("scenario"), item.get("horizon")) for item in items]
    if len(items) != len(expected_pairs) or set(pairs) != set(expected_pairs):
        _fail("stac-reference", "STAC item matrix is incomplete or duplicated")
    for item in items:
        if item.get("dataReleaseId") != release_id:
            _fail("cross-release-reference", "STAC item release ID differs from candidate")
        scenario, horizon = item["scenario"], item["horizon"]
        item_path = f"stac/items/{scenario}-{horizon}.json"
        expected_targets = {
            "analysisHref": f"analysis/{scenario}/{horizon}.tif",
            "visualHref": f"layers/{scenario}/{horizon}.pmtiles",
            "tableHref": "analysis/projections.parquet",
        }
        if item.get("path") != item_path or any(
            _resolve_href(item_path, item.get(field)) != target
            for field, target in expected_targets.items()
        ):
            _fail("stac-reference", f"STAC item links differ: {scenario}-{horizon}")
    return len(expected_pairs)


def _validate_sealing(
    candidate: Mapping[str, Any], artifacts: Sequence[Mapping[str, Any]]
) -> None:
    by_path = {artifact["path"]: artifact for artifact in artifacts}
    checksum = candidate["checksumInventory"]
    subjects = checksum.get("subjects", [])
    subject_paths = [subject.get("path") for subject in subjects]
    expected_subjects = set(by_path) - {"checksums.txt"}
    if (
        checksum.get("path") != "checksums.txt"
        or checksum.get("algorithm") != "sha256"
        or len(subject_paths) != len(set(subject_paths))
        or subject_paths != sorted(subject_paths)
        or set(subject_paths) != expected_subjects
    ):
        _fail("checksum-coverage", "checksums must cover the exact sorted non-self inventory")
    if any(subject.get("sha256") != by_path[subject["path"]]["sha256"] for subject in subjects):
        _fail("checksum-integrity", "checksum entries must match the sealed artifact hashes")

    gate_paths = {"evidence/gate-report.json", "evidence/gate-report.md"}
    gate = candidate["gateReportSemantics"]
    expected_exclusions = ["checksums.txt", *sorted(gate_paths), "manifest.json"]
    gate_subjects = set(by_path) - gate_paths - {"checksums.txt"}
    if (
        gate.get("candidateState") != "pre-manifest-snapshot"
        or gate.get("validatedScope")
        != "required-artifacts-except-gate-reports-checksums-and-manifest"
        or gate.get("validatedArtifactCount") != len(gate_subjects)
        or gate.get("excludedPaths") != expected_exclusions
        or gate.get("manifestHashReferenced") is not False
    ):
        _fail("gate-report-scope", "gate reports must validate an acyclic pre-manifest snapshot")
    if min(by_path[path]["writeSequence"] for path in gate_paths) <= max(
        by_path[path]["writeSequence"] for path in gate_subjects
    ):
        _fail("gate-report-scope", "gate reports must follow every artifact they validate")
    checksum_sequence = by_path["checksums.txt"]["writeSequence"]
    if checksum_sequence <= max(
        artifact["writeSequence"]
        for artifact in artifacts
        if artifact["path"] != "checksums.txt"
    ):
        _fail("checksum-order", "checksums must be written after every declared subject")


def validate_candidate_completeness(
    candidate: Mapping[str, Any],
    contract: Mapping[str, Any],
    *,
    schema_path: Path,
) -> CandidateCompletenessSummary:
    """Validate the immutable engineering inventory without assembling it."""
    _required(
        candidate,
        "contractId",
        "dataReleaseId",
        "publicationClaim",
        "manifest",
        "attributionRegistry",
        "geometryPolicy",
        "projectionGrid",
        "artifacts",
        "checksumInventory",
        "gateReportSemantics",
        "stac",
        "parity",
    )
    if candidate["contractId"] != contract.get("contractId"):
        _fail("candidate-schema", "candidate and required-artifact contract IDs differ")
    _validate_geometry_policy(candidate)
    if candidate["projectionGrid"] != contract.get("projectionGrid"):
        _fail("projection-grid", "projection grid differs from the public v1 grid")
    artifacts = _validate_artifacts(candidate, contract)
    dataset_count = _validate_stac(candidate, contract)
    _validate_sealing(candidate, artifacts)
    parity = candidate["parity"]
    if parity.get("status") != "passed" or parity.get("python") != parity.get("typescript"):
        _fail("cross-runtime-parity", "Python and TypeScript lookup evidence differs")

    manifest = candidate["manifest"]
    sequences = [artifact["writeSequence"] for artifact in artifacts]
    if (
        sorted(sequences) != list(range(1, len(artifacts) + 1))
        or manifest.get("path") != "manifest.json"
        or manifest.get("artifactCount") != len(artifacts)
        or manifest.get("writeSequence") != len(artifacts) + 1
    ):
        _fail("manifest-order", "artifact writes must be contiguous and manifest exactly last")
    _schema_validate(candidate, schema_path)
    return CandidateCompletenessSummary(
        artifact_count=len(artifacts),
        dataset_count=dataset_count,
        manifest_written_last=True,
    )
