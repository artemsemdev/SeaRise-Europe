from __future__ import annotations

import errno
import fcntl
import hashlib
import os
import secrets
import stat
import sys
from collections import namedtuple
from contextlib import ExitStack, contextmanager
from pathlib import Path, PurePosixPath
from typing import Iterator

from .spatial_classification import (
    SPATIAL_TOOLCHAIN_MANIFEST_SHA256,
    GeometryBindings,
    SpatialClassificationError,
    _validate_geometry,
)
from .spatial_toolchain import (
    SpatialToolchainError,
    SpatialToolchainEvidence,
    load_spatial_manifest,
)

_NOFOLLOW_FLAGS = sum(getattr(os, flag, 0) for flag in ("O_CLOEXEC", "O_NOFOLLOW"))
_DIRECTORY_FLAGS = os.O_RDONLY | _NOFOLLOW_FLAGS | getattr(os, "O_DIRECTORY", 0)
_FILE_FLAGS = os.O_RDONLY | _NOFOLLOW_FLAGS | getattr(os, "O_NONBLOCK", 0)
_CREATE_FLAGS = os.O_WRONLY | os.O_CREAT | os.O_EXCL | _NOFOLLOW_FLAGS


class SpatialAssetAuthorityError(ValueError):
    """A spatial source cannot be admitted to a private build authority."""


GeometrySnapshot = namedtuple("GeometrySnapshot", "role path sha256")
SpatialAssetPaths = namedtuple(
    "SpatialAssetPaths",
    "manifest_path manifest_sha256 extension_path extension_sha256 "
    "geometries geometry_contract_sha256 evidence",
)
_Directory = namedtuple("_Directory", "descriptor parent name label device inode")
_Asset = namedtuple("_Asset", "descriptor parent name label device inode size sha256 directories")


def _identity(metadata: os.stat_result) -> tuple[int, int]:
    return metadata.st_dev, metadata.st_ino


def _fd_stat(descriptor: int) -> os.stat_result:
    try:
        return os.fstat(descriptor)
    except OSError:
        return os.stat(descriptor)


def _scan_stat(parent: int, name: str) -> os.stat_result:
    try:
        with os.scandir(parent) as entries:
            for entry in entries:
                if entry.name == name:
                    return entry.stat(follow_symlinks=False)
        raise FileNotFoundError(name)
    except OSError:
        with ExitStack() as stack:
            return _fd_stat(_stack_open(stack, name, _FILE_FLAGS, dir_fd=parent))


def _path_stat(parent: int, name: str) -> os.stat_result:
    try:
        return os.stat(name, dir_fd=parent, follow_symlinks=False)
    except OSError:
        try:
            return os.lstat(name, dir_fd=parent)
        except OSError:
            return _scan_stat(parent, name)


def _sha256_descriptor(descriptor: int, size: int) -> str:
    digest = hashlib.sha256()
    offset = 0
    while offset < size:
        chunk = os.pread(descriptor, min(1024 * 1024, size - offset), offset)
        if not chunk:
            raise SpatialAssetAuthorityError("opened spatial asset size changed")
        digest.update(chunk)
        offset += len(chunk)
    return digest.hexdigest()


def _directory(descriptor: int, parent: int | None, name: str, label: str) -> _Directory:
    metadata = _fd_stat(descriptor)
    if not stat.S_ISDIR(metadata.st_mode):
        raise SpatialAssetAuthorityError(f"{label} must be a directory without symlinks")
    return _Directory(descriptor, parent, name, label, *_identity(metadata))


def _asset(descriptor, parent, name, label, directories=()):  # type: ignore[no-untyped-def]
    metadata = _fd_stat(descriptor)
    if not stat.S_ISREG(metadata.st_mode):
        raise SpatialAssetAuthorityError(f"{label} must be a regular file without symlinks")
    device, inode = _identity(metadata)
    digest = _sha256_descriptor(descriptor, metadata.st_size)
    return _Asset(
        descriptor, parent, name, label, device, inode, metadata.st_size, digest, directories
    )


def _raise_open_error(label: str, exc: OSError) -> None:
    if exc.errno in (errno.ELOOP, errno.ENOTDIR):
        raise SpatialAssetAuthorityError(f"{label} path contains an intermediate symlink") from exc
    raise SpatialAssetAuthorityError(f"cannot open {label}: {exc}") from exc


def _note_cleanup(error: object, cleanup: object) -> None:
    getattr(error, "add_note", lambda _: None)(f"spatial cleanup failed closed: {cleanup}")


def _close(descriptor: int, error: BaseException | None = None) -> None:
    try:
        os.close(descriptor)
    except BaseException as cleanup:
        if error is None:
            raise
        _note_cleanup(error, cleanup)


