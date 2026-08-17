"""Tests for immutable pre-verification production evidence finalization."""

from __future__ import annotations

import base64
import errno
import hashlib
import json
import os
import runpy
import shutil
from pathlib import Path, PurePosixPath
from types import SimpleNamespace
from typing import Mapping

import pytest

import searise_pipeline.supply_chain.production_evidence as production_evidence
from searise_pipeline.candidate_completeness import (
    canonical_provenance_bytes,
    generate_provenance_statement,
)
from searise_pipeline.supply_chain import SupplyChainContractError
from searise_pipeline.supply_chain.production_evidence import finalize_production_evidence
from tests.contracts.test_provenance_statement import _documents, _write_pair
from tests.supply_chain.test_candidate_evidence_pair import ENVELOPE, ROOT, _load

RUN_ID = "77777777777"
CLI = ROOT / "scripts/release/finalize_production_evidence.py"
INVENTORY = ROOT / "contracts/supply-chain/v1/dependency-inventory.json"
POLICY = ROOT / "contracts/supply-chain/v1/identity-policy.json"


@pytest.fixture(autouse=True)
def _private_snapshot_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "private-snapshots"
    root.mkdir(mode=0o700)
    monkeypatch.setattr(production_evidence, "_TEMP_ROOT", root)


def _candidate(root: Path) -> tuple[Path, Path]:
    candidate, build = _documents()
    candidate["dataProvenanceClass"] = build["dataProvenanceClass"] = "real-source"
    for artifact in candidate["artifacts"]:
        artifact["dataProvenanceClass"] = "real-source"
    checksums = {item["path"]: item for item in candidate["checksumInventory"]["subjects"]}
    build_outputs = {item["path"]: item for item in build["outputs"]}
    deferred = {"source-receipt", "build-receipt", "checksums"}
    for artifact in candidate["artifacts"]:
        if artifact["role"] in deferred:
            continue
        raw = f"production-evidence fixture: {artifact['path']}\n".encode()
        target = root / artifact["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
        artifact.update(byteSize=len(raw), sha256=hashlib.sha256(raw).hexdigest())
        checksums[artifact["path"]]["sha256"] = artifact["sha256"]
        if artifact["path"] in build_outputs:
            build_outputs[artifact["path"]].update(
                byteSize=artifact["byteSize"], sha256=artifact["sha256"]
            )
    manifest, build_path = _write_pair(root, candidate, build)
    checksum_raw = "".join(
        f"{item['sha256']}  {item['path']}\n" for item in candidate["checksumInventory"]["subjects"]
    ).encode()
    (root / "checksums.txt").write_bytes(checksum_raw)
    checksum_artifact = next(item for item in candidate["artifacts"] if item["role"] == "checksums")
    checksum_artifact.update(
        byteSize=len(checksum_raw), sha256=hashlib.sha256(checksum_raw).hexdigest()
    )
    manifest.write_text(json.dumps(candidate, indent=2) + "\n", encoding="utf-8")
    return manifest, build_path


def _bundle(path: Path, fixture: str, subject: bytes) -> Path:
    document = _load(ENVELOPE.parent / fixture)
    document["messageSignature"]["messageDigest"]["digest"] = base64.b64encode(
        hashlib.sha256(subject).digest()
    ).decode()
    path.write_text(json.dumps(document, separators=(",", ":"), sort_keys=True) + "\n")
    return path


def _inputs(root: Path) -> tuple[Path, Path, Path]:
    manifest, build = _candidate(root / "candidate")
    provenance = canonical_provenance_bytes(
        generate_provenance_statement(
            manifest,
            build,
            trusted_invocation_uri=(
                f"https://github.com/artemsemdev/SeaRise-Europe/actions/runs/{RUN_ID}/attempts/1"
            ),
        )
    )
    return (
        manifest.parent,
        _bundle(root / "manifest.bundle.json", "manifest.sigstore.json", manifest.read_bytes()),
        _bundle(root / "provenance.bundle.json", "provenance.sigstore.json", provenance),
    )


def _finalize(root: Path) -> object:
    candidate, manifest_bundle, provenance_bundle = _inputs(root)
    return _invoke(candidate, manifest_bundle, provenance_bundle, root / "evidence")


def _invoke(
    candidate: Path,
    manifest_bundle: Path,
    provenance_bundle: Path,
    output: Path,
    *,
    repository: Path = ROOT,
    run_id: str = RUN_ID,
) -> object:
    if repository != ROOT:
        assert production_evidence._FINALIZATION_LOCK.acquire(blocking=False)
        try:
            return production_evidence._finalize_production_evidence(
                candidate,
                repository_root=repository,
                repository_authority_root=repository,
                controlled_build_run_id=run_id,
                manifest_bundle=manifest_bundle.absolute(),
                provenance_bundle=provenance_bundle.absolute(),
                output_root=output.absolute(),
            )
        finally:
            production_evidence._FINALIZATION_LOCK.release()
    return finalize_production_evidence(
        candidate,
        repository_root=repository,
        controlled_build_run_id=run_id,
        manifest_bundle=manifest_bundle.absolute(),
        provenance_bundle=provenance_bundle.absolute(),
        output_root=output.absolute(),
    )


def _cli_args(*paths: Path) -> list[str]:
    candidate, manifest_bundle, provenance_bundle, output = paths
    return [
        "--candidate-root",
        str(candidate),
        "--repository-root",
        str(ROOT),
        "--controlled-build-run-id",
        RUN_ID,
        "--manifest-bundle",
        str(manifest_bundle.absolute()),
        "--provenance-bundle",
        str(provenance_bundle.absolute()),
        "--output-root",
        str(output.absolute()),
    ]


def _minimal_repository(root: Path, inventory: bytes) -> Path:
    policy = root / "contracts/supply-chain/v1/identity-policy.json"
    policy.parent.mkdir(parents=True)
    policy.write_bytes(POLICY.read_bytes())
    (policy.parent / "dependency-inventory.json").write_bytes(inventory)
    return root


def _repository_authority(root: Path) -> Path:
    inventory = _load(INVENTORY)
    paths = {production_evidence._POLICY, production_evidence._DEPENDENCY_INVENTORY}
    paths.update(
        PurePosixPath(item["path"])
        for component in inventory["components"]
        for item in component["inputs"]
    )
    paths.update(
        production_evidence._SBOM_ROOT / PurePosixPath(logical).relative_to("sbom")
        for logical in production_evidence._SBOM_PATHS
    )
    profile = ROOT / "contracts/supply-chain/v2/static-target-profile.json"
    with production_evidence.materialize_historical_dependency_authority(
        profile,
        repository_root=ROOT,
    ) as (historical_root, _historical_inventory):
        for logical in paths:
            target = root.joinpath(*logical.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(historical_root.joinpath(*logical.parts), target)
    return root


def test_finalizes_real_source_evidence_with_only_preverification_nonclaims(tmp_path: Path) -> None:
    summary = _finalize(tmp_path)
    evidence = tmp_path / "evidence"
    envelope = _load(evidence / "evidence-envelope.json")
    provenance = _load(evidence / "provenance.intoto.jsonl")
    published = {
        PurePosixPath(path.relative_to(evidence).as_posix()): path.read_bytes()
        for path in evidence.rglob("*")
        if path.is_file()
    }

    assert summary.evidence_root == evidence.absolute()
    assert summary.evidence_sha256 == production_evidence._evidence_sha256(published)
    assert summary.sbom_count == 10
    assert envelope["dataProvenanceClass"] == "real-source"
    assert envelope["verification"] == {
        "status": "real-source-unverified",
        "fixtureOnly": False,
        "verified": False,
        "policySatisfied": False,
        "productionClaim": False,
        "publicationClaim": False,
        "scientificApproval": False,
        "reason": (
            "Cryptographic verification has not run; no signing, identity, environment, "
            "production, publication, or scientific approval claim is made."
        ),
    }
    assert provenance["predicate"]["buildDefinition"]["internalParameters"]["claims"] == {
        "cryptographicVerification": False,
        "production": False,
        "publication": False,
        "scientific": False,
        "signing": False,
        "syntheticFixture": False,
    }
    assert (evidence / "sbom").is_dir()
    assert len(list((evidence / "sbom").rglob("*.cdx.json"))) == 10


def test_cli_reports_canonical_commit_identity_and_only_nonclaims(
    tmp_path: Path, capfd: pytest.CaptureFixture[str]
) -> None:
    candidate, manifest_bundle, provenance_bundle = _inputs(tmp_path)
    main = runpy.run_path(str(CLI))["main"]
    evidence = (tmp_path / "evidence").absolute()
    assert main(_cli_args(candidate, manifest_bundle, provenance_bundle, evidence)) == 0
    captured = capfd.readouterr()
    result = json.loads(captured.out)
    published = {
        PurePosixPath(path.relative_to(evidence).as_posix()): path.read_bytes()
        for path in evidence.rglob("*")
        if path.is_file()
    }
    assert captured.err == ""
    assert captured.out == json.dumps(
        result, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ) + "\n"
    assert result == {
        "candidateId": _load(candidate / "manifest.json")["candidateId"],
        "cryptographicVerification": False,
        "evidenceRoot": str(evidence),
        "evidenceSha256": production_evidence._evidence_sha256(published),
        "productionClaim": False,
        "provenanceSha256": hashlib.sha256(
            (evidence / "provenance.intoto.jsonl").read_bytes()
        ).hexdigest(),
        "publicationClaim": False,
        "sbomCount": 10,
        "scientificApproval": False,
    }


@pytest.mark.parametrize("failure", ["broken-pipe", "closed-stdout", "flush-failure"])
def test_cli_reporting_failure_cannot_reverse_a_durable_commit(
    failure: str,
    tmp_path: Path,
) -> None:
    candidate, manifest_bundle, provenance_bundle = _inputs(tmp_path)
    namespace = runpy.run_path(str(CLI))
    main, emit = namespace["main"], namespace["_emit_committed_success"]
    cli_os, cli_sys = namespace["os"], namespace["sys"]
    original_write, original_stdout = cli_os.write, cli_sys.stdout
    evidence = (tmp_path / "evidence").absolute()

    class ClosedStdout:
        def fileno(self) -> int:
            raise OSError("injected closed stdout")

    class FlushFailure:
        def fileno(self) -> int:
            return original_stdout.fileno()

        def flush(self) -> None:
            raise OSError("injected flush failure")
    def fail_write(_descriptor: int, _raw: object) -> int:
        raise BrokenPipeError("injected broken pipe")
    def after_commit(summary: object) -> None:
        assert (evidence / "evidence-envelope.json").is_file()
        try:
            if failure == "broken-pipe":
                cli_os.write = fail_write
            elif failure == "closed-stdout":
                cli_sys.stdout = ClosedStdout()
            else:
                cli_sys.stdout = FlushFailure()
            emit(summary)
        finally:
            cli_os.write = original_write
            cli_sys.stdout = original_stdout

    main.__globals__["_emit_committed_success"] = after_commit
    assert main(_cli_args(candidate, manifest_bundle, provenance_bundle, evidence)) == 0
    assert (evidence / "evidence-envelope.json").is_file()


def test_existing_output_is_never_overwritten(tmp_path: Path) -> None:
    candidate, manifest_bundle, provenance_bundle = _inputs(tmp_path)
    output = (tmp_path / "evidence").absolute()
    output.mkdir()
    sentinel = output / "sentinel"
    sentinel.write_text("preserve")
    with pytest.raises(SupplyChainContractError, match="already exists"):
        _invoke(candidate, manifest_bundle, provenance_bundle, output)
    assert sentinel.read_text() == "preserve"


def test_destination_created_during_publish_is_preserved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    candidate, manifest_bundle, provenance_bundle = _inputs(tmp_path)
    output = (tmp_path / "evidence").absolute()
    original = production_evidence._rename_exclusive
    def race(parent: int, source: str, destination: str) -> None:
        os.mkdir(destination, dir_fd=parent)
        (output / "alien").write_text("preserve")
        original(parent, source, destination)
    monkeypatch.setattr(production_evidence, "_rename_exclusive", race)
    with pytest.raises(SupplyChainContractError, match="already exists"):
        _invoke(candidate, manifest_bundle, provenance_bundle, output)
    assert (output / "alien").read_text() == "preserve"


def test_output_parent_swap_fails_and_preserves_replacement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    candidate, manifest_bundle, provenance_bundle = _inputs(tmp_path / "inputs")
    parent, moved = tmp_path / "output", tmp_path / "moved-output"
    parent.mkdir(mode=0o700)
    original = production_evidence._publish
    def swap(*args: object) -> None:
        parent.rename(moved)
        parent.mkdir()
        (parent / "alien").write_text("preserve")
        original(*args)  # type: ignore[arg-type]
    monkeypatch.setattr(production_evidence, "_publish", swap)
    with pytest.raises(SupplyChainContractError, match="parent changed"):
        _invoke(candidate, manifest_bundle, provenance_bundle, parent / "evidence")
    assert (parent / "alien").read_text() == "preserve"


def test_output_parent_swap_after_publish_fails_and_preserves_foreign_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    candidate, manifest_bundle, provenance_bundle = _inputs(tmp_path / "inputs")
    parent, moved = tmp_path / "output", tmp_path / "moved-output"
    parent.mkdir(mode=0o700)
    output = (parent / "evidence").absolute()
    original = production_evidence._rename_exclusive
    def swap(parent_descriptor: int, source: str, destination: str) -> None:
        original(parent_descriptor, source, destination)
        if destination == output.name:
            parent.rename(moved)
            parent.mkdir()
            output.mkdir()
            (output / "alien").write_text("preserve", encoding="utf-8")
    monkeypatch.setattr(production_evidence, "_rename_exclusive", swap)
    with pytest.raises(SupplyChainContractError, match="parent.*changed"):
        _invoke(candidate, manifest_bundle, provenance_bundle, output)
    assert (output / "alien").read_text(encoding="utf-8") == "preserve"
    assert not (output / "evidence-envelope.json").exists()


def test_stage_name_swap_fails_without_deleting_foreign_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    candidate, manifest_bundle, provenance_bundle = _inputs(tmp_path)
    original = production_evidence._publish
    def swap(
        parent: int,
        parent_identity: os.stat_result,
        stage_identity: os.stat_result,
        stage_descriptor: int,
        expected_tree: object,
        baseline: object,
        parent_path: Path,
        stage: str,
        output: str,
    ) -> None:
        os.rename(stage, "retired-stage", src_dir_fd=parent, dst_dir_fd=parent)
        os.mkdir(stage, dir_fd=parent)
        original(
            parent,
            parent_identity,
            stage_identity,
            stage_descriptor,
            expected_tree,
            baseline,
            parent_path,
            stage,
            output,
        )
    monkeypatch.setattr(production_evidence, "_publish", swap)
    with pytest.raises(SupplyChainContractError, match="staging directory changed"):
        _invoke(candidate, manifest_bundle, provenance_bundle, tmp_path / "evidence")
    assert any(path.name.startswith(".evidence-incomplete-") for path in tmp_path.iterdir())


def test_intermediate_symlink_race_preserves_primary_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    candidate, manifest_bundle, provenance_bundle = _inputs(tmp_path)
    foreign = tmp_path / "foreign"
    foreign.mkdir()
    original, injected = production_evidence._snapshot_fd, False
    def race(root: int, logical: PurePosixPath, raw: bytes) -> None:
        nonlocal injected
        if logical.parts[0] == "sbom" and not injected:
            os.symlink(foreign, "sbom", target_is_directory=True, dir_fd=root)
            injected = True
        original(root, logical, raw)
    monkeypatch.setattr(production_evidence, "_snapshot_fd", race)
    with pytest.raises(SupplyChainContractError, match="descriptor-bound evidence stage"):
        _invoke(candidate, manifest_bundle, provenance_bundle, tmp_path / "evidence")
    assert list(foreign.iterdir()) == []


def test_transient_private_snapshot_path_swap_cannot_change_descriptor_consumers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    candidate, manifest_bundle, provenance_bundle = _inputs(tmp_path / "inputs")
    original = production_evidence.generate_provenance_statement
    original_snapshot = production_evidence._new_private_snapshot
    captured: list[Path] = []
    foreign_root = tmp_path / "foreign-snapshot"
    foreign_root.mkdir()
    (foreign_root / "sentinel").write_text("preserve", encoding="utf-8")
    def capture(**kwargs: object) -> tuple[int, str, int, Path, os.stat_result]:
        result = original_snapshot(**kwargs)  # type: ignore[arg-type]
        captured.append(result[3])
        return result
    def swap(manifest_path: Path, receipt_path: Path, **kwargs: object) -> object:
        snapshot_root = captured[0]
        retired = snapshot_root.with_name(snapshot_root.name + "-retired")
        snapshot_root.rename(retired)
        foreign_root.rename(snapshot_root)
        try:
            return original(manifest_path, receipt_path, **kwargs)
        finally:
            snapshot_root.rename(foreign_root)
            retired.rename(snapshot_root)
    monkeypatch.setattr(production_evidence, "_new_private_snapshot", capture)
    monkeypatch.setattr(production_evidence, "generate_provenance_statement", swap)
    _invoke(candidate, manifest_bundle, provenance_bundle, tmp_path / "evidence")
    assert (foreign_root / "sentinel").read_text(encoding="utf-8") == "preserve"


def test_transient_swap_inside_dependency_resolve_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    candidate, manifest_bundle, provenance_bundle = _inputs(tmp_path / "inputs")
    original_snapshot = production_evidence._new_private_snapshot
    original_resolve = Path.resolve
    original_validate = production_evidence.validate_dependency_inventory
    captured: list[Path] = []
    swapped: list[tuple[Path, Path, Path]] = []
    active = False
    def capture(**kwargs: object) -> tuple[int, str, int, Path, os.stat_result]:
        result = original_snapshot(**kwargs)  # type: ignore[arg-type]
        captured.append(result[3])
        return result
    def resolve(path: Path, *args: object, **kwargs: object) -> Path:
        resolved = original_resolve(path, *args, **kwargs)  # type: ignore[arg-type]
        if active and path == Path(".") and not swapped:
            snapshot = captured[0]
            retired = snapshot.with_name(snapshot.name + "-retired")
            foreign = snapshot.with_name(snapshot.name + "-foreign")
            shutil.copytree(snapshot, foreign)
            target = foreign / "repository/src/frontend/package.json"
            target.chmod(0o600)
            target.write_bytes(target.read_bytes() + b" ")
            snapshot.rename(retired)
            foreign.rename(snapshot)
            swapped.append((snapshot, retired, foreign))
        return resolved
    def validate(*args: object, **kwargs: object) -> dict[str, object]:
        nonlocal active
        active = True
        try:
            return original_validate(*args, **kwargs)  # type: ignore[return-value]
        finally:
            active = False
            if swapped:
                snapshot, retired, foreign = swapped[0]
                snapshot.rename(foreign)
                retired.rename(snapshot)
    monkeypatch.setattr(production_evidence, "_new_private_snapshot", capture)
    monkeypatch.setattr(Path, "resolve", resolve)
    monkeypatch.setattr(production_evidence, "validate_dependency_inventory", validate)
    with pytest.raises(SupplyChainContractError, match="dependency input"):
        _invoke(candidate, manifest_bundle, provenance_bundle, tmp_path / "evidence")
    assert not (tmp_path / "evidence").exists()


def test_bad_bundle_leaves_no_final_output(tmp_path: Path) -> None:
    candidate, manifest_bundle, provenance_bundle = _inputs(tmp_path)
    bundle = _load(manifest_bundle)
    bundle["messageSignature"]["messageDigest"]["digest"] = base64.b64encode(b"wrong").decode()
    manifest_bundle.write_text(json.dumps(bundle) + "\n")
    output = (tmp_path / "evidence").absolute()
    with pytest.raises(SupplyChainContractError, match="message digest"):
        _invoke(candidate, manifest_bundle, provenance_bundle, output)
    assert not output.exists()


@pytest.mark.parametrize("run_id", ["0", "01", "run-1", "9" * 21])
def test_invalid_controlled_run_id_fails_before_publication(tmp_path: Path, run_id: str) -> None:
    candidate, manifest_bundle, provenance_bundle = _inputs(tmp_path)
    output = (tmp_path / "evidence").absolute()
    with pytest.raises(SupplyChainContractError, match="canonical positive integer"):
        _invoke(candidate, manifest_bundle, provenance_bundle, output, run_id=run_id)
    assert not output.exists()


def test_valid_but_different_run_id_cannot_rebind_the_provenance_bundle(tmp_path: Path) -> None:
    candidate, manifest_bundle, provenance_bundle = _inputs(tmp_path)
    with pytest.raises(SupplyChainContractError, match="message digest"):
        _invoke(
            candidate,
            manifest_bundle,
            provenance_bundle,
            tmp_path / "evidence",
            run_id=str(int(RUN_ID) + 1),
        )
    assert not (tmp_path / "evidence").exists()


@pytest.mark.parametrize(
    "unsafe",
    ["/tmp/outside", "../outside", "a//b", "a\\b", ".git/config"],
)
def test_unsafe_inventory_path_is_rejected_before_dependency_reads(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    unsafe: str,
) -> None:
    candidate, manifest_bundle, provenance_bundle = _inputs(tmp_path / "inputs")
    inventory = _load(INVENTORY)
    inventory["components"][0]["inputs"][0]["path"] = unsafe
    repository = _minimal_repository(
        tmp_path / "repository",
        (json.dumps(inventory, separators=(",", ":")) + "\n").encode(),
    )
    reads = []
    original = production_evidence._read_bounded
    def track(*args: object, **kwargs: object) -> bytes:
        reads.append(str(args[2]))
        return original(*args, **kwargs)  # type: ignore[arg-type]
    monkeypatch.setattr(production_evidence, "_read_bounded", track)
    with pytest.raises(SupplyChainContractError):
        _invoke(
            candidate,
            manifest_bundle,
            provenance_bundle,
            tmp_path / "evidence",
            repository=repository,
        )
    assert not any(label.startswith(("dependency input", "repository sbom/")) for label in reads)


def test_unrecorded_source_dependency_is_rejected_before_snapshot_use(tmp_path: Path) -> None:
    candidate, manifest_bundle, provenance_bundle = _inputs(tmp_path / "inputs")
    repository = _repository_authority(tmp_path / "repository")
    rogue = repository / ".github/workflows/unrecorded-release.yml"
    rogue.parent.mkdir(parents=True, exist_ok=True)
    rogue.write_text("name: unrecorded\n", encoding="utf-8")
    with pytest.raises(SupplyChainContractError, match="dependency discovery mismatch"):
        _invoke(
            candidate,
            manifest_bundle,
            provenance_bundle,
            tmp_path / "evidence",
            repository=repository,
        )


def test_source_root_replacement_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    candidate, manifest_bundle, provenance_bundle = _inputs(tmp_path / "inputs")
    repository = _repository_authority(tmp_path / "repository")
    moved = tmp_path / "moved-repository"
    original = production_evidence._read_bounded
    injected = False
    def replace_root(*args: object, **kwargs: object) -> bytes:
        nonlocal injected
        raw = original(*args, **kwargs)  # type: ignore[arg-type]
        if not injected and str(args[2]).startswith("dependency input"):
            injected = True
            repository.rename(moved)
            repository.mkdir()
            (repository / "foreign").write_text("preserve", encoding="utf-8")
        return raw
    monkeypatch.setattr(production_evidence, "_read_bounded", replace_root)
    with pytest.raises(SupplyChainContractError, match="repository .* changed"):
        _invoke(
            candidate,
            manifest_bundle,
            provenance_bundle,
            tmp_path / "evidence",
            repository=repository,
        )
    assert (repository / "foreign").read_text(encoding="utf-8") == "preserve"


def test_full_inventory_hash_validation_precedes_sbom_consumption(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    candidate, manifest_bundle, provenance_bundle = _inputs(tmp_path)
    original = production_evidence._read_bounded
    def change_dependency(*args: object, **kwargs: object) -> bytes:
        raw = original(*args, **kwargs)  # type: ignore[arg-type]
        if str(args[2]).endswith("src/frontend/package.json"):
            return raw + b" "
        return raw
    monkeypatch.setattr(production_evidence, "_read_bounded", change_dependency)
    with pytest.raises(SupplyChainContractError, match="SHA-256 mismatch"):
        _invoke(candidate, manifest_bundle, provenance_bundle, tmp_path / "evidence")


def test_tampered_sbom_is_rejected_by_its_merged_authority(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    candidate, manifest_bundle, provenance_bundle = _inputs(tmp_path)
    original = production_evidence._read_bounded
    target = "contracts/supply-chain/v1/sboms/frontend-npm.cdx.json"
    def change_sbom(*args: object, **kwargs: object) -> bytes:
        raw = original(*args, **kwargs)  # type: ignore[arg-type]
        if args[1] == PurePosixPath(target):
            document = json.loads(raw)
            document["metadata"]["component"]["name"] = "substituted-frontend"
            return (json.dumps(document, separators=(",", ":"), sort_keys=True) + "\n").encode()
        return raw
    monkeypatch.setattr(production_evidence, "_read_bounded", change_sbom)
    with pytest.raises(SupplyChainContractError, match="npm SBOM differs"):
        _invoke(candidate, manifest_bundle, provenance_bundle, tmp_path / "evidence")


def test_all_ten_sboms_are_checked_against_merged_authorities(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    candidate, manifest_bundle, provenance_bundle = _inputs(tmp_path)
    validated = []
    original = production_evidence._validate_sbom_authority
    def record(
        logical: str,
        path: Path,
        root: Path,
        dependency_inventory: Path,
    ) -> dict[str, object]:
        validated.append(logical)
        return original(logical, path, root, dependency_inventory)
    monkeypatch.setattr(production_evidence, "_validate_sbom_authority", record)
    _invoke(candidate, manifest_bundle, provenance_bundle, tmp_path / "evidence")
    assert tuple(validated) == production_evidence._SBOM_PATHS * 2


@pytest.mark.parametrize("mutation", ["extra", "missing", "replacement"])
def test_complete_stage_tree_revalidation_rejects_late_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    candidate, manifest_bundle, provenance_bundle = _inputs(tmp_path)
    original = production_evidence._publish
    def mutate(
        parent: int,
        parent_identity: os.stat_result,
        stage_identity: os.stat_result,
        stage_descriptor: int,
        expected_tree: Mapping[PurePosixPath, bytes],
        baseline: object,
        parent_path: Path,
        stage: str,
        output: str,
    ) -> None:
        logical = PurePosixPath("manifest.sigstore.json")
        if mutation == "extra":
            descriptor = os.open(
                "foreign",
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o400,
                dir_fd=stage_descriptor,
            )
            os.close(descriptor)
        else:
            if mutation == "replacement":
                descriptor = os.open(
                    ".distinct-replacement",
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                    0o400,
                    dir_fd=stage_descriptor,
                )
                try:
                    remaining = memoryview(expected_tree[logical])
                    while remaining:
                        written = os.write(descriptor, remaining)
                        assert written > 0
                        remaining = remaining[written:]
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
                os.replace(
                    ".distinct-replacement",
                    logical.name,
                    src_dir_fd=stage_descriptor,
                    dst_dir_fd=stage_descriptor,
                )
            else:
                os.unlink(logical.name, dir_fd=stage_descriptor)
        original(
            parent,
            parent_identity,
            stage_identity,
            stage_descriptor,
            expected_tree,
            baseline,  # type: ignore[arg-type]
            parent_path,
            stage,
            output,
        )
    monkeypatch.setattr(production_evidence, "_publish", mutate)
    with pytest.raises(SupplyChainContractError, match="evidence tree"):
        _invoke(candidate, manifest_bundle, provenance_bundle, tmp_path / "evidence")
    assert not (tmp_path / "evidence").exists()


@pytest.mark.parametrize("mutation", ["extra", "missing", "replacement", "root-mode"])
def test_complete_published_tree_revalidation_rejects_post_rename_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    candidate, manifest_bundle, provenance_bundle = _inputs(tmp_path)
    output = (tmp_path / "evidence").absolute()
    original = production_evidence._rename_exclusive
    def mutate(parent: int, source: str, destination: str) -> None:
        original(parent, source, destination)
        if destination != output.name:
            return
        if mutation == "root-mode":
            os.chmod(output, 0o755)
            return
        if mutation == "extra":
            (output / "foreign-after-rename").write_text("unvalidated", encoding="utf-8")
            os.chmod(output / "foreign-after-rename", 0o400)
            return
        target = output / "manifest.sigstore.json"
        raw = target.read_bytes()
        if mutation == "replacement":
            replacement = tmp_path / "distinct-replacement"
            replacement.write_bytes(raw)
            replacement.chmod(0o400)
            replacement.replace(target)
        else:
            target.unlink()
    monkeypatch.setattr(production_evidence, "_rename_exclusive", mutate)
    with pytest.raises(SupplyChainContractError, match="evidence"):
        _invoke(candidate, manifest_bundle, provenance_bundle, output)
    assert not output.exists()
    assert (
        len([path for path in tmp_path.iterdir() if path.name.startswith(".evidence-incomplete-")])
        == 1
    )


def test_bounded_descriptor_enumeration_stops_before_unbounded_materialization(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    yielded = 0

    class Entries:
        def __enter__(self) -> Entries:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def __iter__(self):  # type: ignore[no-untyped-def]
            nonlocal yielded
            for index in range(10_000):
                yielded += 1
                yield SimpleNamespace(name=f"entry-{index}")

    descriptor = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    monkeypatch.setattr(production_evidence.os, "scandir", lambda _descriptor: Entries())
    try:
        with pytest.raises(SupplyChainContractError, match="entry limit"):
            production_evidence._bounded_names(descriptor, maximum=3, label="probe")
    finally:
        os.close(descriptor)
    assert yielded == 4


def test_enumeration_memory_failure_is_a_contract_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    descriptor = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    def fail(_descriptor: int) -> object:
        raise MemoryError("injected bounded enumeration failure")
    monkeypatch.setattr(production_evidence.os, "scandir", fail)
    try:
        with pytest.raises(SupplyChainContractError, match="bounded evidence tree"):
            production_evidence._bounded_names(descriptor, maximum=1, label="evidence tree")
    finally:
        os.close(descriptor)


def test_owned_final_path_is_quarantined_without_parent_scan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "evidence"
    output.mkdir(mode=0o700)
    parent = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    expected = os.stat(output, follow_symlinks=False)
    monkeypatch.setattr(
        production_evidence,
        "_bounded_names",
        lambda *_args, **_kwargs: pytest.fail("owned final path must not scan its parent"),
    )
    try:
        residue = production_evidence._move_owned_to_residue(parent, expected, output.name)
    finally:
        os.close(parent)
    assert residue is not None
    assert not output.exists()
    assert (tmp_path / residue).is_dir()


def test_quarantine_rename_restores_foreign_racing_replacement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "evidence"
    output.mkdir(mode=0o700)
    expected = os.stat(output, follow_symlinks=False)
    owned_away = tmp_path / "owned-away"
    foreign = tmp_path / "foreign"
    foreign.mkdir()
    (foreign / "sentinel").write_text("preserve", encoding="utf-8")
    original = production_evidence._rename_exclusive
    injected = False
    def race(parent: int, left: str, right: str) -> None:
        nonlocal injected
        if not injected:
            injected = True
            output.rename(owned_away)
            foreign.rename(output)
        original(parent, left, right)
    monkeypatch.setattr(production_evidence, "_rename_exclusive", race)
    parent = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        assert production_evidence._move_owned_to_residue(parent, expected, output.name) is None
    finally:
        os.close(parent)
    assert (output / "sentinel").read_text(encoding="utf-8") == "preserve"
    assert owned_away.is_dir()
    assert not any(path.name.startswith(".evidence-incomplete-") for path in tmp_path.iterdir())


def test_quarantine_restore_never_overwrites_second_foreign_replacement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "evidence"
    output.mkdir(mode=0o700)
    expected = os.stat(output, follow_symlinks=False)
    owned_away = tmp_path / "owned-away"
    foreign = tmp_path / "foreign"
    foreign.mkdir()
    (foreign / "first").write_text("preserve", encoding="utf-8")
    original = production_evidence._rename_exclusive
    calls = 0
    def race(parent: int, left: str, right: str) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            output.rename(owned_away)
            foreign.rename(output)
        elif calls == 2:
            output.mkdir()
            (output / "second").write_text("preserve", encoding="utf-8")
        original(parent, left, right)
    monkeypatch.setattr(production_evidence, "_rename_exclusive", race)
    parent = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        assert production_evidence._move_owned_to_residue(parent, expected, output.name) is None
    finally:
        os.close(parent)
    assert (output / "second").read_text(encoding="utf-8") == "preserve"
    residues = [
        path for path in tmp_path.iterdir() if path.name.startswith(".evidence-incomplete-")
    ]
    assert len(residues) == 1
    assert (residues[0] / "first").read_text(encoding="utf-8") == "preserve"
    assert owned_away.is_dir()


def test_failure_retains_one_bounded_private_snapshot_and_no_public_residue(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    candidate, manifest_bundle, provenance_bundle = _inputs(tmp_path / "inputs")
    output = (tmp_path / "evidence").absolute()
    original = production_evidence._require_published_tree
    calls = 0
    def fail(*args: object) -> None:
        nonlocal calls
        calls += 1
        original(*args)  # type: ignore[arg-type]
        if calls == 2:
            raise SupplyChainContractError("injected post-publication failure")
    monkeypatch.setattr(production_evidence, "_require_published_tree", fail)
    with pytest.raises(SupplyChainContractError, match="injected post-publication failure"):
        _invoke(candidate, manifest_bundle, provenance_bundle, output)
    assert not output.exists()
    residues = list(production_evidence._TEMP_ROOT.iterdir())
    assert len(residues) == 1
    assert residues[0].name.startswith("searise-production-evidence-")
    assert residues[0].stat().st_mode & 0o777 == 0o700
    assert (residues[0] / "candidate/manifest.json").is_file()
    assert (residues[0] / "repository/contracts/supply-chain/v1").is_dir()


def test_external_hardlink_to_staged_file_fails_before_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    candidate, manifest_bundle, provenance_bundle = _inputs(tmp_path / "inputs")
    external = tmp_path / "external-hardlink"
    original = production_evidence._snapshot_fd
    def link(root: int, logical: PurePosixPath, raw: bytes) -> None:
        original(root, logical, raw)
        if logical == production_evidence._PROVENANCE:
            os.link(logical.name, external, src_dir_fd=root)
    monkeypatch.setattr(production_evidence, "_snapshot_fd", link)
    with pytest.raises(SupplyChainContractError, match="exactly one hard link"):
        _invoke(candidate, manifest_bundle, provenance_bundle, tmp_path / "evidence")
    assert not (tmp_path / "evidence").exists()


def test_replacement_after_publish_is_rejected_and_foreign_path_is_preserved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    candidate, manifest_bundle, provenance_bundle = _inputs(tmp_path / "inputs")
    output = (tmp_path / "evidence").absolute()
    owned = tmp_path / "owned-after-publish"
    original = production_evidence._publish
    def replace(*args: object) -> None:
        original(*args)  # type: ignore[arg-type]
        output.rename(owned)
        output.mkdir(mode=0o700)
        (output / "foreign").write_text("preserve", encoding="utf-8")
    monkeypatch.setattr(production_evidence, "_publish", replace)
    with pytest.raises(SupplyChainContractError, match="durable checkpoint"):
        _invoke(candidate, manifest_bundle, provenance_bundle, output)
    assert (output / "foreign").read_text(encoding="utf-8") == "preserve"
    assert not owned.exists()
    residues = [
        path for path in tmp_path.iterdir() if path.name.startswith(".evidence-incomplete-")
    ]
    assert len(residues) == 1
    assert (residues[0] / "evidence-envelope.json").is_file()


@pytest.mark.parametrize("foreign_replacement", [False, True])
def test_parent_fsync_failure_quarantines_only_owned_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    foreign_replacement: bool,
) -> None:
    candidate, manifest_bundle, provenance_bundle = _inputs(tmp_path)
    output = (tmp_path / "evidence").absolute()
    parent_identity = output.parent.stat()
    original = os.fsync
    parent_fsync_calls = 0
    def fail_parent_fsync(descriptor: int) -> None:
        nonlocal parent_fsync_calls
        if os.path.samestat(os.fstat(descriptor), parent_identity):
            parent_fsync_calls += 1
            if parent_fsync_calls == 1:
                if foreign_replacement:
                    output.rename(tmp_path / "owned-moved")
                    output.mkdir()
                    (output / "foreign").write_text("preserve", encoding="utf-8")
                raise OSError("injected parent fsync failure")
        original(descriptor)
    monkeypatch.setattr(production_evidence.os, "fsync", fail_parent_fsync)
    with pytest.raises(SupplyChainContractError, match="durably publish"):
        _invoke(candidate, manifest_bundle, provenance_bundle, output)
    residues = [
        path for path in tmp_path.iterdir() if path.name.startswith(".evidence-incomplete-")
    ]
    assert len(residues) == 1
    assert (residues[0] / "evidence-envelope.json").is_file()
    assert parent_fsync_calls == 2
    if foreign_replacement:
        assert (output / "foreign").read_text(encoding="utf-8") == "preserve"
    else:
        assert not output.exists()


def test_quarantine_fsync_failure_remains_an_explicit_safe_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    candidate, manifest_bundle, provenance_bundle = _inputs(tmp_path)
    output = (tmp_path / "evidence").absolute()
    parent_identity = output.parent.stat()
    original = os.fsync
    parent_fsync_calls = 0
    def fail_parent_fsync(descriptor: int) -> None:
        nonlocal parent_fsync_calls
        if os.path.samestat(os.fstat(descriptor), parent_identity):
            parent_fsync_calls += 1
            raise OSError("injected persistent parent fsync failure")
        original(descriptor)
    monkeypatch.setattr(production_evidence.os, "fsync", fail_parent_fsync)
    with pytest.raises(SupplyChainContractError, match="durably publish"):
        _invoke(candidate, manifest_bundle, provenance_bundle, output)
    assert parent_fsync_calls == 2
    assert not output.exists()
    assert (
        len([path for path in tmp_path.iterdir() if path.name.startswith(".evidence-incomplete-")])
        == 1
    )


@pytest.mark.parametrize(
    ("constant", "message"),
    [
        ("_MAX_BUNDLE_BYTES", "manifest bundle exceeds"),
        ("_MAX_MANIFEST_BYTES", "candidate manifest exceeds"),
        ("_MAX_INVENTORY_BYTES", "dependency inventory exceeds"),
        ("_MAX_SBOM_BYTES", "repository contracts/supply-chain/v1/sboms/"),
        ("_MAX_TOTAL_READ_BYTES", "aggregate input byte limit"),
    ],
)
def test_per_file_and_aggregate_read_limits_fail_before_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    constant: str,
    message: str,
) -> None:
    candidate, manifest_bundle, provenance_bundle = _inputs(tmp_path)
    monkeypatch.setattr(production_evidence, constant, 1)
    with pytest.raises(SupplyChainContractError, match=message):
        _invoke(candidate, manifest_bundle, provenance_bundle, tmp_path / "evidence")
    assert not (tmp_path / "evidence").exists()


def test_output_parent_descriptor_closes_when_bundle_read_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    candidate, manifest_bundle, provenance_bundle = _inputs(tmp_path)
    captured = []
    original = production_evidence._output_parent
    def capture(path: Path) -> int:
        descriptor = original(path)
        captured.append(descriptor)
        return descriptor
    def fail(*args: object) -> bytes:
        raise SupplyChainContractError("injected bundle read failure")
    monkeypatch.setattr(production_evidence, "_output_parent", capture)
    monkeypatch.setattr(production_evidence, "_read_external", fail)
    with pytest.raises(SupplyChainContractError, match="injected bundle read failure"):
        _invoke(candidate, manifest_bundle, provenance_bundle, tmp_path / "evidence")
    assert len(captured) == 1
    with pytest.raises(OSError):
        os.fstat(captured[0])


def test_snapshot_parent_descriptor_closes_when_first_child_creation_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    candidate, manifest_bundle, provenance_bundle = _inputs(tmp_path)
    captured = []
    def fail(parent: int, name: str, label: str) -> int:
        captured.append(parent)
        raise SupplyChainContractError("injected candidate snapshot creation failure")
    monkeypatch.setattr(production_evidence, "_create_directory", fail)
    with pytest.raises(SupplyChainContractError, match="injected candidate snapshot"):
        _invoke(candidate, manifest_bundle, provenance_bundle, tmp_path / "evidence")
    assert len(captured) == 1
    with pytest.raises(OSError):
        os.fstat(captured[0])


def test_snapshot_child_descriptor_closes_on_identity_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    original = os.open
    captured = []
    def track(path: str, flags: int, *args: object, **kwargs: object) -> int:
        descriptor = original(path, flags, *args, **kwargs)  # type: ignore[arg-type]
        if path == "nested":
            captured.append(descriptor)
        return descriptor
    monkeypatch.setattr(production_evidence.os, "open", track)
    monkeypatch.setattr(production_evidence, "_same", lambda left, right: False)
    try:
        with pytest.raises(SupplyChainContractError, match="directory changed"):
            production_evidence._snapshot_fd(root, PurePosixPath("nested/file"), b"value")
    finally:
        os.close(root)
    assert len(captured) == 1
    with pytest.raises(OSError):
        os.fstat(captured[0])


def test_created_directory_inode_is_bound_before_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    parent = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    original = os.open
    moved = tmp_path / "owned-created"
    injected = False
    def replace(path: str, flags: int, *args: object, **kwargs: object) -> int:
        nonlocal injected
        if path == "child" and not injected:
            injected = True
            (tmp_path / "child").rename(moved)
            (tmp_path / "child").mkdir()
        return original(path, flags, *args, **kwargs)  # type: ignore[arg-type]
    monkeypatch.setattr(production_evidence.os, "open", replace)
    try:
        with pytest.raises(SupplyChainContractError, match="changed during creation"):
            production_evidence._create_directory(parent, "child", "test")
    finally:
        os.close(parent)
    assert moved.is_dir()
    assert (tmp_path / "child").is_dir()


def test_unisolated_temp_parent_is_rejected_before_the_unprovable_mkdir_gap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    shared = tmp_path / "shared-temp"
    shared.mkdir(mode=0o755)
    shared.chmod(0o755)
    calls = 0
    original = os.mkdir
    def track(*args: object, **kwargs: object) -> None:
        nonlocal calls
        calls += 1
        original(*args, **kwargs)  # type: ignore[arg-type]
    monkeypatch.setattr(production_evidence, "_TEMP_ROOT", shared.absolute())
    monkeypatch.setattr(production_evidence.os, "mkdir", track)
    with pytest.raises(SupplyChainContractError, match="inaccessible to group/other"):
        production_evidence._new_private_snapshot()
    assert calls == 0


def test_unisolated_output_parent_is_rejected_before_staging(tmp_path: Path) -> None:
    shared = tmp_path / "shared-output"
    shared.mkdir(mode=0o755)
    shared.chmod(0o755)
    with pytest.raises(SupplyChainContractError, match="inaccessible to group/other"):
        production_evidence._output_parent(shared / "evidence")


@pytest.mark.parametrize("operation", ["stat", "open"])
def test_post_mkdir_snapshot_setup_failure_retains_one_root_without_retry(
    operation: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = 0
    original = getattr(production_evidence.os, operation)
    def fail(path: object, *args: object, **kwargs: object) -> object:
        nonlocal calls
        if (
            isinstance(path, str)
            and path.startswith("searise-production-evidence-")
            and kwargs.get("dir_fd") is not None
        ):
            calls += 1
            raise OSError(errno.EMFILE, "injected post-mkdir setup failure")
        return original(path, *args, **kwargs)  # type: ignore[call-overload]
    monkeypatch.setattr(production_evidence.os, operation, fail)
    with pytest.raises(SupplyChainContractError, match="could not create private"):
        production_evidence._new_private_snapshot()
    residues = list(production_evidence._TEMP_ROOT.iterdir())
    assert calls == 1
    assert len(residues) == 1
    assert residues[0].name.startswith("searise-production-evidence-")


def test_private_snapshot_retries_only_a_true_precreation_collision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tokens = iter(("0" * 32, "1" * 32))
    collision = production_evidence._TEMP_ROOT / f"searise-production-evidence-{'0' * 32}"
    collision.mkdir(mode=0o700)
    monkeypatch.setattr(production_evidence.secrets, "token_hex", lambda _size: next(tokens))
    parent, name, descriptor, path, _identity = production_evidence._new_private_snapshot()
    try:
        assert name == f"searise-production-evidence-{'1' * 32}"
        assert path == production_evidence._TEMP_ROOT / name
        assert collision.is_dir()
    finally:
        os.close(descriptor)
        os.close(parent)


@pytest.mark.parametrize("work_parent", ["output", "snapshot"])
@pytest.mark.parametrize("authority_name", ["candidate", "repository"])
@pytest.mark.parametrize("relation", ["equal", "descendant"])
def test_work_parents_reject_authority_overlap_before_mkdir_without_residue(
    work_parent: str,
    authority_name: str,
    relation: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate, repository = tmp_path / "candidate", tmp_path / "repository"
    candidate.mkdir(mode=0o700)
    repository.mkdir(mode=0o700)
    authority = candidate if authority_name == "candidate" else repository
    parent = authority
    if relation == "descendant":
        parent = authority / "private-work"
        parent.mkdir(mode=0o700)
    before = tuple(sorted(path.relative_to(tmp_path) for path in tmp_path.rglob("*")))
    with pytest.raises(SupplyChainContractError, match="outside candidate and repository"):
        if work_parent == "output":
            _invoke(
                candidate,
                tmp_path / "missing-manifest-bundle",
                tmp_path / "missing-provenance-bundle",
                parent / "evidence",
                repository=repository,
            )
        else:
            monkeypatch.setattr(production_evidence, "_TEMP_ROOT", parent.absolute())
            production_evidence._new_private_snapshot(
                candidate_root=candidate,
                repository_root=repository,
            )

    after = tuple(sorted(path.relative_to(tmp_path) for path in tmp_path.rglob("*")))
    assert after == before


def test_finalizer_is_non_reentrant_before_reading_inputs(tmp_path: Path) -> None:
    assert production_evidence._FINALIZATION_LOCK.acquire(blocking=False)
    try:
        with pytest.raises(SupplyChainContractError, match="non-reentrant"):
            _invoke(
                tmp_path / "missing-candidate",
                tmp_path / "missing-manifest-bundle",
                tmp_path / "missing-provenance-bundle",
                tmp_path / "evidence",
            )
    finally:
        production_evidence._FINALIZATION_LOCK.release()


def test_exact_candidate_byte_gate_rejects_artifact_mutation(tmp_path: Path) -> None:
    candidate, manifest_bundle, provenance_bundle = _inputs(tmp_path)
    target = candidate / "config/scenarios.json"
    target.write_bytes(target.read_bytes() + b"mutated")
    with pytest.raises(SupplyChainContractError, match="artifact byte size differs"):
        _invoke(candidate, manifest_bundle, provenance_bundle, tmp_path / "evidence")
    assert not (tmp_path / "evidence").exists()


def test_finalizer_normalizes_provenance_contract_failures(tmp_path: Path) -> None:
    candidate, manifest_bundle, provenance_bundle = _inputs(tmp_path)
    (candidate / "receipts/build.json").write_text("{}\n", encoding="utf-8")
    with pytest.raises(SupplyChainContractError, match="build-receipt-contract") as raised:
        _invoke(candidate, manifest_bundle, provenance_bundle, tmp_path / "evidence")
    assert raised.value.__cause__ is not None
    assert type(raised.value.__cause__).__name__ == "ProvenanceContractError"
    assert not (tmp_path / "evidence").exists()


def test_cli_reports_provenance_contract_failures_without_a_traceback(
    tmp_path: Path,
    capfd: pytest.CaptureFixture[str],
) -> None:
    candidate, manifest_bundle, provenance_bundle = _inputs(tmp_path)
    (candidate / "receipts/build.json").write_text("{}\n", encoding="utf-8")
    main = runpy.run_path(str(CLI))["main"]
    output = tmp_path / "evidence"
    assert main(_cli_args(candidate, manifest_bundle, provenance_bundle, output)) == 2
    captured = capfd.readouterr()
    assert captured.out == ""
    assert captured.err.startswith("error: build-receipt-contract:")
    assert "Traceback" not in captured.err
    assert not (tmp_path / "evidence").exists()


def test_post_commit_descriptor_close_error_cannot_reverse_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: list[int] = []
    original_new_stage = production_evidence._new_stage
    original_close = os.close

    def capture(parent: int) -> tuple[str, int, os.stat_result]:
        result = original_new_stage(parent)
        captured.append(result[1])
        return result

    def fail_stage_close(descriptor: int) -> None:
        if captured and descriptor == captured[0]:
            raise OSError("injected post-commit close failure")
        original_close(descriptor)
    monkeypatch.setattr(production_evidence, "_new_stage", capture)
    monkeypatch.setattr(production_evidence.os, "close", fail_stage_close)
    summary = _finalize(tmp_path)
    assert summary.evidence_root == (tmp_path / "evidence").absolute()
    assert (tmp_path / "evidence/evidence-envelope.json").is_file()
    original_close(captured[0])


def test_snapshot_descriptors_close_without_masking_primary_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    candidate, manifest_bundle, provenance_bundle = _inputs(tmp_path)
    captured: list[int] = []
    close_attempts: list[int] = []
    original_create = production_evidence._create_directory
    original_close = os.close

    def capture(parent: int, name: str, label: str) -> int:
        descriptor = original_create(parent, name, label)
        captured.append(descriptor)
        return descriptor

    def fail_snapshot(*args: object, **kwargs: object) -> object:
        raise SupplyChainContractError("injected snapshot primary failure")

    def close(descriptor: int) -> None:
        if descriptor in captured:
            close_attempts.append(descriptor)
            if len(captured) > 1 and descriptor == captured[1]:
                raise OSError("injected cleanup failure")
        original_close(descriptor)
    monkeypatch.setattr(production_evidence, "_create_directory", capture)
    monkeypatch.setattr(production_evidence, "_candidate_snapshot", fail_snapshot)
    monkeypatch.setattr(production_evidence.os, "close", close)
    with pytest.raises(SupplyChainContractError, match="snapshot primary failure"):
        _invoke(candidate, manifest_bundle, provenance_bundle, tmp_path / "evidence")
    assert close_attempts[:2] == captured[1:3]
    assert set(close_attempts) == set(captured)
    original_close(captured[1])
