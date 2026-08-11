"""CycloneDX input-authority foundation for candidate build-plane files."""

from __future__ import annotations

import hashlib
import json
import os
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


def generate_build_plane_sbom(
    inventory_path: Path,
    *,
    repository_root: Path,
) -> dict[str, Any]:
    """Generate a canonical CycloneDX 1.7 BOM from reviewed file inputs."""
    inventory, inventory_bytes, authority = _authority(
        inventory_path,
        repository_root=repository_root,
    )
    inventory_sha256 = _sha256(inventory_bytes)
    by_id = {component["id"]: component for component in inventory["components"]}
    components: list[dict[str, Any]] = []
    references: list[str] = []
    for component_id in _INCLUDED_COMPONENTS:
        source = by_id[component_id]
        for item in source["inputs"]:
            path = item["path"]
            reference = _input_reference(path, item["sha256"])
            references.append(reference)
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
    components.sort(key=lambda component: component["name"])
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
            ("opentofu.coverage", "not-present"),
            ("opentofu.input-count", 0),
            ("opentofu.release-use", "not-present"),
            ("production-claim", False),
            ("release-approved", False),
            ("scope", "candidate-build-plane-file-inputs-only"),
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
            *({"ref": reference, "dependsOn": []} for reference in sorted(references)),
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
