"""Contract tests for the exact Phase 0.6 source inspection evidence."""

from __future__ import annotations

import json
from pathlib import Path

from searise_pipeline.sources.registry import load_registry

PIPELINE_ROOT = Path(__file__).parents[2]
EVIDENCE_PATH = PIPELINE_ROOT / "science" / "evidence" / "vertical-source-inspection.json"
LOCK_PATH = PIPELINE_ROOT / "sources" / "source-lock.json"


def _evidence() -> dict:
    return json.loads(EVIDENCE_PATH.read_text(encoding="utf-8"))


def test_every_required_vertical_source_has_a_verified_receipt() -> None:
    evidence = _evidence()
    receipts = {(item["sourceId"], item["assetId"]): item for item in evidence["sourceReceipts"]}

    assert set(receipts) == {
        ("ipcc-ar6-sea-level", "regional-confidence-archive"),
        ("copernicus-marine-eur-sla-monthly", "monthly-sla-1995-2014"),
        ("copernicus-marine-eur-mdt", "europe-mdt"),
        ("goco06s-gravity-model", "goco06s-coefficients"),
        ("egm2008-gravity-model", "spherical-harmonics"),
        ("copernicus-dem-glo30", "regional-control-set"),
        ("copernicus-dem-glo90", "regional-control-set"),
    }
    assert all(item["result"] == "verified" for item in receipts.values())
    assert (
        receipts[("copernicus-marine-eur-sla-monthly", "monthly-sla-1995-2014")]["details"][
            "calendarDayWeight"
        ]
        == 7305
    )


def test_source_lock_points_to_the_same_evidence_and_exact_archive_members() -> None:
    registry = load_registry(LOCK_PATH)
    raw_lock = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    sources = {source.id: source for source in registry.sources}
    raw_sources = {source["id"]: source for source in raw_lock["sources"]}

    projection_archive = next(
        asset
        for asset in sources["ipcc-ar6-sea-level"].assets
        if asset.id == "regional-confidence-archive"
    )
    assert [member.id for member in projection_archive.members] == [
        "ssp126-medium-total",
        "ssp245-medium-total",
        "ssp585-medium-total",
    ]
    assert all(
        source["inspection"]["evidenceRef"]
        == "src/pipeline/science/evidence/vertical-source-inspection.json"
        for source in raw_sources.values()
        if source.get("inspection")
    )


def test_coverage_and_licence_gaps_are_explicit_not_inferred() -> None:
    evidence = _evidence()
    coverage = {item["region"]: item for item in evidence["coverageMatrix"]}

    assert coverage["ports-estuaries"]["baselineSla"] == "partial"
    assert coverage["north-of-66.03125n"]["baselineSla"] == "not-covered"
    assert all(item["rawBytesInGit"] is False for item in evidence["licenceDisposition"])
    assert evidence["residualGates"]