def _stack_close(stack: ExitStack, descriptor: int) -> int:
    def close(_kind, error, _traceback):  # type: ignore[no-untyped-def]
        _close(descriptor, error)

    stack.push(close)
    return descriptor


def _stack_open(stack, *args, **kwargs):  # type: ignore[no-untyped-def]
    return _stack_close(stack, os.open(*args, **kwargs))


@contextmanager
def _validated(value, items, validate):  # type: ignore[no-untyped-def]
    try:
        yield value
    except BaseException as primary:
        try:
            for item in items:
                validate(item)
        except BaseException as secondary:
            _note_cleanup(primary, secondary)
        raise
    for item in items:
        validate(item)


def _assert_directory(directory: _Directory) -> None:
    opened = _fd_stat(directory.descriptor)
    try:
        if directory.parent is None:
            current = os.lstat("/")
        else:
            current = _path_stat(directory.parent, directory.name)
    except OSError as exc:
        raise SpatialAssetAuthorityError(f"{directory.label} path identity changed") from exc
    if (
        not stat.S_ISDIR(opened.st_mode)
        or not stat.S_ISDIR(current.st_mode)
        or _identity(opened) != (directory.device, directory.inode)
        or _identity(current) != (directory.device, directory.inode)
    ):
        raise SpatialAssetAuthorityError(f"{directory.label} path identity changed")


def _absolute(path: Path, label: str) -> Path:
    if ".." in path.parts:
        raise SpatialAssetAuthorityError(f"{label} path contains parent traversal")
    return path.absolute()


@contextmanager
def _open_directory_path(path: Path, label: str) -> Iterator[_Directory]:
    absolute = _absolute(path, label)
    with ExitStack() as stack:
        opened = []
        try:
            root_fd = _stack_open(stack, "/", _DIRECTORY_FLAGS)
            current = _directory(root_fd, None, "/", "filesystem root")
            opened.append(current)
            for index, part in enumerate(absolute.parts[1:], 1):
                descriptor = _stack_open(stack, part, _DIRECTORY_FLAGS, dir_fd=current.descriptor)
                child_label = label if index == len(absolute.parts) - 1 else f"{label} ancestor"
                current = _directory(descriptor, current.descriptor, part, child_label)
                opened.append(current)
        except OSError as exc:
            _raise_open_error(label, exc)
        with _validated(current, opened, _assert_directory):
            yield current


def _relative(value: str | Path, label: str) -> PurePosixPath:
    path = PurePosixPath(str(value))
    if not path.parts or path.is_absolute() or ".." in path.parts:
        raise SpatialAssetAuthorityError(f"{label} path is unsafe")
    return path


@contextmanager
def _open_asset(root: _Directory, relative: PurePosixPath, label: str) -> Iterator[_Asset]:
    with ExitStack() as stack:
        directories = []
        current = root
        try:
            for part in relative.parts[:-1]:
                child = _stack_open(stack, part, _DIRECTORY_FLAGS, dir_fd=current.descriptor)
                current = _directory(child, current.descriptor, part, f"{label} ancestor")
                directories.append(current)
            descriptor = _stack_open(stack, relative.name, _FILE_FLAGS, dir_fd=current.descriptor)
            asset = _asset(descriptor, current.descriptor, relative.name, label, tuple(directories))
        except OSError as exc:
            _raise_open_error(label, exc)
        with _validated(asset, (asset,), _assert_asset):
            yield asset


def _assert_asset(asset: _Asset) -> None:
    for directory in asset.directories:
        _assert_directory(directory)
    opened = _fd_stat(asset.descriptor)
    try:
        current = _path_stat(asset.parent, asset.name)
    except OSError as exc:
        raise SpatialAssetAuthorityError(f"{asset.label} path identity changed") from exc
    if (
        not stat.S_ISREG(opened.st_mode)
        or not stat.S_ISREG(current.st_mode)
        or _identity(opened) != (asset.device, asset.inode)
        or _identity(current) != (asset.device, asset.inode)
        or opened.st_size != asset.size
        or _sha256_descriptor(asset.descriptor, asset.size) != asset.sha256
    ):
        raise SpatialAssetAuthorityError(f"{asset.label} identity changed while in use")


def _enter_asset(stack: ExitStack, root: _Directory, path: str | Path, label: str) -> _Asset:
    return stack.enter_context(_open_asset(root, _relative(path, label), label))


