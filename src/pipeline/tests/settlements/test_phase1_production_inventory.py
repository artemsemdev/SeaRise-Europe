from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[4]
INVENTORY = ROOT / "docs/evidence/phase-1-settlement-production-inventory.json"
SOURCE_LOCK = ROOT / "src/pipeline/sources/source-lock.phase-1-settlements.json"


def _load(path: Path) -> dict[str, Any]:
    document = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(document, dict)
    return document


def test_production_inventory_is_exact_and_non_promotional() -> None:
    inventory = _load(INVENTORY)
    assert inventory["schemaVersion"] == 1
    assert inventory["issue"] == 298
    assert inventory["dataProvenanceClass"] == "real-source"
    assert inventory["localHandoffRoot"] == "local-data/phase-1"

    artifacts = inventory["artifacts"]
    assert len(artifacts) == 18
    assert len({item["id"] for item in artifacts}) == len(artifacts)
    assert len({item["path"] for item in artifacts}) == len(artifacts)
    for artifact in artifacts:
        assert type(artifact["byteSize"]) is int and artifact["byteSize"] > 0
        assert re.fullmatch(r"[0-9a-f]{64}", artifact["sha256"])
        assert not artifact["path"].startswith("/")
        assert ".." not in Path(artifact["path"]).parts

    assert inventory["sourceValidation"]["placeScan"]["failureCount"] == 0
    assert inventory["sourceValidation"]["alternateNameScan"]["failureCount"] == 0
    assert inventory["counts"]["classifiedPlaces"] == inventory["counts"]["geoparquetRows"]
    assert inventory["counts"]["classifiedPlaces"] == inventory["counts"]["projectionRecords"]
    assert inventory["reproducibility"]["geoparquetByteForByteRebuild"] is True
    assert inventory["reproducibility"]["projectionByteForByteReplay"] is True
    assert inventory["diagnostic"]["executionOutcome"] == "pass"
    assert inventory["diagnostic"]["browserRuntimeMeasured"] is False
    assert inventory["diagnostic"]["acceptedBrowserBudgetOutcome"] == "not-measured"
    browser = inventory["browserRuntime"]
    assert browser["gateOutcome"] == "pass"
    assert browser["initializationP95Milliseconds"] < 1_000
    assert browser["queryP95Milliseconds"] < 50
    assert browser["peakObservedWorkerBytes"] > 0
    assert browser["queryTransmissionOutcome"] == "pass"
    assert browser["crossOriginIsolated"] is True
    assert inventory["claims"] == {
        "browserReference": True,
        "candidateBound": False,
        "immutableRetention": False,
        "production": False,
        "publication": False,
        "scientificApproval": False,
        "signing": False,
    }
    assert inventory["blockingItems"] == sorted(set(inventory["blockingItems"]))


def test_production_inventory_geonames_assets_match_the_scoped_lock() -> None:
    inventory = _load(INVENTORY)
    source_lock = _load(SOURCE_LOCK)
    source_assets = source_lock["sources"][0]["assets"]
    locked = {
        asset["id"]: (asset["cachePath"], asset["byteSize"], asset["sha256"])
        for asset in source_assets
    }
    recorded = {
        item["id"].removeprefix("geonames-"): (
            Path(item["path"]).name,
            item["byteSize"],
            item["sha256"],
        )
        for item in inventory["artifacts"]
        if item["id"].startswith("geonames-")
    }
    assert recorded == locked
