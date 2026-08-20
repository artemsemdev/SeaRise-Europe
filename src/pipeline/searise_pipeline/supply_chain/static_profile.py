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
_HISTORICAL_VALIDATOR_PATH = "contracts/supply-chain/v2/historical/v1-contracts.py"
_HISTORICAL_EVIDENCE = {
    "path": "contracts/supply-chain/v1",
    "status": "immutable-phase-1-history",
    "dependencyInventory": {
        "path": "contracts/supply-chain/v1/dependency-inventory.json",
        "sha256": "250a9579372492e58649714f102be2b5673471c04d86b628c23b412ed6d7b70a",
    },
    "gitAuthority": {
        "commit": "1637057f758599b1edcd35ffba0d31ec65cf8c24",
        "tree": "d517d57cc80a097a54da641d638b8dfc2abd6b32",
        "phase1ContractsTree": "b69cd57b74e9a2dfa7738c8bc07a0b32b3f97a16",
    },
    "modeAuthority": {
        ".github/workflows/ci.yml": "100644",
        ".github/workflows/codeql.yml": "100644",
        ".github/workflows/offline-release-controlled.yml": "100644",
        ".github/workflows/phase-0r-owner-promotion.yml": "100644",
        ".github/workflows/phase-1-release-sign.yml": "100644",
        ".github/workflows/static-quality.yml": "100644",
        "contracts/supply-chain/v2/historical/v1-contracts.py": "100644",
        "docker-compose.yml": "100644",
        "infra/blob-seed/Dockerfile": "100644",
        "infra/blob-seed/requirements.lock": "100644",
        "infra/blob-seed/requirements.txt": "100644",
        "package-lock.json": "100644",
        "package.json": "100644",
        "src/api/Directory.Build.props": "100644",
        "src/api/Dockerfile": "100644",
        "src/api/SeaRise.Api.Tests/SeaRise.Api.Tests.csproj": "100644",
        "src/api/SeaRise.Api.Tests/packages.lock.json": "100644",
        "src/api/SeaRise.Api/SeaRise.Api.csproj": "100644",
        "src/api/SeaRise.Api/packages.lock.json": "100644",
        "src/api/SeaRise.Application/SeaRise.Application.csproj": "100644",
        "src/api/SeaRise.Application/packages.lock.json": "100644",
        "src/api/SeaRise.Domain/SeaRise.Domain.csproj": "100644",
        "src/api/SeaRise.Domain/packages.lock.json": "100644",
        "src/api/SeaRise.Infrastructure/SeaRise.Infrastructure.csproj": "100644",
        "src/api/SeaRise.Infrastructure/packages.lock.json": "100644",
        "src/frontend/Dockerfile": "100644",
        "src/frontend/package-lock.json": "100644",
        "src/frontend/package.json": "100644",
        "src/pipeline/offline_release/Dockerfile": "100644",
        "src/pipeline/pyproject.toml": "100644",
        "src/pipeline/requirements-phase1-final-macos-x86_64.lock": "100644",
        "src/pipeline/requirements-pipeline.txt": "100644",
        "src/pipeline/requirements-release-macos-arm64.lock": "100644",
        "src/pipeline/requirements-release.lock": "100644",
        "src/pipeline/requirements-settlements-spatial-linux-x86_64.lock": "100644",
        "src/pipeline/requirements-settlements-spatial-macos-arm64.lock": "100644",
        "src/pipeline/science/geoid-evaluator-requirements.txt": "100644",
        "src/pipeline/toolchain/Dockerfile.tippecanoe-linux-x86_64": "100644",
        "src/pipeline/toolchain/build_macos_tippecanoe.sh": "100755",
        "src/pipeline/toolchain/duckdb-spatial-extensions.json": "100644",
        "src/pipeline/toolchain/tippecanoe-darwin-arm64-build-receipt.json": "100644",
        "src/pipeline/toolchain/tippecanoe-linux-x86_64-build-receipt.json": "100644",
        "src/web/package.json": "100644",
        "tools/static-quality/package-lock.json": "100644",
        "tools/static-quality/package.json": "100644",
    },
    "validatorAuthority": {
        "path": _HISTORICAL_VALIDATOR_PATH,
        "sha256": "f87e079c534d3bfe10da0c71127f140988436d4e0bec91400fec8a913b8e8ced",
        "gitBlob": "d24ad90dcd45fe927ccc1e6bc8c558068833b1df",
    },
}

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
    "static-quality-npm": ("npm", "development", "locked"),
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
        ".github/workflows/static-quality.yml",
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
    **_authority("profile-contract", "manifest", _HISTORICAL_VALIDATOR_PATH),
    **_authority("static-quality-npm", "lock", "tools/static-quality/package-lock.json"),
    **_authority("static-quality-npm", "manifest", "tools/static-quality/package.json"),
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
    "ci-legacy-api": (71, ".github/workflows/ci.yml", "workflow-job:api"),
    "ci-legacy-compose-smoke": (
        72,
        ".github/workflows/ci.yml",
        "workflow-job:compose-smoke",
    ),
    "ci-legacy-docker-api": (72, ".github/workflows/ci.yml", "workflow-job:docker-api"),
    "ci-legacy-docker-frontend": (
        72,
        ".github/workflows/ci.yml",
        "workflow-job:docker-frontend",
    ),
    "ci-legacy-frontend": (70, ".github/workflows/ci.yml", "workflow-job:frontend"),
    "ci-legacy-infrastructure": (
        71,
        ".github/workflows/ci.yml",
        "workflow-job:infrastructure",
    ),
    "codeql-legacy-csharp": (
        71,
        ".github/workflows/codeql.yml",
        "workflow-job:analyze-csharp",
    ),
    "legacy-api-tree": (71, "src/api", "path-exists"),
    "legacy-api-dockerfile": (72, "src/api/Dockerfile", "path-exists"),
    "legacy-blob-seed-tree": (71, "infra/blob-seed", "path-exists"),
    "legacy-compose-file": (72, "docker-compose.yml", "path-exists"),
    "legacy-compose-short-yaml": (72, "compose.yaml", "path-exists"),
    "legacy-compose-short-yml": (72, "compose.yml", "path-exists"),
    "legacy-compose-yaml": (72, "docker-compose.yaml", "path-exists"),
    "legacy-compose-smoke": (72, "scripts/compose-smoke.sh", "path-exists"),
    "legacy-db-geography": (71, "infra/db/init-geography.sql", "path-exists"),
    "legacy-db-init": (71, "infra/db/init.sql", "path-exists"),
    "legacy-frontend-tree": (70, "src/frontend", "path-exists"),
    "legacy-frontend-dockerfile": (72, "src/frontend/Dockerfile", "path-exists"),
    "legacy-solution-file": (71, "SeaRise Europe.sln", "path-exists"),
    "pipeline-pyproject-azure": (
        71,
        "src/pipeline/pyproject.toml",
        "azure-storage-blob",
    ),
    "pipeline-pyproject-postgis": (
        71,
        "src/pipeline/pyproject.toml",
        "psycopg2-binary",
    ),
    "pipeline-requirements-azure": (
        71,
        "src/pipeline/requirements-pipeline.txt",
        "azure-storage-blob",
    ),
    "pipeline-requirements-postgis": (
        71,
        "src/pipeline/requirements-pipeline.txt",
        "psycopg2-binary",
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
_DISCOVERY_IGNORED_PARTS = frozenset(
    {
        ".git",
        ".next",
        ".pytest_cache",
        ".ruff_cache",
        ".venv",
        "build",
        "coverage",
        "dist",
        "node_modules",
    }
)
_NODE_AUTHORITY_FILES = frozenset(
    {
        "npm-shrinkwrap.json",
        "package-lock.json",
        "package.json",
        "pnpm-lock.yaml",
        "yarn.lock",
    }
)
_PYTHON_AUTHORITY_FILES = frozenset(
    {"Pipfile", "Pipfile.lock", "poetry.lock", "pyproject.toml", "uv.lock"}
)
_CURRENT_SCHEMA_ROOTS = (
    PurePosixPath("contracts/supply-chain/v2"),
    PurePosixPath("src/pipeline/offline_release/profiles"),
)
_CURRENT_SBOM_ROOT = PurePosixPath("contracts/supply-chain/v2/sboms")
_CURRENT_TOOLCHAIN_ROOT = PurePosixPath("src/pipeline/toolchain")
_CURRENT_PROFILE_ROOT = PurePosixPath("src/pipeline/offline_release/profiles")
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
    requirements = _requirements_map(manifest.read_text(encoding="utf-8"), label="static")
    names = list(requirements)
    forbidden = sorted(set(names) & _LEGACY_PYTHON_PACKAGES)
    if forbidden:
        raise SupplyChainContractError(
            f"legacy Python packages cannot enter the static target: {forbidden}"
        )
    if names != sorted(names):
        raise SupplyChainContractError("static contributor requirements must be sorted")
    if set(names) != set(_EXPECTED_CONTRIBUTOR_PACKAGES):
        raise SupplyChainContractError("static contributor package set drifted")


def _canonical_requirement(value: str, *, label: str) -> tuple[str, str]:
    match = _REQUIREMENT_NAME.match(value.strip())
    if match is None:
        raise SupplyChainContractError(f"invalid {label} requirement: {value}")
    name = match.group(1).lower().replace("_", "-").replace(".", "-")
    suffix = re.sub(r"\s+", "", value.strip()[match.end() :]).lower()
    return name, f"{name}{suffix}"


def _requirements_map(value: str, *, label: str) -> dict[str, str]:
    requirements: dict[str, str] = {}
    for line_number, raw in enumerate(value.splitlines(), 1):
        value = raw.split("#", 1)[0].strip()
        if not value:
            continue
        name, canonical = _canonical_requirement(value, label=f"{label} line {line_number}")
        if name in requirements:
            raise SupplyChainContractError(f"duplicate {label} requirement: {name}")
        requirements[name] = canonical
    return requirements


def _pyproject_requirements(value: str) -> dict[str, str]:
    def array(section: str, key: str) -> list[str]:
        section_match = re.search(
            rf"(?ms)^\[{re.escape(section)}\]\s*(.*?)(?=^\[|\Z)",
            value,
        )
        if section_match is None:
            raise SupplyChainContractError(f"pyproject section is missing: {section}")
        array_match = re.search(
            rf"(?ms)^\s*{re.escape(key)}\s*=\s*\[(.*?)^\s*\]",
            section_match.group(1),
        )
        if array_match is None:
            raise SupplyChainContractError(f"pyproject dependency array is missing: {key}")
        return re.findall(r'^\s*"([^"]+)"\s*,?\s*$', array_match.group(1), re.MULTILINE)

    requirements: dict[str, str] = {}
    for raw in [*array("project", "dependencies"), *array("project.optional-dependencies", "dev")]:
        name, canonical = _canonical_requirement(raw, label="pyproject")
        if name in requirements:
            raise SupplyChainContractError(f"duplicate pyproject requirement: {name}")
        requirements[name] = canonical
    return requirements


def _validate_contributor_parity(repository_root: Path) -> None:
    target = _requirements_map(
        (repository_root / _STATIC_CONTRIBUTOR_REQUIREMENTS).read_text(encoding="utf-8"),
        label="static",
    )
    pyproject = _pyproject_requirements(
        (repository_root / "src/pipeline/pyproject.toml").read_text(encoding="utf-8")
    )
    requirements = _requirements_map(
        (repository_root / "src/pipeline/requirements-pipeline.txt").read_text(
            encoding="utf-8"
        ),
        label="pipeline",
    )
    if pyproject != target or requirements != target:
        raise SupplyChainContractError(
            "active contributor manifests must exactly match the static target authority"
        )


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


def _path_lexists(path: Path) -> bool:
    try:
        path.lstat()
    except FileNotFoundError:
        return False
    return True


def _is_current_dependency_authority(path: PurePosixPath) -> bool:
    workflow = (
        path.parts[:2] == (".github", "workflows")
        and path.suffix in {".yaml", ".yml"}
    )
    local_action = (
        path.parts[:2] == (".github", "actions")
        and path.name in {"action.yaml", "action.yml"}
    )
    dockerfile = path.name.startswith("Dockerfile")
    python_authority = (
        path.name in _PYTHON_AUTHORITY_FILES
        or (
            path.name.startswith("requirements")
            and path.suffix in {".in", ".lock", ".txt"}
        )
        or path.name.endswith("requirements.txt")
    )
    toolchain = _CURRENT_TOOLCHAIN_ROOT in path.parents
    build_profile = _CURRENT_PROFILE_ROOT in path.parents
    schema = path.name.endswith(".schema.json") and any(
        root == path.parent or root in path.parents for root in _CURRENT_SCHEMA_ROOTS
    )
    release_schema = path == PurePosixPath(
        "contracts/release/v2/browser-derivation-provenance.schema.json"
    )
    sbom = path.parent == _CURRENT_SBOM_ROOT and path.name.endswith(".cdx.json")
    return (
        path.name in _NODE_AUTHORITY_FILES
        or path.name in _FORBIDDEN_FILES
        or workflow
        or local_action
        or dockerfile
        or python_authority
        or toolchain
        or build_profile
        or schema
        or release_schema
        or sbom
    )


def _discover_current_authority(repository_root: Path) -> set[str]:
    discovered: set[str] = set()
    for candidate in repository_root.rglob("*"):
        relative = candidate.relative_to(repository_root)
        if any(part in _DISCOVERY_IGNORED_PARTS for part in relative.parts):
            continue
        logical = PurePosixPath(relative.as_posix())
        value = logical.as_posix()
        if value in _FORBIDDEN_FILES or value.startswith(_FORBIDDEN_PREFIXES):
            continue
        if _is_current_dependency_authority(logical) and _path_lexists(candidate):
            discovered.add(value)
    return discovered


def _workflow_selector_present(value: str, selector: str) -> bool:
    kind, separator, job_id = selector.partition(":")
    if (
        not separator
        or kind != "workflow-job"
        or not re.fullmatch(r"[A-Za-z0-9_-]+", job_id)
    ):
        raise SupplyChainContractError(f"invalid workflow selector: {selector}")
    return job_id in _parse_workflow_jobs(value)


def _yaml_mapping_entry(line: str, indent: int) -> tuple[str, str] | None:
    prefix = line[:indent]
    if "\t" in prefix:
        raise SupplyChainContractError("workflow YAML indentation must not use tabs")
    content = line[indent:]
    if not content.strip() or content.lstrip().startswith("#"):
        return None
    quote: str | None = None
    escaped = False
    colon = -1
    index = 0
    while index < len(content):
        character = content[index]
        if quote == '"':
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                quote = None
        elif quote == "'":
            if character == "'":
                if index + 1 < len(content) and content[index + 1] == "'":
                    index += 1
                else:
                    quote = None
        elif character in {'"', "'"}:
            quote = character
        elif character == ":":
            colon = index
            break
        elif character == "#" and (index == 0 or content[index - 1].isspace()):
            break
        index += 1
    if quote is not None or colon < 0:
        raise SupplyChainContractError("workflow YAML mapping entry is malformed")
    raw_key = content[:colon].strip()
    remainder = content[colon + 1 :].strip()
    if not raw_key:
        raise SupplyChainContractError("workflow YAML mapping key is empty")
    try:
        if raw_key.startswith('"'):
            if not raw_key.endswith('"'):
                raise ValueError("unterminated double-quoted key")
            key = json.loads(raw_key)
        elif raw_key.startswith("'"):
            if not raw_key.endswith("'"):
                raise ValueError("unterminated single-quoted key")
            key = raw_key[1:-1].replace("''", "'")
        else:
            key = raw_key
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise SupplyChainContractError("workflow YAML mapping key is invalid") from exc
    if not isinstance(key, str) or not key:
        raise SupplyChainContractError("workflow YAML mapping key must be a nonempty string")
    return key, remainder


def _parse_workflow_jobs(value: str) -> frozenset[str]:
    jobs_seen = False
    in_jobs = False
    job_indent: int | None = None
    job_ids: set[str] = set()
    for line in value.splitlines():
        indent = len(line) - len(line.lstrip(" "))
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if indent != 0 and not in_jobs:
            continue
        if in_jobs and indent > 0:
            if job_indent is None:
                job_indent = indent
            elif indent < job_indent:
                raise SupplyChainContractError(
                    "workflow jobs mapping uses inconsistent child indentation"
                )
            if indent > job_indent:
                continue
        entry = _yaml_mapping_entry(line, indent)
        if entry is None:
            continue
        key, remainder = entry
        if indent == 0:
            if key == "jobs":
                if jobs_seen or remainder and not remainder.startswith("#"):
                    raise SupplyChainContractError(
                        "workflow must contain one block-style top-level jobs mapping"
                    )
                jobs_seen = True
                in_jobs = True
                job_indent = None
            elif in_jobs:
                in_jobs = False
            continue
        if not in_jobs or indent != job_indent:
            continue
        if remainder and not remainder.startswith("#"):
            raise SupplyChainContractError("workflow job must use a block mapping")
        if not re.fullmatch(r"[A-Za-z0-9_-]+", key):
            raise SupplyChainContractError(f"workflow job identifier is invalid: {key}")
        if key in job_ids:
            raise SupplyChainContractError(f"duplicate workflow job identifier: {key}")
        job_ids.add(key)
    if not jobs_seen:
        raise SupplyChainContractError("workflow must contain one top-level jobs mapping")
    return frozenset(job_ids)


def _expected_transition(
    repository_root: Path,
) -> tuple[list[dict[str, str]], list[int], bool]:
    present: list[dict[str, str]] = []
    issues: set[int] = set()
    python_pending = False
    contents: dict[str, str] = {}
    python_requirements: dict[str, dict[str, str]] = {}
    for selector_id, (issue, path, selector) in sorted(_LEGACY_SELECTORS.items()):
        present_selector = False
        if selector == "path-exists":
            present_selector = _path_lexists(repository_root / path)
        elif selector_id.startswith("pipeline-"):
            if path not in python_requirements:
                source = _safe_regular_file(repository_root, path).read_text(encoding="utf-8")
                python_requirements[path] = (
                    _pyproject_requirements(source)
                    if path.endswith("pyproject.toml")
                    else _requirements_map(source, label=path)
                )
            present_selector = selector in python_requirements[path]
        else:
            if path not in contents:
                contents[path] = _safe_regular_file(repository_root, path).read_text(
                    encoding="utf-8"
                )
            present_selector = _workflow_selector_present(contents[path], selector)
        if present_selector:
            present.append(
                {"id": selector_id, "issue": issue, "path": path, "selector": selector}
            )
            issues.add(issue)
            python_pending = python_pending or selector_id.startswith("pipeline-")
    return present, sorted(issues), python_pending


def load_static_target_profile_contract(
    profile_path: Path,
    *,
    repository_root: Path = REPOSITORY_ROOT,
) -> dict[str, Any]:
    """Validate the v2 profile schema without asserting current-tree authority."""
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
    return document


def validate_static_target_profile(
    profile_path: Path,
    *,
    repository_root: Path = REPOSITORY_ROOT,
) -> dict[str, Any]:
    """Validate exact target inputs, transition blockers, and reusable SBOM graphs."""
    document = load_static_target_profile_contract(
        profile_path,
        repository_root=repository_root,
    )

    if document["excludedLegacyRequirements"] != _EXPECTED_EXCLUSIONS:
        raise SupplyChainContractError("static supply-chain legacy exclusions drifted")
    if document["historicalEvidence"] != _HISTORICAL_EVIDENCE:
        raise SupplyChainContractError("historical Phase 1 authority drifted")
    inventory = _HISTORICAL_EVIDENCE["dependencyInventory"]
    inventory_path = _safe_regular_file(repository_root, inventory["path"])
    if hashlib.sha256(inventory_path.read_bytes()).hexdigest() != inventory["sha256"]:
        raise SupplyChainContractError("historical Phase 1 inventory bytes changed")
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
    discovered_current = _discover_current_authority(repository_root)
    classified_current = {
        path
        for path in expected_inputs
        if _is_current_dependency_authority(PurePosixPath(path))
    }
    if discovered_current != classified_current:
        missing = sorted(discovered_current - classified_current)
        extra = sorted(classified_current - discovered_current)
        raise SupplyChainContractError(
            f"static current-tree authority discovery drifted; unclassified={missing}, "
            f"missing={extra}"
        )
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
    if not python_pending:
        _validate_contributor_parity(repository_root)
    _validate_active_sboms(repository_root)
    return document
