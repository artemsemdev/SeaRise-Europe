"""Tests for the explicit eight-neighbour connectivity candidate."""

import base64
import hashlib
import json
from copy import deepcopy
from pathlib import Path

import numpy as np
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from searise_pipeline.science import (
    assert_scope_connectivity_approved,
    build_pending_scope_connectivity_review,
    canonical_json_bytes,
    connectivity_comparison,
    decision_binding_sha256,
    evaluate_connectivity_controls,
    load_scope_connectivity_review,
    ocean_connected_cells,
    review_evidence_sha256,
    validate_scope_connectivity_review,
    verify_evidence_bindings,
    verify_independent_review_proofs,
)
from searise_pipeline.science.contracts import ScienceContractError

CONTRACT_DIR = Path(__file__).parents[2] / "science"
REPO_ROOT = Path(__file__).parents[4]
REVIEW_PATH = CONTRACT_DIR / "scope-connectivity-review.json"


def test_diagonal_cells_connect_under_eight_neighbour_rule() -> None:
    eligible = np.array(
        [
            [True, False, False],
            [False, True, False],
            [False, False, True],
        ]
    )
    seeds = np.zeros_like(eligible)
    seeds[0, 0] = True

    connected = ocean_connected_cells(eligible, seeds)

    np.testing.assert_array_equal(connected, eligible)


def test_nodata_barrier_leaves_inland_basin_disconnected() -> None:
    eligible = np.array(
        [
            [True, True, False, False, False],
            [True, True, False, True, True],
            [False, False, False, True, True],
        ]
    )
    seeds = np.zeros_like(eligible)
    seeds[0, 0] = True

    report = connectivity_comparison(eligible, seeds)

    assert report == {
        "eligibleCellCount": 8,
        "connectedCellCount": 4,
        "disconnectedCellCount": 4,
        "disconnectedFraction": 0.5,
    }


def test_seed_must_be_eligible() -> None:
    eligible = np.zeros((2, 2), dtype=np.bool_)
    seeds = np.zeros_like(eligible)
    seeds[0, 0] = True

    with pytest.raises(ValueError, match="eligible"):
        ocean_connected_cells(eligible, seeds)


def test_nodata_and_quality_masks_are_not_traversed() -> None:
    eligible = np.ones((3, 3), dtype=np.bool_)
    seeds = np.zeros_like(eligible)
    seeds[0, 0] = True
    nodata = np.zeros_like(eligible)
    nodata[1, :] = True
    barriers = np.zeros_like(eligible)
    barriers[0, 2] = True

    connected = ocean_connected_cells(
        eligible,
        seeds,
        nodata=nodata,
        barriers=barriers,
    )

    np.testing.assert_array_equal(
        connected,
        np.array(
            [
                [True, True, False],
                [False, False, False],
                [False, False, False],
            ]
        ),
    )


def test_four_neighbour_rule_rejects_diagonal_connection() -> None:
    eligible = np.eye(3, dtype=np.bool_)
    seeds = np.zeros_like(eligible)
    seeds[0, 0] = True

    connected = ocean_connected_cells(eligible, seeds, neighbourhood=4)

    assert int(connected.sum()) == 1


def test_independent_control_corpus_passes() -> None:
    document = json.loads(
        (CONTRACT_DIR / "connectivity-controls.json").read_text(encoding="utf-8")
    )

    report = evaluate_connectivity_controls(document)

    assert report["passed"] == report["count"] == 9


