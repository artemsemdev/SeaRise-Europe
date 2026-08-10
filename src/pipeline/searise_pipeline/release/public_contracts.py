"""Fail-closed validation for the versioned public release contracts."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, NoReturn, Sequence

from jsonschema import Draft202012Validator, FormatChecker  # type: ignore[import-untyped]
from referencing import Registry, Resource


class PublicReleaseContractError(ValueError):
    """Raised when individually valid release documents contradict each other."""


@dataclass(frozen=True)
class PublicManifestSummary:
    """Stable validation result shared by release builders and CI."""

    data_release_id: str
    artifact_count: int
    dataset_count: int


_CONTRACT_ROLES = {
    "scenarioConfig": "scenario-config",
    "methodology": "methodology",
    "attribution": "source-attribution",
    "buildReceipt": "build-receipt",
    "searchRecords": "settlement-geoparquet",
    "qualitySummary": "quality-summary",
    "architectureEvidence": "architecture-evidence",
    "stacCatalog": "stac-catalog",
    "stacCollection": "stac-collection",
    "checksums": "checksums",
    "provenance": "provenance",
    "signature": "signature",
}


def _fail(message: str) -> NoReturn:
    raise PublicReleaseContractError(message)


def _validator(schema_directory: Path, schema_name: str) -> Draft202012Validator:
    schemas = {
        path.name: _read_json_schema(path)
        for path in schema_directory.glob("*.schema.json")
    }
    if schema_name not in schemas:
        _fail(f"public schema is missing: {schema_name}")
    registry = Registry().with_resources(
        (schema["$id"], Resource.from_contents(schema)) for schema in schemas.values()
    )
    return Draft202012Validator(
        schemas[schema_name],
        registry=registry,
        format_checker=FormatChecker(),
    )


def _read_json_schema(path: Path) -> Mapping[str, Any]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PublicReleaseContractError(f"cannot read public schema {path.name}: {exc}") from exc
    if not isinstance(document, dict):
        _fail(f"public schema is not an object: {path.name}")
    return document


def _schema_validate(
    document: Mapping[str, Any], schema_directory: Path, schema_name: str
) -> None:
    errors = sorted(
        _validator(schema_directory, schema_name).iter_errors(document),
        key=lambda error: list(error.absolute_path),
    )
    if errors:
        error = errors[0]
        location = ".".join(str(part) for part in error.absolute_path) or "$"
        _fail(f"{schema_name} rejected {location}: {error.message}")


def validate_public_document(
    document: Mapping[str, Any], *, schema_directory: Path, schema_name: str
) -> None:
    """Validate one document against a named authoritative public schema."""
    _schema_validate(document, schema_directory, schema_name)


def _artifacts_by_id(manifest: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    artifacts = manifest["artifacts"]
    by_id = {artifact["artifactId"]: artifact for artifact in artifacts}
    if len(by_id) != len(artifacts):
        _fail("manifest artifact IDs must be unique")
    paths = [artifact["path"] for artifact in artifacts]
    if len(set(paths)) != len(paths):
        _fail("manifest artifact paths must be unique")
    return by_id


def _require_role(
    artifacts: Mapping[str, Mapping[str, Any]], artifact_id: str, role: str
) -> Mapping[str, Any]:
    artifact = artifacts.get(artifact_id)
    if artifact is None:
        _fail(f"manifest reference does not resolve: {artifact_id}")
    if artifact["role"] != role:
        _fail(f"manifest reference {artifact_id} must have role {role}")
    return artifact


def validate_public_manifest(
    manifest: Mapping[str, Any], *, schema_directory: Path
) -> PublicManifestSummary:
    """Validate one manifest and all semantic references within its inventory."""
    _schema_validate(manifest, schema_directory, "manifest.schema.json")
    release_id = manifest["dataReleaseId"]
    provenance_class = manifest["dataProvenanceClass"]
    authority = manifest["releaseAuthority"]
    if authority["dataProvenanceClass"] != provenance_class:
        _fail("manifest authority and release provenance classes differ")
    if manifest["publication"]["releasePath"] != f"releases/{release_id}":
        _fail("manifest publication path does not match its release ID")

    artifacts = _artifacts_by_id(manifest)
    for artifact in artifacts.values():
        if artifact["dataReleaseId"] != release_id:
            _fail(f"artifact {artifact['artifactId']} has a mismatched release ID")
        if artifact["dataProvenanceClass"] != provenance_class:
            _fail(f"artifact {artifact['artifactId']} has a mismatched provenance class")

    contract_artifacts = manifest["contractArtifacts"]
    for field, role in _CONTRACT_ROLES.items():
        _require_role(artifacts, contract_artifacts[field], role)
    for artifact_id in contract_artifacts["sourceReceipts"]:
        _require_role(artifacts, artifact_id, "source-receipt")
    for artifact_id in contract_artifacts["stacItems"]:
        _require_role(artifacts, artifact_id, "stac-item")
    for source in manifest["sources"]:
        receipt = _require_role(artifacts, source["receiptArtifactId"], "source-receipt")
        if receipt["artifactId"] not in contract_artifacts["sourceReceipts"]:
            _fail(f"source receipt is not declared by contractArtifacts: {receipt['artifactId']}")

    source_hashes = {source["archiveSha256"] for source in manifest["sources"]}
    for dataset in manifest["datasets"]:
        scenario = dataset["scenario"]
        horizon = dataset["horizon"]
        analysis = _require_role(
            artifacts, dataset["analysisArtifactId"], "projection-analysis-cog"
        )
        visual = _require_role(
            artifacts, dataset["visualArtifactId"], "projection-visual-pmtiles"
        )
        analytical = _require_role(
            artifacts, dataset["analyticalArtifactId"], "projection-geoparquet"
        )
        stac_item = _require_role(artifacts, dataset["stacItemArtifactId"], "stac-item")
        for artifact in (analysis, visual):
            context = artifact["projectionContext"]
            if (context["scenario"], context["horizon"]) != (scenario, horizon):
                _fail(f"artifact {artifact['artifactId']} contradicts its dataset context")
            if context["source"]["archiveSha256"] not in source_hashes:
                _fail(f"artifact {artifact['artifactId']} references an undeclared source")
        expected_stac_path = f"stac/items/{scenario}-{horizon}.json"
        if stac_item["path"] != expected_stac_path:
            _fail(f"STAC artifact {stac_item['artifactId']} contradicts its dataset path")
        matrix = analytical["projectionMatrixContext"]
        if scenario not in matrix["scenarios"] or horizon not in matrix["horizons"]:
            _fail("analytical GeoParquet does not cover the complete dataset matrix")

    return PublicManifestSummary(
        data_release_id=release_id,
        artifact_count=len(artifacts),
        dataset_count=len(manifest["datasets"]),
    )


def validate_release_rights(
    manifest: Mapping[str, Any],
    attribution: Mapping[str, Any],
    *,
    schema_directory: Path,
) -> None:
    """Require every artifact role and source to resolve to complete rights metadata."""
    _schema_validate(attribution, schema_directory, "attribution.schema.json")
    if attribution["dataReleaseId"] != manifest["dataReleaseId"]:
        _fail("attribution registry has a mismatched release ID")
    if attribution["dataProvenanceClass"] != manifest["dataProvenanceClass"]:
        _fail("attribution registry has a mismatched provenance class")
    records = {record["attributionId"]: record for record in attribution["records"]}
    if len(records) != len(attribution["records"]):
        _fail("attribution IDs must be unique")
    for source in manifest["sources"]:
        if source["attributionId"] not in records:
            _fail(f"source attribution does not resolve: {source['attributionId']}")
    for artifact in manifest["artifacts"]:
        for attribution_id in artifact["rights"]["attributionIds"]:
            record = records.get(attribution_id)
            if record is None:
                _fail(f"artifact attribution does not resolve: {attribution_id}")
            if artifact["role"] not in record["appliesToRoles"]:
                _fail(
                    f"attribution {attribution_id} does not cover role {artifact['role']}"
                )
            if (
                record["redistribution"] == "conditional"
                and artifact["rights"]["redistribution"] != "conditional"
            ):
                _fail(f"artifact {artifact['artifactId']} weakens conditional rights")
            if record["redistribution"] == "prohibited":
                _fail(f"artifact {artifact['artifactId']} cannot be redistributed")


def validate_release_artifacts(
    manifest: Mapping[str, Any], *, release_root: Path
) -> None:
    """Verify that every inventoried release file has its declared bytes and hash."""
    root = release_root.resolve()
    for artifact in manifest["artifacts"]:
        path = (root / artifact["path"]).resolve()
        if root not in path.parents:
            _fail(f"artifact path escapes the release root: {artifact['path']}")
        if not path.is_file():
            _fail(f"artifact file is missing: {artifact['path']}")
        if path.stat().st_size != artifact["byteSize"]:
            _fail(f"artifact byte size differs: {artifact['artifactId']}")
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        if digest.hexdigest() != artifact["sha256"]:
            _fail(f"artifact SHA-256 differs: {artifact['artifactId']}")


def validate_release_stac(
    manifest: Mapping[str, Any],
    catalog: Mapping[str, Any],
    collection: Mapping[str, Any],
    items: Sequence[Mapping[str, Any]],
    *,
    schema_directory: Path,
) -> None:
    """Bind the static STAC graph and asset identities to the manifest."""
    for document in (catalog, collection, *items):
        _schema_validate(document, schema_directory, "stac.schema.json")
    release_id = manifest["dataReleaseId"]
    provenance_class = manifest["dataProvenanceClass"]
    for document in (catalog, collection, *items):
        if document["searise:data_release_id"] != release_id:
            _fail("STAC document has a mismatched release ID")
        if document["searise:data_provenance_class"] != provenance_class:
            _fail("STAC document has a mismatched provenance class")
    if catalog["id"] != f"{release_id}-catalog":
        _fail("STAC Catalog ID does not match the release")
    if collection["id"] != f"{release_id}-projections":
        _fail("STAC Collection ID does not match the release")

    datasets = {
        (dataset["scenario"], dataset["horizon"]): dataset
        for dataset in manifest["datasets"]
    }
    by_item = {
        (item["properties"]["searise:scenario"], item["properties"]["searise:horizon"]): item
        for item in items
    }
    if len(items) != 9 or set(by_item) != set(datasets):
        _fail("STAC Items do not form the exact manifest 3 x 3 matrix")
    expected_links = [
        f"items/{scenario}-{horizon}.json" for scenario, horizon in datasets
    ]
    observed_links = [
        link["href"] for link in collection["links"] if link["rel"] == "item"
    ]
    if observed_links != expected_links:
        _fail("STAC Collection Item links do not match manifest order")

    artifacts = _artifacts_by_id(manifest)
    for context, dataset in datasets.items():
        scenario, horizon = context
        item = by_item[context]
        if item["id"] != f"{scenario}-{horizon}":
            _fail("STAC Item ID contradicts its scenario and horizon")
        if item["collection"] != collection["id"]:
            _fail(f"STAC Item {item['id']} has a mismatched Collection")
        if item["properties"]["datetime"] != f"{horizon}-01-01T00:00:00Z":
            _fail(f"STAC Item {item['id']} has a contradictory datetime")
        expected_assets = {
            "analysis": dataset["analysisArtifactId"],
            "visual": dataset["visualArtifactId"],
            "table": dataset["analyticalArtifactId"],
        }
        for key, artifact_id in expected_assets.items():
            asset = item["assets"][key]
            artifact = artifacts[artifact_id]
            if asset["searise:artifact_id"] != artifact_id:
                _fail(f"STAC Item {item['id']} has a mismatched {key} artifact ID")
            if asset["href"] != f"../../{artifact['path']}":
                _fail(f"STAC Item {item['id']} has a mismatched {key} path")
            if asset["file:size"] != artifact["byteSize"]:
                _fail(f"STAC Item {item['id']} has a mismatched {key} byte size")
            if asset["checksum:multihash"] != f"1220{artifact['sha256']}":
                _fail(f"STAC Item {item['id']} has a mismatched {key} hash")
