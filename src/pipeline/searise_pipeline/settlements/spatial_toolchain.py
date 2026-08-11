"""Checksum-first, network-free DuckDB Spatial extension verification."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import importlib
import json
import os
import platform
import shutil
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Optional, Sequence


class SpatialToolchainError(ValueError):
    """Raised when a settlement spatial build-plane identity is not exact."""


@dataclass(frozen=True)
class FileIdentity:
    """Immutable identity for one staged file."""

    relative_path: str
    byte_size: int
    sha256: str


@dataclass(frozen=True)
class SpatialPlatform:
    """DuckDB wheel and extension identities for one supported host."""

    key: str
    duckdb_platform: str
    wheel_url: str
    wheel_size: int
    wheel_sha256: str
    archive: FileIdentity
    extension: FileIdentity


@dataclass(frozen=True)
class SpatialManifest:
    """Pinned DuckDB and Spatial extension source identities."""

    duckdb_version: str
    python_version: str
    extension_version: str
    platforms: Mapping[str, SpatialPlatform]


@dataclass(frozen=True)
class SpatialToolchainEvidence:
    """Verified local facts needed by the settlement build plane."""

    platform: str
    duckdb_version: str
    extension_path: str
    extension_sha256: str
    smoke_point: tuple[float, float]
    smoke_distance: float


def _sha256_and_size(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def _regular_file(path: Path, label: str) -> None:
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError as exc:
        raise SpatialToolchainError(f"{label} is missing") from exc
    if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
        raise SpatialToolchainError(f"{label} must be a regular file")


def _verify_file(path: Path, identity: FileIdentity, label: str) -> None:
    _regular_file(path, label)
    observed_hash, observed_size = _sha256_and_size(path)
    if observed_size != identity.byte_size or observed_hash != identity.sha256:
        raise SpatialToolchainError(f"{label} differs from its immutable identity")


def _file_identity(value: Mapping[str, Any], *, needs_path: bool) -> FileIdentity:
    expected = {"relativePath", "byteSize", "sha256"} if needs_path else {"byteSize", "sha256"}
    if set(value) != expected:
        raise SpatialToolchainError("manifest file identity has unexpected fields")
    relative_path = str(value.get("relativePath", ""))
    if needs_path:
        path = PurePosixPath(relative_path)
        if not relative_path or path.is_absolute() or ".." in path.parts:
            raise SpatialToolchainError("manifest cache path is unsafe")
    size = value["byteSize"]
    digest = value["sha256"]
    if not isinstance(size, int) or size <= 0:
        raise SpatialToolchainError("manifest byte size is invalid")
    if (
        not isinstance(digest, str)
        or len(digest) != 64
        or any(character not in "0123456789abcdef" for character in digest)
    ):
        raise SpatialToolchainError("manifest SHA-256 is invalid")
    return FileIdentity(relative_path=relative_path, byte_size=size, sha256=digest)


def load_spatial_manifest(path: Path) -> SpatialManifest:
    """Load the small immutable contract without importing the DuckDB package."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SpatialToolchainError("spatial toolchain manifest is unreadable") from exc
    if not isinstance(raw, dict) or set(raw) != {"schemaVersion", "tool", "extension", "platforms"}:
        raise SpatialToolchainError("spatial toolchain manifest has unexpected fields")
    tool = raw["tool"]
    extension = raw["extension"]
    platforms = raw["platforms"]
    if not isinstance(tool, dict) or set(tool) != {
        "package", "version", "pythonVersion", "pythonRequires"
    }:
        raise SpatialToolchainError("DuckDB tool pin is malformed")
    if tool["package"] != "duckdb" or not all(isinstance(tool[name], str) for name in tool):
        raise SpatialToolchainError("DuckDB tool pin is invalid")
    if not isinstance(extension, dict) or extension != {
        "name": "spatial", "version": f"v{tool['version']}"
    }:
        raise SpatialToolchainError("Spatial extension pin is invalid")
    if raw["schemaVersion"] != 1 or not isinstance(platforms, dict) or set(platforms) != {
        "linux-x86_64", "macos-arm64"
    }:
        raise SpatialToolchainError("spatial toolchain platform set is invalid")

    parsed: dict[str, SpatialPlatform] = {}
    for key, value in platforms.items():
        if not isinstance(value, dict) or set(value) != {
            "duckdbPlatform", "pythonWheel", "extensionArchive", "extension"
        }:
            raise SpatialToolchainError("platform pin has unexpected fields")
        wheel = value["pythonWheel"]
        archive = value["extensionArchive"]
        unpacked = value["extension"]
        if not isinstance(wheel, dict) or set(wheel) != {"url", "byteSize", "sha256"}:
            raise SpatialToolchainError("DuckDB wheel pin is malformed")
        if not isinstance(wheel["url"], str) or not wheel["url"].startswith("https://files.pythonhosted.org/"):
            raise SpatialToolchainError("DuckDB wheel URL is not an official immutable URL")
        wheel_identity = _file_identity(
            {"byteSize": wheel["byteSize"], "sha256": wheel["sha256"]}, needs_path=False
        )
        if not isinstance(archive, dict) or set(archive) != {
            "url", "relativePath", "byteSize", "sha256"
        }:
            raise SpatialToolchainError("Spatial archive pin is malformed")
        if not isinstance(archive["url"], str) or not archive["url"].startswith("https://extensions.duckdb.org/"):
            raise SpatialToolchainError("Spatial archive URL is not an official URL")
        if not isinstance(unpacked, dict):
            raise SpatialToolchainError("Spatial extension pin is malformed")
        parsed[key] = SpatialPlatform(
            key=key,
            duckdb_platform=value["duckdbPlatform"],
            wheel_url=wheel["url"],
            wheel_size=wheel_identity.byte_size,
            wheel_sha256=wheel_identity.sha256,
            archive=_file_identity(
                {
                    "relativePath": archive["relativePath"],
                    "byteSize": archive["byteSize"],
                    "sha256": archive["sha256"],
                },
                needs_path=True,
            ),
            extension=_file_identity(unpacked, needs_path=True),
        )
    return SpatialManifest(
        duckdb_version=tool["version"],
        python_version=tool["pythonVersion"],
        extension_version=extension["version"],
        platforms=parsed,
    )


