"""Tests for immutable pre-verification production evidence finalization."""

from __future__ import annotations

import base64
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


def _candidate(root: Path) -> tuple[Path, Path]:
    candidate, build = _documents()
    candidate["dataProvenanceClass"] = build["dataProvenanceClass"] = "real-source"
    for artifact in candidate["artifacts"]:
        artifact["dataProvenanceClass"] = "real-source"
    return _write_pair(root, candidate, build)


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
    return finalize_production_evidence(
        candidate,
        repository_root=ROOT,
        controlled_build_run_id=RUN_ID,
        manifest_bundle=manifest_bundle.absolute(),
        provenance_bundle=provenance_bundle.absolute(),
        output_root=(root / "evidence").absolute(),
    )


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
    for logical in paths:
        target = root.joinpath(*logical.parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT.joinpath(*logical.parts), target)
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


def test_cli_reports_only_nonclaims(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    candidate, manifest_bundle, provenance_bundle = _inputs(tmp_path)
    main = runpy.run_path(str(CLI))["main"]

    assert (
        main(
            [
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
                str((tmp_path / "evidence").absolute()),
            ]
        )
        == 0
    )
    assert (
        "cryptographic verification, production, publication, and scientific approval not claimed"
        in capsys.readouterr().out
    )


def test_existing_output_is_never_overwritten(tmp_path: Path) -> None:
    candidate, manifest_bundle, provenance_bundle = _inputs(tmp_path)
    output = (tmp_path / "evidence").absolute()
    output.mkdir()
    sentinel = output / "sentinel"
    sentinel.write_text("preserve")

    with pytest.raises(SupplyChainContractError, match="already exists"):
        finalize_production_evidence(
            candidate,
            repository_root=ROOT,
            controlled_build_run_id=RUN_ID,
            manifest_bundle=manifest_bundle.absolute(),
            provenance_bundle=provenance_bundle.absolute(),
            output_root=output,
        )
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
        finalize_production_evidence(
            candidate,
            repository_root=ROOT,
            controlled_build_run_id=RUN_ID,
            manifest_bundle=manifest_bundle.absolute(),
            provenance_bundle=provenance_bundle.absolute(),
            output_root=output,
        )
    assert (output / "alien").read_text() == "preserve"


def test_output_parent_swap_fails_and_preserves_replacement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    candidate, manifest_bundle, provenance_bundle = _inputs(tmp_path / "inputs")
    parent, moved = tmp_path / "output", tmp_path / "moved-output"
    parent.mkdir()
    original = production_evidence._publish

    def swap(*args: object) -> None:
        parent.rename(moved)
        parent.mkdir()
        (parent / "alien").write_text("preserve")
        original(*args)  # type: ignore[arg-type]

    monkeypatch.setattr(production_evidence, "_publish", swap)
    with pytest.raises(SupplyChainContractError, match="parent changed"):
        finalize_production_evidence(
            candidate,
            repository_root=ROOT,
            controlled_build_run_id=RUN_ID,
            manifest_bundle=manifest_bundle.absolute(),
            provenance_bundle=provenance_bundle.absolute(),
            output_root=(parent / "evidence").absolute(),
        )
    assert (parent / "alien").read_text() == "preserve"


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
        finalize_production_evidence(
            candidate,
            repository_root=ROOT,
            controlled_build_run_id=RUN_ID,
            manifest_bundle=manifest_bundle.absolute(),
            provenance_bundle=provenance_bundle.absolute(),
            output_root=(tmp_path / "evidence").absolute(),
        )
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
        finalize_production_evidence(
            candidate,
            repository_root=ROOT,
            controlled_build_run_id=RUN_ID,
            manifest_bundle=manifest_bundle.absolute(),
            provenance_bundle=provenance_bundle.absolute(),
            output_root=(tmp_path / "evidence").absolute(),
        )
    assert list(foreign.iterdir()) == []


def test_bad_bundle_leaves_no_final_output(tmp_path: Path) -> None:
    candidate, manifest_bundle, provenance_bundle = _inputs(tmp_path)
    bundle = _load(manifest_bundle)
    bundle["messageSignature"]["messageDigest"]["digest"] = base64.b64encode(b"wrong").decode()
    manifest_bundle.write_text(json.dumps(bundle) + "\n")
    output = (tmp_path / "evidence").absolute()

    with pytest.raises(SupplyChainContractError, match="message digest"):
        finalize_production_evidence(
            candidate,
            repository_root=ROOT,
            controlled_build_run_id=RUN_ID,
            manifest_bundle=manifest_bundle.absolute(),
            provenance_bundle=provenance_bundle.absolute(),
            output_root=output,
        )
    assert not output.exists()


@pytest.mark.parametrize("run_id", ["0", "01", "run-1", "9" * 21])
def test_invalid_controlled_run_id_fails_before_publication(tmp_path: Path, run_id: str) -> None:
    candidate, manifest_bundle, provenance_bundle = _inputs(tmp_path)
    output = (tmp_path / "evidence").absolute()

    with pytest.raises(SupplyChainContractError, match="canonical positive integer"):
        finalize_production_evidence(
            candidate,
            repository_root=ROOT,
            controlled_build_run_id=run_id,
            manifest_bundle=manifest_bundle.absolute(),
            provenance_bundle=provenance_bundle.absolute(),
            output_root=output,
        )
    assert not output.exists()


def test_valid_but_different_run_id_cannot_rebind_the_provenance_bundle(tmp_path: Path) -> None:
    candidate, manifest_bundle, provenance_bundle = _inputs(tmp_path)

    with pytest.raises(SupplyChainContractError, match="message digest"):
        finalize_production_evidence(
            candidate,
            repository_root=ROOT,
            controlled_build_run_id=str(int(RUN_ID) + 1),
            manifest_bundle=manifest_bundle.absolute(),
            provenance_bundle=provenance_bundle.absolute(),
            output_root=(tmp_path / "evidence").absolute(),
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
        finalize_production_evidence(
            candidate,
            repository_root=repository,
            controlled_build_run_id=RUN_ID,
            manifest_bundle=manifest_bundle.absolute(),
            provenance_bundle=provenance_bundle.absolute(),
            output_root=(tmp_path / "evidence").absolute(),
        )
    assert not any(label.startswith(("dependency input", "repository sbom/")) for label in reads)


def test_unrecorded_source_dependency_is_rejected_before_snapshot_use(tmp_path: Path) -> None:
    candidate, manifest_bundle, provenance_bundle = _inputs(tmp_path / "inputs")
    repository = _repository_authority(tmp_path / "repository")
    rogue = repository / ".github/workflows/unrecorded-release.yml"
    rogue.parent.mkdir(parents=True, exist_ok=True)
    rogue.write_text("name: unrecorded\n", encoding="utf-8")

    with pytest.raises(SupplyChainContractError, match="dependency discovery mismatch"):
        finalize_production_evidence(
            candidate,
            repository_root=repository,
            controlled_build_run_id=RUN_ID,
            manifest_bundle=manifest_bundle.absolute(),
            provenance_bundle=provenance_bundle.absolute(),
            output_root=(tmp_path / "evidence").absolute(),
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
        finalize_production_evidence(
            candidate,
            repository_root=repository,
            controlled_build_run_id=RUN_ID,
            manifest_bundle=manifest_bundle.absolute(),
            provenance_bundle=provenance_bundle.absolute(),
            output_root=(tmp_path / "evidence").absolute(),
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
        finalize_production_evidence(
            candidate,
            repository_root=ROOT,
            controlled_build_run_id=RUN_ID,
            manifest_bundle=manifest_bundle.absolute(),
            provenance_bundle=provenance_bundle.absolute(),
            output_root=(tmp_path / "evidence").absolute(),
        )


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
        finalize_production_evidence(
            candidate,
            repository_root=ROOT,
            controlled_build_run_id=RUN_ID,
            manifest_bundle=manifest_bundle.absolute(),
            provenance_bundle=provenance_bundle.absolute(),
            output_root=(tmp_path / "evidence").absolute(),
        )


def test_all_ten_sboms_are_checked_against_merged_authorities(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    candidate, manifest_bundle, provenance_bundle = _inputs(tmp_path)
    validated = []
    original = production_evidence._validate_sbom_authority

    def record(logical: str, path: Path, root: Path) -> None:
        validated.append(logical)
        original(logical, path, root)

    monkeypatch.setattr(production_evidence, "_validate_sbom_authority", record)
    finalize_production_evidence(
        candidate,
        repository_root=ROOT,
        controlled_build_run_id=RUN_ID,
        manifest_bundle=manifest_bundle.absolute(),
        provenance_bundle=provenance_bundle.absolute(),
        output_root=(tmp_path / "evidence").absolute(),
    )
    assert tuple(validated) == production_evidence._SBOM_PATHS


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
        finalize_production_evidence(
            candidate,
            repository_root=ROOT,
            controlled_build_run_id=RUN_ID,
            manifest_bundle=manifest_bundle.absolute(),
            provenance_bundle=provenance_bundle.absolute(),
            output_root=(tmp_path / "evidence").absolute(),
        )
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
        finalize_production_evidence(
            candidate,
            repository_root=ROOT,
            controlled_build_run_id=RUN_ID,
            manifest_bundle=manifest_bundle.absolute(),
            provenance_bundle=provenance_bundle.absolute(),
            output_root=output,
        )
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
        finalize_production_evidence(
            candidate,
            repository_root=ROOT,
            controlled_build_run_id=RUN_ID,
            manifest_bundle=manifest_bundle.absolute(),
            provenance_bundle=provenance_bundle.absolute(),
            output_root=output,
        )
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
        finalize_production_evidence(
            candidate,
            repository_root=ROOT,
            controlled_build_run_id=RUN_ID,
            manifest_bundle=manifest_bundle.absolute(),
            provenance_bundle=provenance_bundle.absolute(),
            output_root=output,
        )
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
        finalize_production_evidence(
            candidate,
            repository_root=ROOT,
            controlled_build_run_id=RUN_ID,
            manifest_bundle=manifest_bundle.absolute(),
            provenance_bundle=provenance_bundle.absolute(),
            output_root=output,
        )
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
        finalize_production_evidence(
            candidate,
            repository_root=ROOT,
            controlled_build_run_id=RUN_ID,
            manifest_bundle=manifest_bundle.absolute(),
            provenance_bundle=provenance_bundle.absolute(),
            output_root=(tmp_path / "evidence").absolute(),
        )
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
        finalize_production_evidence(
            candidate,
            repository_root=ROOT,
            controlled_build_run_id=RUN_ID,
            manifest_bundle=manifest_bundle.absolute(),
            provenance_bundle=provenance_bundle.absolute(),
            output_root=(tmp_path / "evidence").absolute(),
        )
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
        finalize_production_evidence(
            candidate,
            repository_root=ROOT,
            controlled_build_run_id=RUN_ID,
            manifest_bundle=manifest_bundle.absolute(),
            provenance_bundle=provenance_bundle.absolute(),
            output_root=(tmp_path / "evidence").absolute(),
        )
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
