"""Immutable settlement spatial-stage runner behavior."""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
from types import SimpleNamespace

import duckdb
import pytest

from searise_pipeline.settlements import full_source_stage as source_stage
from searise_pipeline.settlements import spatial_stage_runner as runner
from searise_pipeline.settlements.spatial_classification_stage import SpatialAssetInputs

ROOT = Path(__file__).parents[4]
SPEC = importlib.util.spec_from_file_location(
    "settlement_spatial_cli", ROOT / "scripts/release/build_settlement_spatial_stage.py"
)
assert SPEC is not None and SPEC.loader is not None
spatial_cli = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(spatial_cli)

IDENTITY = {
    "publicationClaim": False,
    "canonicalGeometryClaim": False,
    "hazardExtentClaim": False,
    "scientificApprovalClaim": False,
    "ownerApprovalClaim": False,
    "geometry": {"publicationEligible": False},
    "deterministicIdentity": "a" * 64,
}


def _fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    catalogue = tmp_path / "catalogue.duckdb"
    with duckdb.connect(str(catalogue)) as connection:
        connection.execute("CREATE TABLE marker(value INTEGER)")
    catalogue_receipt = tmp_path / "catalogue.json"
    catalogue_receipt.write_bytes(b"{}\n")
    work = tmp_path / "work"
    work.mkdir()
    inputs = SpatialAssetInputs(tmp_path, tmp_path, work, tmp_path / "manifest.json", None, None)

    def materialize(_catalogue, candidate, _receipt, **_kwargs):  # type: ignore[no-untyped-def]
        candidate.execute("CREATE TABLE spatial_marker(value INTEGER)")
        return dict(IDENTITY)

    validations: list[tuple[Path, Path]] = []

    def validate(database, receipt, *_args, **_kwargs):  # type: ignore[no-untyped-def]
        database, receipt = Path(database), Path(receipt)
        with duckdb.connect(str(database), read_only=True) as connection:
            assert connection.execute("SELECT count(*) FROM spatial_marker").fetchone() == (0,)
        assert receipt.read_bytes().endswith(b"\n")
        validations.append((database, receipt))

    monkeypatch.setattr(runner.catalogue_stage, "_load_catalogue_receipt_bytes", lambda _: {})
    monkeypatch.setattr(runner.stage, "materialize_spatial_candidate", materialize)
    monkeypatch.setattr(runner.stage, "validate_spatial_stage", validate)
    return catalogue, catalogue_receipt, inputs, validations


def _paths(tmp_path: Path) -> tuple[Path, Path]:
    return tmp_path / "spatial.duckdb", tmp_path / "spatial.json"


def _residue(tmp_path: Path) -> list[Path]:
    return [path for path in tmp_path.iterdir() if path.name.startswith(".spatial-assets-")]


