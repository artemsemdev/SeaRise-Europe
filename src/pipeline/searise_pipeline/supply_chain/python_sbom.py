"""Target-specific CycloneDX SBOMs from reviewed Python lock graphs."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import uuid
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import quote

from .contracts import SupplyChainContractError, _validate_cyclonedx
from .python_graph import (
    _logical_lock_path,
    _parse_lock,
    _read_descriptor,
    _read_repository_file,
    validate_python_lock_graph,
)
from .sbom import canonical_sbom_bytes

_PROPERTY_PREFIX = "org.searise.sbom"


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _property(name: str, value: object) -> dict[str, str]:
    rendered = str(value).lower() if isinstance(value, bool) else str(value)
    return {"name": f"{_PROPERTY_PREFIX}.{name}", "value": rendered}


def _properties(*values: tuple[str, object]) -> list[dict[str, str]]:
    return sorted((_property(name, value) for name, value in values), key=lambda item: item["name"])


def _canonical_value(value: object) -> str:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _repository_path(path: Path, repository_root: Path, *, label: str) -> PurePosixPath:
    root = repository_root.absolute()
    try:
        if root != repository_root.resolve(strict=True):
            raise SupplyChainContractError(f"{label} repository root must not be a symlink")
        candidate = path if path.is_absolute() else root / path
        relative = candidate.absolute().relative_to(root)
    except (OSError, ValueError) as exc:
        raise SupplyChainContractError(f"{label} path must be beneath the repository") from exc
    return _logical_lock_path(relative.as_posix())


def _validated_authority(
    annotation_path: Path,
    *,
    repository_root: Path,
    target_id: str,
) -> tuple[dict[str, Any], bytes, PurePosixPath, dict[str, Any], dict[str, tuple[str, str]]]:
    if type(target_id) is not str or not target_id:
        raise SupplyChainContractError("Python SBOM target ID must be a non-empty string")
    annotation_logical = _repository_path(
        annotation_path, repository_root, label="Python graph annotation"
    )
    root_flags = os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_CLOEXEC", 0)
    root_flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        root_descriptor = os.open(repository_root.absolute(), root_flags)
    except OSError as exc:
        raise SupplyChainContractError("Python SBOM repository root could not be opened") from exc
    try:
        annotation_bytes = _read_repository_file(root_descriptor, annotation_logical)
        with tempfile.TemporaryDirectory(prefix="searise-python-sbom-") as temporary:
            snapshot = Path(temporary) / "annotation.json"
            snapshot.write_bytes(annotation_bytes)
            document = validate_python_lock_graph(snapshot, repository_root=repository_root)
        matches = [target for target in document["targets"] if target["id"] == target_id]
        if len(matches) != 1:
            raise SupplyChainContractError(
                f"Python SBOM target ID must select exactly one graph target: {target_id}"
            )
        target = matches[0]
        lock_logical = _logical_lock_path(target["lock"]["path"])
        lock_bytes = _read_repository_file(root_descriptor, lock_logical)
        locked_packages = _parse_lock(lock_bytes, lock_logical, target["lock"]["sha256"])
        if _read_repository_file(root_descriptor, annotation_logical) != annotation_bytes:
            raise SupplyChainContractError("Python graph annotation changed during SBOM generation")
    finally:
        os.close(root_descriptor)
    return document, annotation_bytes, annotation_logical, target, locked_packages


def _python_purl(name: str, version: str) -> str:
    return f"pkg:pypi/{quote(name, safe='')}@{quote(version, safe='')}"


def _root_reference(
    annotation_sha256: str,
    schema_version: str,
    target_id: str,
) -> str:
    return (
        "pkg:generic/searise-python-environment"
        f"@{quote(schema_version, safe='')}"
        f"?annotation_sha256={annotation_sha256}&target={quote(target_id, safe='')}"
    )


def generate_python_sbom(
    annotation_path: Path,
    *,
    repository_root: Path,
    target_id: str,
) -> dict[str, Any]:
    """Generate one deterministic CycloneDX 1.7 BOM for one reviewed target."""
    document, annotation_bytes, annotation_logical, target, locked = _validated_authority(
        annotation_path,
        repository_root=repository_root,
        target_id=target_id,
    )
    annotation_sha256 = _sha256(annotation_bytes)
    packages = {package["name"]: package for package in document["packages"]}
    purls = {name: _python_purl(name, version) for name, (version, _) in locked.items()}
    data_provenance = (
        "synthetic-fixture" if document["review"]["status"] == "synthetic" else "real-source"
    )
    root_ref = _root_reference(annotation_sha256, document["schemaVersion"], target_id)
    marker_environment = _canonical_value(target["markerEnvironment"])

    components = []
    for name in sorted(packages):
        package = packages[name]
        version, wheel_sha256 = locked[name]
        components.append(
            {
                "type": "library",
                "bom-ref": purls[name],
                "name": name,
                "version": version,
                "purl": purls[name],
                "hashes": [{"alg": "SHA-256", "content": wheel_sha256}],
                "properties": _properties(
                    ("python.dependencies", _canonical_value(package["dependencies"])),
                    ("python.root", package["root"]),
                    ("python.selected-extras", _canonical_value(package["selectedExtras"])),
                    ("python.target.id", target_id),
                ),
            }
        )
    components.sort(key=lambda component: (component["purl"], component["bom-ref"]))

    relationships: list[dict[str, Any]] = [
        {
            "ref": root_ref,
            "dependsOn": sorted(
                purls[name] for name, package in packages.items() if package["root"]
            ),
        }
    ]
    relationships.extend(
        {
            "ref": purls[name],
            "dependsOn": sorted(purls[edge["name"]] for edge in packages[name]["dependencies"]),
        }
        for name in sorted(packages)
    )
    relationships.sort(key=lambda relationship: relationship["ref"])

    root_component = {
        "type": "application",
        "bom-ref": root_ref,
        "name": "searise-python-environment",
        "version": document["schemaVersion"],
        "purl": root_ref,
        "properties": _properties(
            ("annotation.id", document["annotationId"]),
            ("annotation.path", annotation_logical.as_posix()),
            ("annotation.sha256", annotation_sha256),
            ("data-provenance-class", data_provenance),
            ("production-claim", document["review"]["productionClaim"]),
            ("python.graph-scope", document["graphScope"]),
            ("python.lock.path", target["lock"]["path"]),
            ("python.lock.sha256", target["lock"]["sha256"]),
            ("python.review.status", document["review"]["status"]),
            ("python.target.id", target_id),
            ("python.target.marker-environment", marker_environment),
        ),
    }
    serial = uuid.uuid5(
        uuid.NAMESPACE_URL,
        f"https://artemsemdev.github.io/SeaRise-Europe/sbom/python/{annotation_sha256}/{target_id}",
    )
    sbom = {
        "$schema": "https://cyclonedx.org/schema/bom-1.7.schema.json",
        "bomFormat": "CycloneDX",
        "specVersion": "1.7",
        "serialNumber": f"urn:uuid:{serial}",
        "version": 1,
        "metadata": {"component": root_component},
        "components": components,
        "dependencies": relationships,
    }
    _validate_cyclonedx(sbom)
    return sbom


def _read_regular_path(path: Path) -> bytes:
    absolute = path.absolute()
    directory = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    try:
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        for part in absolute.parts[1:-1]:
            child = os.open(part, flags | os.O_DIRECTORY, dir_fd=directory)
            os.close(directory)
            directory = child
        descriptor = os.open(
            absolute.name,
            flags | getattr(os, "O_NONBLOCK", 0),
            dir_fd=directory,
        )
        try:
            return _read_descriptor(descriptor, label="Python SBOM", path=path)
        finally:
            os.close(descriptor)
    except OSError as exc:
        raise SupplyChainContractError(
            f"Python SBOM path must be a regular file without symlinks: {path}"
        ) from exc
    finally:
        os.close(directory)


def _load_canonical_sbom(path: Path) -> tuple[bytes, dict[str, Any]]:
    raw = _read_regular_path(path)

    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        output: dict[str, Any] = {}
        for key, value in pairs:
            if key in output:
                raise SupplyChainContractError(f"duplicate Python SBOM key: {key}")
            output[key] = value
        return output

    def reject_constant(value: str) -> None:
        raise SupplyChainContractError(f"invalid Python SBOM numeric constant: {value}")

    try:
        parsed = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=reject_duplicates,
            parse_constant=reject_constant,
        )
    except UnicodeDecodeError as exc:
        raise SupplyChainContractError("Python SBOM must be UTF-8") from exc
    except json.JSONDecodeError as exc:
        raise SupplyChainContractError("Python SBOM JSON is malformed") from exc
    if not isinstance(parsed, dict):
        raise SupplyChainContractError("Python SBOM root must be an object")
    try:
        canonical = canonical_sbom_bytes(parsed)
    except (TypeError, ValueError) as exc:
        raise SupplyChainContractError("Python SBOM contains a noncanonical value") from exc
    if canonical != raw:
        raise SupplyChainContractError("Python SBOM JSON is not canonical")
    _validate_cyclonedx(parsed)
    return raw, parsed


def validate_python_sbom(
    sbom_path: Path,
    annotation_path: Path,
    *,
    repository_root: Path,
    target_id: str,
) -> dict[str, Any]:
    """Validate exact canonical BOM bytes against their current graph authority."""
    raw, document = _load_canonical_sbom(sbom_path)
    expected = generate_python_sbom(
        annotation_path,
        repository_root=repository_root,
        target_id=target_id,
    )
    if raw != canonical_sbom_bytes(expected):
        raise SupplyChainContractError("Python SBOM differs from its graph target authority")
    return document
