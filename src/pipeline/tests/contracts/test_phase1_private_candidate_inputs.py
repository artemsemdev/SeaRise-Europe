from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

from scripts.release import derive_phase1_private_candidate_inputs as module  # noqa: E402


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def test_rewrites_fixture_provenance_to_reviewed_local_authorities(
    tmp_path: Path,
) -> None:
    root = tmp_path / "inputs"
    stac = root / "stac/items/ssp1-26-2030.json"
    architecture = root / "evidence/architecture.json"
    quality = root / "evidence/quality-summary.json"
    attribution = root / "config/source-attribution.json"
    build = root / "receipts/build.json"
    _write(
        stac,
        {
            "properties": {
                "searise:scenario": "ssp1-26",
                "searise:source_archive_sha256": "1" * 64,
                "searise:source_member_sha256": "2" * 64,
            }
        },
    )
    _write(architecture, {"codeRevision": "f" * 40, "generatedAt": "old"})
    _write(
        quality,
        {
            "generatedAt": "old",
            "validations": [
                {"category": category, "evidencePath": f"missing/{category}.json"}
                for category in (
                    "schema",
                    "rights",
                    "hash",
                    "matrix",
                    "projection-parity",
                    "search-reconciliation",
                    "stac",
                    "provenance",
                )
            ],
        },
    )
    _write(
        attribution,
        {
            "records": [
                {
                    "attributionId": "searise-europe-candidate-completeness-v1",
                    "sourceSha256": "0" * 64,
                }
            ]
        },
    )
    outputs = [
        {"path": path.relative_to(root).as_posix(), "byteSize": 0, "sha256": "0" * 64}
        for path in (stac, architecture, quality, attribution)
    ]
    _write(
        build,
        {
            "buildId": "old",
            "codeRevision": "f" * 40,
            "startedAt": "old",
            "completedAt": "old",
            "environment": {},
            "parametersSha256": "b" * 64,
            "tools": [],
            "outputs": outputs,
            "sourceReceipts": [],
        },
    )
    source = {
        "archiveSha256": "a" * 64,
        "memberSha256": {"ssp1-26": "c" * 64},
    }
    revision = "d53ca2d26bf4e00ef8b32dad3847606dbbaec8f2"

    module._rewrite_metadata(
        root,
        source_authority=source,
        code_revision=revision,
        generated_at="2026-08-14T12:00:00Z",
        environment_lock_path="src/pipeline/final.lock",
        environment_lock_sha256="d" * 64,
        parameters_sha256="e" * 64,
        pipeline_identity_sha256="9" * 64,
    )

    stac_document = json.loads(stac.read_text())
    assert stac_document["properties"]["searise:source_archive_sha256"] == "a" * 64
    assert stac_document["properties"]["searise:source_member_sha256"] == "c" * 64
    assert json.loads(architecture.read_text())["codeRevision"] == revision
    assert all(
        not item["evidencePath"].startswith("missing/")
        for item in json.loads(quality.read_text())["validations"]
    )
    expected_contract = hashlib.sha256(module.INVENTORY.read_bytes()).hexdigest()
    assert json.loads(attribution.read_text())["records"][0]["sourceSha256"] == expected_contract
    receipt = json.loads(build.read_text())
    assert receipt["codeRevision"] == revision
    assert receipt["parametersSha256"] == "e" * 64
    for output in receipt["outputs"]:
        output_path = root / output["path"]
        assert output["byteSize"] == output_path.stat().st_size
        assert output["sha256"] == hashlib.sha256(output_path.read_bytes()).hexdigest()
