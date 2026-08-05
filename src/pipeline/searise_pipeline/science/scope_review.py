"""Fail-closed Phase 0.13 scope and connectivity review contracts."""

from __future__ import annotations

import base64
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence

import geopandas as gpd  # type: ignore[import-untyped]
import numpy as np
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from jsonschema import Draft202012Validator, FormatChecker  # type: ignore[import-untyped]
from shapely.geometry import Point  # type: ignore[import-untyped]

from ..domain.result_state import AssessmentSample, determine_result_state
from .connectivity import ocean_connected_cells
from .contracts import ScienceContractError

REQUIRED_EMPIRICAL_KINDS = frozenset(
    {
        "port",
        "estuary",
        "lagoon",
        "island",
        "disconnected-low-terrain",
        "steep-coast",
        "diagonal-leak",
        "wbm-barrier",
        "mosaic-tile-seam",
    }
)
REQUIRED_PUBLIC_STATES = frozenset(
    {"OutOfScope", "UnsupportedGeography", "DataUnavailable"}
)


def _schema_path() -> Path:
    return Path(__file__).parents[2] / "science" / "scope-connectivity-review.schema.json"


def _format_error(error: Any) -> str:
    location = ".".join(str(part) for part in error.absolute_path) or "<root>"
    return f"{location}: {error.message}"


def canonical_json_bytes(value: Any) -> bytes:
    """Serialize review evidence without order, whitespace, or NaN ambiguity."""
    try:
        payload = json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as exc:
        raise ScienceContractError(f"Review evidence is not canonical JSON: {exc}") from exc
    return (payload + "\n").encode("utf-8")


