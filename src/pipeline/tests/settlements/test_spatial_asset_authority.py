import hashlib
import json
import os
import shutil
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from searise_pipeline.settlements import spatial_asset_authority as authority
from searise_pipeline.settlements.spatial_classification import load_fixture_geometry_bindings
from searise_pipeline.settlements.spatial_toolchain import SpatialToolchainEvidence as Evidence

AuthorityError = authority.SpatialAssetAuthorityError
prepare = authority.prepare_spatial_asset_authority

ROOT = Path(__file__).parents[4]
FIXTURE = ROOT / "src/pipeline/tests/settlements/fixtures/spatial/fixture-manifest.json"


@pytest.fixture
def environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    cleanup_error = RuntimeError("primary")
    authority._note_cleanup(cleanup_error, RuntimeError("cleanup"))
    if hasattr(cleanup_error, "add_note"):
        assert cleanup_error.__notes__ == ["spatial cleanup failed closed: cleanup"]
    repository = tmp_path / "repository"
    cache = tmp_path / "cache"
    work = tmp_path / "work"
    for path in (repository, cache, work):
        path.mkdir()
    geometry = load_fixture_geometry_bindings(FIXTURE, repository_root=ROOT)
    for binding in geometry.items:
        target = repository / binding.path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / binding.path, target)
    extension_bytes = b"synthetic spatial extension bytes\n"
    extension_hash = hashlib.sha256(extension_bytes).hexdigest()
    toolchain = ROOT / "src/pipeline/toolchain/duckdb-spatial-extensions.json"
    manifest = json.loads(toolchain.read_text())
    for platform in manifest["platforms"].values():
        platform["extension"].update(byteSize=len(extension_bytes), sha256=extension_hash)
    manifest_path = repository / "src/pipeline/toolchain/duckdb-spatial-extensions.json"
    manifest_path.parent.mkdir(parents=True)
    manifest_bytes = json.dumps(manifest, separators=(",", ":")).encode()
    manifest_path.write_bytes(manifest_bytes)
    manifest_hash = hashlib.sha256(manifest_bytes).hexdigest()
    monkeypatch.setattr(authority, "SPATIAL_TOOLCHAIN_MANIFEST_SHA256", manifest_hash)
    relative = manifest["platforms"]["linux-x86_64"]["extension"]["relativePath"]
    extension = cache / relative
    extension.parent.mkdir(parents=True)
    extension.write_bytes(extension_bytes)
    evidence = Evidence("linux-x86_64", "1.5.4", relative, extension_hash, (12.5, 41.9), 5.0)
    options = {
        "repository_root": repository,
        "spatial_cache_root": cache,
        "work_dir": work,
        "toolchain_manifest_path": manifest_path,
        "evidence": evidence,
        "geometry": geometry,
    }
    names = "repository cache work geometry extension options".split()
    values = repository, cache, work, geometry, extension, options
    return SimpleNamespace(**dict(zip(names, values)))


def _reject(options: dict[str, object], match: str, clean: bool = True) -> None:
    with pytest.raises(AuthorityError, match=match), prepare(**options):
        pass
    assert not clean or not list(options["work_dir"].iterdir())


def _swap(path: Path) -> None:
    replacement = path.with_name("replacement")
    replacement.write_bytes(path.read_bytes())
    os.replace(replacement, path)


def _fail_private_metadata(monkeypatch, target=".spatial-assets-") -> None:  # type: ignore[no-untyped-def]
    def injected(original):  # type: ignore[no-untyped-def]
        def fail(value, *args, **kwargs):  # type: ignore[no-untyped-def]
            if type(value) is str and value.startswith(target):
                raise OSError("injected private metadata failure")
            return original(value, *args, **kwargs)

        return fail

    for operation in ("stat", "lstat"):
        monkeypatch.setattr(authority.os, operation, injected(getattr(authority.os, operation)))


def test_private_paths_cleanup(environment) -> None:  # type: ignore[no-untyped-def]
    with prepare(**environment.options) as prepared:
        private = prepared.manifest_path.parent
        assert private.parent == environment.work
        assert private.stat().st_mode & 0o777 == 0o700
        expected_manifest = environment.options["toolchain_manifest_path"].read_bytes()
        assert prepared.manifest_path.read_bytes() == expected_manifest
        assert prepared.extension_path.read_bytes() == environment.extension.read_bytes()
        assert {item.role for item in prepared.geometries} == {"support", "coastal", "shoreline"}
        assert all(item.path.parent == private for item in prepared.geometries)
    assert not private.exists()


