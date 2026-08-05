"""Contract tests for the audited source lock."""

from __future__ import annotations

import gzip
import hashlib
import json
from pathlib import Path

import pytest

from searise_pipeline.sources.registry import RegistryError, load_registry

PIPELINE_ROOT = Path(__file__).parents[2]
LOCK_PATH = PIPELINE_ROOT / "sources" / "source-lock.json"


def _write_monthly_manifest(tmp_path: Path, *, omit_february: bool = False) -> dict:
    rows = [
        {
            "type": "object",
            "key": "native/dataset/2020/m01.nc",
            "url": "https://example.test/native/dataset/2020/m01.nc",
            "byteSize": 10,
            "sha256": "1" * 64,
            "periodStart": "2020-01-01",
            "periodEndExclusive": "2020-02-01",
            "dayWeight": 31,
        },
        {
            "type": "object",
            "key": "native/dataset/2020/m02.nc",
            "url": "https://example.test/native/dataset/2020/m02.nc",
            "byteSize": 11,
            "sha256": "2" * 64,
            "periodStart": "2020-02-01",
            "periodEndExclusive": "2020-03-01",
            "dayWeight": 29,
        },
    ]
    if omit_february:
        rows.pop()
    header = {
        "type": "manifest",
        "schemaVersion": 1,
        "datasetVersion": "20210809",
        "referencePeriod": {
            "startInclusive": "2020-01-01",
            "endExclusive": "2020-03-01",
        },
        "aggregation": {"totalDayWeight": sum(row["dayWeight"] for row in rows)},
        "objectCount": len(rows),
        "totalByteSize": sum(row["byteSize"] for row in rows),
    }
    payload = (
        "\n".join(json.dumps(item, sort_keys=True) for item in [header, *rows]) + "\n"
    ).encode()
    compressed = gzip.compress(payload, mtime=0)
    manifest_path = tmp_path / "manifests" / "monthly.jsonl.gz"
    manifest_path.parent.mkdir()
    manifest_path.write_bytes(compressed)
    return {
        "contract": "monthly-series-v1",
        "manifestPath": "manifests/monthly.jsonl.gz",
        "manifestMediaType": "application/gzip",
        "manifestByteSize": len(compressed),
        "manifestSha256": hashlib.sha256(compressed).hexdigest(),
        "payloadSha256": hashlib.sha256(payload).hexdigest(),
        "objectCount": len(rows),
        "totalByteSize": sum(row["byteSize"] for row in rows),
        "keyPrefix": "native/dataset",
        "referencePeriod": {
            "startInclusive": "2020-01-01",
            "endExclusive": "2020-03-01",
        },
    }


def _write_lock_with_object_set(tmp_path: Path, object_set: dict) -> Path:
    document = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    asset = document["sources"][0]["assets"][0]
    asset.update(
        kind="object-set",
        url="https://example.test",
        resolvedUrl="https://example.test",
        mediaType="application/x-netcdf",
        cachePath="dataset",
        objectSet=object_set,
    )
    for field in ("byteSize", "sha256", "upstreamChecksum"):
        asset.pop(field, None)
    lock = tmp_path / "source-lock.json"
    lock.write_text(json.dumps(document), encoding="utf-8")
    return lock


def test_committed_source_lock_is_valid_and_covers_required_publishers():
    registry = load_registry(LOCK_PATH)

    assert {source.id for source in registry.sources} == {
        "ipcc-ar6-sea-level",
        "geonames-cities15000",
        "natural-earth-10m",
        "copernicus-dem-glo30",
        "copernicus-dem-glo90",
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

    assert issues == ("ipcc-ar6-sea-level: redistribution status is review-required",)


def test_monthly_object_manifest_is_verified_before_registry_use(tmp_path: Path):
    descriptor = _write_monthly_manifest(tmp_path)

    registry = load_registry(_write_lock_with_object_set(tmp_path, descriptor))

    asset = registry.sources[0].assets[0]
    assert asset.kind == "object-set"
    assert asset.object_set is not None
    assert asset.object_set.object_count == 2


def test_tampered_object_manifest_is_rejected(tmp_path: Path):
    descriptor = _write_monthly_manifest(tmp_path)
    manifest = tmp_path / descriptor["manifestPath"]
    manifest.write_bytes(manifest.read_bytes() + b"tampered")

    with pytest.raises(RegistryError, match="byte size mismatch"):
        load_registry(_write_lock_with_object_set(tmp_path, descriptor))


def test_monthly_object_manifest_gap_is_rejected(tmp_path: Path):
    descriptor = _write_monthly_manifest(tmp_path, omit_february=True)

    with pytest.raises(RegistryError, match="does not reach reference-period end"):
        load_registry(_write_lock_with_object_set(tmp_path, descriptor))
