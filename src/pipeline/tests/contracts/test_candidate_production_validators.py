from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

from searise_pipeline.candidate_completeness.production_validators import (
    production_json_validator_registry,
)
from searise_pipeline.candidate_completeness.qa_dispatch import (
    CandidateQaContext,
    QaValidationRequest,
)
from searise_pipeline.candidate_completeness.qa_matrix import ArtifactSelector

ROOT = Path(__file__).resolve().parents[4]
FIXTURES = ROOT / "contracts/release/v1/fixtures/valid"
RELEASE_ID = "searise-europe-v1.0.0-20260812-0123456789ab"


def _canonical(document: object) -> bytes:
    return (
        json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
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
) -> tuple[QaValidationRequest, object]:
    raw = path.read_bytes()
    request = QaValidationRequest(
        artifact_id=path.stem,
        artifact_path=path,
        selector=ArtifactSelector(role, "application/json", "identity"),
        declared_sha256=hashlib.sha256(raw).hexdigest(),
        candidate=_context(candidate),
    )
    return request, production_json_validator_registry()[validator_id]


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
    path = tmp_path / "receipts/build.json"
    path.write_bytes(_canonical(document))
    request, validator = _request(
        tmp_path,
        path,
        role="build-receipt",
        validator_id="release.build-receipt",
    )
    assert validator(request).status == "pass"

    document["outputs"].pop()
    path.write_bytes(_canonical(document))
    assert validator(request).code == "build-output-binding"


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
        ROOT
        / "contracts/settlements/v4/fixtures/valid/"
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
    path = tmp_path / f"stac/items/{scenario}-{horizon}.json"
    path.parent.mkdir(parents=True)
    path.write_bytes(_canonical(document))
    request, validator = _request(
        tmp_path,
        path,
        role="stac-item",
        validator_id="release.stac.item",
    )
    assert validator(request).status == "pass"

    document["assets"]["analysis"]["file:size"] += 1
    path.write_bytes(_canonical(document))
    assert validator(request).code == "stac-binding"


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
        request, validator = _request(
            tmp_path, path, role=role, validator_id=validator_id
        )
        assert validator(request).status == "pass"
        document["id"] = (
            f"searise-europe-v1.0.0-20260812-ffffffffffff-{suffix}"
        )
        path.write_bytes(_canonical(document))
        assert validator(request).code == "stac-binding"
