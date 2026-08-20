from __future__ import annotations

import copy
import hashlib
import inspect
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from searise_pipeline.candidate_completeness import production_validators
from searise_pipeline.candidate_completeness.production_binary_validators import (
    BoundaryQaAuthority,
    ProductionBinaryQaAuthorities,
    ProjectionQaAuthority,
    SettlementQaAuthority,
)
from searise_pipeline.candidate_completeness.production_validators import (
    PRODUCTION_VALIDATOR_IDS,
    ProductionBuildProvenanceAuthority,
    ProductionQaAuthorities,
    production_json_validator_registry,
    production_validator_dispatcher,
)
from searise_pipeline.candidate_completeness.qa_dispatch import (
    CandidateQaContext,
    QaValidationRequest,
)
from searise_pipeline.candidate_completeness.qa_matrix import ArtifactSelector
from searise_pipeline.candidate_completeness.validator import CandidateContractError

ROOT = Path(__file__).resolve().parents[4]
FIXTURES = ROOT / "contracts/release/v1/fixtures/valid"
RELEASE_ID = "searise-europe-v1.0.0-20260812-0123456789ab"
CODE_REVISION = "d53ca2d26bf4e00ef8b32dad3847606dbbaec8f2"
LOCK_SHA256 = "1" * 63 + "2"
PARAMETERS_SHA256 = "2" * 63 + "3"
PIPELINE_SHA256 = "3" * 63 + "4"


def _provenance() -> ProductionBuildProvenanceAuthority:
    return ProductionBuildProvenanceAuthority(
        code_revision=CODE_REVISION,
        environment_lock_path="src/pipeline/test.lock",
        environment_lock_sha256=LOCK_SHA256,
        parameters_sha256=PARAMETERS_SHA256,
        pipeline_identity_sha256=PIPELINE_SHA256,
    )


def _projection_source() -> SimpleNamespace:
    return SimpleNamespace(
        archive_sha256="4" * 63 + "5",
        layers=(
            SimpleNamespace(
                scenario="ssp2-45",
                horizon=2050,
                member_sha256="5" * 63 + "6",
            ),
        ),
    )


def _authorities(tmp_path: Path) -> ProductionQaAuthorities:
    return ProductionQaAuthorities(
        binary=ProductionBinaryQaAuthorities(
            projection=ProjectionQaAuthority(
                source=object(),  # type: ignore[arg-type]
                contract={},
                tippecanoe=tmp_path / "tippecanoe",
                decode=tmp_path / "decode",
                pmtiles=tmp_path / "pmtiles",
                tippecanoe_source=tmp_path / "tippecanoe-source",
                tippecanoe_build_receipt=tmp_path / "tippecanoe-receipt",
                pmtiles_distribution_asset=tmp_path / "pmtiles-asset",
                platform="test-platform",
            ),
            boundary=BoundaryQaAuthority(
                contract={},
                support_geojson=tmp_path / "support.geojson",
                coastal_geojson=tmp_path / "coastal.geojson",
                tools=object(),  # type: ignore[arg-type]
            ),
            settlement=SettlementQaAuthority(
                spatial_database=tmp_path / "spatial.duckdb",
                spatial_receipt=tmp_path / "spatial.receipt.json",
                work_directory=tmp_path / "spatial-work",
            ),
        ),
        brotli=tmp_path / "brotli",
        brotli_sha256="0" * 64,
        work_directory=tmp_path / "search-work",
        provenance=_provenance(),
    )


