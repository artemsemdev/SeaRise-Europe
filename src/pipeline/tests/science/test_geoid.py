"""Tests for the pinned external geoid-evaluation boundary."""

from __future__ import annotations

import json
import shutil
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from searise_pipeline.science import (
    GeoidEnginePolicy,
    GeoidEvaluation,
    ScienceContractError,
    build_geoid_requests,
    evaluate_geoid_correction,
    evaluator_disagreement_term,
    geoid_evidence_sha256,
    load_geoid_evaluator_evidence,
    load_geoid_evaluator_policy,
    load_science_contracts,
    reconcile_baseline_to_egm2008,
)

REPO_ROOT = Path(__file__).parents[4]


class FakeEvaluator:
    def evaluate(self, request, latitudes, longitudes):  # type: ignore[no-untyped-def]
        values = np.full(latitudes.shape, 5.0 if request.model == "GOCO06S" else 3.0)
        return GeoidEvaluation(
            request=request,
            undulation_m=values,
            engine_name=request.policy.name,
            engine_version=request.policy.version,
            ellipsoid=request.policy.ellipsoid,
            output_tide_system=request.output_tide_system,
            maximum_degree=request.maximum_degree,
            maximum_order=request.maximum_order,
            normalization=request.normalization,
            earth_gravity_constant=request.earth_gravity_constant,
            reference_radius_m=request.reference_radius_m,
            permanent_tide_rule=(
                request.policy.permanent_tide_rule
                if request.requires_permanent_tide_conversion
                else None
            ),
            permanent_tide_conversion_applied=request.requires_permanent_tide_conversion,
            height_anomaly_to_geoid_applied=request.requires_height_anomaly_to_geoid,
        )


def _requests():  # type: ignore[no-untyped-def]
    contracts = load_science_contracts(REPO_ROOT / "src/pipeline/science")
    source_lock = json.loads(
        (REPO_ROOT / "src/pipeline/sources/source-lock.json").read_text(encoding="utf-8")
    )
    policy = GeoidEnginePolicy(
        name="reviewed-engine",
        version="1.0.0",
        ellipsoid="WGS84",
        permanent_tide_rule="reviewed-zero-tide-to-tide-free-v1",
    )
    return build_geoid_requests(contracts.source_semantics, source_lock, policy)


def _complete_requests():  # type: ignore[no-untyped-def]
    source, target = _requests()
    # Synthetic adapter control only. The project contract deliberately keeps
    # these EGM2008 values pending until locked README evidence is inspected.
    target = replace(
        target,
        earth_gravity_constant=398600441500000.0,
        reference_radius_m=6378136.3,
        evaluation_constants_status="locked",
    )
    return source, target


def test_requests_bind_exact_coefficients_and_required_conversions() -> None:
    source, target = _requests()

    assert source.member_sha256 == (
        "351d9d20b84cd2c0f52ce77146b1e3b774f408200b579ffaf98593cf3d271819"
    )
    assert source.native_tide_system == "zero_tide"
    assert source.output_tide_system == "tide_free"
    assert source.requires_permanent_tide_conversion
    assert source.maximum_order == 300
    assert source.normalization == "fully_normalized"
    assert source.earth_gravity_constant == 398600441500000.0
    assert source.reference_radius_m == 6378136.3
    assert target.member_sha256 == (
        "7e448aac4e1b8e63955890cbca08286018ecc6d203e074a64ba5bde21851438a"
    )
    assert target.conversion_member_sha256 == (
        "464ca875a86a5eba8e7dbb8f3cd18196c02375a318b77bc3a0294abf073b07b8"
    )
    assert target.requires_height_anomaly_to_geoid
    assert target.evaluation_constants_status == "pending-locked-readme-inspection"
    assert target.earth_gravity_constant is None
    assert target.reference_radius_m is None


def test_missing_egm2008_evaluation_constants_fail_before_engine_call() -> None:
    source, target = _requests()

    with pytest.raises(ScienceContractError, match="EGM2008 evaluation constants"):
        evaluate_geoid_correction(
            FakeEvaluator(), source, target, np.array([50.0]), np.array([4.0])
        )


