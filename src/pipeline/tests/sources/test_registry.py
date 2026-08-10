"""Contract tests for the audited source lock."""

from __future__ import annotations

import gzip
import hashlib
import json
import shutil
from pathlib import Path

import pytest
from click.testing import CliRunner

from searise_pipeline.sources.cli import cli
from searise_pipeline.sources.registry import (
    RegistryError,
    load_registry,
    load_settlement_registry,
)

PIPELINE_ROOT = Path(__file__).parents[2]
LOCK_PATH = PIPELINE_ROOT / "sources" / "source-lock.json"
SETTLEMENT_LOCK_PATH = (
    PIPELINE_ROOT / "sources" / "source-lock.phase-1-settlements.json"
)
GEONAMES_EVIDENCE = (
    PIPELINE_ROOT / "sources" / "evidence" / "geonames-settlement-snapshot-20260810.json"
)


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
    shutil.copytree(
        PIPELINE_ROOT / "sources" / "manifests", tmp_path / "manifests", dirs_exist_ok=True
    )
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
        "copernicus-marine-eur-sla-monthly",
        "copernicus-marine-eur-mdt",
        "goco06s-gravity-model",
        "egm2008-gravity-model",
    }
    assert len(registry.targets()) == 13
    assert registry.publication_issues() == ()


def test_full_geonames_snapshot_is_one_complete_hash_locked_source():
    registry = load_settlement_registry(SETTLEMENT_LOCK_PATH)
    sources = {source.id: source for source in registry.sources}
    snapshot = sources["geonames-settlement-catalogue"]
    assets = {asset.id: asset for asset in snapshot.assets}

    assert snapshot.selection_status == "selected"
    assert snapshot.version == snapshot.snapshot_date == "2026-08-10"
    assert set(assets) == {
        "admin1-codes-ascii",
        "all-countries",
        "alternate-names-v2",
        "format-readme",
    }
    assert all(asset.availability == "locked" for asset in assets.values())
    assert all(asset.resolved_url == asset.url for asset in assets.values())


def test_geonames_inspection_evidence_matches_every_locked_asset():
    registry = load_settlement_registry(SETTLEMENT_LOCK_PATH)
    source = next(
        item for item in registry.sources if item.id == "geonames-settlement-catalogue"
    )
    evidence = json.loads(GEONAMES_EVIDENCE.read_text(encoding="utf-8"))

    assert evidence["snapshotDate"] == source.snapshot_date
    assert evidence["identityAuthority"] == "sha256-and-byte-size"
    assert evidence["sourceLockBinding"] == {
        "path": "src/pipeline/sources/source-lock.phase-1-settlements.json",
        "sha256": hashlib.sha256(SETTLEMENT_LOCK_PATH.read_bytes()).hexdigest(),
    }
    locked = {asset.id: asset for asset in source.assets}
    assert {item["assetId"] for item in evidence["assets"]} == set(locked)
    for observed in evidence["assets"]:
        asset = locked[observed["assetId"]]
        assert observed["requestedUrl"] == observed["resolvedUrl"] == asset.url
        assert observed["byteSize"] == asset.byte_size
        assert observed["sha256"] == asset.sha256


def _write_settlement_lock(tmp_path: Path, document: dict) -> Path:
    lock = tmp_path / "source-lock.phase-1-settlements.json"
    lock.write_text(json.dumps(document), encoding="utf-8")
    return lock


@pytest.mark.parametrize(
    "mutation",
    ["missing-source", "missing-asset", "unofficial-url", "cities-selected"],
)
def test_geonames_production_source_set_fails_closed(
    tmp_path: Path, mutation: str
) -> None:
    document = json.loads(SETTLEMENT_LOCK_PATH.read_text(encoding="utf-8"))
    snapshot = next(
        source
        for source in document["sources"]
        if source["id"] == "geonames-settlement-catalogue"
    )
    if mutation == "missing-source":
        global_document = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
        cities = next(
            source
            for source in global_document["sources"]
            if source["id"] == "geonames-cities15000"
        )
        document["sources"] = [cities]
    elif mutation == "missing-asset":
        snapshot["assets"].pop()
    elif mutation == "unofficial-url":
        snapshot["assets"][0]["url"] = "https://mirror.example/allCountries.zip"
    else:
        global_document = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
        cities = next(
            source
            for source in global_document["sources"]
            if source["id"] == "geonames-cities15000"
        )
        document["sources"].append(cities)
    with pytest.raises(RegistryError, match="GeoNames"):
        load_settlement_registry(_write_settlement_lock(tmp_path, document))