def _canonical(document: object) -> bytes:
    return (
        json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode()


def _context(candidate: Path) -> CandidateQaContext:
    return CandidateQaContext(
        candidate_root=candidate,
        candidate_id="candidate-phase-1-real-source-20260812-0123456789ab",
        data_release_id=RELEASE_ID,
        data_provenance_class="real-source",
        manifest_sha256=None,
        artifact_count=51,
    )


def _request(
    candidate: Path,
    path: Path,
    *,
    role: str,
    validator_id: str,
    provenance: ProductionBuildProvenanceAuthority | None = None,
    projection_source: object | None = None,
) -> tuple[QaValidationRequest, object]:
    raw = path.read_bytes()
    request = QaValidationRequest(
        artifact_id=path.stem,
        artifact_path=path,
        selector=ArtifactSelector(role, "application/json", "identity"),
        declared_sha256=hashlib.sha256(raw).hexdigest(),
        candidate=_context(candidate),
    )
    return request, production_json_validator_registry(
        provenance=provenance,
        projection_source=projection_source,
    )[validator_id]


def test_public_scenario_contract_requires_candidate_binding(tmp_path: Path) -> None:
    document = json.loads((FIXTURES / "scenario-config.json").read_text())
    document.update(dataReleaseId=RELEASE_ID, dataProvenanceClass="real-source")
    path = tmp_path / "config/scenarios.json"
    path.parent.mkdir(parents=True)
    path.write_bytes(_canonical(document))
    request, validator = _request(
        tmp_path,
        path,
        role="scenario-config",
        validator_id="release.public-contract.scenario-config",
    )
    assert validator(request).status == "pass"

    document["dataReleaseId"] = "searise-europe-v1.0.0-20260812-ffffffffffff"
    path.write_bytes(_canonical(document))
    assert validator(request).code == "json-release-binding"


def test_methodology_reference_is_bound_to_candidate_bytes(tmp_path: Path) -> None:
    scenarios = tmp_path / "config/scenarios.json"
    scenarios.parent.mkdir(parents=True)
    scenarios.write_bytes(b"candidate scenario bytes\n")
    document = json.loads((FIXTURES / "methodology.json").read_text())
    document.update(dataReleaseId=RELEASE_ID, dataProvenanceClass="real-source")
    document["configuration"] = {
        "path": "config/scenarios.json",
        "sha256": hashlib.sha256(scenarios.read_bytes()).hexdigest(),
    }
    path = tmp_path / "config/methodology.json"
    path.write_bytes(_canonical(document))
    request, validator = _request(
        tmp_path,
        path,
        role="methodology",
        validator_id="release.public-contract.methodology",
    )
    assert validator(request).status == "pass"
    document["configuration"]["sha256"] = "0" * 64
    path.write_bytes(_canonical(document))
    assert validator(request).code == "json-reference-binding"


def test_build_receipt_covers_exact_pre_terminal_inventory(tmp_path: Path) -> None:
    inventory = json.loads(
        (ROOT / "contracts/candidate-completeness/v2/required-artifacts.json").read_text()
    )["requiredArtifacts"]
    document = json.loads((FIXTURES / "build-receipt.json").read_text())
    document.update(dataReleaseId=RELEASE_ID, dataProvenanceClass="real-source")
    document["$schema"] = (
        "https://artemsemdev.github.io/SeaRise-Europe/contracts/"
        "release/v2/build-receipt.schema.json"
    )
    document["schemaVersion"] = "2.0.0"
    outputs = []
    source_receipts = []
    for artifact in inventory[:51]:
        if artifact["role"] == "build-receipt":
            continue
        artifact_path = tmp_path / artifact["path"]
        artifact_path.parent.mkdir(parents=True, exist_ok=True)
        artifact_path.write_bytes(f"bytes for {artifact['artifactId']}\n".encode())
        digest = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
        outputs.append(
            {
                "path": artifact["path"],
                "role": artifact["role"],
                "mediaType": artifact["mediaType"],
                "byteSize": artifact_path.stat().st_size,
                "sha256": digest,
            }
        )
        if artifact["role"] == "source-receipt":
            source_receipts.append({"path": artifact["path"], "sha256": digest})
    document["outputs"] = outputs
    document["sourceReceipts"] = source_receipts
    authority = _provenance()
    document["codeRevision"] = authority.code_revision
    document["environment"]["lock"] = {
        "path": authority.environment_lock_path,
        "sha256": authority.environment_lock_sha256,
    }
    document["inputs"] = [
        {
            "path": "contracts/candidate-completeness/v2/required-artifacts.json",
            "sha256": hashlib.sha256(
                (ROOT / "contracts/candidate-completeness/v2/required-artifacts.json").read_bytes()
            ).hexdigest(),
        }
    ]
    document["parametersSha256"] = authority.parameters_sha256
    document["tools"] = [
        {
            "name": "searise-pipeline",
            "version": authority.pipeline_version,
            "identitySha256": authority.pipeline_identity_sha256,
        }
    ]
    path = tmp_path / "receipts/build.json"
    path.write_bytes(_canonical(document))
    request, validator = _request(
        tmp_path,
        path,
        role="build-receipt",
        validator_id="release.build-receipt",
        provenance=authority,
    )
    assert validator(request).status == "pass"

    removed_output = document["outputs"].pop()
    path.write_bytes(_canonical(document))
    assert validator(request).code == "build-output-binding"

    document["outputs"].append(removed_output)
    document["codeRevision"] = "f" * 40
    path.write_bytes(_canonical(document))
    assert validator(request).code == "build-provenance-binding"


def test_rights_must_cover_every_inventory_attribution_and_role(tmp_path: Path) -> None:
    inventory = json.loads(
        (ROOT / "contracts/candidate-completeness/v2/required-artifacts.json").read_text()
    )
    coverage: dict[str, set[str]] = {}
    for artifact in inventory["requiredArtifacts"]:
        for attribution_id in artifact["attributionIds"]:
            coverage.setdefault(attribution_id, set()).add(artifact["role"])
    records = []
    for attribution_id, roles in sorted(coverage.items()):
        records.append(
            {
                "attributionId": attribution_id,
                "sourceId": f"source/{attribution_id}",
                "title": attribution_id,
                "sourceUrl": "https://example.com/source",
                "sourceSha256": "a" * 64,
                "licence": {
                    "name": "Creative Commons Attribution 4.0 International",
                    "spdxId": "CC-BY-4.0",
                    "url": "https://creativecommons.org/licenses/by/4.0/",
                },
                "attributionText": f"Attribution for {attribution_id}.",
                "redistribution": "allowed",
                "appliesToRoles": sorted(roles),
            }
        )
    document = {
        "$schema": (
            "https://artemsemdev.github.io/SeaRise-Europe/contracts/"
            "release/v2/attribution.schema.json"
        ),
        "schemaVersion": "2.0.0",
        "dataReleaseId": RELEASE_ID,
        "dataProvenanceClass": "real-source",
        "records": records,
    }
    path = tmp_path / "config/source-attribution.json"
    path.parent.mkdir(parents=True)
    path.write_bytes(_canonical(document))
    request, validator = _request(
        tmp_path,
        path,
        role="source-attribution",
        validator_id="release.rights",
    )
    assert validator(request).status == "pass"

    incomplete = copy.deepcopy(document)
    incomplete["records"].pop()
    path.write_bytes(_canonical(incomplete))
    assert validator(request).code == "rights-incomplete"


def test_search_receipt_resolves_shards_relative_to_its_directory(tmp_path: Path) -> None:
    fixture = (
        ROOT / "contracts/settlements/v4/fixtures/valid/"
        "settlement-browser-search-shard-set-receipt.json"
    )
    document = json.loads(fixture.read_text())
    document.update(dataReleaseId=RELEASE_ID, dataProvenanceClass="real-source")
    for shard in document["shards"]:
        path = tmp_path / "search" / shard["path"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(f"compressed {shard['shardId']}\n".encode())
        shard["byteSize"] = path.stat().st_size
        shard["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    path = tmp_path / "search/settlement-browser-search-shards.receipt.json"
    path.write_bytes(_canonical(document))
    request, validator = _request(
        tmp_path,
        path,
        role="settlement-search-receipt",
        validator_id="settlements.browser-search-receipt",
    )
    assert validator(request).status == "pass"

    document["shards"][0]["sha256"] = "0" * 64
    path.write_bytes(_canonical(document))
    assert validator(request).code == "search-receipt-binding"


def test_stac_item_binds_exact_candidate_asset_bytes(tmp_path: Path) -> None:
    document = json.loads((FIXTURES / "stac-item.json").read_text())
    scenario = document["properties"]["searise:scenario"]
    horizon = document["properties"]["searise:horizon"]
    paths = {
        "analysis": f"analysis/{scenario}/{horizon}.tif",
        "visual": f"layers/{scenario}/{horizon}.pmtiles",
        "table": "analysis/projections.parquet",
    }
    for key, relative in paths.items():
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(f"{key} bytes\n".encode())
        document["assets"][key]["href"] = f"../../{relative}"
        document["assets"][key]["file:size"] = path.stat().st_size
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        document["assets"][key]["checksum:multihash"] = f"1220{digest}"
    document["searise:data_release_id"] = RELEASE_ID
    document["searise:data_provenance_class"] = "real-source"
    document["collection"] = f"{RELEASE_ID}-projections"
    source = _projection_source()
    document["properties"]["searise:source_archive_sha256"] = source.archive_sha256
    document["properties"]["searise:source_member_sha256"] = source.layers[0].member_sha256
    path = tmp_path / f"stac/items/{scenario}-{horizon}.json"
    path.parent.mkdir(parents=True)
    path.write_bytes(_canonical(document))
    request, validator = _request(
        tmp_path,
        path,
        role="stac-item",
        validator_id="release.stac.item",
        projection_source=source,
    )
    assert validator(request).status == "pass"

    document["assets"]["analysis"]["file:size"] += 1
    path.write_bytes(_canonical(document))
    assert validator(request).code == "stac-binding"

    document["assets"]["analysis"]["file:size"] -= 1
    document["properties"]["searise:source_member_sha256"] = "6" * 64
    path.write_bytes(_canonical(document))
    assert validator(request).code == "stac-source-binding"


def test_stac_catalog_and_collection_bind_the_exact_graph(tmp_path: Path) -> None:
    cases = (
        ("stac-catalog.json", "stac/catalog.json", "stac-catalog", "release.stac.catalog"),
        (
            "stac-collection.json",
            "stac/collection.json",
            "stac-collection",
            "release.stac.collection",
        ),
    )
    for fixture, relative, role, validator_id in cases:
        document = json.loads((FIXTURES / fixture).read_text())
        document["searise:data_release_id"] = RELEASE_ID
        document["searise:data_provenance_class"] = "real-source"
        suffix = "catalog" if role == "stac-catalog" else "projections"
        document["id"] = f"{RELEASE_ID}-{suffix}"
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(_canonical(document))
        request, validator = _request(tmp_path, path, role=role, validator_id=validator_id)
        assert validator(request).status == "pass"
        document["id"] = f"searise-europe-v1.0.0-20260812-ffffffffffff-{suffix}"
        path.write_bytes(_canonical(document))
        assert validator(request).code == "stac-binding"


def test_production_dispatcher_covers_the_complete_closed_matrix(tmp_path: Path) -> None:
    dispatcher = production_validator_dispatcher(_authorities(tmp_path))
    assert set(dispatcher.validator_ids) == PRODUCTION_VALIDATOR_IDS
    assert set(dispatcher.validator_ids) == {
        route.validator_id for route in dispatcher.matrix.routes
    }


def test_production_dispatcher_has_no_runtime_registry_input() -> None:
    assert production_validator_dispatcher.__module__ == (
        "searise_pipeline.candidate_completeness.production_validators"
    )
    assert tuple(inspect.signature(production_validator_dispatcher).parameters) == (
        "authorities",
    )


@pytest.mark.parametrize(
    "module_name",
    ["searise_pipeline.domain.result_state", "external.runtime.plugin"],
)
def test_production_dispatcher_rejects_uncommitted_validator_modules(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    module_name: str,
) -> None:
    original = production_validators.production_json_validator_registry

    def injected_registry(**kwargs: object):  # type: ignore[no-untyped-def]
        registry = original(**kwargs)

        def injected(_request: QaValidationRequest):  # type: ignore[no-untyped-def]
            return None

        injected.__module__ = module_name
        registry["release.public-contract.scenario-config"] = injected
        return registry

    monkeypatch.setattr(
        production_validators,
        "production_json_validator_registry",
        injected_registry,
    )

    with pytest.raises(CandidateContractError, match="validators are untrusted"):
        production_validator_dispatcher(_authorities(tmp_path))
