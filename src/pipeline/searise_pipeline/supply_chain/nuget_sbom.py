"""Target-aware CycloneDX generation from NuGet lock files and project manifests."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import re
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path, PurePosixPath
from typing import Any, Mapping
from urllib.parse import quote

from .contracts import SupplyChainContractError, _validate_cyclonedx
from .python_graph import _read_descriptor, _read_repository_file
from .sbom import canonical_sbom_bytes, write_new_sbom

_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_TARGET = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.+_-]{0,63}$")
_PREFIX = "org.searise.sbom"


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _canonical(value: object) -> str:
    return json.dumps(
        value, allow_nan=False, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    )


def _properties(*values: tuple[str, object]) -> list[dict[str, str]]:
    def render(value: object) -> str:
        return str(value).lower() if isinstance(value, bool) else str(value)

    return sorted(
        ({"name": f"{_PREFIX}.{name}", "value": render(value)} for name, value in values),
        key=lambda item: item["name"],
    )


def _logical_path(path: Path, repository_root: Path, *, label: str) -> PurePosixPath:
    root = repository_root.absolute()
    try:
        if root != repository_root.resolve(strict=True):
            raise SupplyChainContractError(f"{label} repository root must not be a symlink")
        candidate = path if path.is_absolute() else root / path
        relative = candidate.absolute().relative_to(root)
    except (OSError, ValueError) as exc:
        raise SupplyChainContractError(f"{label} path must be beneath the repository") from exc
    logical = PurePosixPath(relative.as_posix())
    if not logical.parts or any(part in {"", ".", ".."} for part in logical.parts):
        raise SupplyChainContractError(f"unsafe {label} path: {path}")
    return logical


def _load_json(data: bytes) -> dict[str, Any]:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise SupplyChainContractError(f"duplicate NuGet lock key: {key}")
            result[key] = value
        return result

    def reject_constant(value: str) -> None:
        raise SupplyChainContractError(f"invalid NuGet lock numeric constant: {value}")

    try:
        document = json.loads(
            data.decode("utf-8"),
            object_pairs_hook=reject_duplicates,
            parse_constant=reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SupplyChainContractError("NuGet lock must be valid UTF-8 JSON") from exc
    if not isinstance(document, dict):
        raise SupplyChainContractError("NuGet lock root must be an object")
    return document


def _reference_name(value: str) -> str:
    if not value or value.startswith(("/", "\\")) or ":" in value:
        raise SupplyChainContractError(f"unsupported ProjectReference path: {value}")
    logical = PurePosixPath(value.replace("\\", "/"))
    if logical.is_absolute() or logical.suffix != ".csproj" or not logical.stem:
        raise SupplyChainContractError(f"unsafe ProjectReference path: {value}")
    return logical.stem


def _parse_project(data: bytes, logical: PurePosixPath, target: str) -> dict[str, Any]:
    if b"<!DOCTYPE" in data.upper() or b"<!ENTITY" in data.upper():
        raise SupplyChainContractError(f"project XML declarations are unsupported: {logical}")
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise SupplyChainContractError(f"project manifest XML is malformed: {logical}") from exc
    if root.tag != "Project" or set(root.attrib) - {"Sdk"}:
        raise SupplyChainContractError(f"unsupported project manifest root: {logical}")
    frameworks = [item.text for item in root.iter("TargetFramework")]
    if frameworks != [target]:
        raise SupplyChainContractError(f"project target framework differs: {logical}")
    test_values = [item.text for item in root.iter("IsTestProject")]
    if test_values not in ([], ["true"], ["false"]):
        raise SupplyChainContractError(f"project test identity is ambiguous: {logical}")
    sdk = root.attrib.get("Sdk", "")
    kind = (
        "test"
        if test_values == ["true"]
        else "production-api"
        if sdk.endswith(".Web")
        else "library"
    )

    packages: dict[str, tuple[str, str]] = {}
    projects: dict[str, tuple[str, str]] = {}
    for item in root.iter():
        if "Condition" in item.attrib:
            raise SupplyChainContractError(f"conditional manifest is unsupported: {logical}")
        tag = item.tag
        if tag not in {"PackageReference", "ProjectReference"}:
            continue
        if set(item.attrib) - {"Include", "Version"}:
            raise SupplyChainContractError(f"conditional or unsupported dependency: {logical}")
        include = item.attrib.get("Include")
        if not isinstance(include, str) or not include:
            raise SupplyChainContractError(f"dependency Include is missing: {logical}")
        if tag == "PackageReference":
            version = item.attrib.get("Version")
            if not isinstance(version, str) or not version:
                raise SupplyChainContractError(f"PackageReference Version is missing: {logical}")
            if not _NAME.fullmatch(include) or include.casefold() in packages:
                raise SupplyChainContractError(f"invalid or duplicate PackageReference: {include}")
            packages[include.casefold()] = (include, version)
        else:
            name = _reference_name(include)
            if not _NAME.fullmatch(name) or name.casefold() in projects:
                raise SupplyChainContractError(f"invalid or duplicate ProjectReference: {include}")
            projects[name.casefold()] = (name, include)
    return {
        "name": logical.stem,
        "kind": kind,
        "packages": packages,
        "projects": projects,
    }


def _text(value: object, *, label: str) -> str:
    if not isinstance(value, str) or not value or any(ord(character) < 32 for character in value):
        raise SupplyChainContractError(f"NuGet {label} must be a non-empty string")
    return value


def _parse_entries(document: Mapping[str, Any], target: str) -> dict[str, dict[str, Any]]:
    if set(document) != {"version", "dependencies"} or type(document["version"]) is not int:
        raise SupplyChainContractError("NuGet lock v1 structure is required")
    if document["version"] != 1 or not isinstance(document["dependencies"], dict):
        raise SupplyChainContractError("NuGet lock v1 dependencies are required")
    targets = document["dependencies"]
    if target not in targets or not isinstance(targets[target], dict):
        raise SupplyChainContractError(f"NuGet target framework is absent: {target}")
    entries: dict[str, dict[str, Any]] = {}
    for name, raw in targets[target].items():
        if not isinstance(name, str) or not _NAME.fullmatch(name) or name.casefold() in entries:
            raise SupplyChainContractError(f"invalid or duplicate NuGet package identity: {name}")
        if not isinstance(raw, dict) or raw.get("type") not in {"Direct", "Transitive", "Project"}:
            raise SupplyChainContractError(f"unsupported NuGet dependency entry: {name}")
        dependency_type = raw["type"]
        required = {"type"} if dependency_type == "Project" else {"type", "resolved", "contentHash"}
        if dependency_type == "Direct":
            required.add("requested")
        if not required <= set(raw) or set(raw) - (required | {"dependencies"}):
            raise SupplyChainContractError(f"NuGet dependency fields differ: {name}")
        dependencies = raw.get("dependencies", {})
        if not isinstance(dependencies, dict):
            raise SupplyChainContractError(f"NuGet dependency ranges must be an object: {name}")
        ranges = {
            _text(dependency, label="dependency name"): _text(value, label="dependency range")
            for dependency, value in dependencies.items()
        }
        if len({dependency.casefold() for dependency in ranges}) != len(ranges):
            raise SupplyChainContractError(f"duplicate NuGet dependency identity: {name}")
        entry = {"name": name, "type": dependency_type, "dependencies": ranges}
        if dependency_type != "Project":
            entry["resolved"] = _text(raw["resolved"], label="resolved version")
            content_hash = _text(raw["contentHash"], label="contentHash")
            try:
                digest = base64.b64decode(content_hash, validate=True)
            except (binascii.Error, ValueError) as exc:
                raise SupplyChainContractError(f"invalid NuGet contentHash: {name}") from exc
            if len(digest) != 64:
                raise SupplyChainContractError(f"NuGet contentHash is not SHA-512: {name}")
            entry.update(content_hash=content_hash, sha512=digest.hex())
        if dependency_type == "Direct":
            entry["requested"] = _text(raw["requested"], label="requested range")
        entries[name.casefold()] = entry
    for entry in entries.values():
        missing = sorted(name for name in entry["dependencies"] if name.casefold() not in entries)
        if missing:
            raise SupplyChainContractError(
                f"unresolved NuGet dependencies: {entry['name']} -> {missing}"
            )
    return entries


def _authority(
    project_path: Path,
    lock_path: Path,
    *,
    repository_root: Path,
    target_framework: str,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]], dict[str, tuple[PurePosixPath, bytes]]]:
    if not isinstance(target_framework, str) or not _TARGET.fullmatch(target_framework):
        raise SupplyChainContractError("NuGet target framework must be explicit")
    project = _logical_path(project_path, repository_root, label="NuGet project")
    lock = _logical_path(lock_path, repository_root, label="NuGet lock")
    if lock.parent != project.parent:
        raise SupplyChainContractError("NuGet lock must be a sibling of its project manifest")

    flags = os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        root_descriptor = os.open(repository_root.absolute(), flags)
    except OSError as exc:
        raise SupplyChainContractError("NuGet repository root could not be opened") from exc
    try:
        lock_bytes = _read_repository_file(root_descriptor, lock)
        project_bytes = _read_repository_file(root_descriptor, project)
        entries = _parse_entries(_load_json(lock_bytes), target_framework)
        root_project = _parse_project(project_bytes, project, target_framework)
        direct = {name for name, entry in entries.items() if entry["type"] == "Direct"}
        if direct != set(root_project["packages"]):
            raise SupplyChainContractError(
                "root PackageReference set differs from Direct lock entries"
            )
        locked_projects = {name for name, entry in entries.items() if entry["type"] == "Project"}
        if not set(root_project["projects"]) <= locked_projects:
            raise SupplyChainContractError(
                "root ProjectReference is absent from Project lock entries"
            )

        roots = direct | set(root_project["projects"])
        reachable, pending_names = set(roots), list(roots)
        while pending_names:
            for dependency in entries[pending_names.pop()]["dependencies"]:
                key = dependency.casefold()
                if key not in reachable:
                    reachable.add(key)
                    pending_names.append(key)
        if reachable != set(entries):
            missing = sorted(set(entries) - reachable)
            raise SupplyChainContractError(f"unreachable NuGet lock entries: {missing}")

        snapshots = {"project": (project, project_bytes), "lock": (lock, lock_bytes)}
        for logical, original in snapshots.values():
            if _read_repository_file(root_descriptor, logical) != original:
                raise SupplyChainContractError(
                    f"NuGet authority changed during generation: {logical}"
                )
    finally:
        os.close(root_descriptor)
    return root_project, entries, snapshots


def _package_ref(entry: Mapping[str, Any]) -> str:
    return f"pkg:nuget/{quote(entry['name'], safe='')}@{quote(entry['resolved'], safe='')}"


def _project_ref(name: str, manifest_sha256: str) -> str:
    return f"urn:searise:nuget-project:{quote(name.casefold(), safe='')}:sha256:{manifest_sha256}"


def generate_nuget_sbom(
    project_path: Path,
    lock_path: Path,
    *,
    repository_root: Path,
    target_framework: str,
) -> dict[str, Any]:
    """Generate one canonicalizable CycloneDX 1.7 BOM for one project and TFM."""
    project, entries, snapshots = _authority(
        project_path,
        lock_path,
        repository_root=repository_root,
        target_framework=target_framework,
    )
    project_logical, project_bytes = snapshots["project"]
    lock_logical, lock_bytes = snapshots["lock"]
    project_sha256, lock_sha256 = _sha256(project_bytes), _sha256(lock_bytes)
    references: dict[str, str] = {}
    for key, entry in entries.items():
        if entry["type"] == "Project":
            references[key] = _project_ref(entry["name"], lock_sha256)
        else:
            references[key] = _package_ref(entry)

    components = []
    for key in sorted(entries):
        entry = entries[key]
        values: list[tuple[str, object]] = [
            ("nuget.dependencies", _canonical(entry["dependencies"])),
            ("nuget.dependency-type", entry["type"]),
            ("nuget.target-framework", target_framework),
        ]
        component: dict[str, Any] = {
            "type": "library",
            "bom-ref": references[key],
            "name": entry["name"],
        }
        if entry["type"] == "Project":
            values.extend(
                [
                    ("nuget.project.integrity", "not-available-in-packages-lock-v1"),
                    ("nuget.project.resolved-version", "not-available-in-packages-lock-v1"),
                ]
            )
        else:
            component.update(version=entry["resolved"], purl=references[key])
            component["hashes"] = [{"alg": "SHA-512", "content": entry["sha512"]}]
            values.append(("nuget.content-hash-base64", entry["content_hash"]))
            if entry["type"] == "Direct":
                values.extend(
                    [
                        ("nuget.manifest-version", project["packages"][key][1]),
                        ("nuget.requested", entry["requested"]),
                    ]
                )
        component["properties"] = _properties(*values)
        components.append(component)
    components.sort(key=lambda item: item["bom-ref"])

    root_ref = (
        f"urn:searise:nuget-root:sha256:{project_sha256}:"
        f"{lock_sha256}:{quote(target_framework, safe='')}"
    )
    root_component = {
        "type": "application" if project["kind"] != "library" else "library",
        "bom-ref": root_ref,
        "name": project["name"],
        "properties": _properties(
            ("candidate-inclusion", "unclaimed"),
            ("license-completeness", "unclaimed"),
            ("nuget.lock.path", lock_logical.as_posix()),
            ("nuget.lock.sha256", lock_sha256),
            ("nuget.lock.version", 1),
            ("nuget.project.kind", project["kind"]),
            ("nuget.project.manifest.path", project_logical.as_posix()),
            ("nuget.project.manifest.sha256", project_sha256),
            (
                "nuget.project.package-references",
                _canonical({name: version for name, version in project["packages"].values()}),
            ),
            ("nuget.target-framework", target_framework),
            ("production-claim", False),
            ("scope", "nuget-project-target-framework-lock"),
            ("vulnerability-completeness", "unclaimed"),
        ),
    }
    relationships: list[dict[str, Any]] = [
        {
            "ref": root_ref,
            "dependsOn": sorted(
                references[name] for name in set(project["packages"]) | set(project["projects"])
            ),
        }
    ]
    relationships.extend(
        {
            "ref": references[key],
            "dependsOn": sorted(references[name.casefold()] for name in entry["dependencies"]),
        }
        for key, entry in entries.items()
    )
    relationships.sort(key=lambda item: item["ref"])
    serial = uuid.uuid5(
        uuid.NAMESPACE_URL,
        f"https://artemsemdev.github.io/SeaRise-Europe/sbom/nuget/{project_sha256}/{lock_sha256}/{target_framework}",
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


def _read_regular_path(path: Path) -> bytes:
    absolute = path.absolute()
    directory = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    try:
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        for part in absolute.parts[1:-1]:
            child = os.open(part, flags | os.O_DIRECTORY, dir_fd=directory)
            os.close(directory)
            directory = child
        descriptor = os.open(absolute.name, flags | getattr(os, "O_NONBLOCK", 0), dir_fd=directory)
        try:
            return _read_descriptor(descriptor, label="NuGet SBOM", path=path)
        finally:
            os.close(descriptor)
    except OSError as exc:
        raise SupplyChainContractError(
            f"NuGet SBOM must be a regular file without symlinks: {path}"
        ) from exc
    finally:
        os.close(directory)


def validate_nuget_sbom(
    sbom_path: Path,
    project_path: Path,
    lock_path: Path,
    *,
    repository_root: Path,
    target_framework: str,
) -> dict[str, Any]:
    """Validate canonical SBOM bytes by exact regeneration from current authority."""
    raw = _read_regular_path(sbom_path)
    document = _load_json(raw)
    try:
        canonical = canonical_sbom_bytes(document)
    except (TypeError, ValueError) as exc:
        raise SupplyChainContractError("NuGet SBOM contains a noncanonical value") from exc
    if canonical != raw:
        raise SupplyChainContractError("NuGet SBOM JSON is not canonical")
    _validate_cyclonedx(document)
    expected = generate_nuget_sbom(
        project_path,
        lock_path,
        repository_root=repository_root,
        target_framework=target_framework,
    )
    if raw != canonical_sbom_bytes(expected):
        raise SupplyChainContractError("NuGet SBOM differs from its project/lock authority")
    return document


def publish_nuget_sbom(
    output_path: Path,
    project_path: Path,
    lock_path: Path,
    *,
    repository_root: Path,
    target_framework: str,
) -> dict[str, Any]:
    """Generate and durably publish one immutable project/TFM SBOM."""
    document = generate_nuget_sbom(
        project_path,
        lock_path,
        repository_root=repository_root,
        target_framework=target_framework,
    )
    write_new_sbom(output_path, canonical_sbom_bytes(document))
    return document