def test_reconciliation_uses_goco_minus_egm_sign() -> None:
    source, target = _complete_requests()
    coordinates = np.array([50.0, 51.0])

    correction = evaluate_geoid_correction(
        FakeEvaluator(), source, target, coordinates, np.array([4.0, 5.0])
    )
    baseline = reconcile_baseline_to_egm2008(np.array([1.0, np.nan]), correction)

    np.testing.assert_array_equal(correction.values_m, [2.0, 2.0])
    assert baseline[0] == 3.0
    assert np.isnan(baseline[1])


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("output_tide_system", "zero_tide", "not tide-free"),
        ("ellipsoid", "GRS80", "ellipsoid"),
        ("permanent_tide_conversion_applied", False, "permanent-tide"),
        ("height_anomaly_to_geoid_applied", False, "height-anomaly"),
        ("normalization", "unnormalized", "harmonic constants"),
        ("maximum_order", 1, "harmonic constants"),
        ("earth_gravity_constant", 1.0, "harmonic constants"),
    ],
)
def test_unreviewed_reference_operation_fails_closed(
    field: str, value: object, message: str
) -> None:
    source, target = _complete_requests()

    class InvalidEvaluator(FakeEvaluator):
        def evaluate(self, request, latitudes, longitudes):  # type: ignore[no-untyped-def]
            evaluation = super().evaluate(request, latitudes, longitudes)
            invalid_model = (
                "EGM2008" if field == "height_anomaly_to_geoid_applied" else "GOCO06S"
            )
            if request.model == invalid_model:
                return replace(evaluation, **{field: value})
            return evaluation

    with pytest.raises(ScienceContractError, match=message):
        evaluate_geoid_correction(
            InvalidEvaluator(), source, target, np.array([50.0]), np.array([4.0])
        )


def test_incomplete_engine_policy_is_rejected_before_evaluation() -> None:
    contracts = load_science_contracts(REPO_ROOT / "src/pipeline/science")
    source_lock = json.loads(
        (REPO_ROOT / "src/pipeline/sources/source-lock.json").read_text(encoding="utf-8")
    )

    with pytest.raises(ScienceContractError, match="policy is incomplete"):
        build_geoid_requests(
            contracts.source_semantics,
            source_lock,
            GeoidEnginePolicy("", "", "WGS84", ""),
        )


def test_pinned_evaluator_policy_resolves_every_harmonic_convention() -> None:
    policy = load_geoid_evaluator_policy()
    models = {item["model"]: item for item in policy["models"]}

    assert policy["status"] == "blocked"
    assert policy["evaluator"] == {
        "name": "pyshtools",
        "version": "4.13.1",
        "tagCommit": "4c7fd73fd61f863351fdc067294c8538acc70d89",
        "sourceUrl": "https://github.com/SHTOOLS/SHTOOLS/tree/v4.13.1",
        "sourceArchive": {
            "url": (
                "https://files.pythonhosted.org/packages/f4/58/b75aa783852e3b5af74e5657163c5ddc"
                "2d3a906d3cf935b4f41a57defcbc/pyshtools-4.13.1.tar.gz"
            ),
            "byteSize": 41577254,
            "sha256": "cc4a323e9cbc905c04ae9e2e9fedeea6d76f3315a6863ede353a4dec87b8c018",
        },
        "licence": {
            "spdx": "BSD-3-Clause",
            "url": "https://github.com/SHTOOLS/SHTOOLS/blob/v4.13.1/LICENSE.txt",
            "redistribution": "compatible",
        },
        "backend": "native-shtools-fortran",
        "supportedMaximumDegree": 2800,
        "dependencyPolicy": "hash-locked-wheel-and-transitive-environment",
    }
    assert policy["referenceFrame"]["synthesisLatitude"].startswith("geocentric-")
    assert policy["harmonicConvention"] == {
        "normalization": "fully-normalized-geodesy-4pi",
        "condonShortleyPhase": "excluded-csphase-plus-one",
        "coefficientOrdering": "degree-ascending-order-ascending-cosine-then-sine",
        "missingCoefficientRule": "explicit-zero-only-no-implicit-truncation",
        "interpolation": "point-synthesis-no-interpolation",
        "extrapolation": "none",
        "nodata": "reject-nonfinite-coordinate-or-coefficient-and-propagate-nodata",
    }
    assert models["GOCO06S"]["epoch"] == {
        "status": "applicable",
        "value": "2010-01-01",
        "timeVariableTerms": "evaluate-at-epoch",
    }
    assert models["GOCO06S"]["permanentTideConversion"][
        "deltaFullyNormalizedC20"
    ] == 4.1736e-9
    assert models["EGM2008"]["epoch"] == {
        "status": "not-applicable-static-model",
        "value": None,
        "timeVariableTerms": "not-applicable",
    }
    assert policy["publicationGate"]["ciCanApprove"] is False


