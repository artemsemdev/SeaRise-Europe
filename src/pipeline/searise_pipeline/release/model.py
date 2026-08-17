"""Source-native regional arrays and the audited offline fixture format."""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import numpy as np
from jsonschema import Draft202012Validator
from numpy.typing import NDArray

from searise_pipeline.science.ar6 import extract_projection_interval
from searise_pipeline.science.ar6_lookup import (
    open_verified_ar6_member,
    verify_ar6_archive,
)
from searise_pipeline.science.contracts import ScienceContractError

_CHUNK_BYTES = 1024 * 1024
_VERIFIED_ARCHIVE_CAPABILITY = object()
_OFFLINE_FIXTURE_CAPABILITY = object()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(_CHUNK_BYTES), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_json(document: Mapping[str, Any]) -> bytes:
    encoded = json.dumps(
        document,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return (encoded + "\n").encode("utf-8")


def load_release_contract(path: Path) -> Mapping[str, Any]:
    """Load and fully schema-validate the fixed issue #110 contract."""
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
        schema = json.loads(path.with_suffix(".schema.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ScienceContractError(f"Cannot read AR6 release contract: {exc}") from exc
    errors = sorted(Draft202012Validator(schema).iter_errors(document), key=lambda e: list(e.path))
    if errors:
        details = "; ".join(error.message for error in errors)
        raise ScienceContractError(f"Invalid AR6 regional release contract: {details}")
    return document


@dataclass(frozen=True)
class RegionalLayer:
    """Three exact AR6 quantiles for one scenario and horizon, stored in mm."""

    scenario: str
    horizon: int
    member_sha256: str
    lower_mm: NDArray[np.int16]
    central_mm: NDArray[np.int16]
    upper_mm: NDArray[np.int16]

    @property
    def valid(self) -> NDArray[np.bool_]:
        return (self.lower_mm != -32768) & (self.central_mm != -32768) & (self.upper_mm != -32768)


@dataclass(frozen=True)
class RegionalReleaseSource:
    """Complete rectangular Europe subset bound to exact source identities."""

    _verification_capability: object
    archive_sha256: str
    contract_sha256: str
    latitudes: NDArray[np.float64]
    longitudes: NDArray[np.float64]
    location_ids: NDArray[np.int64]
    layers: tuple[RegionalLayer, ...]
    _content_sha256: str

    @property
    def source_mode(self) -> str:
        if self._verification_capability is _VERIFIED_ARCHIVE_CAPABILITY:
            return "verified-archive"
        if self._verification_capability is _OFFLINE_FIXTURE_CAPABILITY:
            return "offline-real-source-fixture"
        return "unverified"

    @property
    def archive_and_members_verified_this_build(self) -> bool:
        return self._verification_capability is _VERIFIED_ARCHIVE_CAPABILITY

    @property
    def content_sha256(self) -> str:
        return self._content_sha256


def _to_millimetres(values_m: NDArray[np.float64], nodata: int) -> NDArray[np.int16]:
    complete = np.isfinite(values_m)
    scaled = np.full(values_m.shape, nodata, dtype=np.int16)
    rounded = np.rint(values_m[complete] * 1000)
    if np.any(rounded <= np.iinfo(np.int16).min) or np.any(rounded > np.iinfo(np.int16).max):
        raise ScienceContractError("AR6 regional value cannot be represented as Int16 mm")
    scaled[complete] = rounded.astype(np.int16)
    return scaled


def _validate_source(source: RegionalReleaseSource, contract: Mapping[str, Any]) -> None:
    matrix = contract["matrix"]
    expected_layers = {
        (scenario, horizon) for scenario in matrix["scenarios"] for horizon in matrix["horizons"]
    }
    actual_layers = {(layer.scenario, layer.horizon) for layer in source.layers}
    if actual_layers != expected_layers or len(source.layers) != 9:
        raise ScienceContractError("AR6 regional source does not contain the exact 3 x 3 matrix")
    grid = contract["grid"]
    expected_shape = (grid["height"], grid["width"])
    if source.location_ids.shape != expected_shape:
        raise ScienceContractError("AR6 regional source shape differs from the release contract")
    if source.latitudes.tolist() != list(
        np.arange(grid["latitudeCentres"][0], grid["latitudeCentres"][1] + 1)
    ) or source.longitudes.tolist() != list(
        np.arange(grid["longitudeCentres"][0], grid["longitudeCentres"][1] + 1)
    ):
        raise ScienceContractError("AR6 regional coordinates differ from the native grid contract")
    if np.unique(source.location_ids).size != source.location_ids.size:
        raise ScienceContractError("AR6 regional source location IDs are not unique")

    nodata = contract["values"]["nodata"]
    for layer in source.layers:
        arrays = (layer.lower_mm, layer.central_mm, layer.upper_mm)
        if any(array.shape != expected_shape or array.dtype != np.int16 for array in arrays):
            raise ScienceContractError("AR6 regional quantile arrays changed shape or dtype")
        masks = tuple(array == nodata for array in arrays)
        if not (np.array_equal(masks[0], masks[1]) and np.array_equal(masks[1], masks[2])):
            raise ScienceContractError("AR6 regional quantiles do not share one nodata mask")
        valid = ~masks[0]
        if np.any(
            (layer.lower_mm[valid] > layer.central_mm[valid])
            | (layer.central_mm[valid] > layer.upper_mm[valid])
        ):
            raise ScienceContractError("AR6 regional quantiles are not monotonic")


def _source_content_sha256(
    latitudes: NDArray[np.float64],
    longitudes: NDArray[np.float64],
    location_ids: NDArray[np.int64],
    layers: tuple[RegionalLayer, ...],
) -> str:
    digest = hashlib.sha256()
    for array in (latitudes, longitudes, location_ids):
        digest.update(array.dtype.str.encode())
        digest.update(str(array.shape).encode())
        digest.update(np.ascontiguousarray(array).tobytes())
    for layer in layers:
        digest.update(f"{layer.scenario}/{layer.horizon}/{layer.member_sha256}".encode())
        for array in (layer.lower_mm, layer.central_mm, layer.upper_mm):
            digest.update(array.dtype.str.encode())
            digest.update(str(array.shape).encode())
            digest.update(np.ascontiguousarray(array).tobytes())
    return digest.hexdigest()


def _freeze_array(array: NDArray[Any]) -> NDArray[Any]:
    frozen = np.ascontiguousarray(array).copy()
    frozen.flags.writeable = False
    return frozen


def _freeze_source_arrays(
    latitudes: NDArray[np.float64],
    longitudes: NDArray[np.float64],
    location_ids: NDArray[np.int64],
    layers: tuple[RegionalLayer, ...],
) -> tuple[NDArray[np.float64], NDArray[np.float64], NDArray[np.int64], tuple[RegionalLayer, ...]]:
    frozen_layers = tuple(
        RegionalLayer(
            scenario=layer.scenario,
            horizon=layer.horizon,
            member_sha256=layer.member_sha256,
            lower_mm=_freeze_array(layer.lower_mm),
            central_mm=_freeze_array(layer.central_mm),
            upper_mm=_freeze_array(layer.upper_mm),
        )
        for layer in layers
    )
    return (
        _freeze_array(latitudes),
        _freeze_array(longitudes),
        _freeze_array(location_ids),
        frozen_layers,
    )


def assert_source_integrity(
    source: RegionalReleaseSource,
    contract: Mapping[str, Any],
    *,
    require_verified_archive: bool,
) -> None:
    """Revalidate semantics and the post-verification content seal before building."""
    if require_verified_archive and not source.archive_and_members_verified_this_build:
        raise ScienceContractError("Scientific release requires freshly verified archive bytes")
    _validate_source(source, contract)
    _assert_source_content_seal(source)


def _assert_source_content_seal(source: RegionalReleaseSource) -> None:
    """Reject any array mutation after source verification or fixture loading."""
    observed = _source_content_sha256(
        source.latitudes, source.longitudes, source.location_ids, source.layers
    )
    if observed != source._content_sha256:
        raise ScienceContractError("AR6 regional source changed after verification")


def build_source_from_verified_archive(
    archive_path: Path,
    *,
    source_lock: Mapping[str, Any],
    source_semantics: Mapping[str, Any],
    release_contract: Mapping[str, Any],
    release_contract_path: Path,
) -> RegionalReleaseSource:
    """Verify the 9.24 GB archive and members before extracting the Europe grid."""
    try:
        contract_bytes = json.loads(release_contract_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ScienceContractError(f"Cannot re-read release contract bytes: {exc}") from exc
    if contract_bytes != release_contract:
        raise ScienceContractError("Release contract mapping differs from its versioned file")
    projection = source_semantics["projection"]
    if release_contract["source"]["archiveSha256"] != projection["archive"]["sha256"]:
        raise ScienceContractError("Release and source-semantics archive identities differ")
    verified = verify_ar6_archive(archive_path, source_lock, projection)
    grid = release_contract["grid"]
    nodata = release_contract["values"]["nodata"]
    layers: list[RegionalLayer] = []
    regional_latitudes: NDArray[np.float64] | None = None
    regional_longitudes: NDArray[np.float64] | None = None
    regional_location_ids: NDArray[np.int64] | None = None
    for scenario in release_contract["matrix"]["scenarios"]:
        with open_verified_ar6_member(verified, scenario) as (dataset, identity):
            for horizon in release_contract["matrix"]["horizons"]:
                interval = extract_projection_interval(
                    dataset,
                    projection,
                    scenario,
                    horizon,
                    member_identity=identity,
                    verified_member_sha256=identity.sha256,
                )
                latitude_mask = (interval.lower.latitudes >= grid["latitudeCentres"][0]) & (
                    interval.lower.latitudes <= grid["latitudeCentres"][1]
                )
                longitude_mask = (interval.lower.longitudes >= grid["longitudeCentres"][0]) & (
                    interval.lower.longitudes <= grid["longitudeCentres"][1]
                )
                selection = np.ix_(latitude_mask, longitude_mask)
                latitudes = interval.lower.latitudes[latitude_mask]
                longitudes = interval.lower.longitudes[longitude_mask]
                location_ids = interval.lower.location_ids[selection]
                if regional_latitudes is None:
                    regional_latitudes = latitudes
                    regional_longitudes = longitudes
                    regional_location_ids = location_ids
                elif not (
                    np.array_equal(regional_latitudes, latitudes)
                    and np.array_equal(regional_longitudes, longitudes)
                    and np.array_equal(regional_location_ids, location_ids)
                ):
                    raise ScienceContractError("AR6 members do not share one regional grid")
                layers.append(
                    RegionalLayer(
                        scenario=scenario,
                        horizon=horizon,
                        member_sha256=identity.sha256,
                        lower_mm=_to_millimetres(interval.lower.values_m[selection], nodata),
                        central_mm=_to_millimetres(interval.central.values_m[selection], nodata),
                        upper_mm=_to_millimetres(interval.upper.values_m[selection], nodata),
                    )
                )
    if regional_latitudes is None or regional_longitudes is None or regional_location_ids is None:
        raise ScienceContractError("AR6 regional source extraction produced no grid")
    frozen = _freeze_source_arrays(
        regional_latitudes, regional_longitudes, regional_location_ids, tuple(layers)
    )
    source = RegionalReleaseSource(
        _verification_capability=_VERIFIED_ARCHIVE_CAPABILITY,
        archive_sha256=verified.sha256,
        contract_sha256=hashlib.sha256(_canonical_json(release_contract)).hexdigest(),
        latitudes=frozen[0],
        longitudes=frozen[1],
        location_ids=frozen[2],
        layers=frozen[3],
        _content_sha256=_source_content_sha256(*frozen),
    )
    _validate_source(source, release_contract)
    return source


def _fixture_document(source: RegionalReleaseSource) -> Mapping[str, Any]:
    return {
        "schemaVersion": 1,
        "fixtureId": "ar6-europe-regional-source-v1",
        "sourceMode": "offline-real-source-fixture",
        "archiveSha256": source.archive_sha256,
        "releaseContractSha256": source.contract_sha256,
        "latitudes": source.latitudes.tolist(),
        "longitudes": source.longitudes.tolist(),
        "locationIds": source.location_ids.ravel().tolist(),
        "layers": [
            {
                "scenario": layer.scenario,
                "horizon": layer.horizon,
                "memberSha256": layer.member_sha256,
                "lowerMm": layer.lower_mm.ravel().tolist(),
                "centralMm": layer.central_mm.ravel().tolist(),
                "upperMm": layer.upper_mm.ravel().tolist(),
            }
            for layer in source.layers
        ],
    }


def write_source_fixture(source: RegionalReleaseSource, path: Path) -> Mapping[str, Any]:
    """Write a deterministic gzip fixture derived from already verified bytes."""
    _assert_source_content_seal(source)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = _canonical_json(_fixture_document(source))
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as temporary:
        temporary_path = Path(temporary.name)
        with gzip.GzipFile(filename="", mode="wb", fileobj=temporary, mtime=0) as stream:
            stream.write(payload)
    os.replace(temporary_path, path)
    return {
        "fixtureId": "ar6-europe-regional-source-v1",
        "byteSize": path.stat().st_size,
        "sha256": _sha256(path),
        "archiveSha256": source.archive_sha256,
        "memberSha256": {
            layer.scenario: layer.member_sha256 for layer in source.layers if layer.horizon == 2030
        },
        "releaseContractSha256": source.contract_sha256,
        "derivation": f"{source.source_mode}-native-grid-subset-no-resampling",
        "sourceArchiveVerifiedForThisWrite": source.archive_and_members_verified_this_build,
        "scientificReleaseEligible": False,
    }


def rebind_source_fixture_contract(
    path: Path,
    *,
    receipt: Mapping[str, Any],
    release_contract: Mapping[str, Any],
    expected_previous_contract_sha256: str,
) -> tuple[bytes, Mapping[str, Any]]:
    """Rebind an intact offline fixture after a non-scientific contract edit.

    This migration never grants verified-archive capability. It verifies the
    previous byte receipt and source identities, validates every retained array
    against the current contract, and returns deterministic replacement bytes
    plus an explicitly non-release-eligible receipt.
    """
    previous_fixture_sha256 = _sha256(path)
    if path.stat().st_size != receipt.get("byteSize") or previous_fixture_sha256 != receipt.get(
        "sha256"
    ):
        raise ScienceContractError("AR6 regional source fixture integrity mismatch")
    try:
        with gzip.open(path, "rt", encoding="utf-8") as stream:
            document = json.load(stream)
    except (OSError, json.JSONDecodeError) as exc:
        raise ScienceContractError(f"Cannot read AR6 regional source fixture: {exc}") from exc
    if (
        document.get("releaseContractSha256") != expected_previous_contract_sha256
        or receipt.get("releaseContractSha256") != expected_previous_contract_sha256
    ):
        raise ScienceContractError("Fixture does not match the authorized previous contract")
    if (
        document.get("archiveSha256") != receipt.get("archiveSha256")
        or document.get("archiveSha256") != release_contract["source"]["archiveSha256"]
    ):
        raise ScienceContractError("Fixture archive identity differs during contract rebind")

    expected_members = receipt.get("memberSha256")
    if not isinstance(expected_members, Mapping):
        raise ScienceContractError("Fixture receipt has no member identity mapping")
    for item in document.get("layers", []):
        if expected_members.get(item.get("scenario")) != item.get("memberSha256"):
            raise ScienceContractError("Fixture member identity differs during contract rebind")

    current_contract_sha256 = hashlib.sha256(_canonical_json(release_contract)).hexdigest()
    rebound_document = dict(document)
    rebound_document["releaseContractSha256"] = current_contract_sha256
    payload = _canonical_json(rebound_document)
    with tempfile.TemporaryFile() as temporary:
        with gzip.GzipFile(filename="", mode="wb", fileobj=temporary, mtime=0) as stream:
            stream.write(payload)
        temporary.seek(0)
        rebound_bytes = temporary.read()

    with tempfile.TemporaryDirectory() as directory:
        rebound_path = Path(directory) / "source-fixture.json.gz"
        rebound_path.write_bytes(rebound_bytes)
        base_receipt = {
            "fixtureId": "ar6-europe-regional-source-v1",
            "byteSize": len(rebound_bytes),
            "sha256": hashlib.sha256(rebound_bytes).hexdigest(),
            "archiveSha256": document["archiveSha256"],
            "memberSha256": dict(expected_members),
            "releaseContractSha256": current_contract_sha256,
            "derivation": "verified-archive-native-grid-subset-no-resampling-contract-rebind",
            "sourceArchiveVerifiedForThisWrite": False,
            "scientificReleaseEligible": False,
            "contractRebind": {
                "previousContractSha256": expected_previous_contract_sha256,
                "previousFixtureSha256": previous_fixture_sha256,
                "scientificValuesChanged": False,
            },
        }
        rebound = load_source_fixture(
            rebound_path,
            receipt=base_receipt,
            release_contract=release_contract,
        )
        _assert_source_content_seal(rebound)
    return rebound_bytes, base_receipt


def load_source_fixture(
    path: Path,
    *,
    receipt: Mapping[str, Any],
    release_contract: Mapping[str, Any],
) -> RegionalReleaseSource:
    """Load a committed real-source fixture only after checking its receipt."""
    if path.stat().st_size != receipt.get("byteSize") or _sha256(path) != receipt.get("sha256"):
        raise ScienceContractError("AR6 regional source fixture integrity mismatch")
    try:
        with gzip.open(path, "rt", encoding="utf-8") as stream:
            document = json.load(stream)
    except (OSError, json.JSONDecodeError) as exc:
        raise ScienceContractError(f"Cannot read AR6 regional source fixture: {exc}") from exc
    if document.get("fixtureId") != "ar6-europe-regional-source-v1":
        raise ScienceContractError("Unexpected AR6 regional source fixture")
    shape = (release_contract["grid"]["height"], release_contract["grid"]["width"])
    layers = tuple(
        RegionalLayer(
            scenario=item["scenario"],
            horizon=item["horizon"],
            member_sha256=item["memberSha256"],
            lower_mm=np.asarray(item["lowerMm"], dtype=np.int16).reshape(shape),
            central_mm=np.asarray(item["centralMm"], dtype=np.int16).reshape(shape),
            upper_mm=np.asarray(item["upperMm"], dtype=np.int16).reshape(shape),
        )
        for item in document["layers"]
    )
    raw_latitudes = np.asarray(document["latitudes"], dtype=np.float64)
    raw_longitudes = np.asarray(document["longitudes"], dtype=np.float64)
    raw_location_ids = np.asarray(document["locationIds"], dtype=np.int64).reshape(shape)
    frozen = _freeze_source_arrays(raw_latitudes, raw_longitudes, raw_location_ids, layers)
    source = RegionalReleaseSource(
        _verification_capability=_OFFLINE_FIXTURE_CAPABILITY,
        archive_sha256=document["archiveSha256"],
        contract_sha256=document["releaseContractSha256"],
        latitudes=frozen[0],
        longitudes=frozen[1],
        location_ids=frozen[2],
        layers=frozen[3],
        _content_sha256=_source_content_sha256(*frozen),
    )
    if source.archive_sha256 != release_contract["source"]["archiveSha256"]:
        raise ScienceContractError("Fixture archive identity differs from the release contract")
    expected_contract_sha256 = hashlib.sha256(_canonical_json(release_contract)).hexdigest()
    if (
        source.contract_sha256 != expected_contract_sha256
        or receipt.get("releaseContractSha256") != expected_contract_sha256
    ):
        raise ScienceContractError("Fixture release-contract binding differs")
    _validate_source(source, release_contract)
    return source
