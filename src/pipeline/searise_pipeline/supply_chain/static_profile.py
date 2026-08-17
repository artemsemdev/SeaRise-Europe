"""Validate the static-browser supply-chain transition profile."""

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
_SCHEMA_PATH = "contracts/supply-chain/v2/static-target-profile.schema.json"

_BASE_COMPONENTS = {
    "active-sboms": ("cyclonedx", "candidate", "locked"),
    "github-actions": ("github-actions", "candidate", "locked"),
    "native-build-plane": ("native", "candidate", "locked"),
    "pipeline-container": ("container", "candidate", "locked"),
    "pipeline-geoid-evaluator": ("python", "candidate", "locked"),
    "pipeline-python-contributor": ("python", "development", "range-constrained"),
    "pipeline-python-release": ("python", "candidate", "locked"),
    "profile-contract": ("standard-schema", "candidate", "locked"),
    "provenance-signing-contracts": ("standard-schema", "candidate", "locked"),
    "settlement-spatial-python": ("python", "candidate", "locked"),
    "static-web-npm": ("npm", "candidate", "locked"),
    "vendored-cyclonedx-schemas": ("standard-schema", "candidate", "locked"),
}
_PENDING_COMPONENT = {
    "pending-legacy-python-authorities": ("python", "development", "range-constrained")
}


def _authority(component: str, role: str, *paths: str) -> dict[str, tuple[str, str]]:
    return {path: (component, role) for path in paths}


