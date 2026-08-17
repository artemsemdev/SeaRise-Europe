"""Validate the active static-browser supply-chain profile."""

from __future__ import annotations

import hashlib
import json
import re
import stat
from pathlib import Path, PurePosixPath
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from .contracts import SupplyChainContractError
from .python_sbom import validate_python_sbom
from .sbom import validate_npm_sbom

REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
CONTRACT_ROOT = REPOSITORY_ROOT / "contracts" / "supply-chain" / "v2"

_EXPECTED_COMPONENTS = {
    "active-sboms": ("cyclonedx", "candidate", "locked"),
    "github-actions": ("github-actions", "candidate", "locked"),
    "native-build-plane": ("native", "candidate", "locked"),
    "pipeline-container": ("container", "candidate", "locked"),
    "pipeline-geoid-evaluator": ("python", "candidate", "locked"),
    "pipeline-python-contributor": ("python", "development", "range-constrained"),
    "pipeline-python-release": ("python", "candidate", "locked"),
    "provenance-signing-contracts": ("standard-schema", "candidate", "locked"),
    "settlement-spatial-python": ("python", "candidate", "locked"),
    "static-web-npm": ("npm", "candidate", "locked"),
    "vendored-cyclonedx-schemas": ("standard-schema", "candidate", "locked"),
}
_REQUIRED_PATHS = frozenset(
    {
        ".github/workflows/ci.yml",
        ".github/workflows/codeql.yml",
        ".github/workflows/offline-release-controlled.yml",
        ".github/workflows/phase-0r-owner-promotion.yml",
        ".github/workflows/phase-1-release-sign.yml",
        "contracts/release/v2/browser-derivation-provenance.schema.json",
        "contracts/supply-chain/v1/build-types/offline-release-real-source-v1.json",
        "contracts/supply-chain/v1/build-types/offline-release-v1.json",
        "contracts/supply-chain/v1/cosign-tool-lock.schema.json",
        "contracts/supply-chain/v1/cryptographic-verification-receipt.schema.json",
        "contracts/supply-chain/v1/evidence-envelope.schema.json",
        "contracts/supply-chain/v1/identity-policy.json",
        "contracts/supply-chain/v1/identity-policy.schema.json",
        "contracts/supply-chain/v1/python-graphs/release-runtime.json",
        "contracts/supply-chain/v1/python-graphs/settlement-spatial-runtime.json",
        "contracts/supply-chain/v1/public-readback-verification-receipt.schema.json",
        "contracts/supply-chain/v1/real-source-unverified-evidence-envelope.schema.json",
        "contracts/supply-chain/v1/release-evidence-retention-receipt.schema.json",
        "contracts/supply-chain/v1/sboms/python-release-linux-x86-64-cp311.cdx.json",
        "contracts/supply-chain/v1/sboms/python-release-macos-arm64-cp311.cdx.json",
        "contracts/supply-chain/v1/sboms/python-settlement-spatial-linux-x86-64-cp311.cdx.json",
        "contracts/supply-chain/v1/sboms/python-settlement-spatial-macos-arm64-cp311.cdx.json",
        "contracts/supply-chain/v1/tools/cosign-linux-amd64.json",
        "contracts/supply-chain/v1/vendor/bom-1.7.schema.json",
        "contracts/supply-chain/v1/vendor/cryptography-defs.schema.json",
        "contracts/supply-chain/v1/vendor/jsf-0.82.schema.json",
        "contracts/supply-chain/v1/vendor/manifest.json",
        "contracts/supply-chain/v1/vendor/spdx.schema.json",
        "contracts/supply-chain/v2/python/static-target-contributor-requirements.txt",
        "contracts/supply-chain/v2/sboms/static-web-npm.cdx.json",
        "package-lock.json",
        "package.json",
        "src/pipeline/offline_release/Dockerfile",
        "src/pipeline/requirements-phase1-final-macos-x86_64.lock",
        "src/pipeline/requirements-release-macos-arm64.lock",
        "src/pipeline/requirements-release.lock",
        "src/pipeline/requirements-settlements-spatial-linux-x86_64.lock",
        "src/pipeline/requirements-settlements-spatial-macos-arm64.lock",
        "src/pipeline/science/geoid-evaluator-requirements.txt",
        "src/pipeline/toolchain/Dockerfile.tippecanoe-linux-x86_64",
        "src/pipeline/toolchain/build_macos_tippecanoe.sh",
        "src/pipeline/toolchain/duckdb-spatial-extensions.json",
        "src/pipeline/toolchain/tippecanoe-darwin-arm64-build-receipt.json",
        "src/pipeline/toolchain/tippecanoe-linux-x86_64-build-receipt.json",
        "src/web/package.json",
    }
)
_FORBIDDEN_PREFIXES = (
    "infra/blob-seed/",
    "src/api/",
    "src/frontend/",
)
_FORBIDDEN_FILES = frozenset(
    {"compose.yaml", "compose.yml", "docker-compose.yaml", "docker-compose.yml"}
)
_EXPECTED_EXCLUSIONS = [
    "api-nuget",
    "azurite-blob-seed",
    "legacy-compose-runtime",
    "legacy-runtime-images",
    "nextjs-frontend-runtime",
]
_STATIC_CONTRIBUTOR_REQUIREMENTS = (
    "contracts/supply-chain/v2/python/static-target-contributor-requirements.txt"
)
_EXPECTED_CONTRIBUTOR_PACKAGES = frozenset(
    {
        "click",
        "cryptography",
        "geopandas",
        "jsonschema",
        "netcdf4",
        "numpy",
        "pandas",
        "pyarrow",
        "pyproj",
        "pytest",
        "rasterio",
        "rio-cogeo",
        "shapely",
        "xarray",
    }
)
_LEGACY_PYTHON_PACKAGES = frozenset({"azure-storage-blob", "psycopg2-binary"})
_REQUIREMENT_NAME = re.compile(r"^([A-Za-z0-9][A-Za-z0-9_.-]*)")
_PYTHON_SBOMS = {
    "contracts/supply-chain/v1/sboms/python-release-linux-x86-64-cp311.cdx.json": (
        "contracts/supply-chain/v1/python-graphs/release-runtime.json",
        "linux-x86-64-cp311",
    ),
    "contracts/supply-chain/v1/sboms/python-release-macos-arm64-cp311.cdx.json": (
        "contracts/supply-chain/v1/python-graphs/release-runtime.json",
        "macos-arm64-cp311",
    ),
    "contracts/supply-chain/v1/sboms/python-settlement-spatial-linux-x86-64-cp311.cdx.json": (
        "contracts/supply-chain/v1/python-graphs/settlement-spatial-runtime.json",
        "linux-x86-64-cp311",
    ),
    "contracts/supply-chain/v1/sboms/python-settlement-spatial-macos-arm64-cp311.cdx.json": (
        "contracts/supply-chain/v1/python-graphs/settlement-spatial-runtime.json",
        "macos-arm64-cp311",
    ),
}


