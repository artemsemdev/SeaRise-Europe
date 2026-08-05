"""Tests for the pinned external geoid-evaluation boundary."""

from __future__ import annotations

import json
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