def test_authoritative_benchmarks_are_machine_checkable_and_fail_closed() -> None:
    evidence = load_geoid_evaluator_evidence()
    comparisons = {item["model"]: item for item in evidence["comparisons"]}
    egm = comparisons["EGM2008"]
    goco = comparisons["GOCO06S"]

    disagreements = [
        abs(point["expectedMetres"] - point["actualMetres"])
        for point in egm["points"]
    ]
    assert max(disagreements) == pytest.approx(egm["maximumAbsoluteDisagreementMetres"])
    assert max(disagreements) <= egm["toleranceMetres"]
    coverage = {
        value
        for item in evidence["comparisons"]
        for point in item["points"]
        for value in point["coverage"]
    }
    required = load_geoid_evaluator_policy()["benchmarkPolicy"]["requiredCoverage"]
    assert coverage.issuperset(required)
    assert goco["status"] == "blocked"
    assert goco["resultReceipt"]["status"] == "upstream-result-unavailable"
    assert evidence["review"]["independent"] is False
    assert evidence["status"] == "blocked"

    term = evaluator_disagreement_term(evidence, (2, 3))
    assert term.bound_m is None
    assert "status=blocked" in term.provenance
    assert len(geoid_evidence_sha256(evidence)) == 64


def test_evaluator_policy_identity_or_evidence_tampering_is_rejected(
    tmp_path: Path,
) -> None:
    science_dir = REPO_ROOT / "src" / "pipeline" / "science"
    policy = json.loads((science_dir / "geoid-evaluator.json").read_text(encoding="utf-8"))
    policy["evaluator"]["version"] = "unreviewed"
    policy_path = tmp_path / "geoid-evaluator.json"
    policy_path.write_text(json.dumps(policy), encoding="utf-8")
    shutil.copy(science_dir / "geoid-evaluator.schema.json", tmp_path)

    with pytest.raises(ScienceContractError, match="Invalid geoid evaluator policy"):
        load_geoid_evaluator_policy(policy_path)

    evidence = json.loads(
        (science_dir / "evidence" / "geoid-evaluator-validation.json").read_text(
            encoding="utf-8"
        )
    )
    evidence["sourceEvidence"] = []
    evidence_path = tmp_path / "invalid-evidence.json"
    evidence_path.write_text(json.dumps(evidence), encoding="utf-8")
    with pytest.raises(ScienceContractError, match="Invalid geoid evaluator evidence"):
        load_geoid_evaluator_evidence(evidence_path)


def test_evidence_rejects_a_different_but_schema_valid_policy(tmp_path: Path) -> None:
    science_dir = REPO_ROOT / "src" / "pipeline" / "science"
    policy_path = tmp_path / "geoid-evaluator.json"
    policy_path.write_bytes((science_dir / "geoid-evaluator.json").read_bytes() + b"\n")
    shutil.copy(science_dir / "geoid-evaluator.schema.json", tmp_path)

    with pytest.raises(ScienceContractError, match="policy checksum mismatch"):
        load_geoid_evaluator_evidence(policy_path=policy_path)
