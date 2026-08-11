"""CycloneDX inventory derived from candidate build-plane authority bytes."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import tempfile
import uuid
from pathlib import Path, PurePosixPath
from typing import Any

from .contracts import (
    SupplyChainContractError,
    _validate_cyclonedx,
    validate_dependency_inventory,
)
from .python_graph import _read_descriptor
from .sbom import canonical_sbom_bytes, write_new_sbom

_INVENTORY_PATH = PurePosixPath("contracts/supply-chain/v1/dependency-inventory.json")
_INCLUDED_COMPONENTS = (
    "github-actions",
    "native-geospatial-toolchain",
    "release-container-image",
)
_OPENTOFU_COMPONENT = "deployment-opentofu"
_PROPERTY_PREFIX = "org.searise.sbom.build-plane"
_DUCKDB_LOCK = "src/pipeline/toolchain/duckdb-spatial-extensions.json"
_LINUX_RECIPE = "src/pipeline/toolchain/Dockerfile.tippecanoe-linux-x86_64"
_MACOS_RECIPE = "src/pipeline/toolchain/build_macos_tippecanoe.sh"
_LINUX_RECEIPT = "src/pipeline/toolchain/tippecanoe-linux-x86_64-build-receipt.json"
_MACOS_RECEIPT = "src/pipeline/toolchain/tippecanoe-darwin-arm64-build-receipt.json"
_RELEASE_DOCKERFILE = "src/pipeline/offline_release/Dockerfile"
_TIPPECANOE_VERSION = "2.79.0"
_DUCKDB_VERSION = "1.5.4"
_REVIEWED_AUTHORITY_SHA256 = {
    _DUCKDB_LOCK: "77c7ea3422e67be2f8d23f0dcef2d5d36236f01b8856f76289ed1e0532359ca6",
    _LINUX_RECIPE: "8d5fb782ea81bc19c9c8d71e31aae19a01bc448f401fd10114f633bd2a6c2dc5",
    _MACOS_RECIPE: "143cfd23ca2f051c60cc1221122236d4cb4305a554ca6fe44d66bec164432bc9",
}
_LINUX_PACKAGE_ROLES = {
    "packages": {
        "build-essential": "12.10ubuntu1",
        "ca-certificates": "20260601~24.04.1",
        "libsqlite3-dev": "3.45.1-1ubuntu2.7",
        "zlib1g-dev": "1:1.3.dfsg-3.1ubuntu2.1",
    },
    "runtimeLibraries": {
        "libc6": "2.39-0ubuntu8.8",
        "libsqlite3-0": "3.45.1-1ubuntu2.7",
        "libstdc++6": "14.2.0-4ubuntu2~24.04.1",
        "zlib1g": "1:1.3.dfsg-3.1ubuntu2.1",
    },
}
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_ACTION = re.compile(
    r"^\s*(?:-\s*)?uses:\s*([A-Za-z0-9_.-]+/[A-Za-z0-9_./-]+)@([0-9a-f]{40})"
    r"\s+#\s+v?([0-9]+\.[0-9]+\.[0-9]+)\s*$"
)


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _property(name: str, value: object) -> dict[str, str]:
    rendered = str(value).lower() if isinstance(value, bool) else str(value)
    return {"name": f"{_PROPERTY_PREFIX}.{name}", "value": rendered}


def _properties(*values: tuple[str, object]) -> list[dict[str, str]]:
    return sorted((_property(name, value) for name, value in values), key=lambda item: item["name"])


def _logical_path(value: str) -> PurePosixPath:
    logical = PurePosixPath(value)
    if (
        not value
        or "\\" in value
        or logical.is_absolute()
        or logical.as_posix() != value
        or any(part in {"", ".", ".."} for part in logical.parts)
    ):
        raise SupplyChainContractError(f"unsafe build-plane input path: {value}")
    return logical


def _repository_root_descriptor(repository_root: Path) -> tuple[Path, int]:
    root = repository_root.absolute()
    try:
        if root != repository_root.resolve(strict=True):
            raise SupplyChainContractError("build-plane repository root must not be a symlink")
        flags = os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        return root, os.open(root, flags)
    except OSError as exc:
        raise SupplyChainContractError("build-plane repository root could not be opened") from exc


def _read_repository_file(root_descriptor: int, logical: PurePosixPath) -> bytes:
    directory = os.dup(root_descriptor)
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        for part in logical.parts[:-1]:
            child = os.open(part, flags | os.O_DIRECTORY, dir_fd=directory)
            os.close(directory)
            directory = child
        descriptor = os.open(
            logical.name,
            flags | getattr(os, "O_NONBLOCK", 0),
            dir_fd=directory,
        )
        try:
            return _read_descriptor(
                descriptor,
                label="build-plane input",
                path=logical,
            )
        finally:
            os.close(descriptor)
    except OSError as exc:
        raise SupplyChainContractError(
            f"build-plane input must exist beneath the repository without symlinks: {logical}"
        ) from exc
    finally:
        os.close(directory)


def _parse_inventory(value: bytes) -> dict[str, Any]:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, item in pairs:
            if key in result:
                raise SupplyChainContractError(f"duplicate inventory key: {key}")
            result[key] = item
        return result

    def reject_constant(constant: str) -> None:
        raise SupplyChainContractError(f"invalid dependency inventory numeric constant: {constant}")

    try:
        document = json.loads(
            value.decode("utf-8"),
            object_pairs_hook=reject_duplicates,
            parse_constant=reject_constant,
        )
    except UnicodeDecodeError as exc:
        raise SupplyChainContractError("dependency inventory must be UTF-8") from exc
    except json.JSONDecodeError as exc:
        raise SupplyChainContractError("dependency inventory JSON is malformed") from exc
    if not isinstance(document, dict):
        raise SupplyChainContractError("dependency inventory root must be an object")
    return document


def _inventory_logical_path(inventory_path: Path, root: Path) -> PurePosixPath:
    try:
        candidate = inventory_path if inventory_path.is_absolute() else root / inventory_path
        logical = PurePosixPath(candidate.absolute().relative_to(root).as_posix())
    except ValueError as exc:
        raise SupplyChainContractError(
            "dependency inventory must be beneath the repository"
        ) from exc
    if logical != _INVENTORY_PATH:
        raise SupplyChainContractError(f"dependency inventory path must be {_INVENTORY_PATH}")
    return logical


def _authority(
    inventory_path: Path,
    *,
    repository_root: Path,
) -> tuple[dict[str, Any], bytes, dict[str, bytes]]:
    root, root_descriptor = _repository_root_descriptor(repository_root)
    try:
        inventory_logical = _inventory_logical_path(inventory_path, root)
        inventory_bytes = _read_repository_file(root_descriptor, inventory_logical)
        parsed = _parse_inventory(inventory_bytes)
        with tempfile.TemporaryDirectory(prefix="searise-build-plane-sbom-") as temporary:
            snapshot = Path(temporary) / "dependency-inventory.json"
            snapshot.write_bytes(inventory_bytes)
            validated = validate_dependency_inventory(snapshot, repository_root=root)
        if validated != parsed:
            raise SupplyChainContractError("dependency inventory changed during validation")

        components = {component["id"]: component for component in validated["components"]}
        opentofu = components[_OPENTOFU_COMPONENT]
        if (
            opentofu["ecosystem"],
            opentofu["releaseUse"],
            opentofu["coverage"],
            opentofu["inputs"],
        ) != ("opentofu", "not-present", "not-present", []):
            raise SupplyChainContractError("OpenTofu absence contract changed")

        authority: dict[str, bytes] = {}
        for component_id in _INCLUDED_COMPONENTS:
            component = components[component_id]
            if (component["releaseUse"], component["coverage"]) != (
                "candidate",
                "locked",
            ):
                raise SupplyChainContractError(
                    f"build-plane component is not candidate locked: {component_id}"
                )
            for item in component["inputs"]:
                logical = _logical_path(item["path"])
                content = _read_repository_file(root_descriptor, logical)
                if _sha256(content) != item["sha256"]:
                    raise SupplyChainContractError(f"build-plane input SHA-256 mismatch: {logical}")
                authority[logical.as_posix()] = content
        if inventory_bytes != _read_repository_file(root_descriptor, inventory_logical):
            raise SupplyChainContractError(
                "dependency inventory changed during build-plane generation"
            )
        return validated, inventory_bytes, authority
    finally:
        os.close(root_descriptor)


def _input_reference(path: str, sha256: str) -> str:
    identity = _sha256(f"{path}\0{sha256}".encode())
    return f"urn:searise:sbom:build-plane-input:sha256:{identity}"


def _expect_keys(value: object, keys: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != keys:
        raise SupplyChainContractError(f"{label} keys are not exact")
    return value


def _exact_string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise SupplyChainContractError(f"{label} must be a nonempty string")
    return value


def _exact_sha256(value: object, label: str) -> str:
    rendered = _exact_string(value, label)
    if not _SHA256.fullmatch(rendered):
        raise SupplyChainContractError(f"{label} must be a lowercase SHA-256")
    return rendered


def _authority_property(paths: list[str], authority: dict[str, bytes]) -> str:
    bindings = [{"path": path, "sha256": _sha256(authority[path])} for path in sorted(paths)]
    return json.dumps(bindings, sort_keys=True, separators=(",", ":"))


def _observable_component(
    *,
    kind: str,
    name: str,
    version: str,
    platform: str,
    authority_paths: list[str],
    authority: dict[str, bytes],
    digest: tuple[str, str] | None,
    extra: tuple[tuple[str, object], ...] = (),
) -> tuple[dict[str, Any], str]:
    authority_value = _authority_property(authority_paths, authority)
    digest_value = (
        f"{digest[0].lower()}:{digest[1]}"
        if digest
        else f"authority-sha256:{_sha256(authority_value.encode())}"
    )
    identity = json.dumps(
        [kind, name, version, platform, digest_value, authority_value],
        separators=(",", ":"),
    )
    reference = f"urn:searise:sbom:build-plane-component:sha256:{_sha256(identity.encode())}"
    component: dict[str, Any] = {
        "type": "container" if kind == "oci-base" else "library",
        "bom-ref": reference,
        "name": name,
        "version": version,
        "properties": _properties(
            ("authority.inputs", authority_value),
            ("digest", digest_value),
            ("kind", kind),
            ("platform", platform),
            *extra,
        ),
    }
    if digest:
        component["hashes"] = [{"alg": digest[0], "content": digest[1]}]
    return component, reference


def _docker_base(value: bytes, label: str) -> tuple[str, str | None, str]:
    try:
        text = value.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SupplyChainContractError(f"{label} must be UTF-8") from exc
    images = re.findall(r"^FROM\s+([^\s]+)\s*$", text, flags=re.MULTILINE)
    if len(images) != 1:
        raise SupplyChainContractError(f"{label} must contain exactly one FROM image")
    match = re.fullmatch(r"([a-z0-9./_-]+)(?::([A-Za-z0-9._-]+))?@sha256:([0-9a-f]{64})", images[0])
    if not match:
        raise SupplyChainContractError(f"{label} base image must be digest pinned")
    return match.group(1), match.group(2), match.group(3)


def _actions(
    authority: dict[str, bytes],
    _input_refs: dict[str, str],
) -> tuple[list[dict[str, Any]], dict[str, set[str]]]:
    observed: dict[str, tuple[str, str, set[str]]] = {}
    descriptors = sorted(
        path
        for path in authority
        if path.startswith(".github/workflows/")
        or (
            path.startswith(".github/actions/")
            and PurePosixPath(path).name in {"action.yml", "action.yaml"}
        )
    )
    if local_descriptors := [path for path in descriptors if path.startswith(".github/actions/")]:
        raise SupplyChainContractError(
            f"local composite Actions are not covered: {local_descriptors}"
        )
    for path in descriptors:
        try:
            lines = authority[path].decode("utf-8").splitlines()
        except UnicodeDecodeError as exc:
            raise SupplyChainContractError(f"workflow must be UTF-8: {path}") from exc
        for line in lines:
            if "uses:" not in line:
                continue
            if re.match(r"^\s*(?:-\s*)?uses:\s*\./", line):
                raise SupplyChainContractError(f"local composite Action use is not covered: {path}")
            match = _ACTION.fullmatch(line)
            if not match:
                raise SupplyChainContractError(
                    f"external GitHub Action is not fully pinned: {path}"
                )
            name, revision, version = match.groups()
            current = observed.setdefault(name, (revision, version, set()))
            if current[:2] != (revision, version):
                raise SupplyChainContractError(f"GitHub Action has conflicting pins: {name}")
            current[2].add(path)
    components: list[dict[str, Any]] = []
    for name, (revision, version, paths) in sorted(observed.items()):
        component, _ = _observable_component(
            kind="github-action",
            name=name,
            version=revision,
            platform="github-actions",
            authority_paths=sorted(paths),
            authority=authority,
            digest=("SHA-1", revision),
            extra=(
                ("action.comment-version", version),
                ("action.comment-version-authoritative", False),
                ("action.revision", revision),
                ("action.uses", f"{name}@{revision}"),
            ),
        )
        components.append(component)
    return components, {}


def _native_components(
    authority: dict[str, bytes],
    _input_refs: dict[str, str],
) -> tuple[list[dict[str, Any]], dict[str, set[str]]]:
    components: list[dict[str, Any]] = []
    edges: dict[str, set[str]] = {}
    receipts: dict[str, tuple[str, dict[str, Any]]] = {}
    for platform, receipt_platform, path, recipe in (
        ("linux-x86_64", "linux-x86_64", _LINUX_RECEIPT, _LINUX_RECIPE),
        ("macos-arm64", "darwin-arm64", _MACOS_RECEIPT, _MACOS_RECIPE),
    ):
        receipt = _expect_keys(
            _parse_inventory(authority[path]),
            {
                "buildCommand",
                "buildEnvironment",
                "commit",
                "decodeBinarySha256",
                "platform",
                "schemaVersion",
                "sourceSha256",
                "tippecanoeBinarySha256",
                "version",
            },
            f"{platform} native receipt",
        )
        environment = receipt["buildEnvironment"]
        expected_environment = (
            {
                "baseImage",
                "buildRecipePath",
                "buildRecipeSha256",
                "compiler",
                "packages",
                "runtimeLibraries",
            }
            if platform == "linux-x86_64"
            else {
                "architecture",
                "buildRecipePath",
                "buildRecipeSha256",
                "compiler",
                "sdkVersion",
                "xcodeBuild",
                "xcodeVersion",
            }
        )
        environment = _expect_keys(
            environment, expected_environment, f"{platform} build environment"
        )
        if platform == "macos-arm64" and environment != {
            "architecture": "arm64",
            "buildRecipePath": _MACOS_RECIPE,
            "buildRecipeSha256": _REVIEWED_AUTHORITY_SHA256[_MACOS_RECIPE],
            "compiler": "Apple clang version 15.0.0 (clang-1500.3.9.4)",
            "sdkVersion": "14.5",
            "xcodeBuild": "15F31d",
            "xcodeVersion": "15.4",
        }:
            raise SupplyChainContractError("macos-arm64 toolchain semantics changed")
        if (
            receipt["schemaVersion"] != 1
            or receipt["platform"] != receipt_platform
            or receipt["version"] != _TIPPECANOE_VERSION
            or receipt["buildCommand"] != ["make", "-j4", "tippecanoe", "tippecanoe-decode"]
            or environment["buildRecipePath"] != recipe
            or environment["buildRecipeSha256"] != _sha256(authority[recipe])
        ):
            raise SupplyChainContractError(f"{platform} native receipt semantics changed")
        commit = _exact_string(receipt["commit"], f"{platform} source commit")
        if not re.fullmatch(r"[0-9a-f]{40}", commit):
            raise SupplyChainContractError(f"{platform} source commit is not exact")
        source_sha = _exact_sha256(receipt["sourceSha256"], f"{platform} source SHA-256")
        receipts[platform] = (path, receipt)
        for name, key in (
            ("tippecanoe", "tippecanoeBinarySha256"),
            ("tippecanoe-decode", "decodeBinarySha256"),
        ):
            digest = _exact_sha256(receipt[key], f"{platform} {name} SHA-256")
            component, _ = _observable_component(
                kind="native-binary",
                name=name,
                version=_TIPPECANOE_VERSION,
                platform=platform,
                authority_paths=[path, recipe],
                authority=authority,
                digest=("SHA-256", digest),
                extra=(
                    ("receipt.platform", receipt_platform),
                    ("source.commit", commit),
                    ("source.sha256", source_sha),
                ),
            )
            components.append(component)
    if any(
        receipts[p][1][key] != receipts["linux-x86_64"][1][key]
        for p in receipts
        for key in ("commit", "sourceSha256", "version")
    ):
        raise SupplyChainContractError(
            "Tippecanoe platform receipts do not share one source identity"
        )

    linux = receipts["linux-x86_64"][1]
    linux_environment = linux["buildEnvironment"]
    image = _exact_string(linux_environment["baseImage"], "Linux receipt base image")
    image_match = re.fullmatch(r"([a-z0-9./_-]+):([A-Za-z0-9._-]+)@sha256:([0-9a-f]{64})", image)
    recipe_name, recipe_tag, recipe_digest = _docker_base(authority[_LINUX_RECIPE], "Linux recipe")
    if not image_match or (image_match.group(1), image_match.group(3)) != (
        recipe_name,
        recipe_digest,
    ):
        raise SupplyChainContractError("Linux receipt and recipe base images differ")
    base, base_ref = _observable_component(
        kind="oci-base",
        name=image_match.group(1),
        version=image_match.group(2),
        platform="linux-x86_64",
        authority_paths=[_LINUX_RECEIPT, _LINUX_RECIPE],
        authority=authority,
        digest=("SHA-256", image_match.group(3)),
        extra=(("oci.reference", image),),
    )
    components.append(base)

    package_refs: dict[str, str] = {}
    for role, values in _LINUX_PACKAGE_ROLES.items():
        if linux_environment[role] != values:
            raise SupplyChainContractError(f"Linux receipt {role} changed")
        for name, version in sorted(values.items()):
            package, reference = _observable_component(
                kind="native-package",
                name=name,
                version=version,
                platform="linux-x86_64",
                authority_paths=[
                    _LINUX_RECEIPT,
                    *([_LINUX_RECIPE] if role == "packages" else []),
                ],
                authority=authority,
                digest=None,
                extra=(
                    ("package.ecosystem", "deb"),
                    ("package.role", "build" if role == "packages" else "runtime"),
                ),
            )
            components.append(package)
            package_refs[name] = reference
    runtime_refs = {package_refs[name] for name in _LINUX_PACKAGE_ROLES["runtimeLibraries"]}
    for component in components:
        if (
            component["name"] in {"tippecanoe", "tippecanoe-decode"}
            and _properties_dict(component)["platform"] == "linux-x86_64"
        ):
            edges.setdefault(component["bom-ref"], set()).update(runtime_refs | {base_ref})

    release_name, release_tag, release_digest = _docker_base(
        authority[_RELEASE_DOCKERFILE], "controlled-release Dockerfile"
    )
    if release_tag is None:
        raise SupplyChainContractError("controlled-release base image must retain an exact tag")
    release, _ = _observable_component(
        kind="oci-base",
        name=release_name,
        version=release_tag,
        platform="linux-container",
        authority_paths=[_RELEASE_DOCKERFILE],
        authority=authority,
        digest=("SHA-256", release_digest),
        extra=(("oci.reference", f"{release_name}:{release_tag}@sha256:{release_digest}"),),
    )
    components.append(release)
    return components, edges


def _properties_dict(component: dict[str, Any]) -> dict[str, str]:
    return {
        item["name"].removeprefix(f"{_PROPERTY_PREFIX}."): item["value"]
        for item in component["properties"]
    }


def _duckdb_components(
    authority: dict[str, bytes],
    input_refs: dict[str, str],
) -> tuple[list[dict[str, Any]], dict[str, set[str]]]:
    lock = _expect_keys(
        _parse_inventory(authority[_DUCKDB_LOCK]),
        {"schemaVersion", "tool", "extension", "platforms"},
        "DuckDB Spatial lock",
    )
    tool = _expect_keys(
        lock["tool"], {"package", "version", "pythonVersion", "pythonRequires"}, "DuckDB tool"
    )
    extension = _expect_keys(lock["extension"], {"name", "version"}, "DuckDB extension")
    platforms = _expect_keys(lock["platforms"], {"linux-x86_64", "macos-arm64"}, "DuckDB platforms")
    if (
        lock["schemaVersion"] != 1
        or tool
        != {
            "package": "duckdb",
            "version": _DUCKDB_VERSION,
            "pythonVersion": "3.11",
            "pythonRequires": ">=3.10",
        }
        or extension != {"name": "spatial", "version": f"v{_DUCKDB_VERSION}"}
    ):
        raise SupplyChainContractError("DuckDB Spatial lock identity changed")

    components: list[dict[str, Any]] = []
    edges: dict[str, set[str]] = {}
    expected_platforms = {"linux-x86_64": "linux_amd64", "macos-arm64": "osx_arm64"}
    for platform, duckdb_platform in expected_platforms.items():
        record = _expect_keys(
            platforms[platform],
            {"duckdbPlatform", "pythonWheel", "extensionArchive", "extension"},
            f"DuckDB {platform}",
        )
        if record["duckdbPlatform"] != duckdb_platform:
            raise SupplyChainContractError(f"DuckDB platform mapping changed: {platform}")
        entries = (
            ("duckdb-python-wheel", "pythonWheel", {"url", "byteSize", "sha256"}),
            (
                "duckdb-spatial-extension-archive",
                "extensionArchive",
                {"url", "relativePath", "byteSize", "sha256"},
            ),
            ("duckdb-spatial-extension", "extension", {"relativePath", "byteSize", "sha256"}),
        )
        references: dict[str, str] = {}
        for name, key, keys in entries:
            item = _expect_keys(record[key], keys, f"{platform} {key}")
            digest = _exact_sha256(item["sha256"], f"{platform} {key} SHA-256")
            size = item["byteSize"]
            if type(size) is not int or size <= 0:
                raise SupplyChainContractError(f"{platform} {key} byteSize must be positive")
            extra: list[tuple[str, object]] = [
                ("artifact.byte-size", size),
                ("artifact.claim", "lock-recorded"),
                ("duckdb.platform", duckdb_platform),
            ]
            if "url" in item:
                url = _exact_string(item["url"], f"{platform} {key} URL")
                extra.append(("artifact.url", url))
            if "relativePath" in item:
                relative_path = _logical_path(
                    _exact_string(item["relativePath"], f"{platform} {key} path")
                )
                expected_suffix = (
                    "spatial.duckdb_extension.gz"
                    if key == "extensionArchive"
                    else "spatial.duckdb_extension"
                )
                if (
                    relative_path.parts[:3] != ("duckdb", f"v{_DUCKDB_VERSION}", duckdb_platform)
                    or relative_path.name != expected_suffix
                ):
                    raise SupplyChainContractError(f"{platform} {key} relative path changed")
                extra.append(("artifact.relative-path", relative_path.as_posix()))
            component, reference = _observable_component(
                kind="duckdb-artifact",
                name=name,
                version=_DUCKDB_VERSION if key == "pythonWheel" else f"v{_DUCKDB_VERSION}",
                platform=platform,
                authority_paths=[_DUCKDB_LOCK],
                authority=authority,
                digest=("SHA-256", digest),
                extra=tuple(extra),
            )
            components.append(component)
            references[key] = reference
        edges.setdefault(references["extension"], set()).add(references["extensionArchive"])
    return components, edges


def _observable_components(
    authority: dict[str, bytes],
    input_refs: dict[str, str],
) -> tuple[list[dict[str, Any]], dict[str, set[str]]]:
    if changed := [
        path
        for path, expected in _REVIEWED_AUTHORITY_SHA256.items()
        if _sha256(authority[path]) != expected
    ]:
        raise SupplyChainContractError(f"reviewed build-plane authority bytes changed: {changed}")
    components: list[dict[str, Any]] = []
    edges: dict[str, set[str]] = {}
    for builder in (_actions, _native_components, _duckdb_components):
        next_components, next_edges = builder(authority, input_refs)
        components.extend(next_components)
        for reference, dependencies in next_edges.items():
            edges.setdefault(reference, set()).update(dependencies)
    references = [component["bom-ref"] for component in components]
    if len(references) != len(set(references)):
        raise SupplyChainContractError("observable build-plane components are not unique")
    for component in components:
        properties = _properties_dict(component)
        for binding in json.loads(properties["authority.inputs"]):
            edges.setdefault(input_refs[binding["path"]], set()).add(component["bom-ref"])
    return components, edges


def generate_build_plane_sbom(
    inventory_path: Path,
    *,
    repository_root: Path,
) -> dict[str, Any]:
    """Generate a canonical CycloneDX 1.7 BOM from reviewed build-plane inputs."""
    inventory, inventory_bytes, authority = _authority(
        inventory_path,
        repository_root=repository_root,
    )
    inventory_sha256 = _sha256(inventory_bytes)
    by_id = {component["id"]: component for component in inventory["components"]}
    components: list[dict[str, Any]] = []
    references: list[str] = []
    input_refs: dict[str, str] = {}
    for component_id in _INCLUDED_COMPONENTS:
        source = by_id[component_id]
        for item in source["inputs"]:
            path = item["path"]
            reference = _input_reference(path, item["sha256"])
            references.append(reference)
            input_refs[path] = reference
            components.append(
                {
                    "type": "file",
                    "bom-ref": reference,
                    "name": path,
                    "hashes": [{"alg": "SHA-256", "content": item["sha256"]}],
                    "properties": _properties(
                        ("coverage", source["coverage"]),
                        ("ecosystem", source["ecosystem"]),
                        ("input.path", path),
                        ("input.role", item["role"]),
                        ("inventory.component", component_id),
                        ("release-use", source["releaseUse"]),
                    ),
                }
            )
    observable, edges = _observable_components(authority, input_refs)
    components.extend(observable)
    components.sort(
        key=lambda component: (
            component["name"],
            component.get("version", ""),
            component["bom-ref"],
        )
    )
    root_ref = f"urn:searise:sbom:build-plane:inventory-sha256:{inventory_sha256}"
    root_component = {
        "type": "application",
        "bom-ref": root_ref,
        "name": "searise-candidate-build-plane-inputs",
        "version": inventory["schemaVersion"],
        "properties": _properties(
            ("candidate-attachment", False),
            ("inventory.path", _INVENTORY_PATH.as_posix()),
            ("inventory.sha256", inventory_sha256),
            ("license-completeness", False),
            ("native-package-digest-completeness", False),
            ("opentofu.coverage", "not-present"),
            ("opentofu.input-count", 0),
            ("opentofu.release-use", "not-present"),
            ("production-claim", False),
            ("production-ready", False),
            ("release-approved", False),
            ("scope", "candidate-build-plane-observable-components"),
            ("signed", False),
            ("vulnerability-completeness", False),
        ),
    }
    document = {
        "$schema": "https://cyclonedx.org/schema/bom-1.7.schema.json",
        "bomFormat": "CycloneDX",
        "specVersion": "1.7",
        "serialNumber": f"urn:uuid:{uuid.uuid5(uuid.NAMESPACE_URL, root_ref)}",
        "version": 1,
        "metadata": {"component": root_component},
        "components": components,
        "dependencies": [
            {"ref": root_ref, "dependsOn": sorted(references)},
            *(
                {"ref": reference, "dependsOn": sorted(edges.get(reference, set()))}
                for reference in sorted([*references, *(item["bom-ref"] for item in observable)])
            ),
        ],
    }
    _validate_cyclonedx(document)
    _, current_inventory, current_authority = _authority(
        inventory_path,
        repository_root=repository_root,
    )
    if current_inventory != inventory_bytes or current_authority != authority:
        raise SupplyChainContractError("build-plane authority changed during SBOM generation")
    return document


def _read_canonical_sbom(path: Path) -> tuple[bytes, dict[str, Any]]:
    absolute = path.absolute()
    parts = absolute.parts
    directory = os.open(
        "/",
        os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_CLOEXEC", 0),
    )
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        for part in parts[1:-1]:
            child = os.open(part, flags | os.O_DIRECTORY, dir_fd=directory)
            os.close(directory)
            directory = child
        descriptor = os.open(
            parts[-1],
            flags | getattr(os, "O_NONBLOCK", 0),
            dir_fd=directory,
        )
        try:
            if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                raise SupplyChainContractError("build-plane SBOM must be a regular file")
            raw = _read_descriptor(
                descriptor,
                label="build-plane SBOM",
                path=path,
            )
        finally:
            os.close(descriptor)
    except OSError as exc:
        raise SupplyChainContractError(
            f"build-plane SBOM path must not use symlinks: {path}"
        ) from exc
    finally:
        os.close(directory)

    document = _parse_inventory(raw)
    try:
        canonical = canonical_sbom_bytes(document)
    except (TypeError, ValueError) as exc:
        raise SupplyChainContractError("build-plane SBOM contains a noncanonical value") from exc
    if raw != canonical:
        raise SupplyChainContractError("build-plane SBOM JSON is not canonical")
    _validate_cyclonedx(document)
    return raw, document


def validate_build_plane_sbom(
    sbom_path: Path,
    inventory_path: Path,
    *,
    repository_root: Path,
) -> dict[str, Any]:
    """Validate canonical BOM bytes against the reviewed current authority."""
    raw, document = _read_canonical_sbom(sbom_path)
    expected = generate_build_plane_sbom(
        inventory_path,
        repository_root=repository_root,
    )
    if raw != canonical_sbom_bytes(expected):
        raise SupplyChainContractError(
            "build-plane SBOM differs from dependency inventory authority"
        )
    return document


def publish_build_plane_sbom(
    output_path: Path,
    inventory_path: Path,
    *,
    repository_root: Path,
) -> dict[str, Any]:
    """Generate and durably publish one immutable build-plane SBOM."""
    document = generate_build_plane_sbom(
        inventory_path,
        repository_root=repository_root,
    )
    write_new_sbom(output_path, canonical_sbom_bytes(document))
    return document
