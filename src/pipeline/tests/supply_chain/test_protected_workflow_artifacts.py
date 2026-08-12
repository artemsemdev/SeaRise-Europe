"""Executable adversarial tests for protected-workflow artifact boundaries."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from searise_pipeline.supply_chain.protected_workflow_artifacts import (
    CONTROLLED_WORKFLOW_NAME,
    CONTROLLED_WORKFLOW_PATH,
    REPOSITORY,
    REPOSITORY_ID,
    CandidateArtifactAuthority,
    ProtectedWorkflowArtifactError,
    extract_protected_candidate,
    extract_protected_evidence,
    load_candidate_artifact_authority,
    validate_candidate_artifact_authority,
    write_candidate_artifact_authority,
)

REPO_ROOT = Path(__file__).parents[4]
SCRIPT = REPO_ROOT / "scripts/release/validate_supply_chain_contract.py"
REVISION = "a" * 40
PROFILE = "regional"
RUN_ID = 12345
WORKFLOW_ID = 991
ARTIFACT_ID = 777
SHA = "b" * 64
EVIDENCE_FILES = {
    "evidence-envelope.json",
    "manifest.sigstore.json",
    "provenance.intoto.jsonl",
    "provenance.sigstore.json",
    "sbom/build-plane.cdx.json",
    "sbom/frontend-npm.cdx.json",
    "sbom/nuget/searise-api-net8.0.cdx.json",
    "sbom/nuget/searise-application-net8.0.cdx.json",
    "sbom/nuget/searise-domain-net8.0.cdx.json",
    "sbom/nuget/searise-infrastructure-net8.0.cdx.json",
    "sbom/python-release-linux-x86-64-cp311.cdx.json",
    "sbom/python-release-macos-arm64-cp311.cdx.json",
    "sbom/python-settlement-spatial-linux-x86-64-cp311.cdx.json",
    "sbom/python-settlement-spatial-macos-arm64-cp311.cdx.json",
}


def _dump(path: Path, document: object) -> None:
    path.write_text(json.dumps(document), encoding="utf-8")


def _run() -> dict[str, object]:
    return {
        "id": RUN_ID,
        "workflow_id": WORKFLOW_ID,
        "run_attempt": 1,
        "event": "workflow_dispatch",
        "status": "completed",
        "conclusion": "success",
        "head_branch": "master",
        "head_sha": REVISION,
        "path": CONTROLLED_WORKFLOW_PATH,
        "name": CONTROLLED_WORKFLOW_NAME,
        "pull_requests": [],
        "repository": {"id": REPOSITORY_ID, "full_name": REPOSITORY},
        "head_repository": {"id": REPOSITORY_ID, "full_name": REPOSITORY},
        "untrusted_extra": "ignored",
    }


def _artifact(*, size: int = 123, digest: str = f"sha256:{SHA}") -> dict[str, object]:
    api = f"https://api.github.com/repos/{REPOSITORY}/actions/artifacts/{ARTIFACT_ID}"
    return {
        "id": ARTIFACT_ID,
        "name": f"offline-release-{PROFILE}-{REVISION}-{RUN_ID}",
        "expired": False,
        "size_in_bytes": size,
        "digest": digest,
        "url": api,
        "archive_download_url": f"{api}/zip",
        "workflow_run": {
            "id": RUN_ID,
            "repository_id": REPOSITORY_ID,
            "head_repository_id": REPOSITORY_ID,
            "head_branch": "master",
            "head_sha": REVISION,
        },
        "untrusted_extra": "ignored",
    }


def _inventory(artifact: dict[str, object] | None = None) -> dict[str, object]:
    return {"total_count": 1, "artifacts": [artifact or _artifact()]}


def _validate(tmp_path: Path, run=None, inventory=None) -> CandidateArtifactAuthority:
    run_path = tmp_path / "run.json"
    artifacts_path = tmp_path / "artifacts.json"
    _dump(run_path, _run() if run is None else run)
    _dump(artifacts_path, _inventory() if inventory is None else inventory)
    return validate_candidate_artifact_authority(
        run_path,
        artifacts_path,
        profile=PROFILE,
        source_revision=REVISION,
        candidate_run_id=RUN_ID,
    )


def _zip(path: Path, files: dict[str, bytes], directories: tuple[str, ...] = ()) -> None:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for directory in directories:
            archive.writestr(f"{directory}/", b"")
        for name, content in files.items():
            archive.writestr(name, content)


def _authority_for_archive(tmp_path: Path, archive: Path) -> Path:
    authority = CandidateArtifactAuthority(
        profile=PROFILE,
        source_revision=REVISION,
        workflow_id=WORKFLOW_ID,
        run_id=RUN_ID,
        artifact_id=ARTIFACT_ID,
        artifact_name=f"offline-release-{PROFILE}-{REVISION}-{RUN_ID}",
        artifact_sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),
        artifact_byte_size=archive.stat().st_size,
    )
    path = tmp_path / "authority.json"
    write_candidate_artifact_authority(path, authority)
    return path


def _output(path: str = "output.bin") -> dict[str, object]:
    return {"path": path, "byteSize": 1, "sha256": hashlib.sha256(b"x").hexdigest()}


def _candidate_documents(*, dispatch_change=None, execution_change=None, build_change=None):
    output = _output()
    stages = [
        {
            "stage": stage,
            "stageKeySha256": "c" * 64,
            "cacheStatus": "miss",
            "durationSeconds": 0.1,
            "outputs": [output],
            "warnings": [],
            "qualityResults": {},
        }
        for stage in (
            "verify-sources",
            "inspect",
            "normalize",
            "derive",
            "package",
            "validate",
            "assemble-release",
        )
    ]
    encoded = json.dumps(
        [output], ensure_ascii=False, allow_nan=False, separators=(",", ":"), sort_keys=True
    ).encode()
    dispatch = {
        "schemaVersion": 1,
        "profile": PROFILE,
        "sourceRevision": REVISION,
        "reviewedInput": {
            "runId": "12",
            "artifactName": "reviewed-input",
            "bundleSha256": "d" * 64,
        },
        "releaseDate": "20260812",
        "receiptTimestamps": {
            "startedAt": "2026-08-12T10:00:00Z",
            "completedAt": "2026-08-12T10:00:01Z",
        },
        "workflowRunId": str(RUN_ID),
        "publicationAttempted": False,
        "activationAttempted": False,
    }
    execution = {
        "schemaVersion": 1,
        "receiptType": "offline-build-execution",
        "buildId": "build-regional-123456789abc",
        "planIdentitySha256": "e" * 64,
        "dataReleaseId": "searise-europe-v1.0.0-20260812-123456789abc",
        "profile": PROFILE,
        "networkAccess": "disabled",
        "status": "complete",
        "stages": stages,
        "finalOutputs": [output],
        "candidate": {
            "fileCount": 1,
            "byteSize": 1,
            "inventorySha256": hashlib.sha256(encoded).hexdigest(),
        },
        "resourceUsage": {"totalDurationSeconds": 1.0, "peakProcessRssBytes": 1},
    }
    build = {
        "$schema": "https://artemsemdev.github.io/SeaRise-Europe/contracts/release/v1/build-receipt.schema.json",
        "schemaVersion": "1.0.0",
        "dataReleaseId": execution["dataReleaseId"],
        "dataProvenanceClass": "real-source",
        "buildId": execution["buildId"],
        "codeRevision": REVISION,
        "buildMode": "offline",
        "networkAccess": "disabled",
        "startedAt": dispatch["receiptTimestamps"]["startedAt"],
        "completedAt": dispatch["receiptTimestamps"]["completedAt"],
        "environment": {
            "platform": "linux",
            "architecture": "x86_64",
            "pythonVersion": "3.11.15",
            "lock": {"path": "requirements.lock", "sha256": "f" * 64},
        },
        "tools": [{"name": "python", "version": "3.11.15", "identitySha256": "1" * 64}],
        "sourceReceipts": [{"path": "receipts/source.json", "sha256": "2" * 64}],
        "inputs": [{"path": "inputs/source.bin", "sha256": "3" * 64}],
        "parametersSha256": "4" * 64,
        "outputs": [
            {
                **output,
                "role": "projection-analysis-cog",
                "mediaType": "image/tiff; application=geotiff; profile=cloud-optimized",
            }
        ],
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
    if dispatch_change:
        dispatch_change(dispatch)
    if execution_change:
        execution_change(execution)
    if build_change:
        build_change(build)
    return dispatch, execution, build


def _candidate_archive(tmp_path: Path, **changes) -> Path:
    dispatch, execution, build = _candidate_documents(**changes)
    path = tmp_path / "candidate.zip"
    _zip(
        path,
        {
            "dispatch.json": json.dumps(dispatch).encode(),
            "execution.json": json.dumps(execution).encode(),
            "candidate/manifest.json": b"{}",
            "candidate/receipts/build.json": json.dumps(build).encode(),
        },
    )
    return path


def test_atomic_authority_binds_exact_run_repository_and_complete_inventory(tmp_path: Path) -> None:
    authority = _validate(tmp_path)

    assert authority == CandidateArtifactAuthority(
        profile=PROFILE,
        source_revision=REVISION,
        workflow_id=WORKFLOW_ID,
        run_id=RUN_ID,
        artifact_id=ARTIFACT_ID,
        artifact_name=f"offline-release-{PROFILE}-{REVISION}-{RUN_ID}",
        artifact_sha256=SHA,
        artifact_byte_size=123,
    )
    assert authority.production is authority.publication is authority.scientific_approval is False


def test_authority_value_object_cannot_broaden_or_alias_false_claims() -> None:
    values = {
        "profile": PROFILE,
        "source_revision": REVISION,
        "workflow_id": WORKFLOW_ID,
        "run_id": RUN_ID,
        "artifact_id": ARTIFACT_ID,
        "artifact_name": f"offline-release-{PROFILE}-{REVISION}-{RUN_ID}",
        "artifact_sha256": SHA,
        "artifact_byte_size": 123,
    }

    with pytest.raises(ProtectedWorkflowArtifactError, match="forbidden claim"):
        CandidateArtifactAuthority(**values, production=True)
    with pytest.raises(ProtectedWorkflowArtifactError, match="forbidden claim"):
        CandidateArtifactAuthority(**values, publication=0)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("id", RUN_ID + 1),
        ("run_attempt", 2),
        ("event", "pull_request"),
        ("status", "in_progress"),
        ("conclusion", "failure"),
        ("head_branch", "feature"),
        ("head_sha", "0" * 40),
        ("path", ".github/workflows/other.yml"),
        ("name", "Other workflow"),
        ("pull_requests", [{}]),
        ("workflow_id", 0),
    ],
)
def test_authority_rejects_run_identity_or_state_drift(tmp_path: Path, field: str, value) -> None:
    run = _run()
    run[field] = value

    with pytest.raises(ProtectedWorkflowArtifactError):
        _validate(tmp_path, run=run)


@pytest.mark.parametrize("repository_field", ["repository", "head_repository"])
@pytest.mark.parametrize(
    "repository",
    [
        {"id": REPOSITORY_ID + 1, "full_name": REPOSITORY},
        {"id": REPOSITORY_ID, "full_name": "attacker/fork"},
        {"id": True, "full_name": REPOSITORY},
    ],
)
def test_authority_rejects_repository_or_head_repository_drift(
    tmp_path: Path, repository_field: str, repository: dict[str, object]
) -> None:
    run = _run()
    run[repository_field] = repository

    with pytest.raises(ProtectedWorkflowArtifactError):
        _validate(tmp_path, run=run)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("id", 0),
        ("name", "unexpected"),
        ("expired", True),
        ("size_in_bytes", 0),
        ("digest", "sha256:" + "A" * 64),
        ("url", "https://api.github.com/repos/attacker/fork/actions/artifacts/777"),
        ("archive_download_url", "https://example.invalid/archive.zip"),
    ],
)
def test_authority_rejects_artifact_identity_drift(tmp_path: Path, field: str, value) -> None:
    artifact = _artifact()
    artifact[field] = value

    with pytest.raises(ProtectedWorkflowArtifactError):
        _validate(tmp_path, inventory=_inventory(artifact))


@pytest.mark.parametrize(
    "inventory",
    [
        {"total_count": 0, "artifacts": []},
        {"total_count": 2, "artifacts": [_artifact()]},
        {"total_count": 1, "artifacts": [_artifact(), _artifact()]},
    ],
)
def test_authority_rejects_incomplete_or_extra_inventory(tmp_path: Path, inventory) -> None:
    with pytest.raises(ProtectedWorkflowArtifactError):
        _validate(tmp_path, inventory=inventory)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("id", RUN_ID + 1),
        ("repository_id", REPOSITORY_ID + 1),
        ("head_repository_id", REPOSITORY_ID + 1),
        ("head_branch", "feature"),
        ("head_sha", "0" * 40),
        ("extra", "forbidden"),
    ],
)
def test_authority_rejects_artifact_workflow_run_drift(tmp_path: Path, field: str, value) -> None:
    artifact = _artifact()
    artifact["workflow_run"][field] = value  # type: ignore[index]

    with pytest.raises(ProtectedWorkflowArtifactError):
        _validate(tmp_path, inventory=_inventory(artifact))


def test_authority_rejects_duplicate_json_keys_and_nonfinite_values(tmp_path: Path) -> None:
    run_path = tmp_path / "run.json"
    inventory_path = tmp_path / "inventory.json"
    run_path.write_text('{"id":12345,"id":12345}', encoding="utf-8")
    _dump(inventory_path, _inventory())

    with pytest.raises(ProtectedWorkflowArtifactError, match="duplicate"):
        validate_candidate_artifact_authority(
            run_path,
            inventory_path,
            profile=PROFILE,
            source_revision=REVISION,
            candidate_run_id=RUN_ID,
        )

    run_path.write_text('{"id":NaN}', encoding="utf-8")
    with pytest.raises(ProtectedWorkflowArtifactError, match="non-finite"):
        validate_candidate_artifact_authority(
            run_path,
            inventory_path,
            profile=PROFILE,
            source_revision=REVISION,
            candidate_run_id=RUN_ID,
        )


def test_authority_metadata_rejects_symlink_and_hardlink(tmp_path: Path) -> None:
    real = tmp_path / "real.json"
    _dump(real, _run())
    linked = tmp_path / "linked.json"
    os.link(real, linked)
    inventory_path = tmp_path / "inventory.json"
    _dump(inventory_path, _inventory())

    with pytest.raises(ProtectedWorkflowArtifactError, match="one linked"):
        validate_candidate_artifact_authority(
            linked,
            inventory_path,
            profile=PROFILE,
            source_revision=REVISION,
            candidate_run_id=RUN_ID,
        )

    real.unlink()
    target = tmp_path / "target.json"
    _dump(target, _run())
    linked.unlink()
    linked.symlink_to(target)
    with pytest.raises(ProtectedWorkflowArtifactError, match="non-symlink"):
        validate_candidate_artifact_authority(
            linked,
            inventory_path,
            profile=PROFILE,
            source_revision=REVISION,
            candidate_run_id=RUN_ID,
        )


def test_authority_metadata_rejects_symlinked_parent_directory(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    _dump(real / "run.json", _run())
    _dump(real / "inventory.json", _inventory())
    linked = tmp_path / "linked"
    linked.symlink_to(real, target_is_directory=True)

    with pytest.raises(ProtectedWorkflowArtifactError, match="non-symlink"):
        validate_candidate_artifact_authority(
            linked / "run.json",
            real / "inventory.json",
            profile=PROFILE,
            source_revision=REVISION,
            candidate_run_id=RUN_ID,
        )


def test_authority_receipt_is_canonical_immutable_and_false_claimed(tmp_path: Path) -> None:
    authority = _validate(tmp_path)
    receipt = tmp_path / "authority.json"
    write_candidate_artifact_authority(receipt, authority)

    raw = receipt.read_bytes()
    assert raw.endswith(b"\n")
    assert (
        raw
        == (
            json.dumps(json.loads(raw), ensure_ascii=False, separators=(",", ":"), sort_keys=True)
            + "\n"
        ).encode()
    )
    assert json.loads(raw)["claims"] == {
        "production": False,
        "publication": False,
        "scientificApproval": False,
    }
    assert load_candidate_artifact_authority(receipt) == authority
    with pytest.raises(ProtectedWorkflowArtifactError):
        write_candidate_artifact_authority(receipt, authority)


def test_authority_loader_rejects_noncanonical_or_claim_broadening(tmp_path: Path) -> None:
    authority = _validate(tmp_path)
    receipt = tmp_path / "authority.json"
    document = authority.as_document()
    receipt.write_text(json.dumps(document, indent=2), encoding="utf-8")
    with pytest.raises(ProtectedWorkflowArtifactError, match="not canonical"):
        load_candidate_artifact_authority(receipt)

    document["claims"]["production"] = True
    receipt.write_bytes(
        (json.dumps(document, separators=(",", ":"), sort_keys=True) + "\n").encode()
    )
    with pytest.raises(ProtectedWorkflowArtifactError, match="forbidden claim"):
        load_candidate_artifact_authority(receipt)


def test_authority_loader_rejects_boolean_integer_aliases(tmp_path: Path) -> None:
    authority = _validate(tmp_path)
    receipt = tmp_path / "authority.json"
    document = authority.as_document()
    document["run"]["attempt"] = True
    receipt.write_bytes(
        (json.dumps(document, separators=(",", ":"), sort_keys=True) + "\n").encode()
    )

    with pytest.raises(ProtectedWorkflowArtifactError, match="run state"):
        load_candidate_artifact_authority(receipt)


def test_candidate_extractor_streams_exact_archive_and_validates_receipts(tmp_path: Path) -> None:
    archive = _candidate_archive(tmp_path)
    authority = _authority_for_archive(tmp_path, archive)
    output = tmp_path / "candidate-output"

    summary = extract_protected_candidate(archive, output, authority)

    assert summary.run_id == RUN_ID
    assert {item.name for item in output.iterdir()} == {
        "candidate",
        "execution.json",
        "dispatch.json",
    }
    assert not any(path.is_symlink() for path in output.glob("**/*"))
    assert stat.S_IMODE((output / "dispatch.json").stat().st_mode) == 0o400


@pytest.mark.parametrize(
    "change",
    [
        {"dispatch_change": lambda value: value.update(publicationAttempted=True)},
        {"dispatch_change": lambda value: value.update(workflowRunId="999")},
        {"execution_change": lambda value: value.update(status="failed")},
        {"execution_change": lambda value: value.update(networkAccess="enabled")},
        {"execution_change": lambda value: value.update(extra="forbidden")},
        {"build_change": lambda value: value.update(codeRevision="0" * 40)},
        {"build_change": lambda value: value.update(dataProvenanceClass="synthetic-fixture")},
        {"build_change": lambda value: value.update(networkAccess="enabled")},
        {"build_change": lambda value: value.update(extra="forbidden")},
    ],
)
def test_candidate_extractor_rejects_descriptor_drift(tmp_path: Path, change) -> None:
    archive = _candidate_archive(tmp_path, **change)
    authority = _authority_for_archive(tmp_path, archive)

    with pytest.raises(ProtectedWorkflowArtifactError):
        extract_protected_candidate(archive, tmp_path / "output", authority)


def test_candidate_extractor_rejects_wrong_hash_size_and_existing_output(tmp_path: Path) -> None:
    archive = _candidate_archive(tmp_path)
    authority_path = _authority_for_archive(tmp_path, archive)
    authority = load_candidate_artifact_authority(authority_path)
    wrong = CandidateArtifactAuthority(
        **{
            **authority.__dict__,
            "artifact_sha256": "0" * 64,
        }
    )
    wrong_path = tmp_path / "wrong.json"
    write_candidate_artifact_authority(wrong_path, wrong)
    with pytest.raises(ProtectedWorkflowArtifactError, match="SHA-256"):
        extract_protected_candidate(archive, tmp_path / "output-one", wrong_path)

    existing = tmp_path / "existing"
    existing.mkdir()
    with pytest.raises(ProtectedWorkflowArtifactError, match="must not already exist"):
        extract_protected_candidate(archive, existing, authority_path)


@pytest.mark.parametrize("malicious", ["../escape", "/absolute", "a\\b"])
def test_evidence_extractor_rejects_noncanonical_paths(tmp_path: Path, malicious: str) -> None:
    archive = tmp_path / "evidence.zip"
    files = {name: b"{}" for name in EVIDENCE_FILES}
    files[malicious] = b"attack"
    _zip(archive, files)

    with pytest.raises(ProtectedWorkflowArtifactError, match="non-canonical"):
        extract_protected_evidence(
            archive,
            tmp_path / "output",
            expected_sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),
            expected_byte_size=archive.stat().st_size,
        )
    assert not (tmp_path / "escape").exists()


def test_evidence_extractor_rejects_symlink_duplicate_encryption_and_extra(tmp_path: Path) -> None:
    for attack in ("symlink", "duplicate", "encrypted", "extra"):
        archive = tmp_path / f"{attack}.zip"
        with zipfile.ZipFile(archive, "w") as target:
            for name in EVIDENCE_FILES:
                info = zipfile.ZipInfo(name)
                if attack == "symlink" and name == "evidence-envelope.json":
                    info.external_attr = (stat.S_IFLNK | 0o777) << 16
                target.writestr(info, b"{}")
            if attack == "duplicate":
                with pytest.warns(UserWarning, match="Duplicate name"):
                    target.writestr("evidence-envelope.json", b"{}")
            if attack == "extra":
                target.writestr("secret.txt", b"secret")
        if attack == "encrypted":
            raw = bytearray(archive.read_bytes())
            for signature, offset in ((b"PK\x03\x04", 6), (b"PK\x01\x02", 8)):
                header = raw.index(signature)
                flags = int.from_bytes(raw[header + offset : header + offset + 2], "little")
                raw[header + offset : header + offset + 2] = (flags | 1).to_bytes(2, "little")
            archive.write_bytes(raw)
        with pytest.raises(ProtectedWorkflowArtifactError):
            extract_protected_evidence(
                archive,
                tmp_path / f"output-{attack}",
                expected_sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),
                expected_byte_size=archive.stat().st_size,
            )


def test_evidence_extractor_requires_exact_inventory_and_bounded_nonempty_files(
    tmp_path: Path,
) -> None:
    for attack, files in (
        ("missing", {name: b"{}" for name in EVIDENCE_FILES if name != "evidence-envelope.json"}),
        (
            "empty",
            {name: (b"" if name == "evidence-envelope.json" else b"{}") for name in EVIDENCE_FILES},
        ),
        (
            "oversized",
            {
                name: (b"x" * (1024 * 1024 + 1) if name == "evidence-envelope.json" else b"{}")
                for name in EVIDENCE_FILES
            },
        ),
    ):
        archive = tmp_path / f"{attack}.zip"
        _zip(archive, files)
        with pytest.raises(ProtectedWorkflowArtifactError):
            extract_protected_evidence(
                archive,
                tmp_path / f"output-{attack}",
                expected_sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),
                expected_byte_size=archive.stat().st_size,
            )


def test_evidence_extractor_accepts_only_exact_bounded_inventory(tmp_path: Path) -> None:
    archive = tmp_path / "evidence.zip"
    _zip(archive, {name: b"{}" for name in EVIDENCE_FILES})
    output = tmp_path / "output"

    extract_protected_evidence(
        archive,
        output,
        expected_sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),
        expected_byte_size=archive.stat().st_size,
    )

    assert {
        path.relative_to(output).as_posix() for path in output.glob("**/*") if path.is_file()
    } == EVIDENCE_FILES
    assert all(
        stat.S_IMODE(path.stat().st_mode) == 0o400 for path in output.glob("**/*") if path.is_file()
    )


def test_archive_source_rejects_symlink_hardlink_and_size_mismatch(tmp_path: Path) -> None:
    archive = tmp_path / "evidence.zip"
    _zip(archive, {name: b"{}" for name in EVIDENCE_FILES})
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    with pytest.raises(ProtectedWorkflowArtifactError, match="byte size"):
        extract_protected_evidence(
            archive,
            tmp_path / "size-output",
            expected_sha256=digest,
            expected_byte_size=archive.stat().st_size + 1,
        )

    hardlink = tmp_path / "hardlink.zip"
    os.link(archive, hardlink)
    with pytest.raises(ProtectedWorkflowArtifactError, match="one linked"):
        extract_protected_evidence(
            hardlink,
            tmp_path / "hardlink-output",
            expected_sha256=digest,
            expected_byte_size=hardlink.stat().st_size,
        )

    hardlink.unlink()
    symlink = tmp_path / "symlink.zip"
    symlink.symlink_to(archive)
    with pytest.raises(ProtectedWorkflowArtifactError, match="non-symlink"):
        extract_protected_evidence(
            symlink,
            tmp_path / "symlink-output",
            expected_sha256=digest,
            expected_byte_size=archive.stat().st_size,
        )


def test_cli_exposes_atomic_authority_and_both_distinct_extractors(tmp_path: Path) -> None:
    run_path = tmp_path / "run.json"
    inventory_path = tmp_path / "inventory.json"
    output = tmp_path / "authority.json"
    _dump(run_path, _run())
    _dump(inventory_path, _inventory())
    environment = {**os.environ, "PYTHONPATH": str(REPO_ROOT / "src/pipeline")}

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "protected-candidate-authority",
            "--run-json",
            str(run_path),
            "--artifacts-json",
            str(inventory_path),
            "--profile",
            PROFILE,
            "--source-revision",
            REVISION,
            "--candidate-run-id",
            str(RUN_ID),
            "--output",
            str(output),
        ],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )

    assert result.returncode == 0, result.stderr
    assert "production, publication, and scientific approval not claimed" in result.stdout
    assert load_candidate_artifact_authority(output).artifact_id == ARTIFACT_ID
    help_result = subprocess.run(
        [sys.executable, str(SCRIPT), "--help"],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )
    assert "protected-candidate-extract" in help_result.stdout
    assert "protected-evidence-extract" in help_result.stdout


def test_module_uses_no_unsafe_recursive_extraction_helpers() -> None:
    source = (
        REPO_ROOT / "src/pipeline/searise_pipeline/supply_chain/protected_workflow_artifacts.py"
    ).read_text(encoding="utf-8")

    assert ".extractall(" not in source
    assert ".extract(" not in source
    assert ".rglob(" not in source
    assert "shutil" not in source
