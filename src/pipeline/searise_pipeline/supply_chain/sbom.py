"""Deterministic CycloneDX generation from supported immutable lock inputs."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
import stat
import uuid
from pathlib import Path, PurePosixPath
from typing import Any, Mapping
from urllib.parse import quote, unquote, urlsplit

from .contracts import SupplyChainContractError, _validate_cyclonedx

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


def generate_npm_sbom(lock_path: Path, *, logical_path: str) -> dict[str, Any]:
    """Generate a deterministic CycloneDX 1.7 graph from package-lock v3."""
    input_bytes, lock = _load_lock_bytes(lock_path)
    if lock.get("lockfileVersion") != 3 or lock.get("requires") is not True:
        raise SupplyChainContractError("npm SBOM generation requires package-lock v3")
    packages = lock.get("packages")
    if not isinstance(packages, dict) or not isinstance(packages.get(""), dict):
        raise SupplyChainContractError("package-lock v3 must contain one root package")
    root = packages[""]
    if "workspaces" in root:
        raise SupplyChainContractError("npm workspaces are unsupported")
    root_name = root.get("name")
    root_version = root.get("version")
    if (
        not isinstance(root_name, str)
        or not root_name
        or not isinstance(root_version, str)
        or not root_version
        or lock.get("name") != root_name
        or lock.get("version") != root_version
    ):
        raise SupplyChainContractError("npm root name/version identity mismatch")
    _validate_npm_name(root_name, context="root package")

    package_entries = {path: entry for path, entry in packages.items() if path}
    if not all(
        isinstance(path, str) and isinstance(entry, dict) for path, entry in package_entries.items()
    ):
        raise SupplyChainContractError("npm package entries must be objects")
    alias_targets = _alias_targets(packages)
    components = [
        _npm_component(path, package_entries[path], alias_targets)
        for path in sorted(package_entries)
    ]
    components.sort(key=lambda component: (component["purl"], component["bom-ref"]))
    refs = {path: _npm_ref(path) for path in package_entries}
    input_sha256 = _sha256_bytes(input_bytes)
    root_ref = f"urn:searise:sbom:npm-root:sha256:{input_sha256}"
    _dependency_groups(root, root=True)
    root_properties = [
        (
            f"npm.root.{group}",
            json.dumps(
                root.get(group, {}),
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
    root_component = {
        "type": "application",
        "bom-ref": root_ref,
        "name": root_name,
        "version": root_version,
        "purl": _npm_purl(root_name, root_version),
        "properties": _properties(*root_properties),
    }

    relationships = [
        {
            "ref": root_ref,
            "dependsOn": list(_resolved_edges(None, root, package_entries, refs)),
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