def _descriptor_path(directory: _Directory) -> Path:
    try:
        if sys.platform == "darwin":
            raw = fcntl.fcntl(directory.descriptor, 50, b"\0" * 1024)
            path = Path(os.fsdecode(raw.split(b"\0", 1)[0]))
        else:
            path = Path(os.readlink(f"/proc/self/fd/{directory.descriptor}"))
        metadata = path.lstat()
    except OSError as exc:
        raise SpatialAssetAuthorityError("cannot resolve private spatial directory") from exc
    if _identity(metadata) != (directory.device, directory.inode):
        raise SpatialAssetAuthorityError("private spatial directory path identity changed")
    return path


def _create_private(parent: _Directory) -> tuple[str, _Directory]:
    for _ in range(128):
        name = f".spatial-assets-{secrets.token_hex(12)}"
        try:
            os.mkdir(name, mode=0o700, dir_fd=parent.descriptor)
        except FileExistsError:
            continue
        descriptor = -1
        created_identity = None
        try:
            descriptor = os.open(name, _DIRECTORY_FLAGS, dir_fd=parent.descriptor)
            created = _directory(descriptor, parent.descriptor, name, "private spatial directory")
            created_identity = created.device, created.inode
            metadata = _path_stat(parent.descriptor, name)
            if not stat.S_ISDIR(metadata.st_mode) or _identity(metadata) != created_identity:
                raise SpatialAssetAuthorityError("private directory replaced; cleanup refused")
            return name, created
        except BaseException as exc:
            if descriptor >= 0:
                _close(descriptor, exc)
            if created_identity is not None:
                try:
                    parent_fd = parent.descriptor
                    tombstone = _move_owned(parent_fd, name, created_identity, directory=True)
                    os.rmdir(tombstone, dir_fd=parent_fd)
                except BaseException as cleanup_error:
                    _note_cleanup(exc, cleanup_error)
            raise
    raise SpatialAssetAuthorityError("cannot allocate a private spatial directory")


def _assert_secure_work_directory(directory: _Directory) -> None:
    metadata = _fd_stat(directory.descriptor)
    if metadata.st_uid != os.geteuid() or stat.S_IMODE(metadata.st_mode) & 0o022:
        raise SpatialAssetAuthorityError("work directory must be owner-controlled")


def _copy_asset(source, private, name, owned):  # type: ignore[no-untyped-def]
    with ExitStack() as copying:
        destination = _stack_open(copying, name, _CREATE_FLAGS, 0o600, dir_fd=private.descriptor)
        metadata = _fd_stat(destination)
        created_identity = _identity(metadata)
        owned.append((name, *created_identity))
        current = _path_stat(private.descriptor, name)
        if not stat.S_ISREG(current.st_mode) or _identity(current) != created_identity:
            raise SpatialAssetAuthorityError("private spatial file was replaced; cleanup refused")
        offset = 0
        while offset < source.size:
            chunk = os.pread(source.descriptor, min(1024 * 1024, source.size - offset), offset)
            if not chunk:
                raise SpatialAssetAuthorityError(f"{source.label} changed while copied")
            written = 0
            while written < len(chunk):
                count = os.write(destination, chunk[written:])
                if count < 1:
                    raise SpatialAssetAuthorityError("private spatial copy produced no bytes")
                written += count
            offset += len(chunk)
    _assert_asset(source)
    descriptor = os.open(name, _FILE_FLAGS, dir_fd=private.descriptor)
    try:
        snapshot = _asset(descriptor, private.descriptor, name, f"private {source.label}")
        if snapshot.size != source.size or snapshot.sha256 != source.sha256:
            raise SpatialAssetAuthorityError(f"private {source.label} differs from source")
    except BaseException as exc:
        _close(descriptor, exc)
        raise
    return snapshot


def _move_owned(parent: int, name: str, identity: tuple[int, int], *, directory: bool) -> str:
    tombstone = f".remove-{secrets.token_hex(12)}"
    os.rename(name, tombstone, src_dir_fd=parent, dst_dir_fd=parent)
    moved = _path_stat(parent, tombstone)
    expected_type = stat.S_ISDIR if directory else stat.S_ISREG
    if _identity(moved) != identity or not expected_type(moved.st_mode):
        try:
            _path_stat(parent, name)
        except FileNotFoundError:
            os.rename(tombstone, name, src_dir_fd=parent, dst_dir_fd=parent)
        raise SpatialAssetAuthorityError("owned spatial entry changed; cleanup refused")
    return tombstone


