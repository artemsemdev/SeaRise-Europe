from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any, Callable

import pytest

from searise_pipeline.candidate_completeness.provenance import (
    BUILD_TYPE,
    BUILDER_ID,
    POLICY_IDENTITY,
    PREDICATE_TYPE,
    STATEMENT_TYPE,
    ProvenanceContractError,
    canonical_provenance_bytes,
    generate_provenance_statement,
    validate_provenance_statement,
)

ROOT = Path(__file__).resolve().parents[4]
CANDIDATE_FIXTURE = (
    ROOT / "contracts/candidate-completeness/v1/fixtures/valid/engineering-candidate.json"
)
BUILD_FIXTURE = ROOT / "contracts/release/v1/fixtures/valid/build-receipt.json"
SOURCE_FIXTURE = ROOT / "contracts/release/v1/fixtures/valid/source-receipt.json"
INVOCATION = "https://github.com/artemsemdev/SeaRise-Europe/actions/runs/77777777777/attempts/1"
OUTPUT_ROLES = {"projection-analysis-cog", "projection-geoparquet", "projection-visual-pmtiles"}


def _read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _documents() -> tuple[dict[str, Any], dict[str, Any]]:
    candidate = _read(CANDIDATE_FIXTURE)
    build = _read(BUILD_FIXTURE)
    build["dataReleaseId"] = candidate["dataReleaseId"]
    build["dataProvenanceClass"] = candidate["dataProvenanceClass"]
    build["sourceReceipts"] = [
        {"path": item["path"], "sha256": item["sha256"]}
        for item in candidate["artifacts"]
        if item["role"] == "source-receipt"
    ]
    build["outputs"] = [
        {key: item[key] for key in ("path", "role", "mediaType", "byteSize", "sha256")}
        for item in candidate["artifacts"]
        if item["role"] in OUTPUT_ROLES
    ]
    return candidate, build


def _write_pair(
    root: Path,
    candidate: dict[str, Any],
    build: dict[str, Any],
    *,
    bind_build: bool = True,
    bind_size: bool = True,
) -> tuple[Path, Path]:
    root.mkdir(parents=True, exist_ok=True)
    artifacts = {item["path"]: item for item in candidate["artifacts"]}
    checksums = {item["path"]: item for item in candidate["checksumInventory"]["subjects"]}
    for index, item in enumerate(build["sourceReceipts"]):
        receipt = _read(SOURCE_FIXTURE)
        receipt.update(
            dataReleaseId=candidate["dataReleaseId"],
            dataProvenanceClass=candidate["dataProvenanceClass"],
            receiptId=f"source-fixture-{index:012x}",
            sourceId=f"fixture/source-{index}",
            sourceVersion=f"fixture-{index}",
            sourceUrl=f"https://fixtures.searise.invalid/source-{index}.bin",
            byteSize=index + 1,
            sha256=f"{index + 1:064x}",
            attributionId=artifacts[item["path"]]["rights"]["attributionIds"][0],
        )
        receipt["cache"]["key"] = f"sha256/{receipt['sha256']}"
        raw = canonical_provenance_bytes(receipt)
        source_path = root / item["path"]
        source_path.parent.mkdir(parents=True, exist_ok=True)
        source_path.write_bytes(raw)
        item["sha256"] = hashlib.sha256(raw).hexdigest()
        artifacts[item["path"]].update(sha256=item["sha256"], byteSize=len(raw))
        checksums[item["path"]]["sha256"] = item["sha256"]

    build_path = root / "receipts/build.json"
    build_path.parent.mkdir(parents=True, exist_ok=True)
    build_bytes = (
        json.dumps(build, allow_nan=False, separators=(",", ":"), sort_keys=True) + "\n"
    ).encode()
    build_path.write_bytes(build_bytes)
    if bind_build:
        digest = hashlib.sha256(build_bytes).hexdigest()
        build_artifact = next(
            item for item in candidate["artifacts"] if item["role"] == "build-receipt"
        )
        build_artifact["sha256"] = digest
        if bind_size:
            build_artifact["byteSize"] = len(build_bytes)
        checksum_subject = next(
            item
            for item in candidate["checksumInventory"]["subjects"]
            if item["path"] == build_artifact["path"]
        )
        checksum_subject["sha256"] = digest
    manifest_path = root / "manifest.json"
    manifest_path.write_text(json.dumps(candidate, indent=2) + "\n", encoding="utf-8")
    return manifest_path, build_path


def _valid_pair(tmp_path: Path) -> tuple[Path, Path]:
    return _write_pair(tmp_path, *_documents())


def _statement(manifest: Path, build: Path) -> dict[str, Any]:
    return generate_provenance_statement(
        manifest,
        build,
        trusted_invocation_uri=INVOCATION,
    )


def _write_statement(path: Path, statement: dict[str, Any]) -> None:
    path.write_bytes(canonical_provenance_bytes(statement))