def test_success_closes_connections_validates_twice_and_publishes_receipt_last(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    catalogue, catalogue_receipt, inputs, validations = _fixture(tmp_path, monkeypatch)
    output, receipt = _paths(tmp_path)
    real_duckdb, pa = source_stage._load_tools()
    closed: list[bool] = []

    class Connection:
        def __init__(self, path: str, **options: object):
            self.inner = real_duckdb.connect(path, **options)

        def __enter__(self):  # type: ignore[no-untyped-def]
            return self

        def __exit__(self, *_args):  # type: ignore[no-untyped-def]
            self.inner.close()
            closed.append(True)

        def __getattr__(self, name: str):
            return getattr(self.inner, name)

    module = SimpleNamespace(connect=Connection)
    monkeypatch.setattr(runner.source_stage, "_load_tools", lambda: (module, pa))
    original_sync = runner._fsync_directory
    states = []

    def observe(directory: object) -> None:
        original_sync(directory)
        states.append((output.exists(), receipt.exists()))

    monkeypatch.setattr(runner, "_fsync_directory", observe)
    document = runner.build_spatial_stage(
        catalogue, catalogue_receipt, output, receipt, asset_inputs=inputs
    )
    assert closed == [True, True]
    assert len(validations) == 2 and closed
    assert states == [(True, False), (True, True)]
    assert receipt.read_bytes() == runner._receipt_bytes(document["candidate"])[1]
    assert document["candidate"] == IDENTITY
    assert _residue(tmp_path) == []


def test_candidate_close_failure_preserves_primary_and_pre_identity_database(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    catalogue, catalogue_receipt, inputs, _ = _fixture(tmp_path, monkeypatch)
    real_duckdb, pa = source_stage._load_tools()
    primary = runner.SpatialStageRunnerError("injected candidate close failure")

    class Connection:
        def __init__(self, path: str, **options: object):
            self.inner = real_duckdb.connect(path, **options)
            self.fail = not options.get("read_only", False)

        def __enter__(self):  # type: ignore[no-untyped-def]
            return self

        def __exit__(self, *_args):  # type: ignore[no-untyped-def]
            self.inner.close()
            if self.fail:
                raise primary

        def __getattr__(self, name: str):
            return getattr(self.inner, name)

    monkeypatch.setattr(
        runner.source_stage, "_load_tools", lambda: (SimpleNamespace(connect=Connection), pa)
    )  # noqa: E501
    output, receipt = _paths(tmp_path)
    with pytest.raises(runner.SpatialStageRunnerError) as caught:
        runner.build_spatial_stage(
            catalogue, catalogue_receipt, output, receipt, asset_inputs=inputs
        )
    assert caught.value is primary
    assert any((path / output.name).is_file() for path in _residue(tmp_path))
    assert not output.exists() and not receipt.exists()


@pytest.mark.parametrize("target", ["database", "receipt"])
@pytest.mark.parametrize("kind", ["file", "symlink"])
def test_collision_and_symlink_outputs_are_preserved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, target: str, kind: str
) -> None:
    catalogue, catalogue_receipt, inputs, _ = _fixture(tmp_path, monkeypatch)
    output, receipt = _paths(tmp_path)
    existing = output if target == "database" else receipt
    if kind == "file":
        existing.write_bytes(b"preserve")
    else:
        existing.symlink_to(catalogue)
    before = os.lstat(existing)
    with pytest.raises(runner.SpatialStageRunnerError, match="overwrite"):
        runner.build_spatial_stage(
            catalogue, catalogue_receipt, output, receipt, asset_inputs=inputs
        )
    after = os.lstat(existing)
    assert (after.st_dev, after.st_ino) == (before.st_dev, before.st_ino)
    assert _residue(tmp_path) == []


def test_symlink_catalogue_is_rejected_without_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    catalogue, catalogue_receipt, inputs, _ = _fixture(tmp_path, monkeypatch)
    linked = tmp_path / "catalogue-link.duckdb"
    linked.symlink_to(catalogue)
    output, receipt = _paths(tmp_path)
    with pytest.raises(runner.SpatialStageRunnerError, match="symlink|open"):
        runner.build_spatial_stage(linked, catalogue_receipt, output, receipt, asset_inputs=inputs)
    assert linked.is_symlink() and not output.exists() and not receipt.exists()


@pytest.mark.parametrize("target", ["database", "receipt"])
def test_racing_replacement_is_restored_and_owned_peer_is_rolled_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, target: str
) -> None:
    catalogue, catalogue_receipt, inputs, _ = _fixture(tmp_path, monkeypatch)
    output, receipt = _paths(tmp_path)
    racer = output if target == "database" else receipt
    trigger = 1 if target == "database" else 2
    original_sync, calls = runner._fsync_directory, 0

    def replace(directory: object) -> None:
        nonlocal calls
        original_sync(directory)
        calls += 1
        if calls == trigger:
            racer.unlink()
            racer.write_bytes(f"alien-{target}".encode())

    monkeypatch.setattr(runner, "_fsync_directory", replace)
    with pytest.raises(runner.SpatialStageRunnerError, match="identity changed"):
        runner.build_spatial_stage(
            catalogue, catalogue_receipt, output, receipt, asset_inputs=inputs
        )
    assert racer.read_bytes() == f"alien-{target}".encode()
    assert not (receipt if target == "database" else output).exists()
    assert _residue(tmp_path) == []