def test_scope_review_preflight_is_reproducible_and_bound() -> None:
    checked_in = load_scope_connectivity_review(REVIEW_PATH)
    rebuilt = build_pending_scope_connectivity_review(REPO_ROOT)

    assert canonical_json_bytes(rebuilt) == REVIEW_PATH.read_bytes()
    assert checked_in["review"] == {
        "approvalReady": False,
        "decisionBindingSha256": None,
        "disposition": None,
        "nextDecision": (
            "Integrate approved issue 95 bounds and issue 96 basin evidence, record both "
            "independent signed reviews, and fail closed on every disputed empirical cell "
            "before issue 98 re-evaluates Phase 0."
        ),
        "reviewedCommit": None,
        "reviewers": {
            "product": {
                "decision": "pending",
                "independenceStatement": None,
                "proof": None,
                "reviewer": None,
                "role": "product reviewer",
            },
            "scientific": {
                "decision": "pending",
                "independenceStatement": None,
                "proof": None,
                "reviewer": None,
                "role": "scientific/data reviewer",
            },
        },
        "status": "pending-independent-review",
    }
    dependency_bindings = checked_in["dependencyBindings"]
    assert [item["id"] for item in dependency_bindings] == [
        "issue-95-uncertainty-budget",
        "issue-96-basin-contract",
        "issue-96-basin-evidence",
    ]
    for binding in dependency_bindings:
        path = REPO_ROOT / binding["path"]
        assert binding["verificationStatus"] == "verified"
        assert binding["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert checked_in["dependencyStatus"] == {
        "95": {
            "approvalReady": False,
            "artifactsVerified": True,
            "publicationGateStatus": "blocked",
            "reviewStatus": "pending-independent",
        },
        "96": {
            "approvalReady": False,
            "artifactsVerified": True,
            "publicationGateStatus": "blocked",
            "reviewStatus": "pending-external",
        },
    }
    verify_evidence_bindings(checked_in, REPO_ROOT)


def test_dependency_blockers_are_derived_from_exact_bound_artifacts() -> None:
    review = deepcopy(load_scope_connectivity_review(REVIEW_PATH))
    review["blockingDependencies"] = [95]
    review["reviewEvidenceSha256"] = review_evidence_sha256(review)

    with pytest.raises(ScienceContractError, match="blockers differ"):
        validate_scope_connectivity_review(review)

    review = deepcopy(load_scope_connectivity_review(REVIEW_PATH))
    review["dependencyStatus"]["95"].update(
        {
            "approvalReady": True,
            "publicationGateStatus": "approved",
            "reviewStatus": "approved",
        }
    )
    review["blockingDependencies"] = [96]
    for control in review["empiricalControls"]:
        control["observation"]["blockingIssues"] = [96]
    review["reviewEvidenceSha256"] = review_evidence_sha256(review)

    with pytest.raises(ScienceContractError, match="dependency status changed after binding"):
        verify_evidence_bindings(review, REPO_ROOT)


def test_every_existing_control_has_expected_observed_and_review_status() -> None:
    review = load_scope_connectivity_review(REVIEW_PATH)
    observations = review["controlObservations"]

    assert len(observations) == 36
    assert sum(item["domain"] == "geography" for item in observations) == 27
    assert sum(item["domain"] == "connectivity" for item in observations) == 9
    for item in observations:
        assert item["provenance"]
        assert item["expected"] == item["observed"]
        assert item["automationStatus"] == "passed"
        assert item["reviewerStatus"] == "pending-independent-review"


def test_public_states_and_sla_limit_are_distinct_and_fail_closed() -> None:
    review = load_scope_connectivity_review(REVIEW_PATH)
    controls = {item["id"]: item for item in review["semanticControls"]}

    assert controls["outside-coastal-scope"]["observedState"] == "OutOfScope"
    assert controls["outside-europe-support"]["observedState"] == "UnsupportedGeography"
    assert controls["north-of-sla-limit"]["latitude"] > 66.03125
    assert controls["north-of-sla-limit"]["observedState"] == "DataUnavailable"
    assert controls["support-boundary-covers"]["observedState"] == "OutOfScope"