def current_spatial_platform() -> str:
    """Return the contract key for a supported host, otherwise fail closed."""
    system = platform.system()
    machine = platform.machine().lower()
    if system == "Linux" and machine in {"x86_64", "amd64"}:
        return "linux-x86_64"
    if system == "Darwin" and machine in {"arm64", "aarch64"}:
        return "macos-arm64"
    raise SpatialToolchainError(f"unsupported DuckDB Spatial platform: {system}/{machine}")


def _cache_path(cache_root: Path, relative_path: str) -> Path:
    root = cache_root.resolve()
    relative = PurePosixPath(relative_path)
    candidate = root.joinpath(*relative.parts)
    if root not in candidate.parents:
        raise SpatialToolchainError("cache path escaped its root")
    return candidate


def _create_cache_parent(path: Path, cache_root: Path) -> None:
    cache_root.mkdir(parents=True, exist_ok=True)
    if cache_root.is_symlink() or not cache_root.is_dir():
        raise SpatialToolchainError("cache directory is unsafe")
    root = cache_root.resolve()
    current = root
    for part in path.parent.relative_to(root).parts:
        current /= part
        if not current.exists():
            current.mkdir()
        if current.is_symlink() or not current.is_dir():
            raise SpatialToolchainError("cache directory is unsafe")


def _atomic_copy(source: Path, destination: Path) -> None:
    with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as temporary:
        temporary_path = Path(temporary.name)
        with source.open("rb") as stream:
            shutil.copyfileobj(stream, temporary)
    try:
        os.replace(temporary_path, destination)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def stage_spatial_archive(
    archive_path: Path, cache_root: Path, platform_pin: SpatialPlatform
) -> Path:
    """Admit a previously acquired archive only after its hash and size match."""
    _verify_file(archive_path, platform_pin.archive, "Spatial archive")
    target = _cache_path(cache_root, platform_pin.archive.relative_path)
    _create_cache_parent(target, cache_root)
    if target.exists():
        _verify_file(target, platform_pin.archive, "cached Spatial archive")
        return target
    _atomic_copy(archive_path, target)
    _verify_file(target, platform_pin.archive, "cached Spatial archive")
    return target


