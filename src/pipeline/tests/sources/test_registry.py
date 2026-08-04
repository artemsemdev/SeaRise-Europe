"""Contract tests for the audited source lock."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from searise_pipeline.sources.registry import RegistryError, load_registry

PIPELINE_ROOT = Path(__file__).parents[2]
LOCK_PATH = PIPELINE_ROOT / "sources" / "source-lock.json"


def test_committed_source_lock_is_valid_and_covers_required_publishers():
    registry = load_registry(LOCK_PATH)

    assert {source.id for source in registry.sources} == {
        "ipcc-ar6-sea-level",
        "geonames-cities15000",
        "natural-earth-10m",
        "copernicus-dem-glo30",
        "copernicus-coastal-zones-2018",
    }
    assert len(registry.targets()) == 4
    assert registry.publication_issues() == ()


def test_target_selection_supports_source_and_asset_ids():
    registry = load_registry(LOCK_PATH)

    source_targets = registry.targets(["natural-earth-10m"])
    asset_target = registry.targets(["natural-earth-10m:ocean"])

    assert [asset.id for _, asset in source_targets] == [
        "admin-0-countries",
        "ocean",
    ]
    assert asset_target[0][1].id == "ocean"


@pytest.mark.parametrize("selector", ["missing", "natural-earth-10m:missing"])
def test_unknown_target_is_rejected(selector: str):
    registry = load_registry(LOCK_PATH)

    with pytest.raises(RegistryError, match="Unknown"):
        registry.targets([selector])


def test_schema_mismatch_is_rejected(tmp_path: Path):
    lock = tmp_path / "source-lock.json"
    lock.write_text(json.dumps({"schemaVersion": 1, "sources": [{}]}), encoding="utf-8")

    with pytest.raises(RegistryError, match="Invalid source lock"):
        load_registry(lock)


def test_resolved_version_mismatch_is_rejected(tmp_path: Path):
    document = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    document["sources"][0]["assets"][0]["resolvedVersion"] = "changed"
    lock = tmp_path / "source-lock.json"
    lock.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(RegistryError, match="Resolved version mismatch"):
        load_registry(lock)


def test_selected_source_with_uncertain_rights_blocks_publication(tmp_path: Path):
    document = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    document["sources"][0]["licence"].update(
        redistributionStatus="review-required",
        reviewer=None,
        reviewedAt=None,
    )
    lock = tmp_path / "source-lock.json"
    lock.write_text(json.dumps(document), encoding="utf-8")

    issues = load_registry(lock).publication_issues()

    assert issues == (
        "ipcc-ar6-sea-level: redistribution status is review-required",
    )