def _load_strict_json(path: Path, *, label: str) -> dict[str, Any]:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise SupplyChainContractError(f"duplicate {label} key: {key}")
            result[key] = value
        return result

    try:
        document = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=reject_duplicates,
            parse_constant=lambda value: (_ for _ in ()).throw(
                SupplyChainContractError(f"invalid {label} numeric constant: {value}")
            ),
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SupplyChainContractError(f"{label} is not valid UTF-8 JSON") from exc
    if not isinstance(document, dict):
        raise SupplyChainContractError(f"{label} root must be an object")
    return document


def _safe_regular_file(repository_root: Path, value: str) -> Path:
    logical = PurePosixPath(value)
    if (
        not value
        or "\\" in value
        or logical.is_absolute()
        or logical.as_posix() != value
        or any(part in {"", ".", ".."} for part in logical.parts)
    ):
        raise SupplyChainContractError(f"unsafe static supply-chain input path: {value}")
    root = repository_root.resolve(strict=True)
    candidate = repository_root
    for part in logical.parts:
        candidate = candidate / part
        if candidate.is_symlink():
            raise SupplyChainContractError(
                f"static supply-chain input must not use symlinks: {value}"
            )
    try:
        mode = candidate.stat().st_mode
        candidate.resolve(strict=True).relative_to(root)
    except (OSError, ValueError) as exc:
        raise SupplyChainContractError(
            f"static supply-chain input is outside or missing: {value}"
        ) from exc
    if not stat.S_ISREG(mode):
        raise SupplyChainContractError(
            f"static supply-chain input must be a regular file: {value}"
        )
    return candidate


def _validate_static_contributor_manifest(repository_root: Path) -> None:
    manifest = repository_root / _STATIC_CONTRIBUTOR_REQUIREMENTS
    names: list[str] = []
    for line_number, raw in enumerate(manifest.read_text(encoding="utf-8").splitlines(), 1):
        value = raw.split("#", 1)[0].strip()
        if not value:
            continue
        match = _REQUIREMENT_NAME.match(value)
        if match is None:
            raise SupplyChainContractError(
                f"invalid static contributor requirement at line {line_number}"
            )
        names.append(match.group(1).lower().replace("_", "-"))
    forbidden = sorted(set(names) & _LEGACY_PYTHON_PACKAGES)
    if forbidden:
        raise SupplyChainContractError(
            f"legacy Python packages cannot enter the static target: {forbidden}"
        )
    if len(names) != len(set(names)) or names != sorted(names):
        raise SupplyChainContractError(
            "static contributor requirements must be unique and sorted"
        )
    if set(names) != set(_EXPECTED_CONTRIBUTOR_PACKAGES):
        raise SupplyChainContractError("static contributor package set drifted")


