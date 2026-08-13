"""Authoritative candidate-bound validators for production JSON contracts."""

from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, NoReturn

from jsonschema import Draft202012Validator

from searise_pipeline.release.public_contracts import (
    PublicReleaseContractError,
    validate_public_document,
)

from .qa_dispatch import ArtifactValidator, QaValidationOutcome, QaValidationRequest
from .validator import CandidateContractError

REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
RELEASE_V1_SCHEMA_ROOT = REPOSITORY_ROOT / "contracts/release/v1"
RELEASE_V2_SCHEMA_ROOT = REPOSITORY_ROOT / "contracts/release/v2"
SETTLEMENT_SCHEMA = REPOSITORY_ROOT / "contracts/settlements/v4/search-artifact.schema.json"
INVENTORY = REPOSITORY_ROOT / "contracts/candidate-completeness/v2/required-artifacts.json"

_PUBLIC_SCHEMAS = {
    "release.public-contract.architecture-evidence": (
        RELEASE_V1_SCHEMA_ROOT,
        "architecture-evidence.schema.json",
    ),
    "release.build-receipt": (RELEASE_V2_SCHEMA_ROOT, "build-receipt.schema.json"),
    "release.public-contract.methodology": (
        RELEASE_V1_SCHEMA_ROOT,
        "methodology.schema.json",
    ),
    "release.public-contract.quality-summary": (
        RELEASE_V1_SCHEMA_ROOT,
        "quality-summary.schema.json",
    ),
    "release.public-contract.scenario-config": (
        RELEASE_V1_SCHEMA_ROOT,
        "scenario-config.schema.json",
    ),
    "release.rights": (RELEASE_V2_SCHEMA_ROOT, "attribution.schema.json"),
    "release.public-contract.source-receipt": (
        RELEASE_V1_SCHEMA_ROOT,
        "source-receipt.schema.json",
    ),
    "release.stac.catalog": (RELEASE_V1_SCHEMA_ROOT, "stac.schema.json"),
    "release.stac.collection": (RELEASE_V1_SCHEMA_ROOT, "stac.schema.json"),
    "release.stac.item": (RELEASE_V1_SCHEMA_ROOT, "stac.schema.json"),
}


class _DuplicateKeyError(ValueError):
    pass


def _fail(code: str, message: str) -> NoReturn:
    raise CandidateContractError(code, message)


def _object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateKeyError(key)
        result[key] = value
    return result


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_object_pairs,
            parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)),
        )
    except (OSError, UnicodeDecodeError, ValueError, json.JSONDecodeError) as exc:
        raise CandidateContractError("qa-json", "artifact is not strict UTF-8 JSON") from exc
    if not isinstance(value, dict):
        _fail("qa-json", "artifact JSON root must be an object")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@lru_cache(maxsize=1)
def _candidate_paths() -> frozenset[str]:
    return frozenset(item["path"] for item in _load_json(INVENTORY)["requiredArtifacts"])


def _candidate_path(request: QaValidationRequest, value: str) -> Path:
    logical = PurePosixPath(value)
    if logical.is_absolute() or any(part in {"", ".", ".."} for part in logical.parts):
        _fail("qa-json-reference", f"candidate reference is unsafe: {value}")
    return request.candidate.candidate_root.joinpath(*logical.parts)


def _binding_outcome(
    request: QaValidationRequest, document: Mapping[str, Any]
) -> QaValidationOutcome | None:
    context = request.candidate
    data_release_id = document.get(
        "dataReleaseId", document.get("searise:data_release_id")
    )
    provenance_class = document.get(
        "dataProvenanceClass", document.get("searise:data_provenance_class")
    )
    if data_release_id != context.data_release_id:
        return QaValidationOutcome(
            "fail", "json-release-binding", "JSON data release identity differs"
        )
    if provenance_class != context.data_provenance_class:
        return QaValidationOutcome(
            "fail", "json-provenance-binding", "JSON provenance class differs"
        )
    return None


def _validate_references(
    request: QaValidationRequest,
    value: Any,
) -> QaValidationOutcome | None:
    """Verify every object carrying a candidate path and SHA-256 pair."""
    if isinstance(value, Mapping):
        path = value.get("path")
        digest = value.get("sha256")
        if isinstance(path, str) and isinstance(digest, str):
            if path in _candidate_paths():
                try:
                    candidate_path = _candidate_path(request, path)
                    if not candidate_path.is_file() or _sha256(candidate_path) != digest:
                        return QaValidationOutcome(
                            "fail", "json-reference-binding", f"referenced bytes differ: {path}"
                        )
                except OSError:
                    return QaValidationOutcome(
                        "fail",
                        "json-reference-binding",
                        f"referenced bytes cannot be read: {path}",
                    )
        for child in value.values():
            outcome = _validate_references(request, child)
            if outcome is not None:
                return outcome
    elif isinstance(value, list):
        for child in value:
            outcome = _validate_references(request, child)
            if outcome is not None:
                return outcome
    return None


