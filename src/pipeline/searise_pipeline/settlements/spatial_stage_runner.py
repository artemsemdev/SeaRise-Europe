"""Immutable publication boundary for the settlement spatial stage."""

from __future__ import annotations

import ctypes
import os
import secrets
import stat
import sys
from contextlib import ExitStack
from pathlib import Path, PurePosixPath
from typing import Any

from . import full_source_stage as source_stage
from . import normalized_catalogue_stage as catalogue_stage
from . import spatial_asset_authority as authority
from . import spatial_classification_stage as stage
from .spatial_classification_stage import SpatialAssetInputs


class SpatialStageRunnerError(ValueError):
    """The spatial candidate could not be built and published exactly."""


# fmt: off
_FALSE_CLAIMS = ("publicationClaim", "canonicalGeometryClaim", "hazardExtentClaim", "scientificApprovalClaim", "ownerApprovalClaim")  # noqa: E501
# fmt: on


def _absent(directory: Any, name: str) -> bool:
    try:
        authority._path_stat(directory.descriptor, name)
    except FileNotFoundError:
        return True
    return False


def _fsync_directory(directory: Any) -> None:
    try:
        os.fsync(directory.descriptor)
    except OSError as exc:
        raise SpatialStageRunnerError(f"cannot fsync {directory.label}: {exc}") from exc


def _fsync_asset(asset: Any) -> None:
    try:
        os.fsync(asset.descriptor)
    except OSError as exc:
        raise SpatialStageRunnerError(f"cannot fsync {asset.label}: {exc}") from exc


def _write_owned(directory: Any, name: str, content: bytes, owned: list[tuple]) -> None:
    descriptor = -1
    primary: BaseException | None = None
    try:
        descriptor = os.open(name, authority._CREATE_FLAGS, 0o600, dir_fd=directory.descriptor)
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise SpatialStageRunnerError("spatial candidate receipt is not a regular file")
        owned.append((name, metadata.st_dev, metadata.st_ino))
        offset = 0
        while offset < len(content):
            written = os.write(descriptor, content[offset:])
            if written < 1:
                raise SpatialStageRunnerError("spatial candidate receipt produced no bytes")
            offset += written
        os.fsync(descriptor)
    except BaseException as exc:
        primary = exc
        raise
    finally:
        if descriptor >= 0:
            authority._close(descriptor, primary)


def _assert_binding(directory: Any, name: str, asset: Any) -> None:
    try:
        current = authority._path_stat(directory.descriptor, name)
    except OSError as exc:
        raise SpatialStageRunnerError(f"{asset.label} entry identity changed") from exc
    if (
        not stat.S_ISREG(current.st_mode)
        or authority._identity(current) != (asset.device, asset.inode)
        or current.st_size != asset.size
    ):
        raise SpatialStageRunnerError(f"{asset.label} entry identity changed")
    authority._assert_asset(asset)


def _link_no_overwrite(source: Any, name: str, output: Any) -> None:
    os.link(
        name,
        name,
        src_dir_fd=source.descriptor,
        dst_dir_fd=output.descriptor,
        follow_symlinks=False,
    )


def _rename_no_overwrite(source: Any, name: str, output: Any, target: str) -> None:
    libc = ctypes.CDLL(None, use_errno=True)
    if sys.platform == "darwin":
        rename, flag = libc.renameatx_np, 4
    elif sys.platform.startswith("linux"):
        rename, flag = libc.renameat2, 1
    else:
        raise SpatialStageRunnerError("exclusive rollback rename is unsupported")
    rename.argtypes = (
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    )
    rename.restype = ctypes.c_int
    result = rename(
        source.descriptor,
        os.fsencode(name),
        output.descriptor,
        os.fsencode(target),
        flag,
    )
    if result != 0:
        code = ctypes.get_errno()
        raise OSError(code, os.strerror(code), name)


def _rollback_owned(output: Any, name: str, expected: Any, quarantine: Any) -> str | None:
    retained = f".rollback-{secrets.token_hex(12)}"
    try:
        _rename_no_overwrite(output, name, quarantine, retained)
    except FileNotFoundError:
        return None
    except OSError as exc:
        return f"cannot quarantine {name}: {exc}"
    try:
        moved = authority._path_stat(quarantine.descriptor, retained)
        if stat.S_ISREG(moved.st_mode) and authority._identity(moved) == (
            expected.device,
            expected.inode,
        ):
            os.unlink(retained, dir_fd=quarantine.descriptor)
            return None
        os.link(
            retained,
            name,
            src_dir_fd=quarantine.descriptor,
            dst_dir_fd=output.descriptor,
            follow_symlinks=False,
        )
        os.unlink(retained, dir_fd=quarantine.descriptor)
        return None
    except OSError as exc:
        return f"foreign {name} retained as {retained}: {exc}"


def _rollback_publication(
    primary: BaseException,
    output: Any,
    quarantine: Any,
    promoted: list[tuple[str, Any]],
) -> None:
    for name, asset in reversed(promoted):
        try:
            error = _rollback_owned(output, name, asset, quarantine)
        except BaseException as cleanup:
            authority._note_cleanup(primary, cleanup)
            continue
        if error is not None:
            authority._note_cleanup(primary, error)
    try:
        _fsync_directory(output)
    except BaseException as cleanup:
        authority._note_cleanup(primary, cleanup)


def _claims_are_false(identity: dict[str, Any]) -> None:
    geometry = identity.get("geometry")
    if (
        any(identity.get(name) is not False for name in _FALSE_CLAIMS)
        or type(geometry) is not dict
        or geometry.get("publicationEligible") is not False
    ):
        raise SpatialStageRunnerError("spatial candidate attempted to broaden its claims")


