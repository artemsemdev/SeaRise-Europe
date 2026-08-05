"""Build the reproducible, fail-closed Phase 0.9 regional attempt evidence."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from ..science.contracts import load_science_contracts
from ..science.receipt import load_vertical_receipt

BLOCKER_IDS = (
    "egm2008-evaluator-conventions",
    "numerical-uncertainty-bounds",
    "independent-scientific-data-review",
    "baltic-black-sea-controls",
    "product-scope-connectivity-approval",
    "cross-environment-reproducibility",
    "reviewed-golden-vectors",
)
SCENARIOS = ("ssp1-26", "ssp2-45", "ssp5-85")
HORIZONS = (2030, 2050, 2100)


def _read_json(path: Path) -> Mapping[str, Any]:
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return document


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _binding(repo_root: Path, path: str) -> Mapping[str, str]:
    return {"path": path, "sha256": _sha256(repo_root / path)}


def _source(source_lock: Mapping[str, Any], source_id: str) -> Mapping[str, Any]:
    return next(item for item in source_lock["sources"] if item["id"] == source_id)


def _asset(source: Mapping[str, Any], asset_id: str) -> Mapping[str, Any]:
    return next(item for item in source["assets"] if item["id"] == asset_id)


def _blocked_attempt(
    scenario: str,
    source_scenario: str,
    horizon: int,
    member: Mapping[str, Any],
) -> Mapping[str, Any]:
    return {
        "scenario": scenario,
        "sourceScenario": source_scenario,
        "horizon": horizon,
        "status": "blocked-before-array",
        "failureStage": "scientific-preflight",
        "projectionMember": {"id": member["id"], "sha256": member["sha256"]},
        "projectionQuantiles": [0.167, 0.5, 0.833],
        "sourceLineageRefs": [
            "#/lineage/projection",
            "#/lineage/baseline",
            "#/lineage/geoid",
            "#/lineage/terrain",
            "#/lineage/geography",
            "#/lineage/uncertainty",
            "#/lineage/connectivity",
            "#/lineage/software",
        ],
        "failureReasons": list(BLOCKER_IDS),
        "emittedScientificClassValues": [],
        "artifacts": [],
        "statistics": None,
    }


def build_blocked_phase_0_9_attempt(
    repo_root: Path, *, recorded_at: str = "2026-08-05"
) -> Mapping[str, Any]:
    """Describe all nine attempts without opening unavailable scientific payloads."""
    science_root = repo_root / "src/pipeline/science"
    contracts = load_science_contracts(science_root)
    source_lock = _read_json(repo_root / "src/pipeline/sources/source-lock.json")
    receipt_path = science_root / "evidence/vertical-transformation-implementation.json"
    receipt = load_vertical_receipt(receipt_path)

    ar6 = _source(source_lock, "ipcc-ar6-sea-level")
    ar6_asset = _asset(ar6, "regional-confidence-archive")
    members_by_scenario = {member["scenario"]: member for member in ar6_asset["members"]}
    sla = _source(source_lock, "copernicus-marine-eur-sla-monthly")
    sla_asset = _asset(sla, "monthly-sla-1995-2014")
    mdt = _source(source_lock, "copernicus-marine-eur-mdt")
    mdt_asset = _asset(mdt, "europe-mdt")
    terrain = _source(source_lock, "copernicus-dem-glo30")
    terrain_asset = _asset(terrain, "regional-control-set")
    mapping = contracts.source_semantics["projection"]["mapping"]
    baseline_method = contracts.vertical_methodology["baseline"]

    contract_paths = (
        "src/pipeline/science/source-semantics.json",
        "src/pipeline/science/vertical-methodology.json",
        "src/pipeline/science/terrain-decision.json",
        "src/pipeline/science/geography-rules.json",
        "src/pipeline/science/connectivity-controls.json",
        "src/pipeline/science/evidence/vertical-transformation-implementation.json",
        "src/pipeline/sources/source-lock.json",
    )
    used_source_ids = (
        "ipcc-ar6-sea-level",
        "copernicus-marine-eur-sla-monthly",
        "copernicus-marine-eur-mdt",
        "goco06s-gravity-model",
        "egm2008-gravity-model",
        "copernicus-dem-glo30",
        "natural-earth-10m",
    )
    source_licences = [
        {
            "sourceId": source_id,
            "version": _source(source_lock, source_id)["version"],
            "registryRedistributionStatus": _source(source_lock, source_id)[
                "licence"
            ]["redistributionStatus"],
        }
        for source_id in used_source_ids
    ]

    attempts = []
    for scenario in SCENARIOS:
        source_scenario = mapping["scenarios"][scenario]
        member = members_by_scenario[source_scenario]
        for horizon in HORIZONS:
            attempts.append(_blocked_attempt(scenario, source_scenario, horizon, member))

    geography = contracts.geography_rules
    terrain_object_set = terrain_asset["objectSet"]
    return {
        "schemaVersion": 1,
        "evidenceId": "phase-0.9-regional-blocked-attempt",
        "issue": 85,
        "recordedAt": recorded_at,
        "status": "preflight-blocked",
        "syntheticScientificInputsUsed": False,
        "historicalEvidence": _binding(repo_root, "docs/evidence/phase-0-regional-fixture.md"),
        "contractLineage": [_binding(repo_root, path) for path in contract_paths],
        "sourceAndLicence": {
            "integrity": "locked-and-verified",
            "review": "project-registry-evidence-independent-licence-review-pending",
            "usedSources": source_licences,
        },
        "lineage": {
            "projection": {
                "sourceId": ar6["id"],
                "version": ar6["version"],
                "archiveSha256": ar6_asset["sha256"],
                "variable": mapping["variable"],
                "quantiles": [0.167, 0.5, 0.833],
                "units": mapping["units"],
                "unitToMetres": mapping["unitToMetres"],
                "interpolation": "bilinear-inside-source-support",
                "extrapolation": "none",
            },
            "baseline": {
                "sourceProductId": baseline_method["sourceProductId"],
                "slaSourceId": sla["id"],
                "version": sla["version"],
                "sourceVariable": baseline_method["sourceVariable"],
                "derivedVariable": baseline_method["derivedVariable"],
                "supportingMdtProductId": baseline_method["supportingMdtProductId"],
                "manifestSha256": sla_asset["objectSet"]["manifestSha256"],
                "payloadSha256": sla_asset["objectSet"]["payloadSha256"],
                "mdtSha256": mdt_asset["sha256"],
                "referencePeriod": {"startInclusive": "1995-01-01", "endExclusive": "2015-01-01"},
                "monthlyObjectCount": 240,
                "calendarDayWeight": 7305,
                "equation": contracts.source_semantics["verticalInputs"]["baseline"][
                    "equation"
                ],
            },
            "geoid": receipt["geoid"],
            "terrain": {
                "sourceId": terrain["id"],
                "release": terrain["version"],
                "manifestSha256": terrain_object_set["manifestSha256"],
                "payloadSha256": terrain_object_set["payloadSha256"],
                "requiredLayers": ["DEM", "EDM", "FLM", "HEM", "WBM"],
                "horizontalCrs": "WGS84-G1150 (EPSG:4326)",
                "verticalCrs": "EGM2008 (EPSG:3855)",
                "pixelInterpretation": "RasterPixelIsPoint",
                "regionalShape": None,
                "regionalAffine": None,
                "nodataRule": "propagate-any-missing-source-or-neighbour",
            },
            "geography": {
                "support": {
                    "version": geography["support"]["version"],
                    "sha256": geography["support"]["sha256"],
                },
                "coastal": {
                    "version": geography["coastal"]["version"],
                    "sha256": geography["coastal"]["sha256"],
                },
                "predicate": geography["predicate"],
            },
            "uncertainty": {
                "receiptSha256": _sha256(receipt_path),
                "aggregation": receipt["uncertainty"]["aggregation"],
                "numericBoundsStatus": receipt["uncertainty"]["numericBoundsStatus"],
                "maximumTotalUncertaintyMetres": receipt["uncertainty"][
                    "maximumTotalUncertaintyMetres"
                ],
                "termStatuses": [
                    {"id": term["id"], "status": term["status"]}
                    for term in receipt["uncertainty"]["baselineTerms"]
                    + receipt["uncertainty"]["terrainTerms"]
                ],
            },
            "connectivity": {
                "method": geography["connectivity"]["id"],
                "controlsSha256": geography["connectivity"]["controls"]["sha256"],
                "reviewStatus": geography["connectivity"]["review"]["status"],
            },
            "software": receipt["software"],
        },
        "controlContexts": [
            "straight-coast",
            "estuary-port",
            "disconnected-inland-low-terrain",
            "nodata-void",
            "steep-coast",
            "island",
            "baltic",
            "mediterranean-adriatic",
            "black-sea",
            "atlantic-north-sea",
        ],
        "blockers": [
            {"id": blocker_id, "outcome": "stop-before-array"}
            for blocker_id in BLOCKER_IDS
        ],
        "attempts": attempts,
        "connectivityComparison": {"status": "not-run", "reason": "no vertical classes"},
        "lookupParity": {"status": "not-run", "reason": "no reviewed golden vectors"},
        "artifactQa": {
            "analysisCogs": "not-generated",
            "visualPmtiles": "not-generated",
            "geoParquet": "not-generated",
        },
        "performance": {"status": "not-run", "buildTimeSeconds": None, "peakMemoryBytes": None},
        "outputs": [],
    }


def canonical_phase_0_9_attempt_bytes(document: Mapping[str, Any]) -> bytes:
    """Serialize attempt evidence with stable ordering and no non-finite values."""
    text = json.dumps(
        document,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return (text + "\n").encode("utf-8")