def _validate_rights(document: Mapping[str, Any]) -> QaValidationOutcome | None:
    inventory = _load_json(INVENTORY)
    required = inventory["requiredArtifacts"]
    expected_ids = {
        attribution_id
        for artifact in required
        for attribution_id in artifact["attributionIds"]
    }
    records = document.get("records")
    if not isinstance(records, list):
        return QaValidationOutcome("fail", "rights-incomplete", "rights records are absent")
    by_id = {
        item.get("attributionId"): item for item in records if isinstance(item, Mapping)
    }
    if set(by_id) != expected_ids or len(by_id) != len(records):
        return QaValidationOutcome(
            "fail", "rights-incomplete", "rights identities differ from candidate inventory"
        )
    for artifact in required:
        for attribution_id in artifact["attributionIds"]:
            record = by_id[attribution_id]
            if (
                record.get("redistribution") != "allowed"
                or artifact["role"] not in record.get("appliesToRoles", [])
            ):
                return QaValidationOutcome(
                    "fail",
                    "rights-incomplete",
                    f"rights do not allow role {artifact['role']}: {attribution_id}",
                )
    return None


def _build_receipt_binding(document: Mapping[str, Any]) -> QaValidationOutcome | None:
    inventory = _load_json(INVENTORY)["requiredArtifacts"]
    expected_paths = {
        item["path"]
        for item in inventory[:51]
        if item["role"] != "build-receipt"
    }
    outputs = document.get("outputs")
    if not isinstance(outputs, list):
        return QaValidationOutcome("fail", "build-output-binding", "outputs are absent")
    observed_paths = {
        item.get("path") for item in outputs if isinstance(item, Mapping)
    }
    if len(outputs) != len(observed_paths) or observed_paths != expected_paths:
        return QaValidationOutcome(
            "fail",
            "build-output-binding",
            "build outputs differ from the exact pre-terminal candidate inventory",
        )
    expected_receipts = {
        item["path"] for item in inventory[:51] if item["role"] == "source-receipt"
    }
    source_receipts = document.get("sourceReceipts")
    observed_receipts = {
        item.get("path") for item in source_receipts if isinstance(item, Mapping)
    } if isinstance(source_receipts, list) else set()
    if len(observed_receipts) != len(expected_receipts) or observed_receipts != expected_receipts:
        return QaValidationOutcome(
            "fail",
            "build-source-binding",
            "build source receipts differ from the required source inventory",
        )
    return None


def _stac_binding(
    request: QaValidationRequest, document: Mapping[str, Any]
) -> QaValidationOutcome | None:
    release_id = request.candidate.data_release_id
    if request.selector.role == "stac-catalog":
        links = document.get("links")
        expected = [
            {"rel": "root", "href": "catalog.json", "type": "application/json"},
            {"rel": "child", "href": "collection.json", "type": "application/json"},
        ]
        if document.get("id") != f"{release_id}-catalog" or links != expected:
            return QaValidationOutcome(
                "fail", "stac-binding", "STAC Catalog identity or graph differs"
            )
        return None
    if request.selector.role == "stac-collection":
        links = document.get("links")
        expected_items = [
            f"items/{scenario}-{horizon}.json"
            for scenario in ("ssp1-26", "ssp2-45", "ssp5-85")
            for horizon in (2030, 2050, 2100)
        ]
        observed_items = [
            item.get("href")
            for item in links
            if isinstance(item, Mapping) and item.get("rel") == "item"
        ] if isinstance(links, list) else []
        if (
            document.get("id") != f"{release_id}-projections"
            or observed_items != expected_items
        ):
            return QaValidationOutcome(
                "fail", "stac-binding", "STAC Collection identity or items differ"
            )
        return None
    if request.selector.role != "stac-item":
        return None
    properties = document.get("properties")
    assets = document.get("assets")
    if not isinstance(properties, Mapping) or not isinstance(assets, Mapping):
        return QaValidationOutcome("fail", "stac-binding", "STAC Item fields are absent")
    scenario = properties.get("searise:scenario")
    horizon = properties.get("searise:horizon")
    expected_name = f"{scenario}-{horizon}.json"
    if (
        request.artifact_path.name != expected_name
        or document.get("id") != f"{scenario}-{horizon}"
        or document.get("collection") != f"{release_id}-projections"
    ):
        return QaValidationOutcome(
            "fail", "stac-binding", "STAC Item identity differs from its candidate path"
        )
    expected_paths = {
        "analysis": f"analysis/{scenario}/{horizon}.tif",
        "visual": f"layers/{scenario}/{horizon}.pmtiles",
        "table": "analysis/projections.parquet",
    }
    for key, expected_path in expected_paths.items():
        asset = assets.get(key)
        if not isinstance(asset, Mapping) or asset.get("href") != f"../../{expected_path}":
            return QaValidationOutcome(
                "fail", "stac-binding", f"STAC {key} path differs"
            )
        path = _candidate_path(request, expected_path)
        try:
            if (
                asset.get("file:size") != path.stat().st_size
                or asset.get("checksum:multihash") != f"1220{_sha256(path)}"
            ):
                return QaValidationOutcome(
                    "fail", "stac-binding", f"STAC {key} byte identity differs"
                )
        except OSError:
            return QaValidationOutcome(
                "fail", "stac-binding", f"STAC {key} bytes cannot be read"
            )
    return None