def _receipt_bytes(identity: dict[str, Any]) -> tuple[dict[str, Any], bytes]:
    document = stage.spatial_receipt(identity)
    try:
        content = (source_stage._canonical_json(document) + "\n").encode("utf-8")
    except (ValueError, UnicodeEncodeError) as exc:
        raise SpatialStageRunnerError("spatial receipt cannot be canonicalized") from exc
    return document, content


def _reject_wal(directory: Any, database_name: str) -> None:
    if not _absent(directory, f"{database_name}.wal"):
        raise SpatialStageRunnerError("spatial candidate retained a DuckDB WAL")


def _build_in_private(
    catalogue_database: Path,
    catalogue_receipt: Path,
    output: Path,
    receipt_path: Path,
    inputs: SpatialAssetInputs,
    output_directory: Any,
    private: Any,
    owned: list[tuple],
) -> dict[str, Any]:
    promoted: list[tuple[str, Any]] = []
    database_asset = receipt_asset = None
    document: dict[str, Any]
    try:
        with ExitStack() as stack:
            source_root, sources = stack.enter_context(
                stage._validation_snapshots(
                    {
                        "catalogue.duckdb": catalogue_database,
                        "catalogue-receipt.json": catalogue_receipt,
                    },
                    inputs.work_dir,
                )
            )
            receipt = catalogue_stage._load_catalogue_receipt_bytes(
                stage._read_asset(sources["catalogue-receipt.json"])
            )
            private_root = authority._descriptor_path(private)
            database_path = private_root / output.name
            candidate_receipt = private_root / receipt_path.name
            duckdb, _ = source_stage._load_tools()
            with duckdb.connect(str(source_root / "catalogue.duckdb"), read_only=True) as catalogue:
                with duckdb.connect(str(database_path)) as candidate:
                    identity = stage.materialize_spatial_candidate(
                        catalogue, candidate, receipt, asset_inputs=inputs
                    )
                    candidate.execute("CHECKPOINT")
            _reject_wal(private, output.name)
            database_asset = stack.enter_context(
                authority._open_asset(private, PurePosixPath(output.name), "spatial candidate DB")
            )
            owned.append((output.name, database_asset.device, database_asset.inode))
            _fsync_asset(database_asset)
            _claims_are_false(identity)
            document, content = _receipt_bytes(identity)
            _write_owned(private, receipt_path.name, content, owned)
            receipt_asset = stack.enter_context(
                authority._open_asset(
                    private, PurePosixPath(receipt_path.name), "spatial candidate receipt"
                )
            )
            stage.validate_spatial_stage(
                database_path,
                candidate_receipt,
                source_root / "catalogue.duckdb",
                source_root / "catalogue-receipt.json",
                asset_inputs=inputs,
            )
            authority._assert_directory(output_directory)
            _link_no_overwrite(private, output.name, output_directory)
            promoted.append((output.name, database_asset))
            _fsync_directory(output_directory)
            _assert_binding(output_directory, output.name, database_asset)
            _link_no_overwrite(private, receipt_path.name, output_directory)
            promoted.append((receipt_path.name, receipt_asset))
            _fsync_directory(output_directory)
            _assert_binding(output_directory, output.name, database_asset)
            _assert_binding(output_directory, receipt_path.name, receipt_asset)
            stage.validate_spatial_stage(
                output,
                receipt_path,
                source_root / "catalogue.duckdb",
                source_root / "catalogue-receipt.json",
                asset_inputs=inputs,
            )
            _assert_binding(output_directory, output.name, database_asset)
            _assert_binding(output_directory, receipt_path.name, receipt_asset)
            authority._assert_directory(output_directory)
    except BaseException as primary:
        if promoted:
            _rollback_publication(primary, output_directory, private, promoted)
        raise
    return document


def build_spatial_stage(
    catalogue_database: Path,
    catalogue_receipt: Path,
    output: Path,
    receipt_path: Path,
    *,
    asset_inputs: SpatialAssetInputs,
) -> dict[str, Any]:
    """Build, independently validate, and immutably publish one spatial pair."""
    try:
        with ExitStack() as stack:
            output_parent = stack.enter_context(
                authority._open_directory_path(output.parent, "spatial output directory")
            )
            receipt_parent = stack.enter_context(
                authority._open_directory_path(receipt_path.parent, "spatial receipt directory")
            )
            authority._assert_secure_work_directory(output_parent)
            if output.name == receipt_path.name or (output_parent.device, output_parent.inode) != (
                receipt_parent.device,
                receipt_parent.inode,
            ):
                raise SpatialStageRunnerError(
                    "spatial database and receipt need distinct paths in one directory"
                )
            if not _absent(output_parent, output.name) or not _absent(
                output_parent, receipt_path.name
            ):
                raise SpatialStageRunnerError("spatial output exists; overwrite is refused")
            published_root = authority._descriptor_path(output_parent)
            output, receipt_path = published_root / output.name, published_root / receipt_path.name
            private_name, private = authority._create_private(output_parent)
            authority._stack_close(stack, private.descriptor)
            owned: list[tuple] = []
            primary: BaseException | None = None
            try:
                return _build_in_private(
                    catalogue_database,
                    catalogue_receipt,
                    output,
                    receipt_path,
                    asset_inputs,
                    output_parent,
                    private,
                    owned,
                )
            except BaseException as exc:
                primary = exc
                raise
            finally:
                try:
                    authority._remove_private(
                        output_parent, private_name, private, tuple(owned), ()
                    )
                except BaseException as cleanup:
                    if primary is None:
                        raise
                    authority._note_cleanup(primary, cleanup)
    except SpatialStageRunnerError:
        raise
    except Exception as exc:
        raise SpatialStageRunnerError(f"spatial stage publication failed: {exc}") from exc