def test_statement_is_exact_slsa_v1_and_deterministic(tmp_path: Path) -> None:
    manifest, build = _valid_pair(tmp_path)
    first = _statement(manifest, build)
    definition = first["predicate"]["buildDefinition"]
    internal = definition["internalParameters"]
    manifest_digest = hashlib.sha256(manifest.read_bytes()).hexdigest()

    assert first == _statement(manifest, build)
    assert first["_type"] == STATEMENT_TYPE == "https://in-toto.io/Statement/v1"
    assert first["predicateType"] == PREDICATE_TYPE == "https://slsa.dev/provenance/v1"
    subjects = first["subject"]
    assert [item["name"] for item in subjects] == sorted(item["name"] for item in subjects)
    expected_outputs = [
        {"name": item["path"], "digest": {"sha256": item["sha256"]}}
        for item in _read(manifest)["artifacts"]
        if item["role"] in OUTPUT_ROLES
    ]
    assert subjects[:-1] == sorted(expected_outputs, key=lambda item: item["name"])
    assert {"name": "manifest.json", "digest": {"sha256": manifest_digest}} in subjects
    assert definition["buildType"] == BUILD_TYPE
    assert definition["externalParameters"] == {
        "candidateId": "candidate-phase-1-fixture-20260811-0123456789ab",
        "dataReleaseId": "searise-europe-v1.0.0-20260811-0123456789ab",
        "dataProvenanceClass": "synthetic-fixture",
        "actualManifestSha256": manifest_digest,
    }
    assert internal["policyIdentity"] == POLICY_IDENTITY
    assert internal["parametersSha256"] == "b" * 64
    assert "buildReceipt" not in internal
    assert internal["claims"] == {
        "cryptographicVerification": False,
        "production": False,
        "publication": False,
        "scientific": False,
        "signing": False,
        "syntheticFixture": True,
    }
    assert first["predicate"]["runDetails"] == {
        "builder": {"id": BUILDER_ID},
        "metadata": {
            "invocationId": INVOCATION,
            "startedOn": "2026-08-10T12:01:00Z",
            "finishedOn": "2026-08-10T12:01:01Z",
        },
        "byproducts": [
            {
                "name": "receipts/build.json",
                "digest": {"sha256": hashlib.sha256(build.read_bytes()).hexdigest()},
                "annotations": {"byteSize": len(build.read_bytes())},
            }
        ],
    }
    dependencies = definition["resolvedDependencies"]
    assert [item["uri"] for item in dependencies] == sorted(item["uri"] for item in dependencies)
    assert len(dependencies) == 18
    assert len([item for item in dependencies if item["uri"].startswith("https://fixtures")]) == 7
    source_dependency = next(item for item in dependencies if item["uri"].endswith("/source-0.bin"))
    assert source_dependency["digest"] == {"sha256": f"{1:064x}"}
    assert any(
        item["digest"] == {"gitCommit": "c096aeab4e0994faa7a9d2253b47215ef897dfcb"}
        for item in dependencies
    )
    rendered = canonical_provenance_bytes(first)
    assert rendered.count(b"\n") == 1 and rendered.endswith(b"\n")
    assert "signingIdentity" not in rendered.decode()
    with pytest.raises(ProvenanceContractError, match="provenance-json"):
        canonical_provenance_bytes({"invalid": chr(0xD800)})


def test_canonical_statement_validates_exactly(tmp_path: Path) -> None:
    manifest, build = _valid_pair(tmp_path)
    statement = _statement(manifest, build)
    path = tmp_path / "provenance.intoto.jsonl"
    _write_statement(path, statement)

    assert (
        validate_provenance_statement(
            path,
            manifest,
            build,
            trusted_invocation_uri=INVOCATION,
        )
        == statement
    )


@pytest.mark.parametrize("raw", [b'{"x":1,"x":2}\n', b'{"x":NaN}\n', b"[]\n"])
def test_nonstandard_statement_json_fails(tmp_path: Path, raw: bytes) -> None:
    manifest, build = _valid_pair(tmp_path)
    path = tmp_path / "bad.jsonl"
    path.write_bytes(raw)

    with pytest.raises(ProvenanceContractError, match="provenance-json"):
        validate_provenance_statement(
            path,
            manifest,
            build,
            trusted_invocation_uri=INVOCATION,
        )


@pytest.mark.parametrize(
    "target,raw,code",
    [
        ("manifest", b'{"x":1,"x":2}\n', "candidate-json"),
        ("build", b'{"x":NaN}\n', "build-receipt-json"),
    ],
)
def test_nonstandard_pair_json_fails(tmp_path: Path, target: str, raw: bytes, code: str) -> None:
    manifest, build = _valid_pair(tmp_path)
    (manifest if target == "manifest" else build).write_bytes(raw)

    with pytest.raises(ProvenanceContractError, match=code):
        _statement(manifest, build)


def test_noncanonical_statement_bytes_fail(tmp_path: Path) -> None:
    manifest, build = _valid_pair(tmp_path)
    path = tmp_path / "pretty.json"
    path.write_text(json.dumps(_statement(manifest, build), indent=2) + "\n", encoding="utf-8")

    with pytest.raises(ProvenanceContractError, match="provenance-canonical"):
        validate_provenance_statement(
            path,
            manifest,
            build,
            trusted_invocation_uri=INVOCATION,
        )