@pytest.mark.parametrize(
    "field,value",
    [("duckdb_version", "1.5.3"), ("extension_sha256", "0" * 64), ("smoke_distance", 4.0)],
)
def test_bad_evidence(environment, field, value) -> None:  # type: ignore[no-untyped-def]
    options = {
        **environment.options,
        "evidence": replace(environment.options["evidence"], **{field: value}),
    }
    _reject(options, "evidence")


@pytest.mark.parametrize("target", ["extension", "support"])
def test_source_swap(environment, target) -> None:  # type: ignore[no-untyped-def]
    source = environment.extension
    if target == "support":
        source = environment.repository / environment.geometry.support.path
    with pytest.raises(AuthorityError, match="identity changed"):
        with prepare(**environment.options) as prepared:
            private = prepared.manifest_path.parent
            _swap(source)
            assert prepared.extension_path.read_bytes()
    assert not private.exists()


@pytest.mark.parametrize("primary", [OSError("consumer primary"), RuntimeError("consumer primary")])
def test_consumer_primary(tmp_path: Path, environment, primary) -> None:  # type: ignore[no-untyped-def]
    source = environment.repository / environment.geometry.support.path
    moved_work = tmp_path / "moved-work"
    with pytest.raises(type(primary), match="consumer primary") as caught:
        with prepare(**environment.options):
            _swap(source)
            environment.work.rename(moved_work)
            environment.work.mkdir()
            raise primary
    assert caught.value is primary
    environment.work.rmdir()
    moved_work.rmdir()