def materialize_spatial_extension(cache_root: Path, platform_pin: SpatialPlatform) -> Path:
    """Expand a verified archive into the exact extension cache path."""
    archive = _cache_path(cache_root, platform_pin.archive.relative_path)
    _verify_file(archive, platform_pin.archive, "cached Spatial archive")
    target = _cache_path(cache_root, platform_pin.extension.relative_path)
    _create_cache_parent(target, cache_root)
    if target.exists():
        _verify_file(target, platform_pin.extension, "cached Spatial extension")
        return target
    with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as temporary:
        temporary_path = Path(temporary.name)
        try:
            with gzip.open(archive, "rb") as compressed:
                shutil.copyfileobj(compressed, temporary)
            temporary.flush()
            _verify_file(temporary_path, platform_pin.extension, "expanded Spatial extension")
            os.replace(temporary_path, target)
        finally:
            if temporary_path.exists():
                temporary_path.unlink()
    return target


def acquire_spatial_extension(
    archive_path: Path,
    cache_root: Path,
    manifest: SpatialManifest,
    *,
    platform_key: Optional[str] = None,
) -> Path:
    """Build the local cache from an externally acquired, immutable archive."""
    key = platform_key or current_spatial_platform()
    try:
        platform_pin = manifest.platforms[key]
    except KeyError as exc:
        raise SpatialToolchainError(f"unsupported manifest platform: {key}") from exc
    stage_spatial_archive(archive_path, cache_root, platform_pin)
    return materialize_spatial_extension(cache_root, platform_pin)


def _load_extension(connection: Any, extension_path: Path) -> None:
    quoted = extension_path.as_posix().replace("'", "''")
    connection.execute(f"LOAD '{quoted}'")


def verify_spatial_toolchain(
    cache_root: Path,
    manifest: SpatialManifest,
    *,
    platform_key: Optional[str] = None,
    duckdb_module: Optional[Any] = None,
) -> SpatialToolchainEvidence:
    """Prove exact DuckDB, cached Spatial bytes, loadability, and spatial math."""
    key = platform_key or current_spatial_platform()
    try:
        platform_pin = manifest.platforms[key]
    except KeyError as exc:
        raise SpatialToolchainError(f"unsupported manifest platform: {key}") from exc
    archive = _cache_path(cache_root, platform_pin.archive.relative_path)
    extension = _cache_path(cache_root, platform_pin.extension.relative_path)
    _verify_file(archive, platform_pin.archive, "cached Spatial archive")
    _verify_file(extension, platform_pin.extension, "cached Spatial extension")
    module = duckdb_module or importlib.import_module("duckdb")
    if str(getattr(module, "__version__", "")) != manifest.duckdb_version:
        raise SpatialToolchainError("DuckDB version differs from the spatial toolchain pin")
    connection = module.connect()
    try:
        _load_extension(connection, extension)
        row = connection.execute(
            "SELECT ST_X(ST_Point(12.5, 41.9)), ST_Y(ST_Point(12.5, 41.9)), "
            "ST_Distance(ST_Point(0, 0), ST_Point(3, 4))"
        ).fetchone()
    finally:
        close = getattr(connection, "close", None)
        if close is not None:
            close()
    if row != (12.5, 41.9, 5.0):
        raise SpatialToolchainError(
            "Spatial deterministic smoke query differs from its expected result"
        )
    return SpatialToolchainEvidence(
        platform=key,
        duckdb_version=manifest.duckdb_version,
        extension_path=platform_pin.extension.relative_path,
        extension_sha256=platform_pin.extension.sha256,
        smoke_point=(12.5, 41.9),
        smoke_distance=5.0,
    )


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Run the fail-closed live preflight against an already prepared cache."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--cache-root", required=True, type=Path)
    parser.add_argument("--platform", choices=("linux-x86_64", "macos-arm64"))
    parser.add_argument(
        "--archive",
        type=Path,
        help="Previously acquired official Spatial gzip archive to admit to the cache.",
    )
    arguments = parser.parse_args(argv)
    manifest = load_spatial_manifest(arguments.manifest)
    if arguments.archive is not None:
        acquire_spatial_extension(
            arguments.archive,
            arguments.cache_root,
            manifest,
            platform_key=arguments.platform,
        )
    evidence = verify_spatial_toolchain(
        arguments.cache_root, manifest, platform_key=arguments.platform
    )
    print(json.dumps(evidence.__dict__, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised by pinned build-plane command
    raise SystemExit(main())
