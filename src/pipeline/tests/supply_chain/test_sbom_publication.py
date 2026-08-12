"""Adversarial tests for immutable SBOM publication and CLI use."""

from __future__ import annotations

import os
import runpy
from pathlib import Path
from typing import Any, Callable, cast

import pytest

import searise_pipeline.supply_chain.sbom as sbom_module
from searise_pipeline import supply_chain
from searise_pipeline.supply_chain import (
    SupplyChainContractError,
    canonical_sbom_bytes,
    publish_python_sbom,
    validate_python_sbom,
    write_new_sbom,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
main = cast(
    Callable[..., int],
    runpy.run_path(str(REPOSITORY_ROOT / "scripts/release/validate_supply_chain_contract.py"))[
        "main"
    ],
)
ANNOTATION = (
    REPOSITORY_ROOT
    / "contracts"
    / "supply-chain"
    / "v1"
    / "fixtures"
    / "python-graph"
    / "valid.json"
)
TARGET = "linux-x86-64-cp311"
NPM_LOCK = REPOSITORY_ROOT / "src/frontend/package-lock.json"
NPM_ARTIFACT = REPOSITORY_ROOT / "contracts/supply-chain/v1/sboms/frontend-npm.cdx.json"
NPM_LOGICAL_PATH = "src/frontend/package-lock.json"


def _partials(parent: Path) -> list[Path]:
    return list(parent.glob(".searise-sbom-*.partial"))


def test_public_api_publishes_exact_canonical_target_bytes_once(tmp_path: Path) -> None:
    output = tmp_path / "python-sbom.json"
    document = publish_python_sbom(
        output,
        ANNOTATION,
        repository_root=REPOSITORY_ROOT,
        target_id=TARGET,
    )

    assert output.read_bytes() == canonical_sbom_bytes(document)
    assert (
        validate_python_sbom(
            output,
            ANNOTATION,
            repository_root=REPOSITORY_ROOT,
            target_id=TARGET,
        )
        == document
    )
    assert supply_chain.generate_python_sbom
    assert supply_chain.publish_python_sbom
    assert supply_chain.validate_python_sbom

    original = output.read_bytes()
    with pytest.raises(SupplyChainContractError, match="already exists"):
        publish_python_sbom(
            output,
            ANNOTATION,
            repository_root=REPOSITORY_ROOT,
            target_id=TARGET,
        )
    assert output.read_bytes() == original
    assert not _partials(tmp_path)


def test_cli_generates_and_validates_one_explicit_target(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    output = tmp_path / "python-sbom.json"
    common = [
        "--annotation",
        str(ANNOTATION),
        "--repository-root",
        str(REPOSITORY_ROOT),
        "--target",
        TARGET,
    ]

    assert main(["python-sbom", *common, "--output", str(output)]) == 0
    assert f"3 Python components for {TARGET}" in capsys.readouterr().out
    assert main(["python-sbom-validate", *common, "--sbom", str(output)]) == 0
    assert f"validated 3 Python components for {TARGET}" in capsys.readouterr().out

    missing = tmp_path / "missing.json"
    assert (
        main(
            [
                "python-sbom",
                "--annotation",
                str(ANNOTATION),
                "--repository-root",
                str(REPOSITORY_ROOT),
                "--target",
                "missing-target",
                "--output",
                str(missing),
            ]
        )
        == 1
    )
    assert "target ID" in capsys.readouterr().err
    assert not missing.exists()


def test_npm_cli_generates_and_validates_real_frontend_bytes(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    output = tmp_path / "frontend-npm.cdx.json"
    common = [
        "--lock",
        str(NPM_LOCK),
        "--repository-root",
        str(REPOSITORY_ROOT),
        "--logical-path",
        NPM_LOGICAL_PATH,
    ]

    assert main(["npm-sbom", *common, "--output", str(output)]) == 0
    assert "generated 597 npm components" in capsys.readouterr().out
    assert output.read_bytes() == NPM_ARTIFACT.read_bytes()
    assert main(["npm-sbom-validate", *common, "--sbom", str(output)]) == 0
    assert "validated 597 npm components" in capsys.readouterr().out


def test_parent_inode_swap_fails_without_publishing_to_either_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parent = tmp_path / "parent"
    parent.mkdir()
    moved = tmp_path / "moved-parent"
    output = parent / "sbom.json"
    original_match = sbom_module._parent_path_matches
    swapped = False

    def swap_then_match(anchor: int, parts: tuple[str, ...], expected: Any) -> bool:
        nonlocal swapped
        if not swapped:
            parent.rename(moved)
            parent.mkdir()
            swapped = True
        return original_match(anchor, parts, expected)

    monkeypatch.setattr(sbom_module, "_parent_path_matches", swap_then_match)
    with pytest.raises(SupplyChainContractError, match="parent changed"):
        write_new_sbom(output, b"trusted\n")

    assert not output.exists()
    assert not (moved / output.name).exists()
    assert not _partials(parent)
    assert not _partials(moved)


def test_same_size_racing_replacement_survives_verified_rollback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = tmp_path / "sbom.json"
    trusted = b"trusted\n"
    racing = b"racing!\n"
    assert len(trusted) == len(racing)
    original_fsync = sbom_module.os.fsync
    calls = 0

    def replace_before_directory_fsync(descriptor: int) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            output.unlink()
            output.write_bytes(racing)
            raise OSError("injected directory fsync failure")
        original_fsync(descriptor)

    monkeypatch.setattr(sbom_module.os, "fsync", replace_before_directory_fsync)
    with pytest.raises(OSError, match="injected directory fsync failure"):
        write_new_sbom(output, trusted)

    assert output.read_bytes() == racing
    assert not _partials(tmp_path)


def test_same_inode_same_size_content_race_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = tmp_path / "sbom.json"
    trusted = b"trusted\n"
    racing = b"racing!\n"
    original_match = sbom_module._parent_path_matches
    calls = 0

    def mutate_after_directory_fsync(anchor: int, parts: tuple[str, ...], expected: Any) -> bool:
        nonlocal calls
        calls += 1
        if calls == 2:
            output.write_bytes(racing)
        return original_match(anchor, parts, expected)

    monkeypatch.setattr(sbom_module, "_parent_path_matches", mutate_after_directory_fsync)
    with pytest.raises(SupplyChainContractError, match="output bytes changed"):
        write_new_sbom(output, trusted)

    assert not output.exists()
    assert not _partials(tmp_path)


def test_rollback_restores_replacement_racing_the_owned_unlink(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = tmp_path / "sbom.json"
    trusted = b"trusted\n"
    mutated = b"changed!\n"
    racing = b"racing replacement\n"
    original_match = sbom_module._parent_path_matches
    original_rename = sbom_module._rename_no_overwrite
    match_calls = 0
    replaced = False

    def mutate_after_directory_fsync(anchor: int, parts: tuple[str, ...], expected: Any) -> bool:
        nonlocal match_calls
        match_calls += 1
        if match_calls == 2:
            output.write_bytes(mutated)
        return original_match(anchor, parts, expected)

    def replace_before_rollback(parent: int, source: str, target: str) -> None:
        nonlocal replaced
        if source == output.name and not replaced:
            os.unlink(source, dir_fd=parent)
            descriptor = os.open(
                source,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
                dir_fd=parent,
            )
            try:
                os.write(descriptor, racing)
            finally:
                os.close(descriptor)
            replaced = True
        original_rename(parent, source, target)

    monkeypatch.setattr(sbom_module, "_parent_path_matches", mutate_after_directory_fsync)
    monkeypatch.setattr(sbom_module, "_rename_no_overwrite", replace_before_rollback)
    with pytest.raises(SupplyChainContractError, match="output bytes changed"):
        write_new_sbom(output, trusted)

    assert output.read_bytes() == racing
    assert not _partials(tmp_path)
    assert not list(tmp_path.glob(".searise-sbom-rollback-*"))


def test_publication_fsyncs_regular_file_before_parent_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = tmp_path / "sbom.json"
    original_fsync = sbom_module.os.fsync
    modes: list[int] = []

    def record_fsync(descriptor: int) -> None:
        modes.append(os.fstat(descriptor).st_mode)
        original_fsync(descriptor)

    monkeypatch.setattr(sbom_module.os, "fsync", record_fsync)
    write_new_sbom(output, b"exact bytes\n")

    assert len(modes) == 2
    assert sbom_module.stat.S_ISREG(modes[0])
    assert sbom_module.stat.S_ISDIR(modes[1])


def test_cleanup_close_error_cannot_reverse_durable_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "sbom.json"
    content = b"exact committed bytes\n"
    original_exact = sbom_module._descriptor_has_exact_bytes
    original_close = sbom_module.os.close
    exact_checks = 0
    failed_close = False

    def track_exact(descriptor: int, expected: bytes) -> bool:
        nonlocal exact_checks
        exact_checks += 1
        return original_exact(descriptor, expected)

    def fail_first_post_commit_close(descriptor: int) -> None:
        nonlocal failed_close
        if exact_checks == 3 and not failed_close:
            failed_close = True
            raise OSError("injected cleanup-only close failure")
        original_close(descriptor)

    monkeypatch.setattr(sbom_module, "_descriptor_has_exact_bytes", track_exact)
    monkeypatch.setattr(sbom_module.os, "close", fail_first_post_commit_close)

    write_new_sbom(output, content)

    assert failed_close
    assert output.read_bytes() == content


def test_final_name_race_is_never_overwritten_or_removed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = tmp_path / "sbom.json"
    racing = b"racing-owner\n"
    original_link = sbom_module.os.link

    def race_link(source: str, target: str, **kwargs: Any) -> None:
        descriptor = os.open(
            target,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
            dir_fd=kwargs["dst_dir_fd"],
        )
        try:
            os.write(descriptor, racing)
        finally:
            os.close(descriptor)
        original_link(source, target, **kwargs)

    monkeypatch.setattr(sbom_module.os, "link", race_link)
    with pytest.raises(SupplyChainContractError, match="already exists"):
        write_new_sbom(output, b"trusted-owner\n")

    assert output.read_bytes() == racing
    assert not _partials(tmp_path)


def test_partial_inode_race_is_detected_without_deleting_racing_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = tmp_path / "sbom.json"
    trusted = b"trusted\n"
    racing = b"racing!\n"
    original_link = sbom_module.os.link

    def replace_partial(source: str, target: str, **kwargs: Any) -> None:
        source_parent = kwargs["src_dir_fd"]
        os.unlink(source, dir_fd=source_parent)
        descriptor = os.open(
            source,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
            dir_fd=source_parent,
        )
        try:
            os.write(descriptor, racing)
        finally:
            os.close(descriptor)
        original_link(source, target, **kwargs)

    monkeypatch.setattr(sbom_module.os, "link", replace_partial)
    with pytest.raises(SupplyChainContractError, match="promotion ownership changed"):
        write_new_sbom(output, trusted)

    assert output.read_bytes() == racing
    assert _partials(tmp_path)[0].read_bytes() == racing


def test_unsafe_or_symlinked_output_ancestry_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(SupplyChainContractError, match="unsafe SBOM output path"):
        write_new_sbom(Path("../escape.json"), b"content")

    real = tmp_path / "real"
    nested = real / "nested"
    nested.mkdir(parents=True)
    alias = tmp_path / "alias"
    alias.symlink_to(real, target_is_directory=True)
    with pytest.raises(SupplyChainContractError, match="must not be a symlink"):
        write_new_sbom(alias / "nested" / "sbom.json", b"content")
    assert not (nested / "sbom.json").exists()

    with pytest.raises(SupplyChainContractError, match="exact bytes"):
        write_new_sbom(tmp_path / "typed.json", bytearray(b"content"))  # type: ignore[arg-type]
