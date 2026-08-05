"""Validated adapter boundary for GOCO06S-to-EGM2008 geoid evaluation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol

import numpy as np
from numpy.typing import NDArray

from .contracts import ScienceContractError


@dataclass(frozen=True)
class GeoidEnginePolicy:
    """Versioned external evaluator selected outside this implementation."""

    name: str
    version: str
    ellipsoid: str
    permanent_tide_rule: str


@dataclass(frozen=True)
class GeoidModelRequest:
    model: str
    version: str
    coefficients_sha256: str
    member_sha256: str
    native_tide_system: str
    output_tide_system: str
    evaluation_epoch: str | None
    maximum_degree: int
    maximum_order: int
    normalization: str
    earth_gravity_constant: float | None
    reference_radius_m: float | None
    evaluation_constants_status: str
    conversion_member_sha256: str | None
    requires_permanent_tide_conversion: bool
    requires_height_anomaly_to_geoid: bool
    policy: GeoidEnginePolicy


@dataclass(frozen=True)
class GeoidEvaluation:
    """Result and audit metadata returned by an external geodetic engine."""

    request: GeoidModelRequest
    undulation_m: NDArray[np.float64]
    engine_name: str
    engine_version: str
    ellipsoid: str
    output_tide_system: str
    maximum_degree: int
    maximum_order: int
    normalization: str
    earth_gravity_constant: float
    reference_radius_m: float
    permanent_tide_rule: str | None
    permanent_tide_conversion_applied: bool
    height_anomaly_to_geoid_applied: bool


@dataclass(frozen=True)
class GeoidCorrection:
    """GOCO06S minus EGM2008 geoid undulation on one convention."""

    values_m: NDArray[np.float64]
    valid: NDArray[np.bool_]
    source: GeoidEvaluation
    target: GeoidEvaluation


class GeoidEvaluator(Protocol):
    """External, version-pinned geodetic engine interface."""

    def evaluate(
        self,
        request: GeoidModelRequest,
        latitudes: NDArray[np.float64],
        longitudes: NDArray[np.float64],
    ) -> GeoidEvaluation: ...


def _source(document: Mapping[str, Any], source_id: str) -> Mapping[str, Any]:
    matches = [item for item in document["sources"] if item["id"] == source_id]
    if len(matches) != 1:
        raise ScienceContractError(f"Missing or duplicate geoid source: {source_id}")
    result = matches[0]
    if not isinstance(result, dict):
        raise ScienceContractError(f"Invalid geoid source: {source_id}")
    return result


def _member(source: Mapping[str, Any], member_id: str) -> Mapping[str, Any]:
    matches = [
        member
        for asset in source["assets"]
        for member in asset.get("members", [])
        if member["id"] == member_id
    ]
    if len(matches) != 1:
        raise ScienceContractError(f"Missing or duplicate geoid member: {member_id}")
    result = matches[0]
    if not isinstance(result, dict):
        raise ScienceContractError(f"Invalid geoid member: {member_id}")
    return result


def _asset(source: Mapping[str, Any], asset_id: str) -> Mapping[str, Any]:
    matches = [asset for asset in source["assets"] if asset["id"] == asset_id]
    if len(matches) != 1:
        raise ScienceContractError(f"Missing or duplicate geoid asset: {asset_id}")
    result = matches[0]
    if not isinstance(result, dict):
        raise ScienceContractError(f"Invalid geoid asset: {asset_id}")
    return result


def build_geoid_requests(
    source_semantics: Mapping[str, Any],
    source_lock: Mapping[str, Any],
    policy: GeoidEnginePolicy,
) -> tuple[GeoidModelRequest, GeoidModelRequest]:
    """Bind external evaluator requests to the exact locked model bytes."""
    if not all(
        (policy.name, policy.version, policy.ellipsoid, policy.permanent_tide_rule)
    ):
        raise ScienceContractError("Geoid engine policy is incomplete")
    inputs = source_semantics["verticalInputs"]
    source_spec, target_spec = inputs["sourceGeoid"], inputs["targetGeoid"]
    goco = _source(source_lock, source_spec["sourceId"])
    egm = _source(source_lock, target_spec["sourceId"])
    if goco["version"] != source_spec["version"] or egm["version"] != target_spec["version"]:
        raise ScienceContractError("Geoid source-lock version differs from source semantics")

    goco_asset = _asset(goco, "goco06s-coefficients")
    egm_asset = _asset(egm, "spherical-harmonics")
    goco_member = _member(goco, "goco06s-gfc")
    egm_member = _member(egm, "egm2008-coefficients")
    conversion_member = _member(egm, "zeta-to-n-terms")
    source_request = GeoidModelRequest(
        model=source_spec["model"],
        version=source_spec["version"],
        coefficients_sha256=goco_asset["sha256"],
        member_sha256=goco_member["sha256"],
        native_tide_system=source_spec["nativeTideSystem"],
        output_tide_system="tide_free",
        evaluation_epoch=source_spec["evaluationEpoch"],
        maximum_degree=source_spec["maximumDegree"],
        maximum_order=source_spec["maximumOrder"],
        normalization=source_spec["normalization"],
        earth_gravity_constant=source_spec["earthGravityConstant"],
        reference_radius_m=source_spec["referenceRadiusMetres"],
        evaluation_constants_status=source_spec["evaluationConstantsStatus"],
        conversion_member_sha256=None,
        requires_permanent_tide_conversion=True,
        requires_height_anomaly_to_geoid=False,
        policy=policy,
    )
    target_request = GeoidModelRequest(
        model=target_spec["model"],
        version=target_spec["version"],
        coefficients_sha256=egm_asset["sha256"],
        member_sha256=egm_member["sha256"],
        native_tide_system=target_spec["nativeTideSystem"],
        output_tide_system="tide_free",
        evaluation_epoch=None,
        maximum_degree=target_spec["maximumDegree"],
        maximum_order=target_spec["maximumOrder"],
        normalization=target_spec["normalization"],
        earth_gravity_constant=target_spec["earthGravityConstant"],
        reference_radius_m=target_spec["referenceRadiusMetres"],
        evaluation_constants_status=target_spec["evaluationConstantsStatus"],
        conversion_member_sha256=conversion_member["sha256"],
        requires_permanent_tide_conversion=False,
        requires_height_anomaly_to_geoid=True,
        policy=policy,
    )
    return source_request, target_request


def _validate_request(request: GeoidModelRequest) -> None:
    if (
        request.evaluation_constants_status != "locked"
        or request.earth_gravity_constant is None
        or request.reference_radius_m is None
    ):
        raise ScienceContractError(
            f"{request.model} evaluation constants are not pinned"
        )
    if (
        not request.normalization
        or request.maximum_degree < 1
        or request.maximum_order < 0
        or request.maximum_order > request.maximum_degree
    ):
        raise ScienceContractError(f"{request.model} harmonic convention is invalid")


def _validate_evaluation(evaluation: GeoidEvaluation) -> None:
    request = evaluation.request
    policy = request.policy
    if (
        evaluation.engine_name != policy.name
        or evaluation.engine_version != policy.version
        or evaluation.ellipsoid != policy.ellipsoid
    ):
        raise ScienceContractError("Geoid evaluation engine or ellipsoid differs from policy")
    if evaluation.output_tide_system != "tide_free":
        raise ScienceContractError("Geoid evaluation is not tide-free")
    if (
        evaluation.maximum_degree != request.maximum_degree
        or evaluation.maximum_order != request.maximum_order
        or evaluation.normalization != request.normalization
        or evaluation.earth_gravity_constant != request.earth_gravity_constant
        or evaluation.reference_radius_m != request.reference_radius_m
    ):
        raise ScienceContractError("Geoid harmonic constants differ from request")
    required_tide_rule = (
        policy.permanent_tide_rule
        if request.requires_permanent_tide_conversion
        else None
    )
    if evaluation.permanent_tide_rule != required_tide_rule:
        raise ScienceContractError("Geoid permanent-tide rule differs from policy")
    if (
        evaluation.permanent_tide_conversion_applied
        != request.requires_permanent_tide_conversion
    ):
        raise ScienceContractError("Geoid permanent-tide conversion evidence differs from request")
    if evaluation.height_anomaly_to_geoid_applied != request.requires_height_anomaly_to_geoid:
        raise ScienceContractError("Geoid height-anomaly conversion evidence differs from request")


def evaluate_geoid_correction(
    evaluator: GeoidEvaluator,
    source_request: GeoidModelRequest,
    target_request: GeoidModelRequest,
    latitudes: NDArray[np.float64],
    longitudes: NDArray[np.float64],
) -> GeoidCorrection:
    """Evaluate and subtract two models only after all reference checks pass."""
    if latitudes.shape != longitudes.shape:
        raise ScienceContractError("Geoid coordinate arrays do not share a shape")
    if source_request.policy != target_request.policy:
        raise ScienceContractError("Geoid models do not share one evaluation policy")
    _validate_request(source_request)
    _validate_request(target_request)
    source = evaluator.evaluate(source_request, latitudes, longitudes)
    target = evaluator.evaluate(target_request, latitudes, longitudes)
    _validate_evaluation(source)
    _validate_evaluation(target)
    source_values = np.asarray(source.undulation_m, dtype=np.float64)
    target_values = np.asarray(target.undulation_m, dtype=np.float64)
    if source_values.shape != latitudes.shape or target_values.shape != latitudes.shape:
        raise ScienceContractError("Geoid evaluation does not match coordinate shape")
    valid = np.isfinite(source_values) & np.isfinite(target_values)
    values = source_values - target_values
    values[~valid] = np.nan
    return GeoidCorrection(values_m=values, valid=valid, source=source, target=target)


def reconcile_baseline_to_egm2008(
    adt_goco06s_m: NDArray[np.floating[Any]], correction: GeoidCorrection
) -> NDArray[np.float64]:
    """Apply B_EGM2008 = ADT_GOCO06S + N_GOCO06S - N_EGM2008."""
    adt = np.asarray(adt_goco06s_m, dtype=np.float64)
    if adt.shape != correction.values_m.shape:
        raise ScienceContractError("Baseline and geoid correction shapes differ")
    result = adt + correction.values_m
    result[~(np.isfinite(adt) & correction.valid)] = np.nan
    return result
