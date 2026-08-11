"""Immutable settlement GeoParquet publication behavior."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from searise_pipeline.settlements import spatial_geoparquet as geoparquet
from searise_pipeline.settlements import spatial_geoparquet_publication as module

ROOT = Path(__file__).parents[4]
SPEC = importlib.util.spec_from_file_location(
    "settlement_geoparquet_cli", ROOT / "scripts/release/build_settlement_geoparquet.py"
)
assert SPEC is not None and SPEC.loader is not None
cli = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(cli)

RELEASE = "searise-europe-v1.0.0-20260812-34974982e794"
PAYLOAD = b"PAR1deterministic-settlement-geoparquetPAR1"


def _evidence(payload: bytes, receipt: Path) -> geoparquet.SpatialGeoParquetEvidence:
    return geoparquet.SpatialGeoParquetEvidence(
        2,
        "a" * 64,
        "b" * 64,
        hashlib.sha256(payload).hexdigest(),
        hashlib.sha256(receipt.read_bytes()).hexdigest(),
        "c" * 64,
        {
            "dataReleaseId": RELEASE,
            "mediaType": "application/vnd.apache.parquet",
            "formatVersion": "1.1.0",
            "canonicalGeometryClaim": False,
            "hazardExtentClaim": False,
            "scientificApprovalClaim": False,
            "ownerApprovalClaim": False,
            "publicationEligible": False,
        },
    )


def _fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    database, receipt = tmp_path / "spatial.db", tmp_path / "spatial.json"
    database.write_bytes(b"exact spatial database")
    receipt.write_bytes(b'{"exact":"spatial receipt"}\n')
    work = tmp_path / "work"
    work.mkdir()
    state: dict[str, list] = {
        "payloads": [PAYLOAD, PAYLOAD],
        "serialized": [],
        "validated": [],
    }

    def serialize(database, receipt, stream, **kwargs):  # type: ignore[no-untyped-def]
        index = len(state["serialized"])
        payload = state["payloads"][index]
        assert database.parent != tmp_path and receipt.parent != tmp_path
        assert kwargs == {"data_release_id": RELEASE, "work_dir": work}
        stream.write(payload)
        stream.seek(0)
        state["serialized"].append((database, receipt))
        return _evidence(payload, receipt)

    def validate(stream, database, receipt, **kwargs):  # type: ignore[no-untyped-def]
        payload = stream.read()
        stream.seek(0)
        assert database.parent != tmp_path and receipt.parent != tmp_path
        assert kwargs == {"work_dir": work}
        state["validated"].append((database, receipt))
        return _evidence(payload, receipt)

    monkeypatch.setattr(module.geoparquet, "serialize_spatial_geoparquet", serialize)
    monkeypatch.setattr(module.geoparquet, "validate_spatial_geoparquet", validate)
    monkeypatch.setattr(
        module.geoparquet,
        "_receipt",
        lambda raw: SimpleNamespace(
            receipt_sha256=hashlib.sha256(raw).hexdigest(),
            receipt_identity="d" * 64,
            candidate_identity="c" * 64,
        ),
    )
    return database, receipt, work, state


def _paths(tmp_path: Path) -> tuple[Path, Path]:
    return tmp_path / "settlements.parquet", tmp_path / "settlements.receipt.json"


def _residue(tmp_path: Path) -> list[Path]:
    roots = [tmp_path, tmp_path / "work"]
    return [
        path
        for root in roots
        if root.is_dir()
        for path in root.iterdir()
        if path.name.startswith(".spatial-assets-")
    ]


def _publish(database, receipt, output, output_receipt, work):  # type: ignore[no-untyped-def]
    return module.build_spatial_geoparquet(database, receipt, output, output_receipt, data_release_id=RELEASE, work_dir=work)  # noqa: E501  # fmt: skip


def _build(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    database, receipt, work, state = _fixture(tmp_path, monkeypatch)
    output, output_receipt = _paths(tmp_path)
    document = _publish(database, receipt, output, output_receipt, work)
    return document, output, output_receipt, state


def test_success_rebuilds_validates_twice_and_publishes_receipt_last(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original_sync = module.publication._fsync_directory
    states: list[tuple[bool, bool]] = []
    output, output_receipt = _paths(tmp_path)

    def observe(directory: object) -> None:
        original_sync(directory)
        if directory.label == "GeoParquet output directory":  # type: ignore[attr-defined]
            states.append((output.exists(), output_receipt.exists()))

    monkeypatch.setattr(module.publication, "_fsync_directory", observe)
    document, output, output_receipt, state = _build(tmp_path, monkeypatch)
    receipt = json.loads(output_receipt.read_bytes())
    assert output.read_bytes() == PAYLOAD and receipt == document
    assert len(state["serialized"]) == 2 and len(state["validated"]) == 2
    assert states == [(True, False), (True, True)]
    assert document["rebuild"]["byteForByteMatch"] is True
    assert document["source"]["spatialDatabaseSha256"] == hashlib.sha256(b"exact spatial database").hexdigest()  # noqa: E501  # fmt: skip
    unsigned = {key: value for key, value in document.items() if key != "deterministicIdentity"}
    assert document["deterministicIdentity"] == hashlib.sha256(module._canonical(unsigned) + b"\n").hexdigest()  # noqa: E501  # fmt: skip
    assert document["productionClaim"] is False
    assert all(document[name] is False for name in module._FALSE_CLAIMS)
    assert document["publicationEligible"] is False and _residue(tmp_path) == []


@pytest.mark.parametrize("target", ["artifact", "receipt"])
@pytest.mark.parametrize("kind", ["file", "symlink"])
def test_existing_outputs_are_preserved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, target: str, kind: str
) -> None:
    database, receipt, work, _ = _fixture(tmp_path, monkeypatch)
    output, output_receipt = _paths(tmp_path)
    existing = output if target == "artifact" else output_receipt
    if kind == "file":
        existing.write_bytes(b"preserve")
    else:
        existing.symlink_to(database)
    before = os.lstat(existing)
    with pytest.raises(module.SpatialGeoParquetPublicationError, match="overwrite"):
        _publish(database, receipt, output, output_receipt, work)
    after = os.lstat(existing)
    assert (after.st_dev, after.st_ino) == (before.st_dev, before.st_ino)
    assert _residue(tmp_path) == []


@pytest.mark.parametrize("failure", ["receipt-link", "published-validation"])
def test_failure_after_first_promotion_rolls_back_owned_entries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    database, receipt, work, _ = _fixture(tmp_path, monkeypatch)
    primary = module.SpatialGeoParquetPublicationError(f"injected {failure}")
    if failure == "receipt-link":
        original, calls = module.publication._link_no_overwrite, 0

        def fail_link(*args: object) -> None:
            nonlocal calls
            calls += 1
            if calls == 2:
                raise primary
            original(*args)  # type: ignore[arg-type]

        monkeypatch.setattr(module.publication, "_link_no_overwrite", fail_link)
    else:
        original, calls = module._validate_artifact, 0

        def fail_validation(*args: object) -> geoparquet.SpatialGeoParquetEvidence:
            nonlocal calls
            calls += 1
            if calls == 2:
                raise primary
            return original(*args)  # type: ignore[arg-type]

        monkeypatch.setattr(module, "_validate_artifact", fail_validation)
    output, output_receipt = _paths(tmp_path)
    with pytest.raises(module.SpatialGeoParquetPublicationError) as caught:
        _publish(database, receipt, output, output_receipt, work)
    assert caught.value is primary
    assert not output.exists() and not output_receipt.exists() and _residue(tmp_path) == []


@pytest.mark.parametrize("target", ["artifact", "receipt"])
def test_racing_replacement_is_preserved_and_owned_peer_is_removed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, target: str
) -> None:
    database, receipt, work, _ = _fixture(tmp_path, monkeypatch)
    output, output_receipt = _paths(tmp_path)
    racer = output if target == "artifact" else output_receipt
    original_sync, output_syncs = module.publication._fsync_directory, 0

    def replace(directory: object) -> None:
        nonlocal output_syncs
        original_sync(directory)
        if directory.label != "GeoParquet output directory":  # type: ignore[attr-defined]
            return
        output_syncs += 1
        if output_syncs == (1 if target == "artifact" else 2):
            racer.unlink()
            racer.write_bytes(f"alien-{target}".encode())

    monkeypatch.setattr(module.publication, "_fsync_directory", replace)
    with pytest.raises(module.SpatialGeoParquetPublicationError, match="identity changed"):
        _publish(database, receipt, output, output_receipt, work)
    assert racer.read_bytes() == f"alien-{target}".encode()
    assert not (output_receipt if target == "artifact" else output).exists()
    assert _residue(tmp_path) == []


@pytest.mark.parametrize("target", ["source", "output-parent"])
def test_input_and_intermediate_output_symlinks_are_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, target: str
) -> None:
    database, receipt, work, _ = _fixture(tmp_path, monkeypatch)
    output, output_receipt = _paths(tmp_path)
    if target == "source":
        linked = tmp_path / "linked.db"
        linked.symlink_to(database)
        database = linked
    else:
        real = tmp_path / "real-output"
        real.mkdir()
        linked = tmp_path / "linked-output"
        linked.symlink_to(real, target_is_directory=True)
        output, output_receipt = linked / output.name, linked / output_receipt.name
    with pytest.raises(module.SpatialGeoParquetPublicationError, match="symlink|open"):
        _publish(database, receipt, output, output_receipt, work)
    assert not output.exists() and not output_receipt.exists() and _residue(tmp_path) == []


def test_different_rebuild_is_rejected_without_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database, receipt, work, state = _fixture(tmp_path, monkeypatch)
    state["payloads"][1] = PAYLOAD + b"changed"
    output, output_receipt = _paths(tmp_path)
    with pytest.raises(module.SpatialGeoParquetPublicationError, match="rebuild"):
        _publish(database, receipt, output, output_receipt, work)
    assert not output.exists() and not output_receipt.exists() and _residue(tmp_path) == []


def test_staged_path_replacement_is_not_adopted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database, receipt, work, _ = _fixture(tmp_path, monkeypatch)
    original, calls = module._serialize_owned, 0

    def replace(directory, name, *args):  # type: ignore[no-untyped-def]
        nonlocal calls
        evidence = original(directory, name, *args)
        calls += 1
        if calls == 1:
            path = module.authority._descriptor_path(directory) / name
            path.unlink()
            path.write_bytes(PAYLOAD)
        return evidence

    monkeypatch.setattr(module, "_serialize_owned", replace)
    output, output_receipt = _paths(tmp_path)
    with pytest.raises(module.SpatialGeoParquetPublicationError, match="identity changed"):
        _publish(database, receipt, output, output_receipt, work)
    residue = _residue(tmp_path)
    assert len(residue) == 1 and (residue[0] / output.name).read_bytes() == PAYLOAD
    assert not output.exists() and not output_receipt.exists()


def test_partial_owned_artifact_is_removed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    database, receipt, work, _ = _fixture(tmp_path, monkeypatch)
    primary = module.SpatialGeoParquetPublicationError("injected serialization failure")

    def fail(_database, _receipt, stream, **_kwargs):  # type: ignore[no-untyped-def]
        stream.write(b"partial")
        raise primary

    monkeypatch.setattr(module.geoparquet, "serialize_spatial_geoparquet", fail)
    output, output_receipt = _paths(tmp_path)
    with pytest.raises(module.SpatialGeoParquetPublicationError) as caught:
        _publish(database, receipt, output, output_receipt, work)
    assert caught.value is primary
    assert not output.exists() and not output_receipt.exists() and _residue(tmp_path) == []


def test_pre_identity_failure_preserves_inspectable_residue(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database, receipt, work, _ = _fixture(tmp_path, monkeypatch)
    primary = module.SpatialGeoParquetPublicationError("injected pre-identity failure")

    def fail(directory, name, *_args):  # type: ignore[no-untyped-def]
        descriptor = os.open(name, module._CREATE_FLAGS, 0o600, dir_fd=directory.descriptor)
        os.write(descriptor, b"untracked")
        os.close(descriptor)
        raise primary

    monkeypatch.setattr(module, "_serialize_owned", fail)
    output, output_receipt = _paths(tmp_path)
    with pytest.raises(module.SpatialGeoParquetPublicationError) as caught:
        _publish(database, receipt, output, output_receipt, work)
    notes = " ".join(getattr(primary, "__notes__", ()))
    assert caught.value is primary
    residue = _residue(tmp_path)
    assert ("alien entry" in notes and residue[0].name in notes) if hasattr(primary, "add_note") else notes == ()  # noqa: E501  # fmt: skip
    assert len(residue) == 1 and (residue[0] / output.name).read_bytes() == b"untracked"
    assert not output.exists() and not output_receipt.exists()


def test_alien_staging_entry_is_preserved_after_successful_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = module.publication._write_owned

    def add_alien(directory, *args):  # type: ignore[no-untyped-def]
        original(directory, *args)
        (module.authority._descriptor_path(directory) / "alien").write_bytes(b"preserve")

    monkeypatch.setattr(module.publication, "_write_owned", add_alien)
    with pytest.raises(module.SpatialGeoParquetPublicationError, match="alien entry") as caught:
        _build(tmp_path, monkeypatch)
    output, output_receipt = _paths(tmp_path)
    residue = _residue(tmp_path)
    assert output.is_file() and output_receipt.is_file()
    assert len(residue) == 1 and (residue[0] / "alien").read_bytes() == b"preserve"
    assert residue[0].name in str(caught.value)


def test_cli_passes_only_explicit_reviewed_inputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    captured = {}

    def build(*args: object, **kwargs: object) -> dict[str, str]:
        captured.update(args=args, kwargs=kwargs)
        return {"deterministicIdentity": "f" * 64}

    monkeypatch.setattr(cli, "build_spatial_geoparquet", build)
    paths = [
        tmp_path / name
        for name in "spatial.db spatial.json output.parquet output.json work".split()
    ]
    arguments: list[str] = []
    for option, path in zip(
        ("spatial-db", "spatial-receipt", "output", "output-receipt", "work-dir"), paths
    ):
        arguments.extend((f"--{option}", str(path)))
    arguments.extend(("--data-release-id", RELEASE))
    assert cli.main(arguments) == 0
    assert captured == {
        "args": tuple(paths[:4]),
        "kwargs": {"data_release_id": RELEASE, "work_dir": paths[4]},
    }
    assert capsys.readouterr().out.strip() == "f" * 64
