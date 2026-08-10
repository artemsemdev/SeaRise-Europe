"""End-to-end tests for the receipt-driven public release handlers."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

import searise_pipeline.offline_release.projection_bundle as projection_bundle_module
from searise_pipeline.offline_release import (
    StageName,
    compile_profile,
    release_handlers,
    run_build,
    validate_complete_release,
)
from searise_pipeline.offline_release.projection_bundle import (
    validate_reviewed_projection_bundle,
)
from searise_pipeline.science import ScienceContractError

REPO_ROOT = Path(__file__).parents[4]
PROFILE = REPO_ROOT / "src/pipeline/offline_release/profiles/fixture.json"
SCHEMAS = REPO_ROOT / "contracts/release/v1"
OLD_RELEASE_ID = "searise-europe-v1.0.0-20260810-c096aeab4e09"
BUNDLE = REPO_ROOT / "contracts/release/v1/fixtures/release" / OLD_RELEASE_ID


def _compiled():
    return compile_profile(
        PROFILE,
        input_root=REPO_ROOT,
        code_revision="a" * 40,
        release_date="20260810",
        started_at="2026-08-10T12:00:00Z",
        completed_at="2026-08-10T12:00:01Z",
    )


def _build(tmp_path: Path, *, cache: str, output: str):
    compiled = _compiled()
    result = run_build(
        compiled.plan,
        input_root=REPO_ROOT,
        cache_directory=tmp_path / cache,
        output_directory=tmp_path / output,
        handlers=release_handlers(compiled),
    )
    return compiled, result


def test_fixture_handlers_build_a_complete_new_public_release(tmp_path: Path) -> None:
    compiled, result = _build(tmp_path, cache="cache", output="candidate")
    root = result.output_directory
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    receipt = json.loads((root / "receipts/build.json").read_text(encoding="utf-8"))

    assert manifest["dataReleaseId"] == compiled.plan.data_release_id
    assert manifest["dataReleaseId"] != OLD_RELEASE_ID
    assert receipt["dataReleaseId"] == compiled.plan.data_release_id
    assert receipt["buildId"] == compiled.plan.build_id
    assert receipt["codeRevision"] == "a" * 40
    assert receipt["buildMode"] == "offline"
    assert receipt["networkAccess"] == "disabled"
    assert len(receipt["outputs"]) == 19
    source_artifact = next(
        artifact for artifact in manifest["artifacts"] if artifact["role"] == "source-receipt"
    )
    assert receipt["sourceReceipts"] == [
        {"path": source_artifact["path"], "sha256": source_artifact["sha256"]}
    ]
    assert len(list(root.rglob("*"))) == 57
    assert len([path for path in root.rglob("*") if path.is_file()]) == 42
    assert not any(path.name.endswith("-verification.json") for path in root.rglob("*"))
    assert all(stage.quality_results for stage in result.stages)
    assert validate_complete_release(root, schema_directory=SCHEMAS)["complete"] is True

    text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in root.rglob("*")
        if path.is_file()
        and path.suffix in {".json", ".jsonl"}
        and path.relative_to(root).as_posix() != "receipts/build.json"
    )
    assert OLD_RELEASE_ID not in text
    assert any(OLD_RELEASE_ID in item["path"] for item in receipt["inputs"])
    derive = next(stage for stage in result.stages if stage.stage is StageName.DERIVE)
    assert derive.quality_results == {
        "derivedArtifactCount": 19,
        "reviewedProjectionArtifactCount": 19,
        "reviewedProjectionCogsValidated": 9,
        "reviewedProjectionGeoparquetValidated": True,
        "reviewedProjectionPmtilesDecodedParity": "approved-byte-identical",
        "reviewedProjectionGoldenParity": True,
    }


def test_two_independent_fixture_builds_are_byte_identical(tmp_path: Path) -> None:
    _, first = _build(tmp_path, cache="cache-one", output="first")
    _, second = _build(tmp_path, cache="cache-two", output="second")

    first_files = {
        path.relative_to(first.output_directory).as_posix(): path.read_bytes()
        for path in first.output_directory.rglob("*")
        if path.is_file()
    }
    second_files = {
        path.relative_to(second.output_directory).as_posix(): path.read_bytes()
        for path in second.output_directory.rglob("*")
        if path.is_file()
    }
    assert first_files == second_files
    assert [stage.cache_status for stage in first.stages] == ["miss"] * 7
    assert [stage.cache_status for stage in second.stages] == ["miss"] * 7


def test_handlers_expose_no_publication_or_activation_stage() -> None:
    compiled = _compiled()
    handlers = release_handlers(compiled)

    assert set(handlers) == set(StageName)
    assert not ({"publish", "upload", "activate"} & {stage.value for stage in handlers})


def test_projection_bundle_adapter_reuses_semantic_validators(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = {"cog": 0, "geoparquet": 0, "goldens": 0}
    original_cog = projection_bundle_module.validate_analysis_cog
    original_geoparquet = projection_bundle_module.validate_geoparquet
    original_goldens = projection_bundle_module.validate_lookup_goldens

    def count_cog(*args, **kwargs):
        calls["cog"] += 1
        return original_cog(*args, **kwargs)

    def count_geoparquet(*args, **kwargs):
        calls["geoparquet"] += 1
        return original_geoparquet(*args, **kwargs)

    def count_goldens(*args, **kwargs):
        calls["goldens"] += 1
        return original_goldens(*args, **kwargs)

    monkeypatch.setattr(projection_bundle_module, "validate_analysis_cog", count_cog)
    monkeypatch.setattr(projection_bundle_module, "validate_geoparquet", count_geoparquet)
    monkeypatch.setattr(projection_bundle_module, "validate_lookup_goldens", count_goldens)

    summary = validate_reviewed_projection_bundle(BUNDLE, repository_root=REPO_ROOT)

    assert calls == {"cog": 9, "geoparquet": 1, "goldens": 1}
    assert summary["reviewedProjectionArtifactCount"] == 19


def test_projection_bundle_adapter_rejects_pmtiles_outside_approved_bytes(
    tmp_path: Path,
) -> None:
    candidate = tmp_path / "candidate"
    shutil.copytree(BUNDLE, candidate)
    archive = candidate / "layers/ssp2-45/2050.pmtiles"
    archive.write_bytes(archive.read_bytes() + b"tampered")

    with pytest.raises(ScienceContractError, match="reviewed #110 identity"):
        validate_reviewed_projection_bundle(candidate, repository_root=REPO_ROOT)


def test_projection_bundle_adapter_rejects_unapproved_owner_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_read = projection_bundle_module._read_json

    def read_with_rejected_gate(path: Path):
        document = original_read(path)
        if path.name == "final-gate.json":
            document["releaseDisposition"] = "rejected"
        return document

    monkeypatch.setattr(projection_bundle_module, "_read_json", read_with_rejected_gate)

    with pytest.raises(ScienceContractError, match="owner-approved"):
        validate_reviewed_projection_bundle(BUNDLE, repository_root=REPO_ROOT)