def _validate_static_npm_semantics(repository_root: Path) -> None:
    sbom_path = repository_root / "contracts/supply-chain/v2/sboms/static-web-npm.cdx.json"
    document = _load_strict_json(sbom_path, label="static web npm SBOM")
    root = document.get("metadata", {}).get("component", {})
    components = [root, *document.get("components", [])]
    legacy_names = sorted(
        {
            component.get("name", "")
            for component in components
            if isinstance(component, dict)
            and (
                str(component.get("name", "")).casefold() == "next"
                or str(component.get("name", "")).casefold().startswith("@next/")
            )
        }
    )
    property_values = {
        str(item.get("value", ""))
        for component in components
        if isinstance(component, dict)
        for item in component.get("properties", [])
        if isinstance(item, dict)
    }
    if legacy_names or any("src/frontend" in value for value in property_values):
        raise SupplyChainContractError(
            "Next.js or src/frontend cannot enter the active static npm graph"
        )
    root_properties = {
        item.get("name"): item.get("value")
        for item in root.get("properties", [])
        if isinstance(item, dict)
    }
    if (
        root.get("name") != "@searise/web"
        or root_properties.get("org.searise.sbom.input.path") != "package-lock.json"
        or root_properties.get("org.searise.sbom.npm.workspace.path") != "src/web"
    ):
        raise SupplyChainContractError("static npm SBOM root authority drifted")


def _validate_active_sboms(repository_root: Path) -> None:
    _validate_static_npm_semantics(repository_root)
    validate_npm_sbom(
        repository_root / "contracts/supply-chain/v2/sboms/static-web-npm.cdx.json",
        repository_root / "package-lock.json",
        repository_root=repository_root,
        logical_path="package-lock.json",
    )
    for sbom_path, (annotation_path, target_id) in _PYTHON_SBOMS.items():
        validate_python_sbom(
            repository_root / sbom_path,
            repository_root / annotation_path,
            repository_root=repository_root,
            target_id=target_id,
        )


def validate_static_target_profile(
    profile_path: Path,
    *,
    repository_root: Path = REPOSITORY_ROOT,
) -> dict[str, Any]:
    """Validate exact active static-target inputs and reusable SBOM graphs."""
    document = _load_strict_json(profile_path, label="static supply-chain profile")
    schema = _load_strict_json(
        CONTRACT_ROOT / "static-target-profile.schema.json",
        label="static supply-chain schema",
    )
    Draft202012Validator.check_schema(schema)
    errors = sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(document),
        key=lambda error: tuple(str(part) for part in error.absolute_path),
    )
    if errors:
        error = errors[0]
        location = ".".join(str(part) for part in error.absolute_path) or "$"
        raise SupplyChainContractError(f"static supply-chain profile {location}: {error.message}")

    if document["excludedLegacyRequirements"] != _EXPECTED_EXCLUSIONS:
        raise SupplyChainContractError("static supply-chain legacy exclusions drifted")
    components = document["components"]
    component_ids = [component["id"] for component in components]
    if component_ids != sorted(component_ids) or len(component_ids) != len(set(component_ids)):
        raise SupplyChainContractError(
            "static supply-chain components must be unique and sorted"
        )
    if set(component_ids) != set(_EXPECTED_COMPONENTS):
        raise SupplyChainContractError("static supply-chain component set drifted")

    recorded: dict[str, Path] = {}
    for component in components:
        component_id = component["id"]
        actual = (
            component["ecosystem"],
            component["releaseUse"],
            component["coverage"],
        )
        if actual != _EXPECTED_COMPONENTS[component_id]:
            raise SupplyChainContractError(
                f"static supply-chain component contract drifted: {component_id}"
            )
        paths = [item["path"] for item in component["inputs"]]
        if paths != sorted(paths) or len(paths) != len(set(paths)):
            raise SupplyChainContractError(
                f"static supply-chain inputs must be unique and sorted: {component_id}"
            )
        for item in component["inputs"]:
            value = item["path"]
            if value in recorded:
                raise SupplyChainContractError(
                    f"duplicate static supply-chain input across components: {value}"
                )
            if value in _FORBIDDEN_FILES or value.startswith(_FORBIDDEN_PREFIXES):
                raise SupplyChainContractError(
                    f"legacy runtime cannot be an active supply-chain requirement: {value}"
                )
            path = _safe_regular_file(repository_root, value)
            if hashlib.sha256(path.read_bytes()).hexdigest() != item["sha256"]:
                raise SupplyChainContractError(
                    f"static supply-chain input SHA-256 mismatch: {value}"
                )
            recorded[value] = path

    if set(recorded) != set(_REQUIRED_PATHS):
        missing = sorted(_REQUIRED_PATHS - set(recorded))
        extra = sorted(set(recorded) - _REQUIRED_PATHS)
        raise SupplyChainContractError(
            f"static supply-chain input set drifted; missing={missing}, extra={extra}"
        )
    _validate_static_contributor_manifest(repository_root)
    _validate_active_sboms(repository_root)
    return document