def test_pre_identity_failure_preserves_primary_and_inspectable_residue(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    catalogue, catalogue_receipt, inputs, _ = _fixture(tmp_path, monkeypatch)
    primary = runner.SpatialStageRunnerError("injected materialization failure")

    def fail(_catalogue, candidate, *_args, **_kwargs):  # type: ignore[no-untyped-def]
        candidate.execute("CREATE TABLE partial(value INTEGER)")
        raise primary

    monkeypatch.setattr(runner.stage, "materialize_spatial_candidate", fail)
    output, receipt = _paths(tmp_path)
    with pytest.raises(runner.SpatialStageRunnerError) as caught:
        runner.build_spatial_stage(
            catalogue, catalogue_receipt, output, receipt, asset_inputs=inputs
        )
    assert caught.value is primary
    assert "alien entry" in " ".join(getattr(primary, "__notes__", ()))
    assert any((path / output.name).is_file() for path in _residue(tmp_path))
    assert not output.exists() and not receipt.exists()


def test_partial_owned_receipt_is_cleaned_without_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    catalogue, catalogue_receipt, inputs, _ = _fixture(tmp_path, monkeypatch)
    active = False
    original_materialize = runner.stage.materialize_spatial_candidate
    original_write = runner.os.write

    def materialize(*args: object, **kwargs: object):  # type: ignore[no-untyped-def]
        nonlocal active
        value = original_materialize(*args, **kwargs)
        active = True
        return value

    def write(descriptor: int, content: bytes) -> int:
        nonlocal active
        if active:
            active = False
            return 0
        return original_write(descriptor, content)

    monkeypatch.setattr(runner.stage, "materialize_spatial_candidate", materialize)
    monkeypatch.setattr(runner.os, "write", write)
    output, receipt = _paths(tmp_path)
    with pytest.raises(runner.SpatialStageRunnerError, match="produced no bytes"):
        runner.build_spatial_stage(
            catalogue, catalogue_receipt, output, receipt, asset_inputs=inputs
        )
    assert not output.exists() and not receipt.exists() and _residue(tmp_path) == []


@pytest.mark.parametrize("failure", ["receipt-link", "final-validation"])
def test_publication_failure_rolls_back_only_owned_entries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    catalogue, catalogue_receipt, inputs, _ = _fixture(tmp_path, monkeypatch)
    primary = runner.SpatialStageRunnerError(f"injected {failure} failure")
    if failure == "receipt-link":
        original, calls = runner._link_no_overwrite, 0

        def fail_link(*args: object, **kwargs: object) -> None:
            nonlocal calls
            calls += 1
            if calls == 2:
                raise primary
            original(*args, **kwargs)  # type: ignore[arg-type]

        monkeypatch.setattr(runner, "_link_no_overwrite", fail_link)
    else:
        original, calls = runner.stage.validate_spatial_stage, 0

        def fail_validation(*args: object, **kwargs: object) -> None:
            nonlocal calls
            calls += 1
            if calls == 2:
                raise primary
            original(*args, **kwargs)

        monkeypatch.setattr(runner.stage, "validate_spatial_stage", fail_validation)
    output, receipt = _paths(tmp_path)
    with pytest.raises(runner.SpatialStageRunnerError) as caught:
        runner.build_spatial_stage(
            catalogue, catalogue_receipt, output, receipt, asset_inputs=inputs
        )
    assert caught.value is primary
    assert not output.exists() and not receipt.exists() and _residue(tmp_path) == []


def test_alien_staging_entry_is_preserved_on_cleanup_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    catalogue, catalogue_receipt, inputs, _ = _fixture(tmp_path, monkeypatch)
    original = runner._write_owned

    def add_alien(directory, *args):  # type: ignore[no-untyped-def]
        original(directory, *args)
        (runner.authority._descriptor_path(directory) / "alien").write_bytes(b"preserve")

    monkeypatch.setattr(runner, "_write_owned", add_alien)
    output, receipt = _paths(tmp_path)
    with pytest.raises(runner.SpatialStageRunnerError, match="alien entry"):
        runner.build_spatial_stage(
            catalogue, catalogue_receipt, output, receipt, asset_inputs=inputs
        )
    residue = _residue(tmp_path)
    assert len(residue) == 1 and (residue[0] / "alien").read_bytes() == b"preserve"
    assert output.is_file() and receipt.is_file()


def test_cli_constructs_reviewed_explicit_inputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    manifest, evidence, geometry = object(), object(), object()
    monkeypatch.setattr(spatial_cli, "load_spatial_manifest", lambda _: manifest)
    monkeypatch.setattr(spatial_cli, "verify_spatial_toolchain", lambda *args, **kwargs: evidence)
    monkeypatch.setattr(spatial_cli, "production_geometry_bindings", lambda _: geometry)
    captured = {}

    def build(*args: object, **kwargs: object) -> dict[str, str]:
        captured.update(args=args, kwargs=kwargs)
        return {"deterministicIdentity": "d" * 64}

    monkeypatch.setattr(spatial_cli, "build_spatial_stage", build)
    names = "catalogue.db catalogue.json output.db output.json repository cache work manifest"
    paths = [tmp_path / name for name in names.split()]
    arguments = []
    for option, path in zip(
        (
            "catalogue-db",
            "catalogue-receipt",
            "output-db",
            "output-receipt",
            "repository-root",
            "spatial-cache-root",
            "work-dir",
            "toolchain-manifest",
        ),
        paths,
    ):
        arguments.extend((f"--{option}", str(path)))
    arguments.extend(("--platform", "linux-x86_64", "--geometry-profile", "production-reviewed"))
    assert spatial_cli.main(arguments) == 0
    assert captured["args"] == tuple(paths[:4])
    inputs = captured["kwargs"]["asset_inputs"]
    assert inputs == SpatialAssetInputs(*paths[4:], evidence, geometry)
    assert capsys.readouterr().out.strip() == "d" * 64
