"""Deterministic CycloneDX generation from supported immutable lock inputs."""

from __future__ import annotations

import base64
import binascii
import ctypes
import hashlib
import json
import os
import re
import secrets
import stat
import sys
import tempfile
import uuid
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, cast
from urllib.parse import quote, unquote, urlsplit

from .contracts import SupplyChainContractError, _validate_cyclonedx
from .python_graph import _read_descriptor

_NPM_PATH = re.compile(
    r"^node_modules/(?:@[^/\s]+/)?[^/\s]+"
    r"(?:/node_modules/(?:@[^/\s]+/)?[^/\s]+)*$"
)
_ROOT_GROUPS = (
    "dependencies",
    "devDependencies",
    "optionalDependencies",
    "peerDependencies",
)
_PACKAGE_GROUPS = ("dependencies", "optionalDependencies", "peerDependencies")
_PROPERTY_PREFIX = "org.searise.sbom"
_NPM_UNSCOPED_NAME = re.compile(r"^[a-z0-9][a-z0-9._~-]*$")
_NPM_SCOPED_NAME = re.compile(r"^@[a-z0-9][a-z0-9._~-]*/[a-z0-9][a-z0-9._~-]*$")


def canonical_sbom_bytes(document: Mapping[str, Any]) -> bytes:
    """Render one SBOM as byte-stable canonical JSON."""
    return (
        json.dumps(
            document,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


_Inode = tuple[int, int]


def _output_parts(output_path: Path) -> tuple[str, tuple[str, ...], str]:
    rendered = os.fspath(output_path)
    parts = output_path.parts
    absolute = output_path.is_absolute()
    if (
        not rendered
        or "\0" in rendered
        or "\\" in rendered
        or not parts
        or (absolute and parts[0] != "/")
        or any(part in {"", ".", ".."} for part in parts[1 if absolute else 0 :])
    ):
        raise SupplyChainContractError(f"unsafe SBOM output path: {output_path}")
    relative = parts[1:] if absolute else parts
    if not relative:
        raise SupplyChainContractError(f"unsafe SBOM output path: {output_path}")
    return ("/" if absolute else ".", tuple(relative[:-1]), relative[-1])


def _open_directory(anchor: int, parts: tuple[str, ...]) -> int:
    descriptor = os.dup(anchor)
    flags = os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        for part in parts:
            child = os.open(part, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        return descriptor
    except Exception:
        os.close(descriptor)
        raise


def _open_output_parent(output_path: Path) -> tuple[int, int, tuple[str, ...], str]:
    anchor_path, parent_parts, output_name = _output_parts(output_path)
    flags = os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    anchor = -1
    try:
        anchor = os.open(anchor_path, flags)
        parent = _open_directory(anchor, parent_parts)
    except OSError as exc:
        if anchor >= 0:
            os.close(anchor)
        raise SupplyChainContractError(
            "SBOM output parent must not be a symlink and must already exist "
            f"as a directory: {output_path.parent}"
        ) from exc
    return anchor, parent, parent_parts, output_name


def _inode(value: os.stat_result) -> _Inode:
    return value.st_dev, value.st_ino


def _path_inode(parent: int, name: str) -> _Inode | None:
    try:
        return _inode(os.stat(name, dir_fd=parent, follow_symlinks=False))
    except FileNotFoundError:
        return None


def _parent_path_matches(anchor: int, parts: tuple[str, ...], expected: _Inode) -> bool:
    try:
        current = _open_directory(anchor, parts)
    except OSError:
        return False
    try:
        return _inode(os.fstat(current)) == expected
    finally:
        os.close(current)


def _exclusive_rename() -> tuple[Any, int]:
    try:
        libc = ctypes.CDLL(None, use_errno=True)
        if sys.platform == "darwin":
            rename, flag = libc.renameatx_np, 4
        elif sys.platform.startswith("linux"):
            rename, flag = libc.renameat2, 1
        else:
            raise SupplyChainContractError("exclusive immutable-file rename is unsupported")
    except (AttributeError, OSError) as exc:
        raise SupplyChainContractError("exclusive immutable-file rename is unavailable") from exc
    return rename, flag


def _rename_no_overwrite(parent: int, source: str, target: str) -> None:
    rename, flag = _exclusive_rename()
    rename.argtypes = (
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    )
    rename.restype = ctypes.c_int
    if rename(parent, os.fsencode(source), parent, os.fsencode(target), flag) != 0:
        code = ctypes.get_errno()
        raise OSError(code, os.strerror(code), target)


def _unlink_if_owned(parent: int, name: str, expected: _Inode) -> bool:
    """Quarantine before unlinking so a racing replacement is never deleted."""
    quarantine = ""
    for _ in range(32):
        quarantine = f".searise-sbom-rollback-{secrets.token_hex(16)}"
        try:
            _rename_no_overwrite(parent, name, quarantine)
        except FileExistsError:
            continue
        except FileNotFoundError:
            return False
        except OSError:
            return False
        break
    else:
        return False
    if _path_inode(parent, quarantine) == expected:
        try:
            os.unlink(quarantine, dir_fd=parent)
        except OSError:
            return False
        else:
            return True
    try:
        _rename_no_overwrite(parent, quarantine, name)
    except OSError:
        return False
    return False


def _create_partial(parent: int, prefix: str = ".searise-sbom-") -> tuple[int, str]:
    flags = os.O_RDWR | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    for _ in range(32):
        name = f"{prefix}{secrets.token_hex(16)}.partial"
        try:
            return os.open(name, flags, 0o600, dir_fd=parent), name
        except FileExistsError:
            continue
    raise SupplyChainContractError("could not allocate a unique SBOM partial file")


def _write_all(descriptor: int, content: bytes) -> None:
    remaining = memoryview(content)
    while remaining:
        written = os.write(descriptor, remaining)
        if written <= 0:
            raise OSError("SBOM partial write made no progress")
        remaining = remaining[written:]


def _descriptor_has_exact_bytes(descriptor: int, content: bytes) -> bool:
    if os.fstat(descriptor).st_size != len(content):
        return False
    offset = 0
    while offset < len(content):
        expected = content[offset : offset + 131_072]
        actual = os.pread(descriptor, len(expected), offset)
        if actual != expected:
            return False
        offset += len(actual)
    return os.pread(descriptor, 1, len(content)) == b""


def _close_quietly(descriptor: int) -> None:
    """Best-effort cleanup that cannot reverse a durable publication outcome."""
    try:
        os.close(descriptor)
    except OSError:
        pass


def _has_forbidden_ancestor(directory: int, forbidden: frozenset[_Inode]) -> bool:
    if not forbidden:
        return False
    cursor = os.dup(directory)
    flags = os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        while True:
            current = _inode(os.fstat(cursor))
            if current in forbidden:
                return True
            parent = os.open("..", flags, dir_fd=cursor)
            parent_inode = _inode(os.fstat(parent))
            if parent_inode == current:
                _close_quietly(parent)
                return False
            _close_quietly(cursor)
            cursor = parent
    finally:
        _close_quietly(cursor)


def write_new_immutable_bytes(
    output_path: Path,
    content: bytes,
    *,
    label: str,
    mode: int,
    partial_prefix: str,
    required_parent_inode: _Inode | None = None,
    forbidden_ancestor_inodes: frozenset[_Inode] = frozenset(),
) -> None:
    """Durably publish exact new bytes with ownership-safe no-overwrite promotion."""
    if type(content) is not bytes:
        raise SupplyChainContractError(f"{label} content must be exact bytes")
    if not label or mode not in {0o400, 0o600}:
        raise SupplyChainContractError("immutable-file publication parameters are invalid")
    anchor, parent, parent_parts, output_name = _open_output_parent(output_path)
    parent_inode = _inode(os.fstat(parent))
    partial_descriptor = -1
    partial_name: str | None = None
    owned_inode: _Inode | None = None
    promoted = False
    directory_changed = False
    try:
        if required_parent_inode is not None and parent_inode != required_parent_inode:
            raise SupplyChainContractError(f"{label} parent differs from its reviewed identity")
        if _has_forbidden_ancestor(parent, forbidden_ancestor_inodes):
            raise SupplyChainContractError(f"{label} parent overlaps a protected input root")
        if _path_inode(parent, output_name) is not None:
            raise SupplyChainContractError(f"{label} path already exists: {output_path}")
        partial_descriptor, partial_name = _create_partial(parent, partial_prefix)
        partial_stat = os.fstat(partial_descriptor)
        if not stat.S_ISREG(partial_stat.st_mode):
            raise SupplyChainContractError(f"{label} partial must remain a regular file")
        owned_inode = _inode(partial_stat)
        _write_all(partial_descriptor, content)
        os.fchmod(partial_descriptor, mode)
        os.fsync(partial_descriptor)
        partial_stat = os.fstat(partial_descriptor)
        if (
            _inode(partial_stat) != owned_inode
            or not stat.S_ISREG(partial_stat.st_mode)
            or stat.S_IMODE(partial_stat.st_mode) != mode
            or partial_stat.st_nlink != 1
        ):
            raise SupplyChainContractError(f"{label} partial ownership changed during publication")
        if not _descriptor_has_exact_bytes(partial_descriptor, content):
            raise SupplyChainContractError(f"{label} partial bytes changed during publication")

        if not _parent_path_matches(anchor, parent_parts, parent_inode):
            raise SupplyChainContractError(f"{label} output parent changed during publication")
        if _has_forbidden_ancestor(parent, forbidden_ancestor_inodes):
            raise SupplyChainContractError(f"{label} parent moved below a protected input root")
        if _path_inode(parent, partial_name) != owned_inode:
            raise SupplyChainContractError(f"{label} partial ownership changed before promotion")
        _exclusive_rename()
        try:
            os.link(
                partial_name,
                output_name,
                src_dir_fd=parent,
                dst_dir_fd=parent,
                follow_symlinks=False,
            )
        except FileExistsError as exc:
            raise SupplyChainContractError(f"{label} path already exists: {output_path}") from exc
        promoted = True
        directory_changed = True
        if _path_inode(parent, output_name) != owned_inode:
            raise SupplyChainContractError(f"{label} promotion ownership changed")
        if not _descriptor_has_exact_bytes(partial_descriptor, content):
            raise SupplyChainContractError(f"{label} promoted bytes changed")
        if not _unlink_if_owned(parent, partial_name, owned_inode):
            raise SupplyChainContractError(f"{label} partial cleanup failed after promotion")
        partial_name = None
        if os.fstat(partial_descriptor).st_nlink != 1:
            raise SupplyChainContractError(f"{label} final link count is invalid")
        os.fsync(parent)
        directory_changed = False
        if not _parent_path_matches(anchor, parent_parts, parent_inode):
            raise SupplyChainContractError(f"{label} output parent changed during publication")
        if _has_forbidden_ancestor(parent, forbidden_ancestor_inodes):
            raise SupplyChainContractError(f"{label} parent moved below a protected input root")
        if _path_inode(parent, output_name) != owned_inode:
            raise SupplyChainContractError(f"{label} output ownership changed during publication")
        if not _descriptor_has_exact_bytes(partial_descriptor, content):
            raise SupplyChainContractError(f"{label} output bytes changed during publication")
    except Exception:
        cleanup_error: Exception | None = None
        if promoted and owned_inode is not None:
            try:
                directory_changed = _unlink_if_owned(parent, output_name, owned_inode)
            except Exception as exc:
                cleanup_error = exc
        if partial_name is not None and owned_inode is not None:
            try:
                directory_changed = (
                    _unlink_if_owned(parent, partial_name, owned_inode) or directory_changed
                )
            except Exception as exc:
                cleanup_error = cleanup_error or exc
        if directory_changed:
            try:
                os.fsync(parent)
            except OSError:
                pass
        if cleanup_error is not None:
            raise SupplyChainContractError(f"{label} rollback was incomplete") from cleanup_error
        raise
    finally:
        if partial_descriptor >= 0:
            _close_quietly(partial_descriptor)
        _close_quietly(parent)
        _close_quietly(anchor)


def write_new_sbom(output_path: Path, content: bytes) -> None:
    """Durably publish exact new SBOM bytes without following or overwriting paths."""
    write_new_immutable_bytes(
        output_path,
        content,
        label="SBOM output",
        mode=0o600,
        partial_prefix=".searise-sbom-",
    )


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _property(name: str, value: object) -> dict[str, str]:
    if isinstance(value, bool):
        rendered = str(value).lower()
    else:
        rendered = str(value)
    return {"name": f"{_PROPERTY_PREFIX}.{name}", "value": rendered}


def _properties(*values: tuple[str, object]) -> list[dict[str, str]]:
    return sorted(
        (_property(name, value) for name, value in values),
        key=lambda item: item["name"],
    )


def _logical_path(value: str) -> str:
    logical = PurePosixPath(value)
    if (
        not value
        or "\\" in value
        or logical.is_absolute()
        or logical.as_posix() != value
        or any(part in {"", ".", ".."} for part in logical.parts)
    ):
        raise SupplyChainContractError(f"unsafe SBOM input path: {value}")
    return value


def _npm_name(path: str) -> str:
    if not _NPM_PATH.fullmatch(path):
        raise SupplyChainContractError(f"unsupported npm package path: {path}")
    name = path.rsplit("node_modules/", 1)[1]
    parts = name.split("/")
    if (name.startswith("@") and len(parts) != 2) or (not name.startswith("@") and len(parts) != 1):
        raise SupplyChainContractError(f"invalid scoped npm package path: {path}")
    return name


def _validate_npm_name(name: object, *, context: str) -> str:
    if not isinstance(name, str) or not (
        _NPM_SCOPED_NAME.fullmatch(name) or _NPM_UNSCOPED_NAME.fullmatch(name)
    ):
        raise SupplyChainContractError(f"invalid npm package name: {context}")
    return name


def _npm_purl(name: str, version: str) -> str:
    if name.startswith("@"):
        scope, package = name.split("/", 1)
        encoded_name = f"{quote(scope, safe='')}/{quote(package, safe='')}"
    else:
        encoded_name = quote(name, safe="")
    return f"pkg:npm/{encoded_name}@{quote(version, safe='.-_~+')}"


def _npm_ref(path: str) -> str:
    return f"urn:searise:sbom:npm-path:sha256:{_sha256_bytes(path.encode('utf-8'))}"


def _dependency_groups(
    entry: Mapping[str, Any],
    *,
    root: bool,
) -> dict[str, tuple[str, ...]]:
    groups: dict[str, tuple[str, ...]] = {}
    allowed = _ROOT_GROUPS if root else _PACKAGE_GROUPS
    if not root and "devDependencies" in entry:
        raise SupplyChainContractError("npm package entries must not define devDependencies")
    for group in allowed:
        raw = entry.get(group, {})
        if not isinstance(raw, dict) or not all(
            isinstance(name, str) and name and isinstance(version, str) and version
            for name, version in raw.items()
        ):
            raise SupplyChainContractError(f"npm {group} must map names to version ranges")
        for name in raw:
            _validate_npm_name(name, context=f"{group} entry")
        groups[group] = tuple(sorted(raw))
    peer_meta = entry.get("peerDependenciesMeta", {})
    if not isinstance(peer_meta, dict):
        raise SupplyChainContractError("npm peerDependenciesMeta must be an object")
    peers = set(groups["peerDependencies"])
    for name, metadata in peer_meta.items():
        _validate_npm_name(name, context="peerDependenciesMeta entry")
        if (
            not isinstance(metadata, dict)
            or set(metadata) != {"optional"}
            or not isinstance(metadata["optional"], bool)
        ):
            raise SupplyChainContractError(
                "npm peerDependenciesMeta entries must contain one optional boolean"
            )
        if name not in peers and metadata["optional"] is not True:
            raise SupplyChainContractError("npm peerDependenciesMeta-only entries must be optional")
    return groups


def _resolve_npm_dependency(
    parent_path: str | None,
    dependency_name: str,
    packages: Mapping[str, Any],
) -> str | None:
    candidates: list[str] = []
    if parent_path is not None:
        candidates.append(f"{parent_path}/node_modules/{dependency_name}")
        cursor = parent_path
        while "/node_modules/" in cursor:
            cursor = cursor.rsplit("/node_modules/", 1)[0]
            candidates.append(f"{cursor}/node_modules/{dependency_name}")
    candidates.append(f"node_modules/{dependency_name}")
    return next(
        (candidate for candidate in dict.fromkeys(candidates) if candidate in packages), None
    )


def _resolved_edges(
    parent_path: str | None,
    entry: Mapping[str, Any],
    packages: Mapping[str, Any],
    refs: Mapping[str, str],
) -> tuple[str, ...]:
    groups = _dependency_groups(entry, root=parent_path is None)
    optional = set(groups["optionalDependencies"])
    peer_meta = entry.get("peerDependenciesMeta", {})

    edges = []
    for group, names in groups.items():
        for name in names:
            resolved = _resolve_npm_dependency(parent_path, name, packages)
            peer_optional = (
                group == "peerDependencies"
                and isinstance(peer_meta.get(name), dict)
                and peer_meta[name].get("optional") is True
            )
            if resolved is None:
                if group == "optionalDependencies" or name in optional or peer_optional:
                    continue
                owner = parent_path or "<root>"
                raise SupplyChainContractError(f"unresolved npm dependency {name!r} from {owner}")
            edges.append(refs[resolved])
    return tuple(sorted(set(edges)))


def _npm_alias(value: str, *, context: str) -> str | None:
    if not value.startswith("npm:"):
        return None
    target, separator, requested = value.removeprefix("npm:").rpartition("@")
    if (
        not separator
        or not requested
        or requested != requested.strip()
        or any(ord(character) < 32 or ord(character) == 127 for character in requested)
    ):
        raise SupplyChainContractError(f"invalid npm alias range: {context}")
    return _validate_npm_name(target, context=f"alias target for {context}")


def _alias_targets(packages: Mapping[str, Any]) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for parent_path, entry in packages.items():
        groups = _dependency_groups(entry, root=parent_path == "")
        for group in groups:
            declarations = entry.get(group, {})
            for install_name, requested in declarations.items():
                target = _npm_alias(
                    requested,
                    context=f"{parent_path or '<root>'}:{group}:{install_name}",
                )
                if target is None:
                    continue
                resolved = _resolve_npm_dependency(parent_path or None, install_name, packages)
                if resolved is None:
                    continue
                previous = aliases.setdefault(resolved, target)
                if previous != target:
                    raise SupplyChainContractError(f"conflicting npm alias targets for {resolved}")
    return aliases


def _validate_registry_tarball(resolved: object, *, name: str, version: str, path: str) -> str:
    if not isinstance(resolved, str) or not resolved:
        raise SupplyChainContractError(f"npm resolved URL is missing: {path}")
    parsed = urlsplit(resolved)
    decoded_path = unquote(parsed.path)
    leaf = name.rsplit("/", 1)[-1]
    expected_path = f"/{name}/-/{leaf}-{version}.tgz"
    if (
        parsed.scheme != "https"
        or parsed.hostname != "registry.npmjs.org"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port is not None
        or parsed.query
        or parsed.fragment
        or decoded_path != expected_path
    ):
        raise SupplyChainContractError(f"unsupported npm resolved tarball: {path}")
    return resolved


def _npm_component(
    path: str,
    entry: Mapping[str, Any],
    alias_targets: Mapping[str, str],
) -> dict[str, Any]:
    if entry.get("link") is not None:
        raise SupplyChainContractError(f"npm links and workspaces are unsupported: {path}")
    install_name = _npm_name(path)
    name = _validate_npm_name(entry.get("name", install_name), context=path)
    alias_target = alias_targets.get(path)
    if name != install_name and alias_target != name:
        raise SupplyChainContractError(f"npm package name/path mismatch: {path}")
    if alias_target is not None and ("name" not in entry or name != alias_target):
        raise SupplyChainContractError(f"npm alias target mismatch: {path}")
    version = entry.get("version")
    if not isinstance(version, str) or not version:
        raise SupplyChainContractError(f"npm package version is missing: {path}")
    _validate_registry_tarball(entry.get("resolved"), name=name, version=version, path=path)
    for flag in ("dev", "devOptional", "optional", "peer"):
        if flag in entry and not isinstance(entry[flag], bool):
            raise SupplyChainContractError(f"npm {flag} flag must be boolean: {path}")
    optional_scope = entry.get("optional", False) or entry.get("devOptional", False)

    component: dict[str, Any] = {
        "type": "library",
        "bom-ref": _npm_ref(path),
        "name": name,
        "version": version,
        "purl": _npm_purl(name, version),
        "scope": "optional" if optional_scope else "required",
        "properties": _properties(
            ("npm.dev", entry.get("dev", False)),
            ("npm.devOptional", entry.get("devOptional", False)),
            ("npm.install-name", install_name),
            ("npm.lock-entry-sha256", _sha256_bytes(canonical_sbom_bytes(entry))),
            ("npm.lock-path", path),
            ("npm.optional", entry.get("optional", False)),
            ("npm.peer", entry.get("peer", False)),
        ),
    }
    integrity = entry.get("integrity")
    if not isinstance(integrity, str) or not integrity.startswith("sha512-"):
        raise SupplyChainContractError(f"unsupported npm integrity value: {path}")
    try:
        digest = base64.b64decode(integrity.removeprefix("sha512-"), validate=True)
    except (binascii.Error, ValueError) as exc:
        raise SupplyChainContractError(f"invalid npm integrity encoding: {path}") from exc
    if len(digest) != 64:
        raise SupplyChainContractError(f"npm integrity is not SHA-512: {path}")
    component["hashes"] = [{"alg": "SHA-512", "content": digest.hex()}]
    return component


def _load_lock_bytes(lock_path: Path) -> tuple[bytes, dict[str, Any]]:
    if lock_path.is_symlink():
        raise SupplyChainContractError(f"npm lock path must not be a symlink: {lock_path}")
    if not stat.S_ISREG(lock_path.stat().st_mode):
        raise SupplyChainContractError(f"npm lock path must be a regular file: {lock_path}")
    input_bytes = lock_path.read_bytes()

    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise SupplyChainContractError(f"duplicate npm lock key: {key}")
            result[key] = value
        return result

    def reject_constant(value: str) -> None:
        raise SupplyChainContractError(f"invalid non-JSON numeric constant: {value}")

    lock = json.loads(
        input_bytes,
        object_pairs_hook=reject_duplicates,
        parse_constant=reject_constant,
    )
    if not isinstance(lock, dict):
        raise SupplyChainContractError("package-lock root must be an object")
    return input_bytes, lock


def _assert_graph_reachable(
    root_ref: str,
    relationships: list[dict[str, Any]],
    refs: Mapping[str, str],
) -> None:
    graph = {relationship["ref"]: relationship["dependsOn"] for relationship in relationships}
    reachable = {root_ref}
    pending = [root_ref]
    while pending:
        for dependency in graph[pending.pop()]:
            if dependency not in reachable:
                reachable.add(dependency)
                pending.append(dependency)
    paths_by_ref = {reference: path for path, reference in refs.items()}
    unreachable = sorted(paths_by_ref[reference] for reference in set(refs.values()) - reachable)
    if unreachable:
        raise SupplyChainContractError(f"unreachable npm package entries: {', '.join(unreachable)}")


def _npm_application_entry(
    root: Mapping[str, Any],
    packages: Mapping[str, Any],
) -> tuple[Mapping[str, Any], frozenset[str], str | None]:
    """Resolve either a traditional root package or one exact npm workspace app."""
    workspaces = root.get("workspaces")
    if workspaces is None:
        return root, frozenset(), None
    if (
        not isinstance(workspaces, list)
        or len(workspaces) != 1
        or not isinstance(workspaces[0], str)
    ):
        raise SupplyChainContractError("npm workspace declaration must name one exact path")
    workspace_path = _logical_path(workspaces[0])
    if any(character in workspace_path for character in "*?[]{}"):
        raise SupplyChainContractError("npm workspace declaration must name one exact path")
    workspace = packages.get(workspace_path)
    if not isinstance(workspace, dict):
        raise SupplyChainContractError("npm workspace package entry is missing")
    workspace_name = _validate_npm_name(
        workspace.get("name"), context=f"workspace {workspace_path}"
    )
    workspace_version = workspace.get("version")
    if not isinstance(workspace_version, str) or not workspace_version:
        raise SupplyChainContractError("npm workspace package version is missing")
    for group in _ROOT_GROUPS:
        if root.get(group, {}) != {}:
            raise SupplyChainContractError(
                "npm workspace lock must declare application dependencies in the workspace"
            )
    link_path = f"node_modules/{workspace_name}"
    link = packages.get(link_path)
    if link != {"resolved": workspace_path, "link": True}:
        raise SupplyChainContractError("npm workspace link does not match its exact package path")
    return workspace, frozenset({workspace_path, link_path}), workspace_path


def _generate_npm_sbom_file(lock_path: Path, *, logical_path: str) -> dict[str, Any]:
    input_bytes, lock = _load_lock_bytes(lock_path)
    if lock.get("lockfileVersion") != 3 or lock.get("requires") is not True:
        raise SupplyChainContractError("npm SBOM generation requires package-lock v3")
    packages = lock.get("packages")
    if not isinstance(packages, dict) or not isinstance(packages.get(""), dict):
        raise SupplyChainContractError("package-lock v3 must contain one root package")
    root = packages[""]
    if lock.get("name") != root.get("name"):
        raise SupplyChainContractError("npm lock and root package identity mismatch")
    application, excluded_paths, workspace_path = _npm_application_entry(root, packages)
    root_name = application.get("name")
    root_version = application.get("version")
    if (
        not isinstance(root_name, str)
        or not root_name
        or not isinstance(root_version, str)
        or not root_version
        or (workspace_path is None and lock.get("name") != root_name)
        or (workspace_path is None and lock.get("version") != root_version)
    ):
        raise SupplyChainContractError("npm root name/version identity mismatch")
    _validate_npm_name(root_name, context="root package")

    package_entries = {
        path: entry
        for path, entry in packages.items()
        if path and path not in excluded_paths
    }
    if not all(
        isinstance(path, str) and isinstance(entry, dict) for path, entry in package_entries.items()
    ):
        raise SupplyChainContractError("npm package entries must be objects")
    dependency_authority = {"": application, **package_entries}
    alias_targets = _alias_targets(dependency_authority)
    components = [
        _npm_component(path, package_entries[path], alias_targets)
        for path in sorted(package_entries)
    ]
    components.sort(key=lambda component: (component["purl"], component["bom-ref"]))
    refs = {path: _npm_ref(path) for path in package_entries}
    input_sha256 = _sha256_bytes(input_bytes)
    root_ref = f"urn:searise:sbom:npm-root:sha256:{input_sha256}"
    _dependency_groups(application, root=True)
    root_properties: list[tuple[str, object]] = [
        (
            f"npm.root.{group}",
            json.dumps(
                application.get(group, {}),
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ),
        )
        for group in _ROOT_GROUPS
    ]
    root_properties.extend(
        [
            ("input.path", _logical_path(logical_path)),
            ("input.sha256", input_sha256),
            ("production-claim", False),
            ("scope", "frontend-npm-lock-only"),
        ]
    )
    if workspace_path is not None:
        root_properties.append(("npm.workspace.path", workspace_path))
    root_component = {
        "type": "application",
        "bom-ref": root_ref,
        "name": root_name,
        "version": root_version,
        "purl": _npm_purl(root_name, root_version),
        "properties": _properties(*root_properties),
    }

    relationships: list[dict[str, Any]] = [
        {
            "ref": root_ref,
            "dependsOn": list(
                _resolved_edges(None, application, package_entries, refs)
            ),
        }
    ]
    relationships.extend(
        {
            "ref": refs[path],
            "dependsOn": list(_resolved_edges(path, package_entries[path], package_entries, refs)),
        }
        for path in sorted(package_entries)
    )
    relationships.sort(key=lambda relationship: relationship["ref"])
    _assert_graph_reachable(root_ref, relationships, refs)
    serial = uuid.uuid5(
        uuid.NAMESPACE_URL,
        f"https://artemsemdev.github.io/SeaRise-Europe/sbom/npm/{logical_path}/{input_sha256}",
    )
    document = {
        "$schema": "https://cyclonedx.org/schema/bom-1.7.schema.json",
        "bomFormat": "CycloneDX",
        "specVersion": "1.7",
        "serialNumber": f"urn:uuid:{serial}",
        "version": 1,
        "metadata": {"component": root_component},
        "components": components,
        "dependencies": relationships,
    }
    _validate_cyclonedx(document)
    return document


def _repository_lock_bytes(
    lock_path: Path,
    *,
    repository_root: Path,
    logical_path: str,
) -> bytes:
    logical = PurePosixPath(_logical_path(logical_path))
    root = repository_root.absolute()
    try:
        if root != repository_root.resolve(strict=True):
            raise SupplyChainContractError("npm repository root must not be a symlink")
        candidate = lock_path if lock_path.is_absolute() else root / lock_path
        relative = PurePosixPath(candidate.absolute().relative_to(root).as_posix())
    except (OSError, ValueError) as exc:
        raise SupplyChainContractError("npm lock path must be beneath the repository") from exc
    if relative != logical:
        raise SupplyChainContractError("npm lock path differs from its logical path")

    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    root_descriptor = parent_descriptor = file_descriptor = -1
    try:
        root_descriptor = os.open(root, flags | os.O_DIRECTORY)
        parent_descriptor = _open_directory(root_descriptor, tuple(logical.parts[:-1]))
        file_descriptor = os.open(
            logical.name,
            flags | getattr(os, "O_NONBLOCK", 0),
            dir_fd=parent_descriptor,
        )
        return cast(bytes, _read_descriptor(file_descriptor, label="npm lock", path=logical))
    except OSError as exc:
        raise SupplyChainContractError(
            f"npm lock must exist beneath the repository without symlinks: {logical}"
        ) from exc
    finally:
        for descriptor in (file_descriptor, parent_descriptor, root_descriptor):
            if descriptor >= 0:
                os.close(descriptor)


def generate_npm_sbom(
    lock_path: Path,
    *,
    logical_path: str,
    repository_root: Path | None = None,
) -> dict[str, Any]:
    """Generate a deterministic CycloneDX 1.7 graph from package-lock v3."""
    if repository_root is None:
        return _generate_npm_sbom_file(lock_path, logical_path=logical_path)
    authority = _repository_lock_bytes(
        lock_path,
        repository_root=repository_root,
        logical_path=logical_path,
    )
    with tempfile.TemporaryDirectory(prefix="searise-npm-sbom-") as temporary:
        snapshot = Path(temporary) / "package-lock.json"
        snapshot.write_bytes(authority)
        document = _generate_npm_sbom_file(snapshot, logical_path=logical_path)
    if authority != _repository_lock_bytes(
        lock_path,
        repository_root=repository_root,
        logical_path=logical_path,
    ):
        raise SupplyChainContractError("npm lock changed during SBOM generation")
    return document


def _read_canonical_npm_sbom(path: Path) -> tuple[bytes, dict[str, Any]]:
    anchor, parent, _parent_parts, name = _open_output_parent(path)
    descriptor = -1
    try:
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(name, flags | getattr(os, "O_NONBLOCK", 0), dir_fd=parent)
        raw = _read_descriptor(descriptor, label="npm SBOM", path=path)
    except OSError as exc:
        raise SupplyChainContractError(
            f"npm SBOM must be a regular file without symlinks: {path}"
        ) from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        os.close(parent)
        os.close(anchor)

    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        document: dict[str, Any] = {}
        for key, value in pairs:
            if key in document:
                raise SupplyChainContractError(f"duplicate npm SBOM key: {key}")
            document[key] = value
        return document

    def reject_constant(value: str) -> None:
        raise SupplyChainContractError(f"invalid npm SBOM numeric constant: {value}")

    try:
        parsed = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=reject_duplicates,
            parse_constant=reject_constant,
        )
    except UnicodeDecodeError as exc:
        raise SupplyChainContractError("npm SBOM must be UTF-8") from exc
    except json.JSONDecodeError as exc:
        raise SupplyChainContractError("npm SBOM JSON is malformed") from exc
    if not isinstance(parsed, dict):
        raise SupplyChainContractError("npm SBOM root must be an object")
    try:
        canonical = canonical_sbom_bytes(parsed)
    except (TypeError, ValueError) as exc:
        raise SupplyChainContractError("npm SBOM contains a noncanonical value") from exc
    if canonical != raw:
        raise SupplyChainContractError("npm SBOM JSON is not canonical")
    _validate_cyclonedx(parsed)
    return raw, parsed


def validate_npm_sbom(
    sbom_path: Path,
    lock_path: Path,
    *,
    repository_root: Path,
    logical_path: str,
) -> dict[str, Any]:
    """Validate exact canonical BOM bytes against the current npm lock authority."""
    raw, document = _read_canonical_npm_sbom(sbom_path)
    expected = generate_npm_sbom(
        lock_path,
        repository_root=repository_root,
        logical_path=logical_path,
    )
    if raw != canonical_sbom_bytes(expected):
        raise SupplyChainContractError("npm SBOM differs from its lock authority")
    return document


def publish_npm_sbom(
    output_path: Path,
    lock_path: Path,
    *,
    repository_root: Path,
    logical_path: str,
) -> dict[str, Any]:
    """Generate and durably publish one immutable npm SBOM."""
    document = generate_npm_sbom(
        lock_path,
        repository_root=repository_root,
        logical_path=logical_path,
    )
    write_new_sbom(output_path, canonical_sbom_bytes(document))
    return document
