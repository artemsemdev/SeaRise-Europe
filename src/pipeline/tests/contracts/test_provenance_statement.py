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
INVOCATION = "https://github.com/artemsemdev/SeaRise-Europe/actions/runs/77777777777/attempts/1"


def _read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _documents() -> tuple[dict[str, Any], dict[str, Any]]:
    candidate = _read(CANDIDATE_FIXTURE)
    build = _read(BUILD_FIXTURE)
    build["dataReleaseId"] = candidate["dataReleaseId"]
    build["dataProvenanceClass"] = candidate["dataProvenanceClass"]
    artifacts = {item["path"]: item for item in candidate["artifacts"]}
    build["sourceReceipts"] = [
        {"path": item["path"], "sha256": item["sha256"]}
        for item in candidate["artifacts"]
        if item["role"] == "source-receipt"
    ]
    output = artifacts[build["outputs"][0]["path"]]
    build["outputs"] = [
        {key: output[key] for key in ("path", "role", "mediaType", "byteSize", "sha256")}
    ]
    return candidate, build


def _write_pair(
    root: Path,
    candidate: dict[str, Any],
    build: dict[str, Any],
    *,
    bind_build: bool = True,
) -> tuple[Path, Path]:
    root.mkdir(parents=True, exist_ok=True)
    build_path = root / "build.json"
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
    assert first["subject"] == [{"name": "manifest.json", "digest": {"sha256": manifest_digest}}]
    assert definition["buildType"] == BUILD_TYPE
    assert definition["externalParameters"] == {
        "candidateId": "candidate-phase-1-fixture-20260811-0123456789ab",
        "dataReleaseId": "searise-europe-v1.0.0-20260811-0123456789ab",
        "dataProvenanceClass": "synthetic-fixture",
        "actualManifestSha256": manifest_digest,
    }
    assert internal["policyIdentity"] == POLICY_IDENTITY
    assert internal["buildReceipt"]["parametersSha256"] == "b" * 64
    assert internal["buildReceipt"]["sha256"] == hashlib.sha256(build.read_bytes()).hexdigest()
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
    }
    dependencies = definition["resolvedDependencies"]
    assert [item["uri"] for item in dependencies] == sorted(item["uri"] for item in dependencies)
    assert len(dependencies) == 11
    assert any(
        item["digest"] == {"gitCommit": "c096aeab4e0994faa7a9d2253b47215ef897dfcb"}
        for item in dependencies
    )
    rendered = canonical_provenance_bytes(first)
    assert rendered.count(b"\n") == 1 and rendered.endswith(b"\n")
    assert "signingIdentity" not in rendered.decode()


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
        (
            lambda candidate, build: build["outputs"][0].__setitem__("sha256", "0" * 64),
            "candidate-build-outputs",
        ),
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


def test_exact_build_receipt_bytes_are_candidate_bound(tmp_path: Path) -> None:
    manifest, build = _write_pair(tmp_path, *_documents(), bind_build=False)

    with pytest.raises(ProvenanceContractError, match="exact build receipt bytes"):
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
        (lambda value: value.__setitem__("_type", "unsupported"), "provenance-identity"),
        (
            lambda value: value["predicate"]["buildDefinition"]["externalParameters"].__setitem__(
                "candidateId", "candidate-drift"
            ),
            "provenance-identity",
        ),
        (
            lambda value: value["predicate"]["buildDefinition"].__setitem__(
                "buildType", "unapproved"
            ),
            "provenance-identity",
        ),
        (
            lambda value: value["predicate"]["runDetails"]["builder"].__setitem__(
                "id", "future-signing-identity"
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