_BASE_INPUT_AUTHORITY = {
    **_authority(
        "active-sboms",
        "sbom",
        "contracts/supply-chain/v1/sboms/python-release-linux-x86-64-cp311.cdx.json",
        "contracts/supply-chain/v1/sboms/python-release-macos-arm64-cp311.cdx.json",
        "contracts/supply-chain/v1/sboms/python-settlement-spatial-linux-x86-64-cp311.cdx.json",
        "contracts/supply-chain/v1/sboms/python-settlement-spatial-macos-arm64-cp311.cdx.json",
        "contracts/supply-chain/v2/sboms/static-web-npm.cdx.json",
    ),
    **_authority(
        "github-actions",
        "workflow",
        ".github/workflows/ci.yml",
        ".github/workflows/codeql.yml",
        ".github/workflows/offline-release-controlled.yml",
        ".github/workflows/phase-0r-owner-promotion.yml",
        ".github/workflows/phase-1-release-sign.yml",
    ),
    **_authority(
        "provenance-signing-contracts",
        "schema",
        "contracts/release/v2/browser-derivation-provenance.schema.json",
        "contracts/supply-chain/v1/cosign-tool-lock.schema.json",
        "contracts/supply-chain/v1/cryptographic-verification-receipt.schema.json",
        "contracts/supply-chain/v1/evidence-envelope.schema.json",
        "contracts/supply-chain/v1/identity-policy.schema.json",
        "contracts/supply-chain/v1/public-readback-verification-receipt.schema.json",
        "contracts/supply-chain/v1/real-source-unverified-evidence-envelope.schema.json",
        "contracts/supply-chain/v1/release-evidence-retention-receipt.schema.json",
    ),
    **_authority(
        "provenance-signing-contracts",
        "manifest",
        "contracts/supply-chain/v1/build-types/offline-release-real-source-v1.json",
        "contracts/supply-chain/v1/build-types/offline-release-v1.json",
        "contracts/supply-chain/v1/identity-policy.json",
    ),
    **_authority(
        "native-build-plane",
        "lock",
        "contracts/supply-chain/v1/tools/cosign-linux-amd64.json",
        "src/pipeline/toolchain/duckdb-spatial-extensions.json",
    ),
    **_authority(
        "native-build-plane",
        "recipe",
        "src/pipeline/toolchain/Dockerfile.tippecanoe-linux-x86_64",
        "src/pipeline/toolchain/build_macos_tippecanoe.sh",
    ),
    **_authority(
        "native-build-plane",
        "receipt",
        "src/pipeline/toolchain/tippecanoe-darwin-arm64-build-receipt.json",
        "src/pipeline/toolchain/tippecanoe-linux-x86_64-build-receipt.json",
    ),
    **_authority(
        "vendored-cyclonedx-schemas",
        "schema",
        "contracts/supply-chain/v1/vendor/bom-1.7.schema.json",
        "contracts/supply-chain/v1/vendor/cryptography-defs.schema.json",
        "contracts/supply-chain/v1/vendor/jsf-0.82.schema.json",
        "contracts/supply-chain/v1/vendor/spdx.schema.json",
    ),
    **_authority(
        "vendored-cyclonedx-schemas",
        "lock",
        "contracts/supply-chain/v1/vendor/manifest.json",
    ),
    **_authority(
        "pipeline-python-contributor",
        "manifest",
        "contracts/supply-chain/v2/python/static-target-contributor-requirements.txt",
    ),
    **_authority("profile-contract", "schema", _SCHEMA_PATH),
    **_authority("static-web-npm", "lock", "package-lock.json"),
    **_authority("static-web-npm", "manifest", "package.json", "src/web/package.json"),
    **_authority(
        "pipeline-container",
        "recipe",
        "src/pipeline/offline_release/Dockerfile",
        "src/pipeline/offline_release/Dockerfile.dockerignore",
    ),
    **_authority(
        "pipeline-container",
        "manifest",
        "src/pipeline/offline_release/profiles/fixture.json",
        "src/pipeline/offline_release/profiles/full-europe.json",
        "src/pipeline/offline_release/profiles/regional.json",
    ),
    **_authority(
        "pipeline-container",
        "schema",
        "src/pipeline/offline_release/profiles/profile.schema.json",
    ),
    **_authority(
        "pipeline-python-release",
        "manifest",
        "contracts/supply-chain/v1/python-graphs/release-runtime.json",
    ),
    **_authority(
        "pipeline-python-release",
        "lock",
        "src/pipeline/requirements-phase1-final-macos-x86_64.lock",
        "src/pipeline/requirements-release-macos-arm64.lock",
        "src/pipeline/requirements-release.lock",
    ),
    **_authority(
        "settlement-spatial-python",
        "manifest",
        "contracts/supply-chain/v1/python-graphs/settlement-spatial-runtime.json",
    ),
    **_authority(
        "settlement-spatial-python",
        "lock",
        "src/pipeline/requirements-settlements-spatial-linux-x86_64.lock",
        "src/pipeline/requirements-settlements-spatial-macos-arm64.lock",
    ),
    **_authority(
        "pipeline-geoid-evaluator",
        "lock",
        "src/pipeline/science/geoid-evaluator-requirements.txt",
    ),
}
_PENDING_INPUT_AUTHORITY = {
    **_authority(
        "pending-legacy-python-authorities",
        "manifest",
        "src/pipeline/pyproject.toml",
        "src/pipeline/requirements-pipeline.txt",
    )
}
_ACTIVE_CONTRIBUTOR_INPUT_AUTHORITY = {
    **_authority(
        "pipeline-python-contributor",
        "manifest",
        "src/pipeline/pyproject.toml",
        "src/pipeline/requirements-pipeline.txt",
    )
}
_LEGACY_SELECTORS = {
    "ci-legacy-api": (72, ".github/workflows/ci.yml", "src/api"),
    "ci-legacy-compose": (72, ".github/workflows/ci.yml", "compose-smoke"),
    "ci-legacy-dotnet": (72, ".github/workflows/ci.yml", "actions/setup-dotnet@"),
    "ci-legacy-frontend": (72, ".github/workflows/ci.yml", "src/frontend"),
    "codeql-legacy-csharp": (72, ".github/workflows/codeql.yml", "csharp"),
    "pipeline-pyproject-azure": (
        71,
        "src/pipeline/pyproject.toml",
        "azure-storage-blob>=12.19,<13.0",
    ),
    "pipeline-pyproject-postgis": (
        71,
        "src/pipeline/pyproject.toml",
        "psycopg2-binary>=2.9,<3.0",
    ),
    "pipeline-requirements-azure": (
        71,
        "src/pipeline/requirements-pipeline.txt",
        "azure-storage-blob>=12.19,<13.0",
    ),
    "pipeline-requirements-postgis": (
        71,
        "src/pipeline/requirements-pipeline.txt",
        "psycopg2-binary>=2.9,<3.0",
    ),
}
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
        or root_properties.get("org.searise.sbom.scope") != "static-web-npm-lock-only"
    ):
        raise SupplyChainContractError("static npm SBOM root authority drifted")

    root_manifest = _load_strict_json(repository_root / "package.json", label="root npm manifest")
    web_manifest = _load_strict_json(
        repository_root / "src/web/package.json",
        label="static web npm manifest",
    )
    lock = _load_strict_json(repository_root / "package-lock.json", label="root npm lock")
    packages = lock.get("packages", {})
    lock_root = packages.get("") if isinstance(packages, dict) else None
    lock_web = packages.get("src/web") if isinstance(packages, dict) else None
    dependency_groups = (
        "dependencies",
        "devDependencies",
        "optionalDependencies",
        "peerDependencies",
    )
    if (
        root_manifest.get("workspaces") != ["src/web"]
        or not isinstance(lock_root, dict)
        or lock_root.get("workspaces") != ["src/web"]
        or not isinstance(lock_web, dict)
        or any(
            web_manifest.get(field, {}) != lock_web.get(field, {})
            for field in ("name", "version", *dependency_groups)
        )
    ):
        raise SupplyChainContractError("src/web manifest differs from its exact lock workspace")