@pytest.mark.parametrize(
    "mutation",
    [
        "publisher",
        "licence-name",
        "licence-url",
        "licence-spdx",
        "attribution",
        "redistribution",
        "reviewer",
        "reviewed-at",
        "acknowledgement",
        "licence-notes",
        "missing-inspection",
        "inspection-date",
        "inspection-method",
        "inspection-evidence",
        "inspection-result",
    ],
)
def test_geonames_production_metadata_fails_closed(
    tmp_path: Path, mutation: str
) -> None:
    document = json.loads(SETTLEMENT_LOCK_PATH.read_text(encoding="utf-8"))
    source = document["sources"][0]
    licence = source["licence"]
    inspection = source["inspection"]
    if mutation == "publisher":
        source["publisher"] = "Mirror"
    elif mutation in {"licence-name", "licence-url", "licence-spdx"}:
        field, value = {
            "licence-name": ("name", "Different licence"),
            "licence-url": ("url", "https://example.test/licence"),
            "licence-spdx": ("spdx", "LicenseRef-Different"),
        }[mutation]
        licence[field] = value
    elif mutation == "attribution":
        licence["attribution"] = "Changed attribution"
    elif mutation == "redistribution":
        licence["redistributionStatus"] = "review-required"
    elif mutation == "reviewer":
        licence["reviewer"] = "Different reviewer"
    elif mutation == "reviewed-at":
        licence["reviewedAt"] = "2026-08-09"
    elif mutation == "acknowledgement":
        licence["requiredAcknowledgements"] = ["Changed acknowledgement"]
    elif mutation == "licence-notes":
        licence["notes"] = "Changed notes"
    elif mutation == "missing-inspection":
        source.pop("inspection")
    elif mutation == "inspection-date":
        inspection["inspectedAt"] = "2026-08-09"
    elif mutation == "inspection-method":
        inspection["method"] = "Incomplete inspection"
    elif mutation == "inspection-evidence":
        inspection["evidenceRef"] = "other-evidence.json"
    else:
        inspection["result"] = "blocked"

    with pytest.raises(RegistryError, match="GeoNames"):
        load_settlement_registry(_write_settlement_lock(tmp_path, document))


@pytest.mark.parametrize(
    ("asset_id", "member_index", "mutation"),
    [
        ("all-countries", 0, "delete"),
        ("all-countries", 0, "id"),
        ("all-countries", 0, "path"),
        ("all-countries", 0, "role"),
        ("all-countries", 0, "byteSize"),
        ("all-countries", 0, "compressedByteSize"),
        ("all-countries", 0, "crc32"),
        ("all-countries", 0, "sha256"),
        ("all-countries", 0, "extra"),
        ("alternate-names-v2", 0, "delete"),
        ("alternate-names-v2", 0, "path"),
        ("alternate-names-v2", 0, "role"),
        ("alternate-names-v2", 0, "sha256"),
        ("alternate-names-v2", 1, "path"),
        ("alternate-names-v2", 1, "extra"),
        ("admin1-codes-ascii", 0, "text-member"),
        ("format-readme", 0, "text-member"),
    ],
)
def test_geonames_archive_member_inventory_fails_closed(
    tmp_path: Path, asset_id: str, member_index: int, mutation: str
) -> None:
    document = json.loads(SETTLEMENT_LOCK_PATH.read_text(encoding="utf-8"))
    assets = {asset["id"]: asset for asset in document["sources"][0]["assets"]}
    asset = assets[asset_id]
    if mutation == "text-member":
        asset["members"] = [
            {
                "id": "unexpected-member",
                "path": "unexpected.txt",
                "role": "unexpected",
                "byteSize": 1,
                "compressedByteSize": 1,
                "crc32": "00000000",
                "sha256": "0" * 64,
            }
        ]
    elif mutation == "delete":
        asset["members"].pop(member_index)
        if not asset["members"]:
            asset.pop("members")
    elif mutation == "extra":
        extra = dict(asset["members"][member_index])
        extra.update(id="unexpected-member", path="unexpected.txt")
        asset["members"].append(extra)
    else:
        replacements = {
            "id": "changed-member",
            "path": "changed.txt",
            "role": "changed-role",
            "byteSize": 1,
            "compressedByteSize": 1,
            "crc32": "00000000",
            "sha256": "0" * 64,
        }
        asset["members"][member_index][mutation] = replacements[mutation]

    with pytest.raises(RegistryError, match="GeoNames"):
        load_settlement_registry(_write_settlement_lock(tmp_path, document))


def test_source_cli_accepts_and_enforces_the_scoped_settlement_lock(tmp_path: Path):
    runner = CliRunner()
    for command in ("validate", "publication-check"):
        result = runner.invoke(cli, [command, "--lock", str(SETTLEMENT_LOCK_PATH)])
        assert result.exit_code == 0, result.output

    for command in ("fetch", "verify"):
        result = runner.invoke(
            cli,
            [
                command,
                "--lock",
                str(SETTLEMENT_LOCK_PATH),
                "--target",
                "missing",
            ],
        )
        assert result.exit_code == 1
        assert "Unknown source selector" in result.output

    document = json.loads(SETTLEMENT_LOCK_PATH.read_text(encoding="utf-8"))
    document["sources"][0]["publisher"] = "Mirror"
    mutated = _write_settlement_lock(tmp_path, document)
    result = runner.invoke(cli, ["validate", "--lock", str(mutated)])
    assert result.exit_code == 1
    assert "GeoNames" in result.output


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
    shutil.copytree(PIPELINE_ROOT / "sources" / "manifests", tmp_path / "manifests")

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
    shutil.copytree(PIPELINE_ROOT / "sources" / "manifests", tmp_path / "manifests")

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
