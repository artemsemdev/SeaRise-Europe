"""Fail-closed Phase 0.13 scope and connectivity review contracts."""

from __future__ import annotations

import base64
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping

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


def evidence_bundle_sha256(bindings: list[Mapping[str, Any]]) -> str:
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