def _validate_active_sboms(repository_root: Path) -> None:
    _validate_static_npm_semantics(repository_root)
    validate_npm_sbom(
        repository_root / "contracts/supply-chain/v2/sboms/static-web-npm.cdx.json",
        repository_root / "package-lock.json",
        repository_root=repository_root,
        logical_path="package-lock.json",
        scope="static-web-npm-lock-only",
    )
    for sbom_path, (annotation_path, target_id) in _PYTHON_SBOMS.items():
        validate_python_sbom(
            repository_root / sbom_path,
            repository_root / annotation_path,
            repository_root=repository_root,
            target_id=target_id,
        )


def _expected_transition(
    repository_root: Path,
) -> tuple[list[dict[str, str]], list[int], bool]:
    present: list[dict[str, str]] = []
    issues: set[int] = set()
    python_pending = False
    contents: dict[str, str] = {}
    for selector_id, (issue, path, selector) in sorted(_LEGACY_SELECTORS.items()):
        if path not in contents:
            contents[path] = _safe_regular_file(repository_root, path).read_text(encoding="utf-8")
        if selector in contents[path]:
            present.append({"id": selector_id, "path": path, "selector": selector})
            issues.add(issue)
            python_pending = python_pending or selector_id.startswith("pipeline-")
    return present, sorted(issues), python_pending


def validate_static_target_profile(
    profile_path: Path,
    *,
    repository_root: Path = REPOSITORY_ROOT,
) -> dict[str, Any]:
    """Validate exact target inputs, transition blockers, and reusable SBOM graphs."""
    document = _load_strict_json(profile_path, label="static supply-chain profile")
    schema_path = _safe_regular_file(repository_root, _SCHEMA_PATH)
    schema = _load_strict_json(schema_path, label="static supply-chain schema")
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
    pending_selectors, blocking_issues, python_pending = _expected_transition(repository_root)
    expected_status = "pending-legacy-removal" if pending_selectors else "active"
    activation = document["activation"]
    if activation != {
        "status": expected_status,
        "blockingIssues": blocking_issues,
        "pendingSelectors": pending_selectors,
    }:
        raise SupplyChainContractError(
            "static supply-chain activation does not match repository legacy selectors"
        )
    expected_components = dict(_BASE_COMPONENTS)
    expected_inputs = dict(_BASE_INPUT_AUTHORITY)
    if python_pending:
        expected_components.update(_PENDING_COMPONENT)
        expected_inputs.update(_PENDING_INPUT_AUTHORITY)
    else:
        expected_inputs.update(_ACTIVE_CONTRIBUTOR_INPUT_AUTHORITY)
    components = document["components"]
    component_ids = [component["id"] for component in components]
    if component_ids != sorted(component_ids) or len(component_ids) != len(set(component_ids)):
        raise SupplyChainContractError(
            "static supply-chain components must be unique and sorted"
        )
    if set(component_ids) != set(expected_components):
        raise SupplyChainContractError("static supply-chain component set drifted")

    recorded: dict[str, Path] = {}
    for component in components:
        component_id = component["id"]
        actual = (
            component["ecosystem"],
            component["releaseUse"],
            component["coverage"],
        )
        if actual != expected_components[component_id]:
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
            if expected_inputs.get(value) != (component_id, item["role"]):
                raise SupplyChainContractError(
                    f"static supply-chain input owner or role drifted: {value}"
                )
            path = _safe_regular_file(repository_root, value)
            if hashlib.sha256(path.read_bytes()).hexdigest() != item["sha256"]:
                raise SupplyChainContractError(
                    f"static supply-chain input SHA-256 mismatch: {value}"
                )
            recorded[value] = path

    if set(recorded) != set(expected_inputs):
        missing = sorted(set(expected_inputs) - set(recorded))
        extra = sorted(set(recorded) - set(expected_inputs))
        raise SupplyChainContractError(
            f"static supply-chain input set drifted; missing={missing}, extra={extra}"
        )
    _validate_static_contributor_manifest(repository_root)
    _validate_active_sboms(repository_root)
    return document
