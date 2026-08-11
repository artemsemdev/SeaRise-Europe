"""Fail-closed settlement spatial-classification boundary."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Iterable, Optional

from .catalogue import CataloguePlace
from .coastline_contract import (
    CoastlineContractError,
    load_coastline_policy,
    validate_coastline_sources,
)
from .geonames import Lineage
from .spatial_toolchain import (
    SpatialToolchainEvidence,
    load_spatial_manifest,
)

SPATIAL_FIXTURE_SHA256 = "207430931e25c4a3cd1f14c88e4caf719d730f380fbd2904dcac9f5962538a58"
GEOGRAPHY_RULES_SHA256 = "195b7128ba5483a633e8e35187541b0b884ed8644ac40ae8191c9db9935becf5"
SHORELINE_POLICY_SHA256 = "8ee0077687b10f46c3267ccb887e0b2910d7fae5352edf1ea1cdfd6f87c8f547"
SHORELINE_SOURCE_LOCK_SHA256 = "a640da683b1b938715e0661afbdc8c2a8ebb145b7d0b9f5f41a567bcc49b3ccc"
SHORELINE_ARTIFACT_SHA256 = "53972730f9af3f541b67ee67a4653fb5a21ac52011d33c4372eb9fa84bc331ac"
SPATIAL_TOOLCHAIN_MANIFEST_SHA256 = (
    "77c7ea3422e67be2f8d23f0dcef2d5d36236f01b8856f76289ed1e0532359ca6"
)
_PLACE_ID = re.compile(r"^geonames:([1-9][0-9]*)$")

_CLASSIFICATION_SQL = """WITH place_points AS (
  SELECT place_id, latitude, longitude, ST_Point(longitude, latitude) AS point
  FROM spatial_place_input
), evaluated AS (
  SELECT p.place_id, p.latitude, p.longitude,
    ST_Covers(s.geometry, p.point) AS support_covers,
    ST_Covers(c.geometry, p.point) AS coastal_covers,
    ST_Transform(p.point, 'EPSG:4326', 'EPSG:3035', true) AS metric_point,
    ST_Transform(h.geometry, 'EPSG:4326', 'EPSG:3035', true) AS metric_shoreline
  FROM place_points p
  CROSS JOIN spatial_geometry_input s
  CROSS JOIN spatial_geometry_input c
  CROSS JOIN spatial_geometry_input h
  WHERE s.role = 'support' AND c.role = 'coastal' AND h.role = 'shoreline'
)
SELECT place_id, support_covers, coastal_covers,
  CAST(ST_Distance(metric_point, metric_shoreline) AS BIGINT) AS distance_to_shoreline_meters