def _sha256(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise ScienceContractError(f"Cannot read review evidence {path}: {exc}") from exc


def evidence_bundle_sha256(bindings: Sequence[Mapping[str, Any]]) -> str:
    """Hash sorted evidence identities so decisions cannot float across inputs."""
    identities = [
        {"id": item["id"], "path": item["path"], "sha256": item["sha256"]}
        for item in bindings
    ]
    identities.sort(key=lambda item: str(item["id"]))
    return hashlib.sha256(canonical_json_bytes(identities)).hexdigest()


def decision_binding_sha256(
    disposition: str, evidence_bundle: str, reviewed_commit: str
) -> str:
    """Bind an external disposition to exact evidence and reviewed source."""
    return hashlib.sha256(
        canonical_json_bytes(
            {
                "disposition": disposition,
                "evidenceBundleSha256": evidence_bundle,
                "reviewedCommit": reviewed_commit,
            }
        )
    ).hexdigest()


def _validate_metric_observation(control: Mapping[str, Any]) -> bool:
    observation = control["observation"]
    metrics = observation["metrics"]
    if observation["status"] != "complete":
        if any(value is not None for value in metrics.values()):
            raise ScienceContractError(
                f"Incomplete empirical control {control['id']} contains invented metrics"
            )
        return False

    required = (
        "preFilterPositiveCellCount",
        "postFilterPositiveCellCount",
        "removedCellCount",
        "removalFraction",
        "referencePositiveCellCount",
        "falsePositiveBeforeCount",
        "falsePositiveAfterCount",
        "falsePositiveBeforeRate",
        "falsePositiveAfterRate",
        "disputedCellCount",
        "tileSeamMismatchCellCount",
    )
    if any(metrics[name] is None for name in required):
        raise ScienceContractError(f"Complete empirical control {control['id']} lacks metrics")

    pre = int(metrics["preFilterPositiveCellCount"])
    post = int(metrics["postFilterPositiveCellCount"])
    removed = int(metrics["removedCellCount"])
    before_false = int(metrics["falsePositiveBeforeCount"])
    after_false = int(metrics["falsePositiveAfterCount"])
    if pre != post + removed:
        raise ScienceContractError(f"Empirical removal count is inconsistent for {control['id']}")

    expected_rates = {
        "removalFraction": removed / pre if pre else 0.0,
        "falsePositiveBeforeRate": before_false / pre if pre else 0.0,
        "falsePositiveAfterRate": after_false / post if post else 0.0,
    }
    for key, expected in expected_rates.items():
        if not math.isclose(float(metrics[key]), expected, rel_tol=0, abs_tol=1e-12):
            raise ScienceContractError(f"Empirical {key} is inconsistent for {control['id']}")
    return True


def validate_scope_connectivity_review(
    document: Mapping[str, Any], schema_path: Path | None = None
) -> None:
    """Validate review structure and approval invariants without granting approval."""
    try:
        schema = json.loads((schema_path or _schema_path()).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ScienceContractError(f"Cannot read Phase 0.13 review schema: {exc}") from exc
    errors = sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(document),
        key=lambda item: list(item.path),
    )
    if errors:
        details = "; ".join(_format_error(error) for error in errors)
        raise ScienceContractError(f"Invalid Phase 0.13 review: {details}")

    bindings = list(document["evidenceBindings"])
    if len({item["id"] for item in bindings}) != len(bindings):
        raise ScienceContractError("Phase 0.13 evidence binding IDs must be unique")
    expected_bundle = evidence_bundle_sha256(bindings)
    if document["evidenceBundleSha256"] != expected_bundle:
        raise ScienceContractError("Phase 0.13 evidence bundle checksum mismatch")

    empirical = document["empiricalControls"]
    kinds = {item["kind"] for item in empirical}
    if not REQUIRED_EMPIRICAL_KINDS.issubset(kinds):
        missing = ", ".join(sorted(REQUIRED_EMPIRICAL_KINDS - kinds))
        raise ScienceContractError(f"Phase 0.13 empirical coverage is incomplete: {missing}")
    empirical_complete = all(_validate_metric_observation(item) for item in empirical)

    states = {item["expectedState"] for item in document["semanticControls"]}
    if not REQUIRED_PUBLIC_STATES.issubset(states):
        raise ScienceContractError("Phase 0.13 public-state coverage is incomplete")
    sla_controls = [
        item for item in document["semanticControls"] if item["id"] == "north-of-sla-limit"
    ]
    if (
        len(sla_controls) != 1
        or sla_controls[0]["latitude"] <= 66.03125
        or sla_controls[0]["expectedState"] != "DataUnavailable"
    ):
        raise ScienceContractError("Phase 0.13 SLA latitude control is not fail closed")

    review = document["review"]
    disposition = review["disposition"]
    decided = disposition is not None
    reviewer_records = list(review["reviewers"].values())
    proofs_present = all(record["proof"] is not None for record in reviewer_records)
    reviewers_decided = all(record["decision"] != "pending" for record in reviewer_records)
    all_controls_approved = all(
        item["reviewerStatus"] == "approved"
        for item in document["controlObservations"]
    ) and all(item["reviewerStatus"] == "approved" for item in empirical)
    approval_complete = (
        disposition == "approved"
        and not document["blockingDependencies"]
        and empirical_complete
        and all_controls_approved
        and reviewers_decided
        and proofs_present
        and all(record["decision"] == "approved" for record in reviewer_records)
    )
    if bool(review["approvalReady"]) != approval_complete:
        raise ScienceContractError("Phase 0.13 approvalReady differs from review evidence")
    if decided:
        expected_decision_binding = decision_binding_sha256(
            str(disposition), document["evidenceBundleSha256"], review["reviewedCommit"]
        )
        if review["decisionBindingSha256"] != expected_decision_binding:
            raise ScienceContractError("Phase 0.13 disposition is not bound to exact evidence")
    elif review["decisionBindingSha256"] is not None:
        raise ScienceContractError("Pending Phase 0.13 review cannot contain a decision binding")


def verify_evidence_bindings(document: Mapping[str, Any], repo_root: Path) -> None:
    """Require every bound file to match before a reviewer decision is usable."""
    validate_scope_connectivity_review(document)
    for binding in document["evidenceBindings"]:
        if _sha256(repo_root / binding["path"]) != binding["sha256"]:
            raise ScienceContractError(
                f"Phase 0.13 evidence changed after binding: {binding['id']}"
            )


def _reviewer_payload(record: Mapping[str, Any], document: Mapping[str, Any]) -> bytes:
    return canonical_json_bytes(
        {
            "decision": record["decision"],
            "evidenceBundleSha256": document["evidenceBundleSha256"],
            "independenceStatement": record["independenceStatement"],
            "reviewedCommit": document["review"]["reviewedCommit"],
            "reviewer": record["reviewer"],
            "role": record["role"],
        }
    )


def verify_independent_review_proofs(
    document: Mapping[str, Any], repo_root: Path
) -> None:
    """Verify detached Ed25519 proofs for both independent review roles."""
    validate_scope_connectivity_review(document)
    for key, record in document["review"]["reviewers"].items():
        proof = record["proof"]
        if proof is None:
            raise ScienceContractError(f"Independent {key} reviewer proof is missing")
        key_path = repo_root / proof["publicKeyPath"]
        if _sha256(key_path) != proof["publicKeySha256"]:
            raise ScienceContractError(f"Independent {key} reviewer key changed")
        try:
            public_key = serialization.load_pem_public_key(key_path.read_bytes())
        except (OSError, ValueError) as exc:
            raise ScienceContractError(f"Cannot read independent {key} reviewer key") from exc
        if not isinstance(public_key, Ed25519PublicKey):
            raise ScienceContractError(f"Independent {key} reviewer key is not Ed25519")
        try:
            public_key.verify(
                base64.b64decode(proof["signatureBase64"], validate=True),
                _reviewer_payload(record, document),
            )
        except (InvalidSignature, ValueError) as exc:
            raise ScienceContractError(
                f"Independent {key} reviewer signature is invalid"
            ) from exc


def load_scope_connectivity_review(path: Path) -> Mapping[str, Any]:
    """Read one checked-in Phase 0.13 review contract."""
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ScienceContractError(f"Cannot read Phase 0.13 review: {exc}") from exc
    if not isinstance(document, dict):
        raise ScienceContractError("Phase 0.13 review must be an object")
    validate_scope_connectivity_review(document)
    return document


def observe_semantic_control(
    control: Mapping[str, Any], support: Any, coastal: Any
) -> dict[str, Any]:
    """Evaluate result-state precedence at one review coordinate."""
    point = Point(control["longitude"], control["latitude"])
    in_support = bool(support.covers(point))
    in_coastal = bool(coastal.covers(point)) if in_support else False
    class_value = None
    observed = determine_result_state(AssessmentSample(in_support, in_coastal, class_value))
    if observed != control["expectedState"]:
        raise ScienceContractError(f"Semantic control failed: {control['id']}")
    return {
        "id": control["id"],
        "inSupport": in_support,
        "inCoastalScope": in_coastal,
        "observedState": observed,
    }


def observe_connectivity_control(control: Mapping[str, Any], neighbourhood: int) -> dict[str, Any]:
    """Record exact observed rows for one symbolic mechanism control."""
    symbols = np.array([list(row) for row in control["grid"]])
    actual = ocean_connected_cells(
        np.isin(symbols, ("O", "L", "B")),
        symbols == "O",
        nodata=symbols == "N",
        barriers=symbols == "B",
        neighbourhood=neighbourhood,
    )
    rows = ["".join("C" if value else "." for value in row) for row in actual]
    return {
        "expectedConnected": control["expectedConnected"],
        "observedConnected": rows,
        "passed": rows == control["expectedConnected"],
    }


def load_review_geometries(repo_root: Path, document: Mapping[str, Any]) -> tuple[Any, Any]:
    """Load only the two checksum-bound geometries named by the review."""
    bindings = {item["id"]: item for item in document["evidenceBindings"]}
    support = gpd.read_file(repo_root / bindings["europe-support"]["path"]).geometry.union_all()
    coastal = gpd.read_file(repo_root / bindings["coastal-scope"]["path"]).geometry.union_all()
    return support, coastal


def _empty_metrics() -> dict[str, None]:
    return {
        "preFilterPositiveCellCount": None,
        "postFilterPositiveCellCount": None,
        "removedCellCount": None,
        "removalFraction": None,
        "referencePositiveCellCount": None,
        "falsePositiveBeforeCount": None,
        "falsePositiveAfterCount": None,
        "falsePositiveBeforeRate": None,
        "falsePositiveAfterRate": None,
        "disputedCellCount": None,
        "tileSeamMismatchCellCount": None,
    }


def _empirical_control(
    identifier: str,
    kind: str,
    name: str,
    longitude: float,
    latitude: float,
    provenance: str,
    expected: str,
    required_checks: list[str],
) -> dict[str, Any]:
    return {
        "id": identifier,
        "kind": kind,
        "name": name,
        "longitude": longitude,
        "latitude": latitude,
        "provenance": provenance,
        "expected": expected,
        "requiredChecks": required_checks,
        "observation": {
            "status": "blocked-by-dependencies",
            "metrics": _empty_metrics(),
            "evidence": None,
            "blockingIssues": [95, 96],
        },
        "reviewerStatus": "pending-independent-review",
    }


def _empirical_controls() -> list[dict[str, Any]]:
    common = [
        "Quantify pre-filter, connected, removed, and independently labelled cells.",
        "Quantify false positives before and after filtering; disputed cells fail closed.",
    ]
    return [
        _empirical_control(
            "rotterdam-port",
            "port",
            "Rotterdam",
            4.47917,
            51.9225,
            "GeoNames 2759794 and the pinned Netherlands GLO-30 five-layer window.",
            "Retain genuinely ocean-connected eligible port cells without bridging WBM barriers.",
            common + ["Inspect port infrastructure and edited DSM categories separately."],
        ),
        _empirical_control(
            "lisbon-estuary",
            "estuary",
            "Lisbon",
            -9.1498,
            38.72509,
            "GeoNames 2267057 and the pinned Lisbon GLO-30 five-layer window.",
            "Retain reviewed Tagus-connected cells and remove terrain isolated from the estuary.",
            common + ["Compare narrow estuary traversal with WBM ocean seed provenance."],
        ),
        _empirical_control(
            "venice-lagoon",
            "lagoon",
            "Venice",
            12.33265,
            45.43713,
            "GeoNames 3164603 and the pinned Venice GLO-30 five-layer window.",
            "Preserve reviewed lagoon connections while disputed diagonal crossings fail closed.",
            common + ["Review lagoon barriers and diagonal adjacency cell by cell."],
        ),
        _empirical_control(
            "valletta-island",
            "island",
            "Valletta",
            14.5148,
            35.89968,
            "GeoNames 2562305 and the pinned Malta GLO-30 five-layer window.",
            "Retain ocean-adjacent small-island land without treating array edges as ocean seeds.",
            common + ["Measure island removals and edge-derived false positives."],
        ),
        _empirical_control(
            "utrecht-disconnected-low-terrain",
            "disconnected-low-terrain",
            "Utrecht",
            5.12222,
            52.09083,
            "GeoNames 2745912 and the pinned Netherlands GLO-30 five-layer window.",
            "Remain OutOfScope under the 25 km eligibility rule; do not infer hazard reach inland.",
            common + ["Separate eligibility-scope removal from connectivity removal."],
        ),
        _empirical_control(
            "bergen-steep-coast",
            "steep-coast",
            "Bergen",
            5.3221,
            60.39299,
            (
                "GeoNames named-place coordinate and exact GLO-30 "
                "DEM/HEM/EDM/FLM/WBM assets required by the regional review."
            ),
            "Block low terrain behind confidently non-exposed steep coastal cells.",
            common + ["Demonstrate that steep barriers are not crossed at corners."],
        ),
        _empirical_control(
            "venice-diagonal-leak",
            "diagonal-leak",
            "Venice diagonal adjacency audit",
            12.33265,
            45.43713,
            "Pinned Venice GLO-30 window with independent reference labels required by issue 96.",
            (
                "Quantify eight-neighbour additions relative to four-neighbour "
                "traversal; disputed corner connections fail closed."
            ),
            common + ["Report the exact cells added only by diagonal traversal."],
        ),
        _empirical_control(
            "netherlands-wbm-barrier",
            "wbm-barrier",
            "Netherlands WBM barrier audit",
            4.47917,
            51.9225,
            "Pinned Netherlands GLO-30 WBM asset and matching DEM/EDM/FLM/HEM layers.",
            "Never traverse water, nodata, rejected quality, or unexpected WBM codes.",
            common + ["Report removals by WBM, nodata, and quality-barrier reason."],
        ),
        _empirical_control(
            "regional-mosaic-tile-seam",
            "mosaic-tile-seam",
            "Regional GLO-30 mosaic seam audit",
            10.0,
            54.0,
            (
                "Adjacent checksum-locked GLO-30 tiles selected by issue 96 "
                "across an internal mosaic seam."
            ),
            (
                "Match a seam-free reference traversal; missing neighbours "
                "produce DataUnavailable, never seeds."
            ),
            common + ["Require zero tile-seam mismatches before approval."],
        ),
    ]


def build_pending_scope_connectivity_review(repo_root: Path) -> dict[str, Any]:
    """Rebuild the dependency-independent Phase 0.13 review preflight."""
    contract_dir = repo_root / "src" / "pipeline" / "science"
    bound_paths = {
        "terrain-decision": "src/pipeline/science/terrain-decision.json",
        "terrain-measurements": "src/pipeline/science/evidence/phase-0-8-terrain-geography.json",
        "geography-rules": "src/pipeline/science/geography-rules.json",
        "geography-controls": "src/pipeline/science/geography-controls.json",
        "connectivity-controls": "src/pipeline/science/connectivity-controls.json",
        "europe-support": "data/geometry/europe.geojson",
        "coastal-scope": "data/geometry/coastal_analysis_zone.geojson",
        "source-lock": "src/pipeline/sources/source-lock.json",
    }
    bindings = [
        {"id": identifier, "path": path, "sha256": _sha256(repo_root / path)}
        for identifier, path in bound_paths.items()
    ]
    support = gpd.read_file(repo_root / bound_paths["europe-support"]).geometry.union_all()
    coastal = gpd.read_file(repo_root / bound_paths["coastal-scope"]).geometry.union_all()
    geography = json.loads(
        (contract_dir / "geography-controls.json").read_text(encoding="utf-8")
    )
    connectivity = json.loads(
        (contract_dir / "connectivity-controls.json").read_text(encoding="utf-8")
    )

    control_observations: list[dict[str, Any]] = []
    for control in geography["controls"]:
        point = Point(control["longitude"], control["latitude"])
        observed = {
            "support": bool(support.covers(point)),
            "coastal": bool(coastal.covers(point)),
        }
        expected = {"support": control["support"], "coastal": control["coastal"]}
        control_observations.append(
            {
                "id": f"geography-{control['recordId']}",
                "domain": "geography",
                "kind": control["kind"],
                "provenance": {
                    "sourceId": geography["source"]["sourceId"],
                    "sourceVersion": geography["source"]["version"],
                    "recordId": control["recordId"],
                    "name": control["name"],
                },
                "expected": expected,
                "observed": observed,
                "automationStatus": "passed" if observed == expected else "failed",
                "reviewerStatus": "pending-independent-review",
            }
        )
    for control in connectivity["controls"]:
        outcome = observe_connectivity_control(control, int(connectivity["neighbourhood"]))
        control_observations.append(
            {
                "id": f"connectivity-{control['id']}",
                "domain": "connectivity",
                "kind": control["kind"],
                "provenance": {
                    "contractId": connectivity["contractId"],
                    "basis": control["provenance"]["basis"],
                },
                "expected": {"connectedRows": outcome["expectedConnected"]},
                "observed": {"connectedRows": outcome["observedConnected"]},
                "automationStatus": "passed" if outcome["passed"] else "failed",
                "reviewerStatus": "pending-independent-review",
            }
        )

    boundary = support.boundary.representative_point()
    semantic_inputs = [
        {
            "id": "outside-coastal-scope",
            "name": "Prague",
            "longitude": 14.42076,
            "latitude": 50.08804,
            "provenance": (
                "GeoNames 3067696; inside support and outside the 25 km eligibility scope."
            ),
            "expectedState": "OutOfScope",
        },
        {
            "id": "outside-europe-support",
            "name": "Saint Petersburg",
            "longitude": 30.31413,
            "latitude": 59.93863,
            "provenance": "GeoNames 498817; excluded Russia control.",
            "expectedState": "UnsupportedGeography",
        },
        {
            "id": "north-of-sla-limit",
            "name": "Bodo",
            "longitude": 14.405,
            "latitude": 67.28,
            "provenance": (
                "Named-place coordinate inside support/coastal scope but north of "
                "the SLA 66.03125 degree limit."
            ),
            "expectedState": "DataUnavailable",
        },
        {
            "id": "support-boundary-covers",
            "name": "Exact support boundary point",
            "longitude": boundary.x,
            "latitude": boundary.y,
            "provenance": (
                "Deterministic representative point of the checksum-bound support "
                "boundary; covers, not contains, is authoritative."
            ),
            "expectedState": "OutOfScope",
        },
    ]
    semantic_controls = []
    for control in semantic_inputs:
        observed = observe_semantic_control(control, support, coastal)
        semantic_controls.append(
            {
                **control,
                "observedState": observed["observedState"],
                "reviewerStatus": "pending-independent-review",
            }
        )

    document: dict[str, Any] = {
        "$schema": "./scope-connectivity-review.schema.json",
        "schemaVersion": 1,
        "reviewId": "phase-0.13-scope-connectivity-review",
        "issue": 97,
        "recordedAt": "2026-08-05",
        "candidate": {
            "terrain": {
                "instance": "GLO-30",
                "release": "2021_1",
                "model": "digital-surface-model",
                "status": "selected-for-external-review",
            },
            "support": {
                "version": "natural-earth-5.1.1-explicit-scope-v2",
                "predicate": "covers",
                "status": "selected-scope-approximation",
                "canonical": False,
            },
            "coastalScope": {
                "version": "natural-earth-5.1.1-25km-scope-v2",
                "distanceMetres": 25000,
                "role": "product-eligibility-only",
                "hazardExtentClaim": False,
                "canonical": False,
            },
            "connectivity": {
                "id": "ocean-seeded-eight-neighbour-v1",
                "neighbourhood": 8,
                "seedSource": "pinned GLO-30 WBM ocean cells",
                "status": "selected-for-external-review",
                "hydrodynamicModel": False,
            },
        },
        "evidenceBindings": bindings,
        "evidenceBundleSha256": evidence_bundle_sha256(bindings),
        "controlObservations": control_observations,
        "semanticControls": semantic_controls,
        "empiricalControls": _empirical_controls(),
        "blockingDependencies": [95, 96],
        "review": {
            "status": "pending-independent-review",
            "disposition": None,
            "approvalReady": False,
            "reviewedCommit": None,
            "decisionBindingSha256": None,
            "reviewers": {
                "product": {
                    "role": "product reviewer",
                    "decision": "pending",
                    "reviewer": None,
                    "independenceStatement": None,
                    "proof": None,
                },
                "scientific": {
                    "role": "scientific/data reviewer",
                    "decision": "pending",
                    "reviewer": None,
                    "independenceStatement": None,
                    "proof": None,
                },
            },
            "nextDecision": (
                "Integrate approved issue 95 bounds and issue 96 basin evidence, "
                "record both independent signed reviews, and fail closed on every "
                "disputed empirical cell before issue 98 re-evaluates Phase 0."
            ),
        },
    }
    validate_scope_connectivity_review(document)
    return document