def test_empirical_review_plan_covers_required_regional_failure_modes() -> None:
    review = load_scope_connectivity_review(REVIEW_PATH)
    controls = review["empiricalControls"]

    assert {item["kind"] for item in controls} == {
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
    for item in controls:
        assert item["observation"]["status"] == "blocked-by-dependencies"
        assert item["observation"]["blockingIssues"] == [95, 96]
        assert set(item["observation"]["metrics"].values()) == {None}
        assert item["reviewerStatus"] == "pending-independent-review"
    assert review["candidate"]["support"]["canonical"] is False
    assert review["candidate"]["coastalScope"] == {
        "canonical": False,
        "distanceMetres": 25000,
        "hazardExtentClaim": False,
        "role": "product-eligibility-only",
        "version": "natural-earth-5.1.1-25km-scope-v2",
    }


def test_blocked_empirical_control_cannot_contain_metrics() -> None:
    review = deepcopy(load_scope_connectivity_review(REVIEW_PATH))
    review["empiricalControls"][0]["observation"]["metrics"][
        "preFilterPositiveCellCount"
    ] = 1
    review["reviewEvidenceSha256"] = review_evidence_sha256(review)

    with pytest.raises(ScienceContractError, match="invented metrics"):
        validate_scope_connectivity_review(review)

    review = deepcopy(load_scope_connectivity_review(REVIEW_PATH))
    review["empiricalControls"][-1]["observation"]["blockingIssues"] = [95]
    review["reviewEvidenceSha256"] = review_evidence_sha256(review)

    with pytest.raises(ScienceContractError, match="blockers differ"):
        validate_scope_connectivity_review(review)


def _complete_first_empirical_control(review: dict) -> None:  # type: ignore[type-arg]
    review["empiricalControls"][0]["observation"] = {
        "status": "complete",
        "metrics": {
            "preFilterPositiveCellCount": 10,
            "postFilterPositiveCellCount": 8,
            "removedCellCount": 2,
            "removalFraction": 0.2,
            "referencePositiveCellCount": 8,
            "falsePositiveBeforeCount": 2,
            "falsePositiveAfterCount": 0,
            "falsePositiveBeforeRate": 0.2,
            "falsePositiveAfterRate": 0.0,
            "disputedCellCount": 0,
            "tileSeamMismatchCellCount": 0,
        },
        "evidence": {
            "id": "rotterdam-port-evidence",
            "path": "data/geometry/europe.geojson",
            "sha256": "0" * 64,
        },
        "blockingIssues": [],
    }
    review["reviewEvidenceSha256"] = review_evidence_sha256(review)


def test_complete_empirical_control_requires_checksum_bound_evidence() -> None:
    review = deepcopy(load_scope_connectivity_review(REVIEW_PATH))
    _complete_first_empirical_control(review)
    review["empiricalControls"][0]["observation"]["evidence"] = None
    review["reviewEvidenceSha256"] = review_evidence_sha256(review)

    with pytest.raises(ScienceContractError, match="Invalid Phase 0.13 review"):
        validate_scope_connectivity_review(review)


def test_completed_empirical_evidence_checksum_is_verified() -> None:
    review = deepcopy(load_scope_connectivity_review(REVIEW_PATH))
    _complete_first_empirical_control(review)

    with pytest.raises(ScienceContractError, match="empirical evidence changed"):
        verify_evidence_bindings(review, REPO_ROOT)


def test_observation_change_invalidates_review_evidence_hash() -> None:
    review = deepcopy(load_scope_connectivity_review(REVIEW_PATH))
    review["semanticControls"][0]["observedState"] = "DataUnavailable"

    with pytest.raises(ScienceContractError, match="observations checksum mismatch"):
        validate_scope_connectivity_review(review)


def test_evidence_change_invalidates_review_binding(tmp_path: Path) -> None:
    review = load_scope_connectivity_review(REVIEW_PATH)
    bound = review["evidenceBindings"][0]
    target = tmp_path / bound["path"]
    target.parent.mkdir(parents=True)
    target.write_text("changed", encoding="utf-8")

    with pytest.raises(ScienceContractError, match="evidence changed after binding"):
        verify_evidence_bindings(review, tmp_path)


def _signed_blocked_review(tmp_path: Path) -> dict:  # type: ignore[type-arg]
    review = deepcopy(load_scope_connectivity_review(REVIEW_PATH))
    reviewed_commit = "a" * 40
    review["review"].update(
        {
            "status": "decided",
            "disposition": "blocked",
            "reviewedCommit": reviewed_commit,
            "decisionBindingSha256": decision_binding_sha256(
                "blocked",
                review["evidenceBundleSha256"],
                review["reviewEvidenceSha256"],
                reviewed_commit,
            ),
        }
    )
    for key, record in review["review"]["reviewers"].items():
        private_key = Ed25519PrivateKey.generate()
        public_bytes = private_key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        key_path = tmp_path / f"reviewer-{key}.pem"
        key_path.write_bytes(public_bytes)
        record.update(
            {
                "decision": "blocked",
                "reviewer": f"Independent {key} reviewer",
                "independenceStatement": "I did not implement the reviewed controls.",
            }
        )
        payload = canonical_json_bytes(
            {
                "decision": record["decision"],
                "evidenceBundleSha256": review["evidenceBundleSha256"],
                "reviewEvidenceSha256": review["reviewEvidenceSha256"],
                "independenceStatement": record["independenceStatement"],
                "reviewedCommit": reviewed_commit,
                "reviewer": record["reviewer"],
                "role": record["role"],
            }
        )
        record["proof"] = {
            "kind": "ed25519-detached-signature",
            "publicKeyPath": key_path.name,
            "publicKeySha256": hashlib.sha256(public_bytes).hexdigest(),
            "signatureBase64": base64.b64encode(private_key.sign(payload)).decode("ascii"),
        }
    return review


def test_independent_reviewer_proofs_are_cryptographically_verified(
    tmp_path: Path,
) -> None:
    review = _signed_blocked_review(tmp_path)

    validate_scope_connectivity_review(review)
    verify_independent_review_proofs(review, tmp_path)

    review["review"]["reviewers"]["product"]["proof"]["signatureBase64"] = (
        base64.b64encode(b"x" * 64).decode("ascii")
    )
    with pytest.raises(ScienceContractError, match="signature is invalid"):
        verify_independent_review_proofs(review, tmp_path)


def test_decision_requires_both_named_signed_reviewers(tmp_path: Path) -> None:
    review = _signed_blocked_review(tmp_path)
    scientific = review["review"]["reviewers"]["scientific"]
    scientific.update(
        {
            "decision": "pending",
            "reviewer": None,
            "independenceStatement": None,
            "proof": None,
        }
    )

    with pytest.raises(ScienceContractError, match="both named, signed"):
        validate_scope_connectivity_review(review)


def test_review_roles_require_distinct_identities_and_keys(tmp_path: Path) -> None:
    review = _signed_blocked_review(tmp_path)
    product = review["review"]["reviewers"]["product"]
    scientific = review["review"]["reviewers"]["scientific"]
    scientific["reviewer"] = f"  {product['reviewer'].upper()}  "

    with pytest.raises(ScienceContractError, match="identities must be distinct"):
        validate_scope_connectivity_review(review)

    review = _signed_blocked_review(tmp_path)
    product = review["review"]["reviewers"]["product"]
    scientific = review["review"]["reviewers"]["scientific"]
    scientific["proof"]["publicKeyPath"] = product["proof"]["publicKeyPath"]
    scientific["proof"]["publicKeySha256"] = product["proof"]["publicKeySha256"]

    with pytest.raises(ScienceContractError, match="fingerprints must be distinct"):
        validate_scope_connectivity_review(review)


def test_automation_cannot_self_approve_the_review() -> None:
    review = deepcopy(load_scope_connectivity_review(REVIEW_PATH))
    reviewed_commit = "a" * 40
    review["review"].update(
        {
            "status": "decided",
            "disposition": "approved",
            "reviewedCommit": reviewed_commit,
            "decisionBindingSha256": decision_binding_sha256(
                "approved",
                review["evidenceBundleSha256"],
                review["reviewEvidenceSha256"],
                reviewed_commit,
            ),
        }
    )

    with pytest.raises(ScienceContractError, match="approved disposition lacks"):
        validate_scope_connectivity_review(review)


def test_pending_or_blocked_review_never_passes_the_approval_guard(
    tmp_path: Path,
) -> None:
    pending = load_scope_connectivity_review(REVIEW_PATH)
    blocked = _signed_blocked_review(tmp_path)

    with pytest.raises(ScienceContractError, match="is not approved"):
        assert_scope_connectivity_approved(pending, REPO_ROOT)
    with pytest.raises(ScienceContractError, match="is not approved"):
        assert_scope_connectivity_approved(blocked, tmp_path)