FROM evaluated
ORDER BY CAST(SUBSTRING(place_id, 10) AS UBIGINT)"""

CORE_CAPITAL_FEATURE_CODES = frozenset({"PPLC", "PPLA", "PPLA2", "PPLA3", "PPLA4", "PPLA5"})
_SHORELINE_PREDICATE = (
    "ST_Transform(EPSG:4326,EPSG:3035,always_xy=true)+CAST(ST_Distance AS BIGINT-half-even)"
)
_PRODUCTION_GEOMETRY_IDENTITIES = (
    (
        "support",
        "europe-support",
        "natural-earth-5.1.1-explicit-scope-v2",
        "data/geometry/europe.geojson",
        "dd98b938df00fc582bbd220b913d96b1fd19bab812e2e9d95ecc4b409330a385",
        "ST_Covers",
    ),
    (
        "coastal",
        "coastal-analysis-zone",
        "natural-earth-5.1.1-25km-scope-v2",
        "data/geometry/coastal_analysis_zone.geojson",
        "aa08f31460c80cbe35eefb44c6f8feb22b90727840eda3734241d707d7a910d9",
        "ST_Covers",
    ),
    (
        "shoreline",
        "europe-settlement-shoreline-v1",
        "natural-earth-direct-linework-europe-selection-v1",
        "data/settlements/europe-settlement-shoreline-v1.geojson",
        SHORELINE_ARTIFACT_SHA256,
        _SHORELINE_PREDICATE,
    ),
)


class SpatialClassificationError(ValueError):
    """An input cannot produce one trustworthy spatial classification."""


@dataclass(frozen=True)
class GeometryBinding:
    role: str
    id: str
    version: str
    path: str
    sha256: str
    predicate: str


@dataclass(frozen=True)
class GeometryBindings:
    data_provenance_class: str
    geometry_status: str
    publication_eligible: bool
    support: GeometryBinding
    coastal: GeometryBinding
    shoreline: GeometryBinding
    contract_sha256: str

    @property
    def items(self) -> tuple[GeometryBinding, ...]:
        return self.support, self.coastal, self.shoreline


@dataclass(frozen=True)
class SpatialResultRow:
    place_id: str
    support_covers: Optional[bool]
    coastal_covers: Optional[bool]
    distance_to_shoreline_meters: Optional[int]


@dataclass(frozen=True)
class SpatiallyClassifiedPlace:
    """Internal accepted audit row; not a claim of public Place v2 validity."""

    place: CataloguePlace
    distance_to_shoreline_meters: int
    is_coastal: bool
    catalog_membership: tuple[str, ...]


@dataclass(frozen=True)
class SpatialRejection:
    place_id: str
    reason: str
    lineage: tuple[Lineage, ...]


@dataclass(frozen=True)
class SpatiallyClassifiedCatalog:
    """Internal classified audit output with independently ordered rejections."""

    geometry: GeometryBindings
    places: tuple[SpatiallyClassifiedPlace, ...]
    rejections: tuple[SpatialRejection, ...]


def classification_sql() -> str:
    """Return the exact DuckDB Spatial analytical query contract."""
    return _CLASSIFICATION_SQL


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _safe_path(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise SpatialClassificationError("fixture path is invalid")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts:
        raise SpatialClassificationError("fixture path is unsafe")
    return value


def _binding_sha256(geometry: GeometryBindings) -> str:
    binding = {
        "dataProvenanceClass": geometry.data_provenance_class,
        "geometryStatus": geometry.geometry_status,
        "publicationEligible": geometry.publication_eligible,
        "geometries": [item.__dict__ for item in geometry.items],
    }
    payload = json.dumps(
        binding, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode()
    return hashlib.sha256(payload).hexdigest()


def _validate_geometry(
    geometry: GeometryBindings, *, expected_provenance: str | None = None
) -> None:
    if geometry.geometry_status != "selected-scope-approximation":
        raise SpatialClassificationError("geometry must remain selected-scope-approximation")
    if expected_provenance is not None and geometry.data_provenance_class != expected_provenance:
        raise SpatialClassificationError("geometry provenance differs")
    if geometry.data_provenance_class not in {"real-source", "synthetic-fixture"}:
        raise SpatialClassificationError("geometry provenance is unsupported")
    if geometry.publication_eligible:
        raise SpatialClassificationError("geometry cannot be publication eligible")
    if tuple(item.role for item in geometry.items) != ("support", "coastal", "shoreline"):
        raise SpatialClassificationError("geometry role order differs")
    if geometry.support.predicate != "ST_Covers" or geometry.coastal.predicate != "ST_Covers":
        raise SpatialClassificationError("geometry binding predicate differs")
    if geometry.shoreline.predicate != _SHORELINE_PREDICATE:
        raise SpatialClassificationError("geometry binding predicate differs")
    if (
        geometry.data_provenance_class == "real-source"
        and tuple(
            (item.role, item.id, item.version, item.path, item.sha256, item.predicate)
            for item in geometry.items
        )
        != _PRODUCTION_GEOMETRY_IDENTITIES
    ):
        raise SpatialClassificationError("production geometry identity differs")
    if (
        len({item.path for item in geometry.items}) != 3
        or len({item.sha256 for item in geometry.items}) != 3
    ):
        raise SpatialClassificationError("shoreline must be separately identified")
    for item in geometry.items:
        if (
            not item.id
            or not item.version
            or len(item.sha256) != 64
            or any(char not in "0123456789abcdef" for char in item.sha256)
        ):
            raise SpatialClassificationError("geometry binding identity is invalid")
    if _binding_sha256(geometry) != geometry.contract_sha256:
        raise SpatialClassificationError("geometry binding differs from its contract")


def load_fixture_geometry_bindings(path: Path, *, repository_root: Path) -> GeometryBindings:
    """Load the hash-bound synthetic geometry identities used only by tests."""
    raw_bytes = path.read_bytes()
    if hashlib.sha256(raw_bytes).hexdigest() != SPATIAL_FIXTURE_SHA256:
        raise SpatialClassificationError("spatial fixture manifest bytes differ")
    raw = json.loads(raw_bytes)
    if (
        raw.get("dataProvenanceClass") != "synthetic-fixture"
        or raw.get("geometryStatus") != "selected-scope-approximation"
        or raw.get("publicationEligible") is not False
        or raw.get("ownerApprovalClaim") is not False
    ):
        raise SpatialClassificationError("spatial fixture status differs")
    geometries = raw.get("geometries")
    if not isinstance(geometries, list) or len(geometries) != 3:
        raise SpatialClassificationError("fixture geometry inventory differs")
    items = []
    expected_fields = {"role", "id", "version", "path", "sha256", "predicate"}
    for value in geometries:
        if not isinstance(value, dict) or set(value) != expected_fields:
            raise SpatialClassificationError("fixture geometry binding is malformed")
        relative_path = _safe_path(value["path"])
        if _sha256(repository_root / relative_path) != value["sha256"]:
            raise SpatialClassificationError("fixture geometry bytes differ from their identity")
        items.append(
            GeometryBinding(
                path=relative_path, **{key: value[key] for key in expected_fields - {"path"}}
            )
        )
    geometry = GeometryBindings(
        data_provenance_class=raw["dataProvenanceClass"],
        geometry_status=raw["geometryStatus"],
        publication_eligible=raw["publicationEligible"],
        support=items[0],
        coastal=items[1],
        shoreline=items[2],
        contract_sha256="",
    )
    geometry = GeometryBindings(
        **{**geometry.__dict__, "contract_sha256": _binding_sha256(geometry)}
    )
    _validate_geometry(geometry, expected_provenance="synthetic-fixture")
    return geometry


def _validate_toolchain(evidence: SpatialToolchainEvidence, manifest_path: Path) -> None:
    if _sha256(manifest_path) != SPATIAL_TOOLCHAIN_MANIFEST_SHA256:
        raise SpatialClassificationError("toolchain manifest identity differs")
    manifest = load_spatial_manifest(manifest_path)
    pin = manifest.platforms.get(evidence.platform)
    if pin is None or (
        evidence.duckdb_version != manifest.duckdb_version
        or evidence.extension_path != pin.extension.relative_path
        or evidence.extension_sha256 != pin.extension.sha256
        or evidence.smoke_point != (12.5, 41.9)
        or evidence.smoke_distance != 5.0
    ):
        raise SpatialClassificationError("toolchain evidence differs from the pinned plane")


def _numeric_place_id(place_id: str) -> int:
    match = _PLACE_ID.fullmatch(place_id)
    if match is None:
        raise SpatialClassificationError(f"invalid catalog place id {place_id!r}")
    return int(match.group(1))


def classify_spatial_rows(
    places: Iterable[CataloguePlace],
    rows: Iterable[SpatialResultRow],
    *,
    geometry: GeometryBindings,
    toolchain_evidence: SpatialToolchainEvidence,
    toolchain_manifest_path: Path,
) -> SpatiallyClassifiedCatalog:
    """Validate exact DuckDB result rows and attach deterministic spatial state."""
    _validate_geometry(geometry)
    _validate_toolchain(toolchain_evidence, toolchain_manifest_path)
    places_by_id: dict[str, CataloguePlace] = {}
    for place in places:
        source_id = _numeric_place_id(place.id)
        if not place.lineage or place.lineage[0].source_record_id != source_id:
            raise SpatialClassificationError(f"invalid catalog place id {place.id!r}")
        if place.id in places_by_id:
            raise SpatialClassificationError(f"duplicate catalog place id {place.id}")
        places_by_id[place.id] = place
    rows_by_id: dict[str, SpatialResultRow] = {}
    for row in rows:
        _numeric_place_id(row.place_id)
        if row.place_id in rows_by_id:
            raise SpatialClassificationError(f"duplicate spatial result {row.place_id}")
        rows_by_id[row.place_id] = row
    missing = set(places_by_id) - set(rows_by_id)
    orphan = set(rows_by_id) - set(places_by_id)
    if missing:
        raise SpatialClassificationError(
            f"missing spatial result {min(missing, key=_numeric_place_id)}"
        )
    if orphan:
        raise SpatialClassificationError(
            f"orphan spatial result {min(orphan, key=_numeric_place_id)}"
        )
    classified = []
    rejections = []
    for place_id in sorted(places_by_id, key=_numeric_place_id):
        row = rows_by_id[place_id]
        distance = row.distance_to_shoreline_meters
        if (
            type(row.support_covers) is not bool
            or type(row.coastal_covers) is not bool
            or type(distance) is not int
            or distance < 0
        ):
            raise SpatialClassificationError(f"invalid spatial result {place_id}")
        if row.coastal_covers and not row.support_covers:
            raise SpatialClassificationError(f"coastal coverage exceeds support {place_id}")
        place = places_by_id[place_id]
        if not row.support_covers:
            rejections.append(SpatialRejection(place_id, "outside-support", place.lineage))
            continue
        membership = []
        if (
            place.population is not None and place.population >= 500
        ) or place.feature_code in CORE_CAPITAL_FEATURE_CODES:
            membership.append("europe-core")
        if row.coastal_covers:
            membership.append("europe-coastal")
        classified.append(
            SpatiallyClassifiedPlace(place, distance, row.coastal_covers, tuple(membership))
        )
    return SpatiallyClassifiedCatalog(geometry, tuple(classified), tuple(rejections))


def production_geometry_bindings(repository_root: Path) -> GeometryBindings:
    """Bind reviewed real-source geometries without granting publication approval."""
    rules_path = repository_root / "src/pipeline/science/geography-rules.json"
    if not rules_path.is_file() or _sha256(rules_path) != GEOGRAPHY_RULES_SHA256:
        raise SpatialClassificationError("production geography rules differ")
    rules = json.loads(rules_path.read_text(encoding="utf-8"))
    expected = {
        "support": {
            "id": "europe-support",
            "version": "natural-earth-5.1.1-explicit-scope-v2",
            "status": "selected-scope-approximation",
            "path": "data/geometry/europe.geojson",
            "sha256": "dd98b938df00fc582bbd220b913d96b1fd19bab812e2e9d95ecc4b409330a385",
        },
        "coastal": {
            "id": "coastal-analysis-zone",
            "version": "natural-earth-5.1.1-25km-scope-v2",
            "status": "selected-scope-approximation",
            "path": "data/geometry/coastal_analysis_zone.geojson",
            "sha256": "aa08f31460c80cbe35eefb44c6f8feb22b90727840eda3734241d707d7a910d9",
        },
    }
    bindings = {}
    for role, identity in expected.items():
        value = rules.get(role, {})
        path = repository_root / identity["path"]
        if (
            {key: value.get(key) for key in identity} != identity
            or not path.is_file()
            or _sha256(path) != identity["sha256"]
        ):
            raise SpatialClassificationError(f"production {role} geometry differs")
        bindings[role] = GeometryBinding(
            role=role,
            id=identity["id"],
            version=identity["version"],
            path=identity["path"],
            sha256=identity["sha256"],
            predicate="ST_Covers",
        )
    if (
        rules.get("predicate") != "covers"
        or rules.get("coastal", {}).get("hazardExtentClaim") is not False
        or rules.get("publicationGate", {}).get("status") != "blocked"
    ):
        raise SpatialClassificationError("production geometry predicate differs")

    policy_path = repository_root / "src/pipeline/settlements/shoreline-distance-policy-v1.json"
    if not policy_path.is_file() or _sha256(policy_path) != SHORELINE_POLICY_SHA256:
        raise SpatialClassificationError("production shoreline policy differs")
    try:
        policy = load_coastline_policy(policy_path)
        source_lock = policy["sourceLock"]
        if source_lock != {
            "path": "src/pipeline/sources/source-lock.phase-1-settlement-coastline.json",
            "sha256": SHORELINE_SOURCE_LOCK_SHA256,
        }:
            raise SpatialClassificationError("production shoreline source binding differs")
        source_lock_path = repository_root / source_lock["path"]
        if (
            not source_lock_path.is_file()
            or _sha256(source_lock_path) != SHORELINE_SOURCE_LOCK_SHA256
        ):
            raise SpatialClassificationError("production shoreline source lock differs")
        validate_coastline_sources(source_lock_path, policy)
    except CoastlineContractError as exc:
        raise SpatialClassificationError("production shoreline contract differs") from exc

    if policy.get("purpose") != {
        "role": "settlement-distance-to-coast-only",
        "status": "selected-scope-approximation",
        "productEligibilityOnly": True,
        "hazardExtentClaim": False,
        "canonicalCoastlineClaim": False,
        "ownerApprovalClaim": False,
        "publicationEligible": False,
    }:
        raise SpatialClassificationError("production shoreline purpose differs")
    if policy.get("coastalClassification") != {
        "derivedFromShorelineDistance": False,
        "geometryVersion": bindings["coastal"].version,
        "predicate": "ST_Covers",
    }:
        raise SpatialClassificationError("production shoreline coastal binding differs")
    output = policy.get("output", {})
    shoreline_identity = {
        "path": "data/settlements/europe-settlement-shoreline-v1.geojson",
        "version": "natural-earth-direct-linework-europe-selection-v1",
        "sha256": SHORELINE_ARTIFACT_SHA256,
        "byteSize": 3553041,
    }
    artifact_path = repository_root / shoreline_identity["path"]
    if (
        {key: output.get(key) for key in shoreline_identity} != shoreline_identity
        or not artifact_path.is_file()
        or artifact_path.stat().st_size != shoreline_identity["byteSize"]
        or _sha256(artifact_path) != SHORELINE_ARTIFACT_SHA256
    ):
        raise SpatialClassificationError("production shoreline artifact differs")
    shoreline = GeometryBinding(
        role="shoreline",
        id="europe-settlement-shoreline-v1",
        version=shoreline_identity["version"],
        path=shoreline_identity["path"],
        sha256=shoreline_identity["sha256"],
        predicate=_SHORELINE_PREDICATE,
    )
    geometry = GeometryBindings(
        data_provenance_class="real-source",
        geometry_status="selected-scope-approximation",
        publication_eligible=False,
        support=bindings["support"],
        coastal=bindings["coastal"],
        shoreline=shoreline,
        contract_sha256="",
    )
    geometry = GeometryBindings(
        **{**geometry.__dict__, "contract_sha256": _binding_sha256(geometry)}
    )
    _validate_geometry(geometry, expected_provenance="real-source")
    return geometry
