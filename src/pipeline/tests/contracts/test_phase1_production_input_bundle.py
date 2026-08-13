from __future__ import annotations

import argparse
import hashlib
import io
import json
import sys
import tarfile
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPOSITORY_ROOT))

from scripts.release import package_phase1_production_inputs as module  # noqa: E402


def _arguments(tmp_path: Path) -> argparse.Namespace:
    candidate = tmp_path / "candidate"
    inventory = json.loads(module.INVENTORY.read_text())
    for index, item in enumerate(inventory["requiredArtifacts"][: module.PRE_GATE_COUNT]):
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
    for name in module.TOOLCHAIN_FILES:
        (tools / name).write_bytes(f"tool-{name}".encode())
    return argparse.Namespace(
        candidate_input_root=candidate,
        toolchain_root=tools,
        output=tmp_path / "phase-1-production-inputs.tar",
        **extras,
    )


def test_bundle_is_deterministic_and_binds_every_exact_input(tmp_path: Path) -> None:
    first = _arguments(tmp_path / "first")
    second = _arguments(tmp_path / "second")
    summary = module.package_inputs(first)
    second_summary = module.package_inputs(second)

    assert first.output.read_bytes() == second.output.read_bytes()
    assert summary["sha256"] == second_summary["sha256"]
    with tarfile.open(fileobj=io.BytesIO(first.output.read_bytes()), mode="r:") as archive:
        members = archive.getmembers()
        authority = json.loads(archive.extractfile("input-authority.json").read())
    assert len(members) == module.PRE_GATE_COUNT + len(module.TOOLCHAIN_FILES) + 5
    assert members == sorted(members, key=lambda item: item.name)
    assert all(item.uid == item.gid == item.mtime == 0 for item in members)
    assert authority["candidateInputCount"] == module.PRE_GATE_COUNT
    assert {
        item["sha256"] for item in authority["files"]
    } == {
        hashlib.sha256(path.read_bytes()).hexdigest()
        for path in [
            *first.candidate_input_root.rglob("*"),
            first.spatial_receipt,
            first.settlement_artifact_receipt,
            first.browser_performance,
            first.performance_queries,
            *(first.toolchain_root / name for name in module.TOOLCHAIN_FILES),
        ]
        if path.is_file()
    }


def test_bundle_rejects_inventory_drift_and_overwrite(tmp_path: Path) -> None:
    args = _arguments(tmp_path)
    unexpected = args.candidate_input_root / "unexpected.bin"
    unexpected.write_bytes(b"unexpected")
    with pytest.raises(module.InputBundleError, match="exactly 51"):
        module.package_inputs(args)
    unexpected.unlink()
    module.package_inputs(args)
    with pytest.raises(FileExistsError):
        module.package_inputs(args)


def test_bundle_rejects_symlinked_input(tmp_path: Path) -> None:
    args = _arguments(tmp_path)
    target = next(path for path in args.candidate_input_root.rglob("*") if path.is_file())
    raw = target.read_bytes()
    target.unlink()
    outside = tmp_path / "outside"
    outside.write_bytes(raw)
    target.symlink_to(outside)

    with pytest.raises(module.InputBundleError, match="cannot open reviewed input"):
        module.package_inputs(args)