def test_consumer_primary_survives_close_failures(environment, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    real_open, real_close = authority.os.open, authority.os.close
    live, attempted = set(), []
    fail = False

    def track_open(*args, **kwargs):  # type: ignore[no-untyped-def]
        descriptor = real_open(*args, **kwargs)
        live.add(descriptor)
        return descriptor

    def track_close(descriptor):  # type: ignore[no-untyped-def]
        real_close(descriptor)
        live.discard(descriptor)
        if fail:
            attempted.append(descriptor)
            raise OSError("injected close failure")

    monkeypatch.setattr(authority.os, "open", track_open)
    monkeypatch.setattr(authority.os, "close", track_close)
    primary = RuntimeError("consumer primary")
    with pytest.raises(RuntimeError, match="consumer primary") as caught:
        with prepare(**environment.options):
            expected = set(live)
            fail = True
            raise primary
    assert caught.value is primary
    assert set(attempted) == expected and not live


def test_intermediate_symlink_is_rejected(tmp_path: Path, environment) -> None:  # type: ignore[no-untyped-def]
    duckdb = environment.cache / "duckdb"
    external = tmp_path / "external-duckdb"
    duckdb.rename(external)
    duckdb.symlink_to(external, target_is_directory=True)
    _reject(environment.options, "intermediate symlink")


@pytest.mark.parametrize("root_name", ["repository_root", "spatial_cache_root", "work_dir"])
def test_parent_traversal(environment, root_name) -> None:  # type: ignore[no-untyped-def]
    original = environment.options[root_name]
    options = {**environment.options, root_name: original / ".." / original.name}
    _reject(options, "parent traversal")


@pytest.mark.parametrize("mutation", ["writable", "foreign-owner"])
def test_insecure_work_root(environment, monkeypatch, mutation) -> None:  # type: ignore[no-untyped-def]
    if mutation == "writable":
        environment.work.chmod(0o777)
    else:
        effective_uid = os.geteuid()
        monkeypatch.setattr(authority.os, "geteuid", lambda: effective_uid + 1)
    _reject(environment.options, "owner-controlled")


@pytest.mark.parametrize("target", [None, ".spatial-assets-", "manifest.json"])
def test_metadata_fallback(environment, monkeypatch, target) -> None:  # type: ignore[no-untyped-def]
    if target:
        _fail_private_metadata(monkeypatch, target)
        monkeypatch.setattr(authority.os, "scandir", lambda _: (_ for _ in ()).throw(OSError()))
    else:
        monkeypatch.setattr(authority.os, "fstat", lambda _: (_ for _ in ()).throw(OSError()))
    with prepare(**environment.options):
        pass
    assert not list(environment.work.iterdir())


def test_setup_failure_rolls_back(environment, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    real_copy = authority._copy_asset
    calls = 0

    def fail_second(*args, **kwargs):  # type: ignore[no-untyped-def]
        nonlocal calls
        calls += 1
        if calls == 2:
            raise AuthorityError("injected copy failure")
        return real_copy(*args, **kwargs)

    monkeypatch.setattr(authority, "_copy_asset", fail_second)
    _reject(environment.options, "injected")
    assert calls == 2 and not list(environment.work.iterdir())


@pytest.mark.parametrize(
    "failure,replace_partial",
    [("write", False), ("write", True), ("scan", True), ("fdstat", True)],
)
def test_mid_copy_failure(environment, monkeypatch, failure, replace_partial) -> None:  # type: ignore[no-untyped-def]
    real_write, real_fd_stat = authority.os.write, authority._fd_stat

    def fail_during_copy(*args):  # type: ignore[no-untyped-def]
        if failure == "write":
            real_write(args[0], args[1][:1])
        private = next(environment.work.iterdir(), None)
        if private is None:
            return real_fd_stat(args[0])
        partial = private / "manifest.json"
        if failure == "fdstat" and not partial.exists():
            return real_fd_stat(args[0])
        if replace_partial:
            replacement = private / "replacement"
            replacement.write_bytes(b"alien replacement")
            os.replace(replacement, partial)
        raise OSError(f"injected {failure} failure")

    if failure == "scan":
        _fail_private_metadata(monkeypatch, "manifest.json")
    owner = authority if failure == "fdstat" else authority.os
    monkeypatch.setattr(
        owner,
        {"write": "write", "scan": "scandir", "fdstat": "_fd_stat"}[failure],
        fail_during_copy,
    )
    error = AuthorityError if failure == "scan" else OSError
    with pytest.raises(error, match="injected|replaced") as caught:
        with prepare(**environment.options):
            pass
    if replace_partial:
        private = next(environment.work.iterdir())
        assert (private / "manifest.json").read_bytes() == b"alien replacement"
        notes = getattr(caught.value, "__notes__", ["cleanup failed closed"])
        assert "cleanup failed closed" in notes[0]
        monkeypatch.undo()
        shutil.rmtree(private)
    else:
        assert not list(environment.work.iterdir())


@pytest.mark.parametrize("kind", ["file", "symlink", "directory"])
def test_cleanup_preserves_aliens(environment, kind) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(AuthorityError, match="alien entry"):
        with prepare(**environment.options) as prepared:
            private = prepared.manifest_path.parent
            alien = private / "alien"
            if kind == "file":
                alien.write_bytes(b"preserve")
            elif kind == "symlink":
                alien.symlink_to(prepared.manifest_path)
            else:
                alien.mkdir()
    assert alien.exists() or alien.is_symlink()
    shutil.rmtree(private)


def test_snapshot_swap(environment, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    real_move = authority._move_owned
    injected = False

    def replace_before_move(parent, name, identity, **kwargs):  # type: ignore[no-untyped-def]
        nonlocal injected
        if not injected and not kwargs["directory"]:
            injected = True
            _swap(private / name)
        return real_move(parent, name, identity, **kwargs)

    monkeypatch.setattr(authority, "_move_owned", replace_before_move)
    with pytest.raises(AuthorityError, match="cleanup refused"):
        with prepare(**environment.options) as prepared:
            private = prepared.manifest_path.parent
    assert injected and private.exists()
    shutil.rmtree(private)


@pytest.mark.parametrize("metadata_failure", [False, True])
def test_private_dir_swap(environment, monkeypatch, metadata_failure) -> None:  # type: ignore[no-untyped-def]
    real_open, real_fd_stat = authority.os.open, authority._fd_stat
    moved = environment.work / "opened-private"
    state = {}

    def track_open(path, *args, **kwargs):  # type: ignore[no-untyped-def]
        descriptor = real_open(path, *args, **kwargs)
        if type(path) is str and path.startswith(".spatial-assets-"):
            state["descriptor"] = descriptor
        return descriptor

    def replace_before_fstat(descriptor):  # type: ignore[no-untyped-def]
        if descriptor == state.get("descriptor"):
            replacement = next(environment.work.glob(".spatial-assets-*"))
            replacement.rename(moved)
            replacement.mkdir()
            (replacement / "preserve.txt").write_text("preserve", encoding="utf-8")
            if metadata_failure:
                raise AuthorityError("cleanup refused: descriptor identity unavailable")
        return real_fd_stat(descriptor)

    monkeypatch.setattr(authority.os, "open", track_open)
    monkeypatch.setattr(authority, "_fd_stat", replace_before_fstat)
    _reject(environment.options, "cleanup refused", clean=False)
    replacement = next(environment.work.glob(".spatial-assets-*"))
    assert (replacement / "preserve.txt").read_text(encoding="utf-8") == "preserve"
    shutil.rmtree(replacement)
    moved.rmdir()
