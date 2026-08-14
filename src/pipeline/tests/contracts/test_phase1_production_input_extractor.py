from __future__ import annotations

import argparse
import io
import sys
import tarfile
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPOSITORY_ROOT))

from scripts.release import package_phase1_production_inputs as packager  # noqa: E402
from scripts.release import prepare_phase1_production_inputs as module  # noqa: E402


def _arguments(tmp_path: Path) -> argparse.Namespace:
    candidate = tmp_path / "candidate"
    inventory = packager.json.loads(packager.INVENTORY.read_text())
    for index, item in enumerate(
        inventory["requiredArtifacts"][: packager.PRE_GATE_COUNT]
    ):
        path = candidate / item["path"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(f"candidate-{index}".encode())
    extras = {}
    for name in (
        "spatial_receipt",
        "settlement_artifact_receipt",
        "browser_performance",
        "performance_queries",
    ):
        extras[name] = tmp_path / f"{name}.json"
        extras[name].write_text("{}\n")
    tools = tmp_path / "tools"
    tools.mkdir()
    for name in packager.TOOLCHAIN_FILES:
        (tools / name).write_bytes(f"tool-{name}".encode())
    return argparse.Namespace(
        candidate_input_root=candidate,
        toolchain_root=tools,
        output=tmp_path / "phase-1-production-inputs.tar",
        **extras,
    )


def _bundle(tmp_path: Path) -> tuple[Path, str]:
    args = _arguments(tmp_path)
    summary = packager.package_inputs(args)
    return args.output, str(summary["sha256"])


def test_preparer_rechecks_authority_and_exposes_exact_tree(tmp_path: Path) -> None:
    archive, digest = _bundle(tmp_path / "source")
    destination = tmp_path / "prepared"
    summary = module.prepare_inputs(archive, destination, expected_sha256=digest)

    assert summary.file_count == 61
    assert summary.destination == destination
    assert (destination / "candidate-inputs").is_dir()
    assert (destination / "authorities/settlements.receipt.json").is_file()
    assert (destination / "toolchain/brotli").stat().st_mode & 0o111


def test_preparer_rejects_archive_hash_and_existing_destination(tmp_path: Path) -> None:
    archive, digest = _bundle(tmp_path / "source")
    with pytest.raises(module.ProductionInputError, match="SHA-256 differs"):
        module.prepare_inputs(archive, tmp_path / "bad", expected_sha256="0" * 64)
    destination = tmp_path / "exists"
    destination.mkdir()
    with pytest.raises(module.ProductionInputError, match="already exists"):
        module.prepare_inputs(archive, destination, expected_sha256=digest)


def test_preparer_rejects_unsorted_or_tampered_authority(tmp_path: Path) -> None:
    archive, _ = _bundle(tmp_path / "source")
    members = []
    with tarfile.open(archive, mode="r:") as package:
        for member in package.getmembers():
            members.append((member, package.extractfile(member).read()))
    output = tmp_path / "tampered.tar"
    with tarfile.open(output, mode="w", format=tarfile.USTAR_FORMAT) as package:
        for member, raw in reversed(members):
            package.addfile(member, io.BytesIO(raw))

    with pytest.raises(module.ProductionInputError, match="not sorted"):
        module.prepare_inputs(
            output,
            tmp_path / "prepared",
            expected_sha256=module._sha256(output),
        )
