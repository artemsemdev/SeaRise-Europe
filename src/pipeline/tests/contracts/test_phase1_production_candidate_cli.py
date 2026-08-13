from __future__ import annotations

import argparse
from pathlib import Path
from types import SimpleNamespace

import pytest
from scripts.release import assemble_phase1_production_candidate as module


def _arguments(tmp_path: Path) -> argparse.Namespace:
    contract = tmp_path / "contract.json"
    contract.write_text("{}")
    receipt = tmp_path / "fixture-receipt.json"
    receipt.write_text("{}")
    fixture = tmp_path / "fixture.json.gz"
    fixture.write_bytes(b"fixture")
    support = tmp_path / "support.geojson"
    support.write_text("{}")
    coastal = tmp_path / "coastal.geojson"
    coastal.write_text("{}")
    toolchain = tmp_path / "toolchain"
    toolchain.mkdir()
    for name in (
        "brotli",
        "tippecanoe",
        "tippecanoe-decode",
        "pmtiles",
        "tippecanoe-2.79.0.tar.gz",
        "go-pmtiles_1.31.2_Linux_x86_64.tar.gz",
    ):
        (toolchain / name).write_bytes(name.encode())
    authority = tmp_path / "authority"
    authority.mkdir()
    for name in (
        "geonames-spatial-stage-v1.receipt.json",
        "settlements.receipt.json",
    ):
        (authority / name).write_text("{}")
    tippecanoe_receipt = tmp_path / "tippecanoe-receipt.json"
    tippecanoe_receipt.write_text("{}")
    return argparse.Namespace(
        input_root=tmp_path / "inputs",
        authority_root=authority,
        toolchain_root=toolchain,
        work_root=tmp_path / "work",
        output=tmp_path / "candidate",
        candidate_id="candidate-phase-1-real-source-20260812-0123456789ab",
        data_release_id="searise-europe-v1.0.0-20260812-0123456789ab",
        generated_at="2026-08-13T00:00:00Z",
        release_contract=contract,
        source_fixture=fixture,
        source_fixture_receipt=receipt,
        tippecanoe_build_receipt=tippecanoe_receipt,
        support_geojson=support,
        coastal_geojson=coastal,
    )


def test_dispatcher_binds_exact_linux_and_retained_authorities(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    args = _arguments(tmp_path)
    observed = {}
    monkeypatch.setattr(module, "load_source_fixture", lambda *args, **kwargs: "source")

    def capture(authorities):  # type: ignore[no-untyped-def]
        observed["authorities"] = authorities
        return "dispatcher"

    monkeypatch.setattr(module, "production_validator_dispatcher", capture)
    dispatcher = module._dispatcher(args)
    authorities = observed["authorities"]

    assert dispatcher == "dispatcher"
    assert authorities.brotli == args.toolchain_root / "brotli"
    assert authorities.brotli_sha256 == module.BROTLI_LINUX_X86_64_SHA256
    assert authorities.binary.projection.platform == "linux-x86_64"
    assert authorities.binary.projection.source == "source"
    assert authorities.binary.boundary.support_geojson == args.support_geojson
    assert authorities.binary.settlement.spatial_database is None
    assert authorities.binary.settlement.artifact_receipt == (
        args.authority_root / "settlements.receipt.json"
    )


def test_assemble_creates_private_workspaces_and_reports_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    args = _arguments(tmp_path)
    monkeypatch.setattr(module, "_dispatcher", lambda value: "dispatcher")
    observed = {}

    def build(input_root, output, metadata, dispatcher):  # type: ignore[no-untyped-def]
        observed.update(
            input_root=input_root,
            output=output,
            metadata=metadata,
            dispatcher=dispatcher,
        )
        return SimpleNamespace(
            candidate_id=metadata.candidate_id,
            artifact_count=54,
            artifact_bytes=123,
            manifest_sha256="a" * 64,
            output_directory=output,
        )

    monkeypatch.setattr(module, "assemble_production_candidate", build)
    result = module.assemble(args)

    assert result == {
        "candidateId": args.candidate_id,
        "artifactCount": 54,
        "artifactBytes": 123,
        "manifestSha256": "a" * 64,
        "output": str(args.output),
    }
    assert observed["dispatcher"] == "dispatcher"
    assert observed["metadata"].data_release_id == args.data_release_id
    assert (args.work_root.stat().st_mode & 0o777) == 0o700
    assert (args.work_root / "settlement").is_dir()
    assert (args.work_root / "search").is_dir()


def test_assemble_refuses_to_reuse_work_root(tmp_path: Path) -> None:
    args = _arguments(tmp_path)
    args.work_root.mkdir()
    with pytest.raises(FileExistsError):
        module.assemble(args)