def _public_validator(
    validator_id: str, schema_directory: Path, schema_name: str
) -> ArtifactValidator:
    def validate(request: QaValidationRequest) -> QaValidationOutcome:
        document = _load_json(request.artifact_path)
        try:
            validate_public_document(
                document,
                schema_directory=schema_directory,
                schema_name=schema_name,
            )
        except PublicReleaseContractError as exc:
            return QaValidationOutcome("fail", "json-schema", str(exc))
        binding = _binding_outcome(request, document)
        if binding is not None:
            return binding
        if validator_id == "release.rights":
            rights = _validate_rights(document)
            if rights is not None:
                return rights
        if validator_id == "release.build-receipt":
            build = _build_receipt_binding(document)
            if build is not None:
                return build
        if validator_id.startswith("release.stac."):
            stac = _stac_binding(request, document)
            if stac is not None:
                return stac
        references = _validate_references(request, document)
        if references is not None:
            return references
        return QaValidationOutcome(
            "pass", "public-contract-valid", f"{schema_name} is valid and candidate-bound"
        )

    return validate


def _search_receipt(request: QaValidationRequest) -> QaValidationOutcome:
    document = _load_json(request.artifact_path)
    schema = _load_json(SETTLEMENT_SCHEMA)
    errors = sorted(
        Draft202012Validator(schema).iter_errors(document),
        key=lambda error: list(error.path),
    )
    if errors:
        return QaValidationOutcome("fail", "search-receipt-schema", errors[0].message)
    binding = _binding_outcome(request, document)
    if binding is not None:
        return binding
    try:
        receipt_parent = request.artifact_path.relative_to(
            request.candidate.candidate_root
        ).parent
    except ValueError:
        _fail("search-receipt-binding", "search receipt escapes the candidate")
    observed_paths: set[str] = set()
    for shard in document.get("shards", []):
        if not isinstance(shard, Mapping) or not isinstance(shard.get("path"), str):
            return QaValidationOutcome(
                "fail", "search-receipt-binding", "search shard receipt is malformed"
            )
        logical = (PurePosixPath(receipt_parent.as_posix()) / str(shard["path"])).as_posix()
        observed_paths.add(logical)
        path = _candidate_path(request, logical)
        try:
            if (
                shard.get("byteSize") != path.stat().st_size
                or shard.get("sha256") != _sha256(path)
            ):
                return QaValidationOutcome(
                    "fail", "search-receipt-binding", "search shard bytes differ"
                )
        except OSError:
            return QaValidationOutcome(
                "fail", "search-receipt-binding", "search shard bytes cannot be read"
            )
    expected_paths = {
        "search/europe-core.codepoint-trie.json.br",
        "search/europe-coastal.codepoint-trie.json.br",
    }
    if observed_paths != expected_paths:
        return QaValidationOutcome(
            "fail", "search-receipt-binding", "search receipt shard inventory differs"
        )
    return QaValidationOutcome(
        "pass", "search-receipt-valid", "search receipt is valid and candidate-bound"
    )


def production_json_validator_registry() -> dict[str, ArtifactValidator]:
    """Return JSON validators that require schema, peer bytes, rights, and identity."""
    validators = {
        validator_id: _public_validator(validator_id, schema_directory, schema_name)
        for validator_id, (schema_directory, schema_name) in _PUBLIC_SCHEMAS.items()
    }
    validators["settlements.browser-search-receipt"] = _search_receipt
    return validators
