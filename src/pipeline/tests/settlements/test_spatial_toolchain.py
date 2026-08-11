"""Mutation coverage for the offline DuckDB Spatial build plane."""

from __future__ import annotations

import gzip
import hashlib
import json
from pathlib import Path

import pytest

from searise_pipeline.settlements.spatial_toolchain import (
    SpatialToolchainError,
    acquire_spatial_extension,
    load_spatial_manifest,
    stage_spatial_archive,
    verify_spatial_toolchain,
)

REPO_ROOT = Path(__file__).parents[4]
MANIFEST_PATH = REPO_ROOT / "src/pipeline/toolchain/duckdb-spatial-extensions.json"


class _Connection:
    def __init__(self) -> None:
        self.commands: list[str] = []
        self.closed = False

    def execute(self, command: str) -> "_Connection":
        self.commands.append(command)
        return self

    def fetchone(self) -> tuple[float, float, float]:
        return (12.5, 41.9, 5.0)

    def close(self) -> None:
        self.closed = True


class _DuckDB:
    def __init__(self, version: str) -> None:
        self.__version__ = version
        self.connection = _Connection()

    def connect(self) -> _Connection:
        return self.connection


def _sha256(path: Path) -> tuple[int, str]:
    return len(path.read_bytes()), hashlib.sha256(path.read_bytes()).hexdigest()


def _test_manifest(tmp_path: Path) -> tuple[Path, Path, Path]:
    payload = b"verified test spatial extension\n"
    source = tmp_path / "spatial.duckdb_extension.gz"
    with gzip.GzipFile(filename=source, mode="wb", mtime=0) as stream:
        stream.write(payload)
    archive_size, archive_hash = _sha256(source)
    extension_hash = hashlib.sha256(payload).hexdigest()
    platform = {
        "duckdbPlatform": "linux_amd64",
        "pythonWheel": {
            "url": "https://files.pythonhosted.org/packages/test/duckdb.whl",
            "byteSize": 1,
            "sha256": "0" * 64,
        },
        "extensionArchive": {
            "url": "https://extensions.duckdb.org/v1.5.4/linux_amd64/spatial.duckdb_extension.gz",
            "relativePath": "duckdb/v1.5.4/linux_amd64/spatial.duckdb_extension.gz",
            "byteSize": archive_size,
            "sha256": archive_hash,
        },
        "extension": {
            "relativePath": "duckdb/v1.5.4/linux_amd64/spatial.duckdb_extension",
            "byteSize": len(payload),
            "sha256": extension_hash,
        },
    }
    macos = json.loads(json.dumps(platform))
    macos["duckdbPlatform"] = "osx_arm64"
    macos["extensionArchive"]["relativePath"] = (
        "duckdb/v1.5.4/osx_arm64/spatial.duckdb_extension.gz"
    )
    macos["extension"]["relativePath"] = "duckdb/v1.5.4/osx_arm64/spatial.duckdb_extension"
    raw = {
        "schemaVersion": 1,
        "tool": {
            "package": "duckdb",
            "version": "1.5.4",
            "pythonVersion": "3.11",
            "pythonRequires": ">=3.10",
        },
        "extension": {"name": "spatial", "version": "v1.5.4"},
        "platforms": {"linux-x86_64": platform, "macos-arm64": macos},
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(raw), encoding="utf-8")
    return manifest_path, source, tmp_path / "cache"


def _prepared_cache(tmp_path: Path):
    manifest_path, source, cache_root = _test_manifest(tmp_path)
    manifest = load_spatial_manifest(manifest_path)
    acquire_spatial_extension(source, cache_root, manifest, platform_key="linux-x86_64")
    return manifest, cache_root


def test_checked_in_manifest_pins_both_official_platform_identities() -> None:
    manifest = load_spatial_manifest(MANIFEST_PATH)

    assert manifest.duckdb_version == "1.5.4"
    assert manifest.python_version == "3.11"
    assert manifest.extension_version == "v1.5.4"
    assert set(manifest.platforms) == {"linux-x86_64", "macos-arm64"}
    assert manifest.platforms["linux-x86_64"].archive.sha256 == (
        "be5c95a1921d5bf66dbcee450272927a93a2839cff7c1e9c2ee815e5461616ac"
    )
    assert manifest.platforms["macos-arm64"].extension.sha256 == (
        "575c609c1eb0b45be5d4000792528579746233c5d57d3fa83aa825d11740a1ec"
    )


def test_cache_acquisition_is_checksum_first_and_live_verifier_only_loads_by_path(
    tmp_path: Path,
) -> None:
    manifest, cache_root = _prepared_cache(tmp_path)
    duckdb = _DuckDB("1.5.4")

    evidence = verify_spatial_toolchain(
        cache_root, manifest, platform_key="linux-x86_64", duckdb_module=duckdb
    )

    assert evidence.smoke_point == (12.5, 41.9)
    assert evidence.smoke_distance == 5.0
    assert duckdb.connection.commands[0].startswith("LOAD '")
    assert "INSTALL" not in "\n".join(duckdb.connection.commands)
    assert duckdb.connection.closed


def test_acquisition_rejects_a_source_archive_with_the_wrong_hash(tmp_path: Path) -> None:
    manifest_path, source, cache_root = _test_manifest(tmp_path)
    source.write_bytes(b"not the reviewed gzip bytes")
    manifest = load_spatial_manifest(manifest_path)

    with pytest.raises(SpatialToolchainError, match="Spatial archive differs"):
        acquire_spatial_extension(source, cache_root, manifest, platform_key="linux-x86_64")


def test_verifier_rejects_a_mutated_cached_extension(tmp_path: Path) -> None:
    manifest, cache_root = _prepared_cache(tmp_path)
    extension = cache_root / manifest.platforms["linux-x86_64"].extension.relative_path
    extension.write_bytes(b"tampered")

    with pytest.raises(SpatialToolchainError, match="cached Spatial extension differs"):
        verify_spatial_toolchain(
            cache_root,
            manifest,
            platform_key="linux-x86_64",
            duckdb_module=_DuckDB("1.5.4"),
        )


def test_verifier_rejects_a_missing_extension_before_duckdb_connects(tmp_path: Path) -> None:
    manifest_path, source, cache_root = _test_manifest(tmp_path)
    manifest = load_spatial_manifest(manifest_path)
    stage_spatial_archive(source, cache_root, manifest.platforms["linux-x86_64"])
    duckdb = _DuckDB("1.5.4")

    with pytest.raises(SpatialToolchainError, match="cached Spatial extension is missing"):
        verify_spatial_toolchain(
            cache_root, manifest, platform_key="linux-x86_64", duckdb_module=duckdb
        )

    assert duckdb.connection.commands == []


def test_verifier_rejects_a_duckdb_version_mutation_before_load(tmp_path: Path) -> None:
    manifest, cache_root = _prepared_cache(tmp_path)
    duckdb = _DuckDB("1.5.3")

    with pytest.raises(SpatialToolchainError, match="DuckDB version differs"):
        verify_spatial_toolchain(
            cache_root, manifest, platform_key="linux-x86_64", duckdb_module=duckdb
        )

    assert duckdb.connection.commands == []
