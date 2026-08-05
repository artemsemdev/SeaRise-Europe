"""Exercise the complete candidate builder with pinned external tools."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Mapping

import pytest

import searise_pipeline.release.builder as release_builder
from searise_pipeline.release import (
    RegionalReleaseSource,
    build_regional_release,
    compare_release_candidates,
    load_source_fixture,
)
from searise_pipeline.release.builder import _validate_stac, _write_stac
from searise_pipeline.science import ScienceContractError

from .test_source_fixture import FIXTURE_DIR, GOLDENS_PATH, contract

REPO_ROOT = Path(__file__).parents[4]


def _load_release_cli():
    script_path = REPO_ROOT / "scripts/science/build_ar6_regional_release.py"
    spec = importlib.util.spec_from_file_location("searise_ar6_release_cli", script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load release CLI from {script_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


release_cli = _load_release_cli()


def _source():
    receipt = json.loads((FIXTURE_DIR / "source-fixture-receipt.json").read_text(encoding="utf-8"))
    return load_source_fixture(
        FIXTURE_DIR / "source-fixture.json.gz",
        receipt=receipt,
        release_contract=contract(),
    )


def _tool_paths() -> dict[str, Path | str]:
    return {
        "tippecanoe_path": Path(os.environ["SEARISE_TIPPECANOE"]),
        "decode_path": Path(os.environ["SEARISE_TIPPECANOE_DECODE"]),
        "pmtiles_path": Path(os.environ["SEARISE_PMTILES"]),
        "tippecanoe_source_archive_path": Path(
            os.environ["SEARISE_TIPPECANOE_SOURCE"]
        ),
        "tippecanoe_build_receipt_path": Path(
            os.environ["SEARISE_TIPPECANOE_BUILD_RECEIPT"]
        ),
        "pmtiles_distribution_asset_path": Path(
            os.environ["SEARISE_PMTILES_ASSET"]
        ),
        "pmtiles_distribution_platform": os.environ["SEARISE_VECTOR_PLATFORM"],
        "python_lock_path": Path(os.environ["SEARISE_PYTHON_LOCK"]),
    }


def _missing_tool_paths() -> dict[str, Path | str]:
    missing = Path("missing")
    return {
        "tippecanoe_path": missing,
        "decode_path": missing,
        "pmtiles_path": missing,
        "tippecanoe_source_archive_path": missing,
        "tippecanoe_build_receipt_path": missing,
        "pmtiles_distribution_asset_path": missing,
        "pmtiles_distribution_platform": "darwin-arm64",
        "python_lock_path": missing,
    }


def _write_json(path: Path, document: object) -> None:
    path.write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _stac_candidate(
    root: Path,
) -> tuple[
    list[dict[str, object]],
    RegionalReleaseSource,
    list[Mapping[str, object]],
]:
    artifacts: list[dict[str, object]] = []

    def add_artifact(
        relative: str,
        *,
        media_type: str,
        role: str,
        scenario: str | None = None,
        horizon: int | None = None,
        member_sha256: str | None = None,
    ) -> None:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((relative + "\n").encode())
        record: dict[str, object] = {
            "path": relative,
            "mediaType": media_type,
            "role": role,
            "byteSize": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
        if member_sha256 is not None:
            record["source"] = {"memberSha256": member_sha256}
        if scenario is not None:
            record["scenario"] = scenario
        if horizon is not None:
            record["horizon"] = horizon
        artifacts.append(record)

    release = contract()
    source = _source()
    member_by_scenario = {
        layer.scenario: layer.member_sha256
        for layer in source.layers
        if layer.horizon == release["matrix"]["horizons"][0]
    }
    for scenario in release["matrix"]["scenarios"]:
        for horizon in release["matrix"]["horizons"]:
            add_artifact(
                f"analysis/{scenario}/{horizon}.tif",
                media_type=(
                    "image/tiff; application=geotiff; profile=cloud-optimized"
                ),
                role="exact-browser-lookup",
                scenario=scenario,
                horizon=horizon,
                member_sha256=member_by_scenario[scenario],
            )
            add_artifact(
                f"layers/{scenario}/{horizon}.pmtiles",
                media_type="application/vnd.pmtiles",
                role="visual-only",
                scenario=scenario,
                horizon=horizon,
            )
    add_artifact(
        "analysis/projections.parquet",
        media_type="application/vnd.apache.parquet",
        role="analytical-parity",
    )
    add_artifact(
        "analysis/source-grid.json.gz",
        media_type="application/gzip",
        role="source-grid-identity",
    )
    stac_records = _write_stac(
        root,
        artifacts,
        release_id="ar6-europe-fixture-v1",
        source=source,
        contract=release,
    )
    return artifacts, source, stac_records


def _manifest_candidate(
    root: Path,
) -> tuple[dict[str, object], RegionalReleaseSource]:
    artifacts, source, stac_records = _stac_candidate(root)
    release = contract()
    notice = release_builder._write_notice(root, release)
    records = [
        *[
            release_builder._attach_lineage(
                artifact,
                source=source,
                contract=release,
            )
            for artifact in artifacts
        ],
        release_builder._attach_lineage(
            notice,
            source=source,
            contract=release,
        ),
        *[
            release_builder._attach_lineage(
                artifact,
                source=source,
                contract=release,
            )
            for artifact in stac_records
        ],
    ]
    source_members = {
        layer.scenario: layer.member_sha256
        for layer in source.layers
        if layer.horizon == release["matrix"]["horizons"][0]
    }
    source_receipt = {
        "schemaVersion": 1,
        "sourceMode": source.source_mode,
        "archiveSha256": source.archive_sha256,
        "archiveAndMembersVerifiedThisBuild": (
            source.archive_and_members_verified_this_build
        ),
        "memberSha256": source_members,
        "releaseContractSha256": source.contract_sha256,
        "licence": release["source"]["licence"],
        "attribution": release["source"]["attribution"],
        "canonicalRecord": release["source"]["canonicalRecord"],
        "requiredAcknowledgements": release["source"]["requiredAcknowledgements"],
        "notice": notice,
        "sourceContentSha256": source.content_sha256,
    }
    cog_bytes = sum(
        (root / f"analysis/{scenario}/{horizon}.tif").stat().st_size
        for scenario in release["matrix"]["scenarios"]
        for horizon in release["matrix"]["horizons"]
    )
    pmtiles_bytes = sum(
        (root / f"layers/{scenario}/{horizon}.pmtiles").stat().st_size
        for scenario in release["matrix"]["scenarios"]
        for horizon in release["matrix"]["horizons"]
    )
    geoparquet_bytes = (root / "analysis/projections.parquet").stat().st_size
    manifest: dict[str, object] = {
        "schemaVersion": 1,
        "releaseId": "ar6-europe-fixture-v1",
        "releaseContractId": release["releaseContractId"],
        "scientificDisposition": release["scientificDisposition"],
        "publicationStatus": "pending-owner",
        "modeledQuantity": "regional-relative-sea-level-change",
        "baseline": release["values"]["baseline"],
        "confidence": release["values"]["confidence"],
        "storageUnits": release["values"]["storageUnits"],
        "scaleToMetres": release["values"]["scaleToMetres"],
        "nativeResolutionDegrees": release["grid"]["nativeResolutionDegrees"],
        "grid": release["grid"],
        "matrix": release["matrix"],
        "source": source_receipt,
        "artifacts": records,
        "totals": {
            "cogBytes": cog_bytes,
            "pmtilesBytes": pmtiles_bytes,
            "geoparquetBytes": geoparquet_bytes,
            "coreArtifactBytes": cog_bytes + pmtiles_bytes + geoparquet_bytes,
        },
        "limitations": [
            "projection-only-not-flood-inundation-terrain-or-property-risk",
            "pmtiles-visual-only",
            "geoparquet-nearest-selection-prohibited",
            "cog-is-the-only-exact-browser-lookup-artifact",
        ],
    }
    release_builder._validate_manifest(
        root,
        manifest,
        release_id="ar6-europe-fixture-v1",
        source=source,
        contract=release,
    )
    return manifest, source


def _first_stac_item(root: Path) -> tuple[Path, dict[str, object]]:
    release = contract()
    scenario = release["matrix"]["scenarios"][0]
    horizon = release["matrix"]["horizons"][0]
    path = root / f"stac/items/{scenario}-{horizon}.json"
    return path, json.loads(path.read_text(encoding="utf-8"))


def _stac_collection(root: Path) -> tuple[Path, dict[str, object]]:
    path = root / "stac/collection.json"
    return path, json.loads(path.read_text(encoding="utf-8"))


EXTERNAL_TOOLS_AVAILABLE = all(
    os.environ.get(name)
    for name in (
        "SEARISE_TIPPECANOE",
        "SEARISE_TIPPECANOE_DECODE",
        "SEARISE_PMTILES",
        "SEARISE_TIPPECANOE_SOURCE",
        "SEARISE_TIPPECANOE_BUILD_RECEIPT",
        "SEARISE_PMTILES_ASSET",
        "SEARISE_VECTOR_PLATFORM",
        "SEARISE_PYTHON_LOCK",
    )
)


@pytest.mark.parametrize(
    "mutation",
    ["missing-extent", "wrong-bbox", "wrong-temporal", "extra-field"],
)
def test_stac_validator_rejects_mutated_collection_envelope(
    tmp_path: Path,
    mutation: str,
) -> None:
    artifacts, source = _stac_candidate(tmp_path)[:2]
    collection_path, collection = _stac_collection(tmp_path)
    if mutation == "missing-extent":
        collection.pop("extent")
    elif mutation == "extra-field":
        collection["unexpected"] = True
    else:
        extent = collection["extent"]
        assert isinstance(extent, dict)
        section = "spatial" if mutation == "wrong-bbox" else "temporal"
        value = extent[section]
        assert isinstance(value, dict)
        value["bbox" if section == "spatial" else "interval"] = []
    _write_json(collection_path, collection)

    with pytest.raises(ScienceContractError, match="Collection envelope"):
        _validate_stac(
            tmp_path,
            artifacts,
            release_id="ar6-europe-fixture-v1",
            source=source,
            contract=contract(),
        )


@pytest.mark.parametrize("mutation", ["empty", "missing", "extra", "swapped"])
def test_stac_validator_rejects_mutated_asset_inventory(
    tmp_path: Path,
    mutation: str,
) -> None:
    artifacts, source, _ = _stac_candidate(tmp_path)
    item_path, item = _first_stac_item(tmp_path)
    assets = item["assets"]
    if mutation == "empty":
        item["assets"] = {}
    elif mutation == "missing":
        assets.pop("visual")
    elif mutation == "extra":
        assets["unexpected"] = dict(assets["analysis"])
    else:
        assets["analysis"], assets["visual"] = assets["visual"], assets["analysis"]
    _write_json(item_path, item)

    with pytest.raises(ScienceContractError, match="asset inventory"):
        _validate_stac(
            tmp_path,
            artifacts,
            release_id="ar6-europe-fixture-v1",
            source=source,
            contract=contract(),
        )


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("id", "identity or geometry"),
        ("collection", "identity or geometry"),
        ("bbox", "identity or geometry"),
        ("geometry", "identity or geometry"),
        ("properties", "lineage"),
    ],
)
def test_stac_validator_rejects_mutated_item_contract(
    tmp_path: Path,
    mutation: str,
    message: str,
) -> None:
    artifacts, source, _ = _stac_candidate(tmp_path)
    item_path, item = _first_stac_item(tmp_path)
    if mutation == "properties":
        item["properties"]["unexpected"] = True
    else:
        item[mutation] = {} if mutation in {"bbox", "geometry"} else "wrong"
    _write_json(item_path, item)

    with pytest.raises(ScienceContractError, match=message):
        _validate_stac(
            tmp_path,
            artifacts,
            release_id="ar6-europe-fixture-v1",
            source=source,
            contract=contract(),
        )


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("duplicate", "unique safe files"),
        ("unsafe", "unsafe or non-canonical"),
        ("bytes", "bytes differ"),
        ("identity", "identity differs"),
        ("source", "source lineage differs"),
        ("method", "method binding differs"),
        ("rights", "rights binding differs"),
        ("values", "value semantics differ"),
    ],
)
def test_manifest_validator_rejects_mutated_artifact_records(
    tmp_path: Path,
    mutation: str,
    message: str,
) -> None:
    manifest, source = _manifest_candidate(tmp_path)
    records = manifest["artifacts"]
    assert isinstance(records, list)
    record = records[0]
    assert isinstance(record, dict)
    if mutation == "duplicate":
        duplicate = records[-1]
        assert isinstance(duplicate, dict)
        duplicate["path"] = record["path"]
    elif mutation == "unsafe":
        record["path"] = "../escape"
    elif mutation == "bytes":
        path = tmp_path / str(record["path"])
        path.write_bytes(path.read_bytes() + b"tamper")
    elif mutation == "identity":
        record["role"] = "wrong"
    else:
        field = {
            "source": "source",
            "method": "method",
            "rights": "rights",
            "values": "valueSemantics",
        }[mutation]
        record[field] = {}

    with pytest.raises(ScienceContractError, match=message):
        release_builder._validate_manifest(
            tmp_path,
            manifest,
            release_id="ar6-europe-fixture-v1",
            source=source,
            contract=contract(),
        )


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("missing", "top-level fields"),
        ("extra", "top-level fields"),
        ("contract", "release contract"),
        ("source", "source receipt"),
        ("totals", "actual core artifact bytes"),
        ("limitations", "product contract"),
    ],
)
def test_manifest_validator_rejects_mutated_envelope(
    tmp_path: Path,
    mutation: str,
    message: str,
) -> None:
    manifest, source = _manifest_candidate(tmp_path)
    if mutation == "missing":
        manifest.pop("releaseContractId")
    elif mutation == "extra":
        manifest["unexpected"] = True
    elif mutation == "contract":
        manifest["modeledQuantity"] = "flood-inundation"
    elif mutation == "source":
        source_receipt = manifest["source"]
        assert isinstance(source_receipt, dict)
        source_receipt["archiveSha256"] = "0" * 64
    elif mutation == "totals":
        totals = manifest["totals"]
        assert isinstance(totals, dict)
        totals["cogBytes"] = int(totals["cogBytes"]) + 1
    else:
        limitations = manifest["limitations"]
        assert isinstance(limitations, list)
        limitations.pop()

    with pytest.raises(ScienceContractError, match=message):
        release_builder._validate_manifest(
            tmp_path,
            manifest,
            release_id="ar6-europe-fixture-v1",
            source=source,
            contract=contract(),
        )


@pytest.mark.skipif(
    not EXTERNAL_TOOLS_AVAILABLE,
    reason="set the three pinned vector-tool paths for the complete release integration",
)
def test_complete_fixture_release_is_deterministic_but_cannot_approve_source(
    tmp_path: Path,
) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    source = _source()

    first_result = build_regional_release(
        source,
        first,
        release_id="ar6-europe-fixture-v1",
        contract=contract(),
        lookup_goldens_path=GOLDENS_PATH,
        build_environment_id="isolated-build-a",
        source_revision="a" * 40,
        **_tool_paths(),
    )
    second_result = build_regional_release(
        source,
        second,
        release_id="ar6-europe-fixture-v1",
        contract=contract(),
        lookup_goldens_path=GOLDENS_PATH,
        build_environment_id="isolated-build-b",
        source_revision="a" * 40,
        **_tool_paths(),
    )
    assert len(list(first.glob("analysis/*/*.tif"))) == 9
    assert len(list(first.glob("layers/*/*.pmtiles"))) == 9
    assert (first / "analysis/projections.parquet").is_file()
    assert (first / "analysis/source-grid.json.gz").is_file()
    assert (first / "NOTICE.md").is_file()
    assert (first / "stac/collection.json").is_file()
    assert len(list(first.glob("stac/items/*.json"))) == 9
    assert len(first_result.manifest["artifacts"]) == 31
    source_grid = next(
        artifact
        for artifact in first_result.manifest["artifacts"]
        if artifact["role"] == "source-grid-identity"
    )
    assert source_grid["path"] == "analysis/source-grid.json.gz"
    assert first_result.manifest == second_result.manifest
    comparison = compare_release_candidates(first, second, contract=contract())
    assert comparison["status"] == "pending-external-provenance"
    assert comparison["localComparisonStatus"] == "passed"
    assert comparison["independentEnvironmentCount"] == 0
    assert comparison["receiptProfileCount"] == 1
    assert comparison["externalProvenanceRequirement"]["receiptProfilesAreProof"] is False
    assert comparison["externalProvenanceRequirement"][
        "distinctValidatedProfileCount"
    ] == 2

    forged = tmp_path / "forged-copy"
    shutil.copytree(first, forged)
    release = contract()
    receipt_path = forged / "build-receipt.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    python_pin = release["toolchain"]["python"]
    python_profile = python_pin["profiles"]["linux-x86_64-cp311"]
    tippecanoe = release["toolchain"]["tippecanoe"]
    vector_reference = tippecanoe["referenceBuilds"]["linux-x86_64"]
    pmtiles = release["toolchain"]["pmtiles"]
    pmtiles_asset = pmtiles["assets"]["linux-x86_64"]
    receipt["environmentIdentity"] = {
        "buildRunId": "forged-linux-build",
        "python": {
            "platform": "linux-x86_64-cp311",
            "python_version": python_profile["pythonVersion"],
            "lock_path": python_profile["lockPath"],
            "lock_sha256": python_profile["lockSha256"],
            "packages": python_pin["packageVersions"],
            "gdal_version": python_profile["gdal"],
            "rasterio_proj_version": python_profile["rasterioProj"],
            "pyproj_proj_version": python_profile["pyprojProj"],
        },
        "vector": {
            "tippecanoe_version": tippecanoe["version"],
            "tippecanoe_source_sha256": tippecanoe["sourceSha256"],
            "tippecanoe_binary_sha256": vector_reference["tippecanoeBinarySha256"],
            "pmtiles_version": pmtiles["version"],
            "pmtiles_commit": pmtiles["commit"],
            "pmtiles_distribution_platform": "linux-x86_64",
            "pmtiles_distribution_sha256": pmtiles_asset["sha256"],
            "decode_binary_sha256": vector_reference["decodeBinarySha256"],
        },
    }
    _write_json(receipt_path, receipt)
    release_builder._checksums(forged)
    forged_comparison = compare_release_candidates(first, forged, contract=release)
    assert forged_comparison["status"] == "pending-external-provenance"
    assert forged_comparison["localComparisonStatus"] == "passed"
    assert forged_comparison["independentEnvironmentCount"] == 0
    assert forged_comparison["receiptProfileCount"] == 2
    assert len(forged_comparison["requiredExternalBindings"]) == 2
    assert len(
        {
            binding["candidateBindingSha256"]
            for binding in forged_comparison["requiredExternalBindings"]
        }
    ) == 2
    assert first_result.gate["automatedValidation"] == "failed"
    assert first_result.gate["releaseDisposition"] == "pending-owner"
    assert first_result.gate["blockingChecks"] == [
        "sourceArchiveAndMembersVerified",
        "crossEnvironmentReproducibility",
        "deliveryMeasurements",
    ]
    assert first_result.gate["phase1Unlocked"] is False

    for line in (first / "checksums.txt").read_text(encoding="utf-8").splitlines():
        expected, relative_path = line.split("  ", 1)
        actual = hashlib.sha256((first / relative_path).read_bytes()).hexdigest()
        assert actual == expected


@pytest.mark.skipif(
    not EXTERNAL_TOOLS_AVAILABLE,
    reason="set the pinned vector-tool paths for the complete release integration",
)
def test_builder_rejects_artifact_record_member_lineage_common_mode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = release_builder._artifact_record

    def corrupted_artifact_record(*args, **kwargs):
        record = original(*args, **kwargs)
        if kwargs.get("scenario") is None:
            return record
        return {
            **record,
            "source": {
                **record["source"],
                "memberSha256": "0" * 64,
            },
        }

    monkeypatch.setattr(
        release_builder,
        "_artifact_record",
        corrupted_artifact_record,
    )
    monkeypatch.setattr(release_builder, "_validate_stac", lambda *args, **kwargs: None)
    output = tmp_path / "candidate"

    with pytest.raises(ScienceContractError, match="Manifest artifact source lineage"):
        build_regional_release(
            _source(),
            output,
            release_id="ar6-europe-fixture-v1",
            contract=contract(),
            lookup_goldens_path=GOLDENS_PATH,
            build_environment_id="lineage-mutation",
            source_revision="a" * 40,
            **_tool_paths(),
        )

    assert not output.exists()


def test_builder_refuses_to_overwrite_immutable_release(tmp_path: Path) -> None:
    output = tmp_path / "existing"
    output.mkdir()

    with pytest.raises(ScienceContractError, match="already exists"):
        build_regional_release(
            _source(),
            output,
            release_id="ar6-europe-fixture-v1",
            contract=contract(),
            lookup_goldens_path=GOLDENS_PATH,
            build_environment_id="test-existing-path",
            source_revision="a" * 40,
            **_missing_tool_paths(),
        )


@pytest.mark.parametrize("release_id", ["../escape", "a/b", "UPPER", "absolute"])
def test_builder_rejects_unsafe_release_ids(tmp_path: Path, release_id: str) -> None:
    unsafe_id = str(tmp_path / "absolute") if release_id == "absolute" else release_id
    output = tmp_path / "candidate"

    with pytest.raises(ScienceContractError, match="Release ID"):
        build_regional_release(
            _source(),
            output,
            release_id=unsafe_id,
            contract=contract(),
            lookup_goldens_path=GOLDENS_PATH,
            build_environment_id="test-unsafe-id",
            source_revision="a" * 40,
            **_missing_tool_paths(),
        )

    assert not output.exists()
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    ("build_environment_id", "source_revision", "message"),
    [
        ("", "a" * 40, "build environment"),
        ("test-build", "branch-name", "Source revision"),
    ],
)
def test_builder_rejects_unbound_build_identity(
    tmp_path: Path,
    build_environment_id: str,
    source_revision: str,
    message: str,
) -> None:
    with pytest.raises(ScienceContractError, match=message):
        build_regional_release(
            _source(),
            tmp_path / "candidate",
            release_id="ar6-europe-fixture-v1",
            contract=contract(),
            lookup_goldens_path=GOLDENS_PATH,
            build_environment_id=build_environment_id,
            source_revision=source_revision,
            **_missing_tool_paths(),
        )


def test_builder_rejects_source_mutation_before_artifact_generation(
    tmp_path: Path,
) -> None:
    source = _source()
    layer = source.layers[0]
    layer.central_mm.flags.writeable = True
    layer.central_mm[0, 0] = layer.central_mm[0, 0] + 1

    with pytest.raises(ScienceContractError, match="changed after verification"):
        build_regional_release(
            source,
            tmp_path / "candidate",
            release_id="ar6-europe-fixture-v1",
            contract=contract(),
            lookup_goldens_path=GOLDENS_PATH,
            build_environment_id="test-mutated-source",
            source_revision="a" * 40,
            **_missing_tool_paths(),
        )

    assert not (tmp_path / "candidate").exists()


def test_builder_rejects_unbound_python_environment_before_vector_tools(
    tmp_path: Path,
) -> None:
    output = tmp_path / "candidate"

    with pytest.raises(ScienceContractError, match="release lock differs"):
        build_regional_release(
            _source(),
            output,
            release_id="ar6-europe-fixture-v1",
            contract=contract(),
            lookup_goldens_path=GOLDENS_PATH,
            build_environment_id="test-unbound-python",
            source_revision="a" * 40,
            **_missing_tool_paths(),
        )

    assert not output.exists()


def test_cli_wires_required_vector_trust_inputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    missing = tmp_path / "missing"
    output = tmp_path / "candidate"
    failure = tmp_path / "failure.json"
    timing = tmp_path / "timing.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "build_ar6_regional_release.py",
            "--fixture",
            str(FIXTURE_DIR / "source-fixture.json.gz"),
            "--fixture-receipt",
            str(FIXTURE_DIR / "source-fixture-receipt.json"),
            "--source-lock",
            str(REPO_ROOT / "src/pipeline/sources/source-lock.json"),
            "--source-semantics",
            str(REPO_ROOT / "src/pipeline/science/source-semantics.json"),
            "--release-contract",
            str(REPO_ROOT / "src/pipeline/science/ar6-regional-release.json"),
            "--lookup-goldens",
            str(GOLDENS_PATH),
            "--tippecanoe",
            str(missing),
            "--tippecanoe-decode",
            str(missing),
            "--pmtiles",
            str(missing),
            "--tippecanoe-source-archive",
            str(missing),
            "--tippecanoe-build-receipt",
            str(missing),
            "--pmtiles-distribution-asset",
            str(missing),
            "--pmtiles-distribution-platform",
            "darwin-arm64",
            "--python-lock",
            str(REPO_ROOT / "src/pipeline/requirements-release-macos-arm64.lock"),
            "--build-environment-id",
            "test-cli",
            "--release-id",
            "ar6-europe-fixture-v1",
            "--output",
            str(output),
            "--failure-gate",
            str(failure),
            "--timing-evidence",
            str(timing),
        ],
    )
    captured: dict[str, object] = {}

    def fake_git(repository: Path, *arguments: str) -> str:
        assert repository == REPO_ROOT
        if arguments == ("status", "--porcelain"):
            return ""
        assert arguments == ("rev-parse", "HEAD")
        return "a" * 40

    def fake_build_regional_release(*args, **kwargs):
        captured.update(kwargs)
        raise ScienceContractError("stop after CLI wiring")

    monkeypatch.setattr(release_cli, "_git", fake_git)
    monkeypatch.setattr(
        release_cli,
        "build_regional_release",
        fake_build_regional_release,
    )

    with pytest.raises(SystemExit):
        release_cli.main()

    blocked = json.loads(failure.read_text(encoding="utf-8"))
    assert blocked["failure"]["type"] == "ScienceContractError"
    assert blocked["automatedValidation"] == "failed"
    assert blocked["releaseDisposition"] == "pending-owner"
    assert blocked["phase1Unlocked"] is False
    assert captured["build_environment_id"] == "test-cli"
    assert captured["source_revision"] == "a" * 40
    assert isinstance(captured["workflow_started_monotonic"], float)
    assert captured["tippecanoe_source_archive_path"] == missing
    assert captured["tippecanoe_build_receipt_path"] == missing
    assert captured["pmtiles_distribution_asset_path"] == missing
    assert captured["pmtiles_distribution_platform"] == "darwin-arm64"
    assert not output.exists()
    assert not timing.exists()


@pytest.mark.parametrize("record_name", ["failure", "timing"])
def test_cli_rejects_records_inside_immutable_candidate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    record_name: str,
) -> None:
    output = tmp_path / "candidate"
    records = {
        "failure": tmp_path / "failure.json",
        "timing": tmp_path / "timing.json",
    }
    records[record_name] = output / f"{record_name}.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "build_ar6_regional_release.py",
            "--fixture",
            "unused",
            "--source-lock",
            "unused",
            "--source-semantics",
            "unused",
            "--release-contract",
            "unused",
            "--lookup-goldens",
            "unused",
            "--tippecanoe",
            "unused",
            "--tippecanoe-decode",
            "unused",
            "--pmtiles",
            "unused",
            "--tippecanoe-source-archive",
            "unused",
            "--tippecanoe-build-receipt",
            "unused",
            "--pmtiles-distribution-asset",
            "unused",
            "--pmtiles-distribution-platform",
            "darwin-arm64",
            "--python-lock",
            "unused",
            "--build-environment-id",
            "test-cli",
            "--release-id",
            "candidate-v1",
            "--output",
            str(output),
            "--failure-gate",
            str(records["failure"]),
            "--timing-evidence",
            str(records["timing"]),
        ],
    )

    with pytest.raises(ScienceContractError, match="outside the immutable candidate"):
        release_cli.main()

    assert not output.exists()
    assert not records["failure"].exists()
    assert not records["timing"].exists()