def _remove_private(parent, name, private, owned, snapshots):  # type: ignore[no-untyped-def]
    if set(os.listdir(private.descriptor)) != {item[0] for item in owned}:
        raise SpatialAssetAuthorityError("private spatial directory has an alien entry")
    for snapshot in snapshots:
        _assert_asset(snapshot)
    _assert_directory(private)
    for owned_name, device, inode in owned:
        tombstone = _move_owned(private.descriptor, owned_name, (device, inode), directory=False)
        moved = _path_stat(private.descriptor, tombstone)
        if _identity(moved) != (device, inode):
            raise SpatialAssetAuthorityError("snapshot changed before removal; cleanup refused")
        os.unlink(tombstone, dir_fd=private.descriptor)
    identity = private.device, private.inode
    tombstone = _move_owned(parent.descriptor, name, identity, directory=True)
    os.rmdir(tombstone, dir_fd=parent.descriptor)


def _validate_evidence(manifest_path: Path, evidence: SpatialToolchainEvidence) -> None:
    try:
        manifest = load_spatial_manifest(manifest_path)
        pin = manifest.platforms[evidence.platform]
    except (KeyError, SpatialToolchainError) as exc:
        raise SpatialAssetAuthorityError("spatial toolchain evidence is not pinned") from exc
    if (
        evidence.duckdb_version != manifest.duckdb_version
        or evidence.extension_path != pin.extension.relative_path
        or evidence.extension_sha256 != pin.extension.sha256
        or evidence.smoke_point != (12.5, 41.9)
        or evidence.smoke_distance != 5.0
    ):
        raise SpatialAssetAuthorityError("spatial toolchain evidence differs from the manifest")


@contextmanager
def prepare_spatial_asset_authority(
    *,
    repository_root: Path,
    spatial_cache_root: Path,
    work_dir: Path,
    toolchain_manifest_path: Path,
    evidence: SpatialToolchainEvidence,
    geometry: GeometryBindings,
) -> Iterator[SpatialAssetPaths]:
    try:
        _validate_geometry(geometry)
    except SpatialClassificationError as exc:
        raise SpatialAssetAuthorityError("spatial geometry authority is invalid") from exc
    repository = _absolute(repository_root, "repository root")
    try:
        manifest_relative = _absolute(toolchain_manifest_path, "manifest").relative_to(repository)
    except ValueError as exc:
        raise SpatialAssetAuthorityError("toolchain manifest is outside the repository") from exc
    with ExitStack() as stack:
        repository_dir = stack.enter_context(_open_directory_path(repository, "repository root"))
        cache_dir = stack.enter_context(_open_directory_path(spatial_cache_root, "cache root"))
        work = stack.enter_context(_open_directory_path(work_dir, "work directory"))
        _assert_secure_work_directory(work)
        manifest = _enter_asset(stack, repository_dir, manifest_relative, "manifest")
        if manifest.sha256 != SPATIAL_TOOLCHAIN_MANIFEST_SHA256:
            raise SpatialAssetAuthorityError("spatial manifest bytes differ from the exact pin")
        private_name, private = _create_private(work)
        _stack_close(stack, private.descriptor)
        snapshots: list[_Asset] = []
        owned = []
        primary_error: BaseException | None = None
        try:
            manifest_snapshot = _copy_asset(manifest, private, "manifest.json", owned)
            snapshots.append(manifest_snapshot)
            _stack_close(stack, manifest_snapshot.descriptor)
            private_root = _descriptor_path(private)
            _validate_evidence(private_root / "manifest.json", evidence)
            extension = _enter_asset(stack, cache_dir, evidence.extension_path, "extension")
            if extension.sha256 != evidence.extension_sha256:
                raise SpatialAssetAuthorityError("Spatial extension bytes differ from evidence")
            extension_snapshot = _copy_asset(extension, private, "spatial.duckdb_extension", owned)
            snapshots.append(extension_snapshot)
            _stack_close(stack, extension_snapshot.descriptor)
            geometry_snapshots = []
            for binding in geometry.items:
                source = _enter_asset(stack, repository_dir, binding.path, binding.role)
                if source.sha256 != binding.sha256:
                    raise SpatialAssetAuthorityError(f"{binding.role} geometry bytes differ")
                snapshot = _copy_asset(source, private, f"{binding.role}.geojson", owned)
                snapshots.append(snapshot)
                _stack_close(stack, snapshot.descriptor)
                geometry_snapshots.append(
                    GeometrySnapshot(binding.role, private_root / snapshot.name, snapshot.sha256)
                )
            paths = SpatialAssetPaths(
                private_root / manifest_snapshot.name,
                manifest_snapshot.sha256,
                private_root / extension_snapshot.name,
                extension_snapshot.sha256,
                tuple(geometry_snapshots),
                geometry.contract_sha256,
                evidence,
            )
            yield paths
        except BaseException as exc:
            primary_error = exc
            raise
        finally:
            try:
                _remove_private(work, private_name, private, tuple(owned), tuple(snapshots))
            except BaseException as cleanup_error:
                if primary_error is None:
                    raise
                _note_cleanup(primary_error, cleanup_error)
