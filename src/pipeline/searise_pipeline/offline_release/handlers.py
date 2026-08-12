"""Deterministic handlers that assemble a public release from reviewed inputs."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any, Mapping

from ..release import (
    validate_public_document,
    validate_public_manifest,
    validate_release_artifacts,
    validate_release_rights,
    validate_release_stac,
)
from .engine import StageContext, StageHandler, StageOutcome
from .model import BuildPlan, StageName
from .profiles import CompiledProfile
from .projection_bundle import validate_reviewed_projection_bundle

_SCIENTIFIC_OUTPUT_ROLES = {
    "projection-analysis-cog",
    "projection-geoparquet",
    "projection-visual-pmtiles",
}
_DOCUMENT_SCHEMAS = {
    "scenario-config": "scenario-config.schema.json",
    "methodology": "methodology.schema.json",
    "source-attribution": "attribution.schema.json",
    "source-receipt": "source-receipt.schema.json",
    "build-receipt": "build-receipt.schema.json",
    "quality-summary": "quality-summary.schema.json",
    "architecture-evidence": "architecture-evidence.schema.json",
}


def release_handlers(compiled: CompiledProfile) -> Mapping[StageName, StageHandler]:
    """Return one handler per typed stage without profile-specific branching."""
    plan = compiled.plan
    definition = compiled.definition

    def source_root(context: StageContext) -> Path:
        _require_plan(context, plan)
        return context.input_root / definition.input_root_path

    def verify_sources(context: StageContext) -> StageOutcome:
        root = source_root(context)
        receipts = []
        for identity in plan.source_receipts:
            document = _read_json(context.input_root / identity.path)
            receipts.append(
                {
                    "path": identity.path,
                    "sha256": identity.sha256,
                    "sourceId": document["sourceId"],
                }
            )
        _write_json(
            context.output_directory / "source-verification.json",
            {
                "schemaVersion": 1,
                "dataReleaseId": plan.data_release_id,
                "inputRoot": definition.input_root_path,
                "manifestSha256": _sha256(root / "manifest.json"),
                "receipts": receipts,
            },
        )
        return StageOutcome(quality_results={"verifiedSourceReceipts": len(receipts)})

    def inspect(context: StageContext) -> StageOutcome:
        root = source_root(context)
        manifest = _read_json(root / "manifest.json")
        _write_json(
            context.output_directory / "inspection.json",
            {
                "schemaVersion": 1,
                "sourceDataReleaseId": manifest["dataReleaseId"],
                "artifactCount": len(manifest["artifacts"]),
                "datasetCount": len(manifest["datasets"]),
                "dependencyStage": StageName.VERIFY_SOURCES.value,
            },
        )
        return StageOutcome(
            quality_results={
                "artifactCount": len(manifest["artifacts"]),
                "datasetCount": len(manifest["datasets"]),
            }
        )

    def normalize(context: StageContext) -> StageOutcome:
        source_root(context)
        _write_json(
            context.output_directory / "normalization.json",
            {
                "schemaVersion": 1,
                "dataReleaseId": plan.data_release_id,
                "parametersSha256": plan.parameters_sha256,
                "locale": plan.parameters["locale"],
                "ordering": plan.parameters["ordering"],
                "numericTypes": plan.parameters["numericTypes"],
                "crsTransforms": plan.parameters["crsTransforms"],
            },
        )
        return StageOutcome(quality_results={"parametersCanonical": True})

    def derive(context: StageContext) -> StageOutcome:
        root = source_root(context)
        projection_validation = validate_reviewed_projection_bundle(
            root,
            repository_root=context.input_root,
        )
        manifest = _read_json(root / "manifest.json")
        outputs = [
            artifact
            for artifact in manifest["artifacts"]
            if artifact["role"] in _SCIENTIFIC_OUTPUT_ROLES
        ]
        for artifact in outputs:
            destination = context.output_directory / "artifacts" / artifact["path"]
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(root / artifact["path"], destination)
        _write_json(
            context.output_directory / "derivation.json",
            {
                "schemaVersion": 1,
                "artifactCount": len(outputs),
                "artifacts": [artifact["path"] for artifact in outputs],
            },
        )
        return StageOutcome(
            quality_results={
                "derivedArtifactCount": len(outputs),
                **projection_validation,
            }
        )

    def package(context: StageContext) -> StageOutcome:
        root = source_root(context)
        candidate = context.output_directory / "candidate"
        shutil.copytree(root, candidate, copy_function=shutil.copyfile)
        derived = context.dependency_directories[StageName.DERIVE] / "artifacts"
        derived_files = tuple(path for path in derived.rglob("*") if path.is_file())
        for path in derived_files:
            relative = path.relative_to(derived)
            shutil.copyfile(path, candidate / relative)
        _write_json(
            context.output_directory / "package.json",
            {
                "schemaVersion": 1,
                "candidateFileCount": len(_files(candidate)),
                "derivedArtifactCount": len(derived_files),
            },
        )
        return StageOutcome(quality_results={"candidatePackaged": True})

    def validate(context: StageContext) -> StageOutcome:
        packaged = context.dependency_directories[StageName.PACKAGE] / "candidate"
        candidate = context.output_directory / "candidate"
        shutil.copytree(packaged, candidate, copy_function=shutil.copyfile)
        summary = validate_complete_release(
            candidate,
            schema_directory=context.input_root / definition.schema_directory,
        )
        _write_json(context.output_directory / "validation.json", summary)
        return StageOutcome(quality_results=summary)

    def assemble(context: StageContext) -> StageOutcome:
        validated = context.dependency_directories[StageName.VALIDATE] / "candidate"
        _copy_contents(validated, context.output_directory)
        _rewrite_release(
            context.output_directory,
            plan=plan,
            schema_directory=context.input_root / definition.schema_directory,
        )
        summary = validate_complete_release(
            context.output_directory,
            schema_directory=context.input_root / definition.schema_directory,
        )
        return StageOutcome(quality_results=summary)

    return {
        StageName.VERIFY_SOURCES: verify_sources,
        StageName.INSPECT: inspect,
        StageName.NORMALIZE: normalize,
        StageName.DERIVE: derive,
        StageName.PACKAGE: package,
        StageName.VALIDATE: validate,
        StageName.ASSEMBLE_RELEASE: assemble,
    }


def validate_complete_release(
    release_root: Path, *, schema_directory: Path
) -> dict[str, Any]:
    """Validate every public document, relationship, file, hash, and checksum."""
    manifest = _read_json(release_root / "manifest.json")
    summary = validate_public_manifest(manifest, schema_directory=schema_directory)
    artifacts = {artifact["role"]: artifact for artifact in manifest["artifacts"]}
    documents = {}
    for role, schema_name in _DOCUMENT_SCHEMAS.items():
        artifact = artifacts[role]
        document = _read_json(release_root / artifact["path"])
        validate_public_document(
            document,
            schema_directory=schema_directory,
            schema_name=schema_name,
        )
        documents[role] = document
    receipt = documents["build-receipt"]
    expected_outputs = _public_outputs(manifest)
    expected_sources = _public_source_receipts(manifest)
    if (
        receipt["dataReleaseId"] != manifest["dataReleaseId"]
        or receipt["dataProvenanceClass"] != manifest["dataProvenanceClass"]
        or receipt["outputs"] != expected_outputs
        or receipt["sourceReceipts"] != expected_sources
    ):
        raise ValueError("public build receipt differs from the release inventory")
    attribution = _read_json(release_root / artifacts["source-attribution"]["path"])
    validate_release_rights(
        manifest,
        attribution,
        schema_directory=schema_directory,
    )
    catalog = _read_json(release_root / artifacts["stac-catalog"]["path"])
    collection = _read_json(release_root / artifacts["stac-collection"]["path"])
    item_paths = manifest["contractArtifacts"]["stacItems"]
    by_id = {artifact["artifactId"]: artifact for artifact in manifest["artifacts"]}
    items = [_read_json(release_root / by_id[item]["path"]) for item in item_paths]
    validate_release_stac(
        manifest,
        catalog,
        collection,
        items,
        schema_directory=schema_directory,
    )
    validate_release_artifacts(manifest, release_root=release_root)
    expected_files = {"manifest.json", *(artifact["path"] for artifact in manifest["artifacts"])}
    observed_files = {path.relative_to(release_root).as_posix() for path in _files(release_root)}
    if observed_files != expected_files:
        raise ValueError("release tree contains missing or unexpected files")
    _validate_checksums(release_root)
    return {
        "schemaVersion": 1,
        "dataReleaseId": summary.data_release_id,
        "artifactCount": summary.artifact_count,
        "datasetCount": summary.dataset_count,
        "complete": True,
    }


def _rewrite_release(root: Path, *, plan: BuildPlan, schema_directory: Path) -> None:
    manifest_path = root / "manifest.json"
    original_manifest = _read_json(manifest_path)
    original_release_id = original_manifest["dataReleaseId"]
    for path in _files(root):
        if path.suffix == ".json":
            document = _read_json(path)
            _write_json(path, _replace_string(document, original_release_id, plan.data_release_id))
        elif path.suffix == ".jsonl":
            lines = [
                _replace_string(json.loads(line), original_release_id, plan.data_release_id)
                for line in path.read_text(encoding="utf-8").splitlines()
                if line
            ]
            path.write_text(
                "".join(
                    json.dumps(line, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
                    + "\n"
                    for line in lines
                ),
                encoding="utf-8",
            )
    manifest = _read_json(manifest_path)
    _write_provenance(root, manifest=manifest, plan=plan)
    for artifact in manifest["artifacts"]:
        if artifact["path"] in {"receipts/build.json", "checksums.txt"}:
            continue
        path = root / artifact["path"]
        artifact["byteSize"] = path.stat().st_size
        artifact["sha256"] = _sha256(path)
    build_receipt = _build_receipt(manifest, plan=plan)
    validate_public_document(
        build_receipt,
        schema_directory=schema_directory,
        schema_name="build-receipt.schema.json",
    )
    receipt_path = root / "receipts/build.json"
    _write_json(receipt_path, build_receipt)
    receipt_hash = _sha256(receipt_path)
    for artifact in manifest["artifacts"]:
        for lineage in artifact["lineage"]:
            lineage_path = root / lineage["path"]
            if lineage["path"] == "receipts/build.json":
                lineage["sha256"] = receipt_hash
            elif lineage_path.is_file():
                lineage["sha256"] = _sha256(lineage_path)
        if artifact["path"] == "checksums.txt":
            continue
        path = root / artifact["path"]
        artifact["byteSize"] = path.stat().st_size
        artifact["sha256"] = _sha256(path)
    _write_checksums(root)
    checksums = next(
        artifact for artifact in manifest["artifacts"] if artifact["path"] == "checksums.txt"
    )
    checksums["byteSize"] = (root / "checksums.txt").stat().st_size
    checksums["sha256"] = _sha256(root / "checksums.txt")
    _write_json(manifest_path, manifest)


def _build_receipt(manifest: Mapping[str, Any], *, plan: BuildPlan) -> dict[str, Any]:
    outputs = _public_outputs(manifest)
    source_receipts = _public_source_receipts(manifest)
    timestamps = plan.parameters["receiptTimestamps"]
    return {
        "$schema": (
            "https://artemsemdev.github.io/SeaRise-Europe/contracts/release/v1/"
            "build-receipt.schema.json"
        ),
        "schemaVersion": "1.0.0",
        "dataReleaseId": plan.data_release_id,
        "dataProvenanceClass": plan.data_provenance_class,
        "buildId": plan.build_id,
        "codeRevision": plan.code_revision,
        "buildMode": "offline",
        "networkAccess": "disabled",
        "startedAt": timestamps["startedAt"],
        "completedAt": timestamps["completedAt"],
        "environment": plan.environment.as_public_dict(),
        "tools": [tool.as_public_dict() for tool in plan.tools],
        "sourceReceipts": source_receipts,
        "inputs": [item.as_public_dict() for item in plan.inputs],
        "parametersSha256": plan.parameters_sha256,
        "outputs": outputs,
        "reproducibilityComparison": {
            "identityFields": [
                "dataReleaseId",
                "codeRevision",
                "environment.lock.sha256",
                "tools",
                "sourceReceipts",
                "inputs",
                "parametersSha256",
                "outputs",
            ],
            "excludedVolatileFields": ["startedAt", "completedAt"],
        },
    }


def _public_outputs(manifest: Mapping[str, Any]) -> list[dict[str, Any]]:
    return sorted(
        [
            {
                "path": artifact["path"],
                "role": artifact["role"],
                "mediaType": artifact["mediaType"],
                "byteSize": artifact["byteSize"],
                "sha256": artifact["sha256"],
            }
            for artifact in manifest["artifacts"]
            if artifact["role"] in _SCIENTIFIC_OUTPUT_ROLES
        ],
        key=lambda item: item["path"],
    )


def _public_source_receipts(manifest: Mapping[str, Any]) -> list[dict[str, str]]:
    return sorted(
        [
            {"path": artifact["path"], "sha256": artifact["sha256"]}
            for artifact in manifest["artifacts"]
            if artifact["role"] == "source-receipt"
        ],
        key=lambda item: item["path"],
    )


def _write_provenance(root: Path, *, manifest: Mapping[str, Any], plan: BuildPlan) -> None:
    path = root / "provenance.intoto.jsonl"
    provenance = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    definition = provenance["predicate"]["buildDefinition"]
    definition["buildType"] = "https://searise.example/build/offline-release/v1"
    definition["externalParameters"] = {
        "dataProvenanceClass": plan.data_provenance_class,
        "dataReleaseId": plan.data_release_id,
        "profile": plan.profile.value,
    }
    definition["internalParameters"] = {
        "networkAccess": "disabled",
        "parametersSha256": plan.parameters_sha256,
        "planIdentitySha256": plan.identity_sha256,
    }
    run = provenance["predicate"]["runDetails"]
    run["builder"]["id"] = (
        f"https://github.com/artemsemdev/SeaRise-Europe/tree/{plan.code_revision}"
    )
    run["metadata"]["invocationId"] = plan.build_id
    provenance["subject"] = [
        {"name": output["path"], "digest": {"sha256": output["sha256"]}}
        for output in _build_receipt(manifest, plan=plan)["outputs"]
    ]
    path.write_text(
        json.dumps(provenance, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n",
        encoding="utf-8",
    )


def _write_checksums(root: Path) -> None:
    lines = [
        "# Complete artifact checksums; manifest.json and checksums.txt are "
        "excluded to avoid self-reference."
    ]
    for path in _files(root):
        relative = path.relative_to(root).as_posix()
        if relative not in {"manifest.json", "checksums.txt"}:
            lines.append(f"{_sha256(path)}  {relative}")
    (root / "checksums.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _validate_checksums(root: Path) -> None:
    observed = (root / "checksums.txt").read_text(encoding="utf-8").splitlines()[1:]
    expected = [
        f"{_sha256(path)}  {path.relative_to(root).as_posix()}"
        for path in _files(root)
        if path.relative_to(root).as_posix() not in {"manifest.json", "checksums.txt"}
    ]
    if observed != expected:
        raise ValueError("checksums.txt differs from the complete sorted file inventory")


def _replace_string(value: Any, old: str, new: str) -> Any:
    if isinstance(value, str):
        return value.replace(old, new)
    if isinstance(value, list):
        return [_replace_string(item, old, new) for item in value]
    if isinstance(value, dict):
        return {key: _replace_string(item, old, new) for key, item in value.items()}
    return value


def _require_plan(context: StageContext, plan: BuildPlan) -> None:
    if context.plan != plan:
        raise ValueError("handler plan differs from the compiled profile")


def _copy_contents(source: Path, destination: Path) -> None:
    for path in source.iterdir():
        target = destination / path.name
        if path.is_dir():
            shutil.copytree(path, target, copy_function=shutil.copyfile)
        else:
            shutil.copyfile(path, target)


def _files(root: Path) -> tuple[Path, ...]:
    return tuple(sorted(path for path in root.rglob("*") if path.is_file()))


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON document is not an object: {path.name}")
    return value


def _write_json(path: Path, document: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