@pytest.mark.parametrize(
    "mutation,code",
    [
        (
            lambda candidate, build: build.__setitem__(
                "dataReleaseId", "searise-europe-v1.0.0-20260811-deadbeefcafe"
            ),
            "candidate-build-identity",
        ),
        (lambda candidate, build: build["sourceReceipts"].pop(), "candidate-build-sources"),
        (lambda candidate, build: build["outputs"].pop(), "candidate-build-outputs"),
        (
            lambda candidate, build: build["tools"].append(
                {**build["tools"][0], "identitySha256": "0" * 64}
            ),
            "provenance-dependencies",
        ),
    ],
)
def test_candidate_build_mismatch_fails(
    tmp_path: Path,
    mutation: Callable[[dict[str, Any], dict[str, Any]], None],
    code: str,
) -> None:
    candidate, build = _documents()
    mutation(candidate, build)
    manifest, build_path = _write_pair(tmp_path, candidate, build)

    with pytest.raises(ProvenanceContractError, match=code):
        _statement(manifest, build_path)


@pytest.mark.parametrize("bind_build,bind_size", [(False, True), (True, False)])
def test_exact_build_receipt_bytes_are_candidate_bound(
    tmp_path: Path, bind_build: bool, bind_size: bool
) -> None:
    manifest, build = _write_pair(
        tmp_path, *_documents(), bind_build=bind_build, bind_size=bind_size
    )

    with pytest.raises(ProvenanceContractError, match="exact build receipt bytes"):
        _statement(manifest, build)


@pytest.mark.parametrize(
    "mode,code",
    [
        ("schema", "source-receipt-contract"),
        ("hash", "source-receipt-identity"),
    ],
)
def test_source_receipt_bytes_and_schema_are_authoritative(
    tmp_path: Path, mode: str, code: str
) -> None:
    manifest, build = _valid_pair(tmp_path)
    source = tmp_path / _read(build)["sourceReceipts"][0]["path"]
    receipt = _read(source)
    if mode == "schema":
        receipt.pop("sourceId")
    else:
        receipt["sourceVersion"] += "-tampered"
    source.write_bytes(canonical_provenance_bytes(receipt))

    with pytest.raises(ProvenanceContractError, match=code):
        _statement(manifest, build)


def test_real_source_and_untrusted_invocation_are_unsupported(tmp_path: Path) -> None:
    candidate, build = _documents()
    candidate["dataProvenanceClass"] = build["dataProvenanceClass"] = "real-source"
    for artifact in candidate["artifacts"]:
        artifact["dataProvenanceClass"] = "real-source"
    manifest, build_path = _write_pair(tmp_path / "claim", candidate, build)
    with pytest.raises(ProvenanceContractError, match="unsupported-claim"):
        _statement(manifest, build_path)

    manifest, build_path = _valid_pair(tmp_path / "invocation")
    with pytest.raises(ProvenanceContractError, match="trusted-invocation"):
        generate_provenance_statement(
            manifest,
            build_path,
            trusted_invocation_uri="https://github.com/example/actions/runs/1",
        )


@pytest.mark.parametrize(
    "mutation,code",
    [
        (lambda value: value["subject"].clear(), "provenance-subjects"),
        (
            lambda value: value["subject"].append(copy.deepcopy(value["subject"][0])),
            "provenance-subjects",
        ),
        (
            lambda value: value["predicate"]["buildDefinition"]["resolvedDependencies"].pop(),
            "provenance-dependencies",
        ),
        (
            lambda value: value["predicate"]["buildDefinition"]["resolvedDependencies"].append(
                copy.deepcopy(value["predicate"]["buildDefinition"]["resolvedDependencies"][0])
            ),
            "provenance-dependencies",
        ),
        (
            lambda value: value["predicate"]["buildDefinition"]["resolvedDependencies"].reverse(),
            "provenance-dependencies",
        ),
        (
            lambda value: value["predicate"]["buildDefinition"]["externalParameters"].__setitem__(
                "candidateId", "candidate-drift"
            ),
            "provenance-identity",
        ),
        (
            lambda value: value["predicate"]["runDetails"]["metadata"].__setitem__(
                "invocationId", "untrusted"
            ),
            "provenance-identity",
        ),
        (
            lambda value: value["predicate"]["buildDefinition"]["internalParameters"].__setitem__(
                "policyIdentity", "drifted"
            ),
            "provenance-identity",
        ),
        (
            lambda value: value["predicate"]["buildDefinition"]["internalParameters"][
                "claims"
            ].__setitem__("signing", True),
            "provenance-identity",
        ),
    ],
)
def test_statement_mutations_fail_closed(
    tmp_path: Path,
    mutation: Callable[[dict[str, Any]], None],
    code: str,
) -> None:
    manifest, build = _valid_pair(tmp_path)
    statement = _statement(manifest, build)
    mutation(statement)
    path = tmp_path / "mutated.intoto.jsonl"
    _write_statement(path, statement)

    with pytest.raises(ProvenanceContractError, match=code):
        validate_provenance_statement(
            path,
            manifest,
            build,
            trusted_invocation_uri=INVOCATION,
        )
