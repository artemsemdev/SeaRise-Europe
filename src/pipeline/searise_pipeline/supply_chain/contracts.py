"""Validate immutable signed-candidate evidence and exception contracts."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import stat
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from jsonschema import Draft7Validator, Draft202012Validator, FormatChecker
from referencing import Registry, Resource

REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
CONTRACT_ROOT = REPOSITORY_ROOT / "contracts" / "supply-chain" / "v1"

_IGNORED_DEPENDENCY_PARTS = frozenset(
    {
        ".git",
        ".mypy_cache",
        ".next",
        ".nox",
        ".pytest_cache",
        ".ruff_cache",
        ".terraform",
        ".tox",
        ".venv",
        "__pycache__",
        "bin",
        "build",
        "coverage",
        "dist",
        "node_modules",
        "obj",
        "target",
    }
)
_COMPOSE_FILES = frozenset(
    {"compose.yaml", "compose.yml", "docker-compose.yaml", "docker-compose.yml"}
)
_NODE_INPUTS = frozenset(
    {"npm-shrinkwrap.json", "package-lock.json", "package.json", "pnpm-lock.yaml", "yarn.lock"}
)
_PYTHON_INPUTS = frozenset({"Pipfile", "Pipfile.lock", "poetry.lock", "pyproject.toml", "uv.lock"})
_DOTNET_INPUTS = frozenset(
    {
        "Directory.Build.props",
        "Directory.Packages.props",
        "NuGet.config",
        "global.json",
        "packages.lock.json",
    }
)
_EXPECTED_COMPONENTS = {
    "api-nuget": ("nuget", "legacy", "locked"),
    "blob-seed-python": ("python", "legacy", "locked"),
    "deployment-opentofu": ("opentofu", "not-present", "not-present"),
    "frontend-npm": ("npm", "candidate", "locked"),
    "github-actions": ("github-actions", "candidate", "locked"),
    "legacy-container-images": ("container", "legacy", "locked"),
    "native-geospatial-toolchain": ("native", "candidate", "locked"),
    "pipeline-geoid-evaluator": ("python", "candidate", "locked"),
    "pipeline-python-contributor": ("python", "development", "range-constrained"),
    "pipeline-python-release": ("python", "candidate", "locked"),
    "release-container-image": ("container", "candidate", "locked"),
    "release-signing-toolchain": ("native", "candidate", "locked"),
    "settlement-spatial-python": ("python", "candidate", "locked"),
    "vendored-standard-schemas": ("standard-schema", "candidate", "locked"),
}
_ALLOWED_STATUS_COMBINATIONS = frozenset(
    {
        ("candidate", "locked"),
        ("development", "range-constrained"),
        ("legacy", "locked"),
        ("not-present", "not-present"),
    }
)
_ALLOWED_ROLES = {
    "container": frozenset({"manifest", "recipe"}),
    "github-actions": frozenset({"workflow"}),
    "native": frozenset({"lock", "receipt", "recipe"}),
    "npm": frozenset({"lock", "manifest"}),
    "nuget": frozenset({"lock", "manifest"}),
    "opentofu": frozenset({"lock", "manifest"}),
    "python": frozenset({"lock", "manifest"}),
    "standard-schema": frozenset({"lock", "schema"}),
}
_REAL_SOURCE_EVIDENCE_SIGNATURE_PATHS = (
    "manifest.sigstore.json",
    "provenance.sigstore.json",
)
_SIGSTORE_TLOG_FIELDS = (
    "canonicalizedBody inclusionPromise integratedTime kindVersion logId logIndex"
)
_REAL_SOURCE_EVIDENCE_SBOM_PATHS = (
    "sbom/build-plane.cdx.json",
    "sbom/frontend-npm.cdx.json",
    "sbom/nuget/searise-api-net8.0.cdx.json",
    "sbom/nuget/searise-application-net8.0.cdx.json",
    "sbom/nuget/searise-domain-net8.0.cdx.json",
    "sbom/nuget/searise-infrastructure-net8.0.cdx.json",
    "sbom/python-release-linux-x86-64-cp311.cdx.json",
    "sbom/python-release-macos-arm64-cp311.cdx.json",
    "sbom/python-settlement-spatial-linux-x86-64-cp311.cdx.json",
    "sbom/python-settlement-spatial-macos-arm64-cp311.cdx.json",
)


class SupplyChainContractError(ValueError):
    """Supply-chain evidence failed a schema or semantic boundary."""


def load_json(path: Path) -> dict[str, Any]:
    """Load one JSON object without accepting non-object roots."""
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise SupplyChainContractError(f"{path}: JSON root must be an object")
    return document


def _strict_json_bytes(raw: bytes, label: str) -> dict[str, Any]:
    def strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result = dict(pairs)
        if len(result) != len(pairs):
            raise ValueError("duplicate object key")
        return result

    def reject_constant(value: str) -> None:
        raise ValueError(f"non-standard JSON constant: {value}")

    try:
        document = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=strict_object,
            parse_constant=reject_constant,
        )
        json.dumps(document, ensure_ascii=False).encode("utf-8")
    except (RecursionError, UnicodeDecodeError, UnicodeEncodeError, ValueError) as exc:
        raise SupplyChainContractError(
            f"{label} must be one strict UTF-8 JSON object: {exc}"
        ) from exc
    if not isinstance(document, dict):
        raise SupplyChainContractError(f"{label} JSON root must be an object")
    return document


def _decoded_base64(value: object, label: str) -> bytes:
    try:
        if not isinstance(value, str) or not value:
            raise ValueError("empty or non-string value")
        decoded = base64.b64decode(value, validate=True)
        if not decoded:
            raise ValueError("empty decoded value")
        return decoded
    except (binascii.Error, ValueError) as exc:
        raise SupplyChainContractError(f"{label} must be nonempty base64") from exc


def _exact_keys(value: object, keys: str) -> bool:
    return isinstance(value, dict) and set(value) == set(keys.split())


def _validate_sigstore_bundle(bundle: Mapping[str, Any], subject: bytes, label: str) -> None:
    try:
        material = bundle["verificationMaterial"]
        signature = bundle["messageSignature"]
        entries = material["tlogEntries"]
        if (
            not _exact_keys(bundle, "mediaType verificationMaterial messageSignature")
            or bundle["mediaType"] != "application/vnd.dev.sigstore.bundle.v0.3+json"
            or not _exact_keys(material, "certificate tlogEntries")
            or not _exact_keys(material["certificate"], "rawBytes")
            or not _exact_keys(signature, "messageDigest signature")
            or not _exact_keys(signature["messageDigest"], "algorithm digest")
            or signature["messageDigest"]["algorithm"] != "SHA2_256"
            or not isinstance(entries, list)
            or not entries
        ):
            raise SupplyChainContractError(
                f"{label} is not the exact supported Sigstore sign-blob subset"
            )
        _decoded_base64(material["certificate"]["rawBytes"], f"{label} certificate")
        _decoded_base64(signature["signature"], f"{label} signature")
        for entry in entries:
            times = (entry["integratedTime"], entry["logIndex"])
            if (
                not _exact_keys(entry, _SIGSTORE_TLOG_FIELDS)
                or not _exact_keys(entry["inclusionPromise"], "signedEntryTimestamp")
                or entry["kindVersion"] != {"kind": "hashedrekord", "version": "0.0.1"}
                or not _exact_keys(entry["logId"], "keyId")
                or not all(type(value) is int and value >= 0 for value in times)
            ):
                raise SupplyChainContractError(
                    f"{label} transparency-log entry is not the exact hashedrekord subset"
                )
            _decoded_base64(entry["canonicalizedBody"], f"{label} log body")
            _decoded_base64(
                entry["inclusionPromise"]["signedEntryTimestamp"], f"{label} log promise"
            )
            _decoded_base64(entry["logId"]["keyId"], f"{label} log ID")
        digest = _decoded_base64(signature["messageDigest"]["digest"], f"{label} message digest")
    except (KeyError, TypeError) as exc:
        raise SupplyChainContractError(f"{label} structure is malformed") from exc
    if digest != hashlib.sha256(subject).digest():
        raise SupplyChainContractError(
            f"{label} message digest does not bind its exact declared subject bytes"
        )


def parse_timestamp(value: str) -> datetime:
    """Parse one timezone-aware RFC 3339 timestamp."""
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SupplyChainContractError(f"invalid timestamp: {value}") from exc
    if parsed.tzinfo is None:
        raise SupplyChainContractError(f"timestamp must include a timezone: {value}")
    return parsed


def _validate_schema(document: Mapping[str, Any], schema_name: str) -> None:
    schema = load_json(CONTRACT_ROOT / schema_name)
    Draft202012Validator.check_schema(schema)
    errors = sorted(
        Draft202012Validator(
            schema,
            format_checker=FormatChecker(),
        ).iter_errors(document),
        key=lambda error: tuple(str(part) for part in error.absolute_path),
    )
    if errors:
        error = errors[0]
        location = ".".join(str(part) for part in error.absolute_path) or "$"
        raise SupplyChainContractError(f"{location}: {error.message}")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _is_opentofu_input(path: PurePosixPath) -> bool:
    return (
        path.suffix == ".tf"
        or path.name.endswith(".tf.json")
        or path.name in {".terraform.lock.hcl", ".tofu.lock.hcl"}
    )


def _is_dependency_input(path: PurePosixPath) -> bool:
    # The immutable v1 inventory discovers the Phase 1 repository boundary.
    # Later versioned profiles own and validate their dependency inputs.
    if path.parts[:3] == ("contracts", "supply-chain", "v2"):
        return False
    name = path.name
    workflow = (
        len(path.parts) >= 3
        and path.parts[:2] == (".github", "workflows")
        and path.suffix in {".yaml", ".yml"}
    )
    local_action = (
        len(path.parts) >= 4
        and path.parts[:2] == (".github", "actions")
        and name in {"action.yaml", "action.yml"}
    )
    dockerfile = name.startswith("Dockerfile") and name != "Dockerfile.dockerignore"
    python_requirement = (
        name.startswith("requirements") and path.suffix in {".in", ".lock", ".txt"}
    ) or name.endswith("requirements.txt")
    toolchain = path.parts[:3] == ("src", "pipeline", "toolchain") and not name.startswith(".")
    vendored_schema = path.parts[:4] == ("contracts", "supply-chain", "v1", "vendor")
    reviewed_python_graph = (
        path.parts[:4] == ("contracts", "supply-chain", "v1", "python-graphs")
        and path.suffix == ".json"
    )
    reviewed_signing_tool = (
        path.parts[:4] == ("contracts", "supply-chain", "v1", "tools") and path.suffix == ".json"
    )
    return (
        workflow
        or local_action
        or dockerfile
        or name in _COMPOSE_FILES | _NODE_INPUTS | _PYTHON_INPUTS | _DOTNET_INPUTS
        or python_requirement
        or path.suffix == ".csproj"
        or _is_opentofu_input(path)
        or toolchain
        or vendored_schema
        or reviewed_python_graph
        or reviewed_signing_tool
    )


def discover_dependency_inputs(repository_root: Path = REPOSITORY_ROOT) -> tuple[str, ...]:
    """Discover every dependency-defining repository input in stable order."""
    root = repository_root.resolve()
    discovered = []
    for candidate in root.rglob("*"):
        relative = candidate.relative_to(root)
        if any(part in _IGNORED_DEPENDENCY_PARTS for part in relative.parts):
            continue
        logical_path = PurePosixPath(relative.as_posix())
        if candidate.is_file() and _is_dependency_input(logical_path):
            discovered.append(logical_path.as_posix())
    return tuple(sorted(discovered))


def _component_for_input(path: PurePosixPath) -> str:
    value = path.as_posix()
    if path.parts[:2] in {(".github", "actions"), (".github", "workflows")}:
        return "github-actions"
    if path.name in _COMPOSE_FILES:
        return "legacy-container-images"
    if path.name.startswith("Dockerfile"):
        if value == "src/pipeline/offline_release/Dockerfile":
            return "release-container-image"
        if path.parts[:3] == ("src", "pipeline", "toolchain"):
            return "native-geospatial-toolchain"
        if value in {
            "infra/blob-seed/Dockerfile",
            "src/api/Dockerfile",
            "src/frontend/Dockerfile",
        }:
            return "legacy-container-images"
    if path.parts[:3] == ("src", "pipeline", "toolchain"):
        return "native-geospatial-toolchain"
    if path.parts[:4] == ("contracts", "supply-chain", "v1", "vendor"):
        return "vendored-standard-schemas"
    if path.parts[:4] == ("contracts", "supply-chain", "v1", "python-graphs"):
        if value == "contracts/supply-chain/v1/python-graphs/release-runtime.json":
            return "pipeline-python-release"
        if value == "contracts/supply-chain/v1/python-graphs/settlement-spatial-runtime.json":
            return "settlement-spatial-python"
    if path.parts[:4] == ("contracts", "supply-chain", "v1", "tools"):
        return "release-signing-toolchain"
    if path.parts[:2] == ("src", "api"):
        return "api-nuget"
    if (len(path.parts) == 1 and path.name in _NODE_INPUTS) or (
        path.parts[:2] == ("src", "web") and path.name in _NODE_INPUTS
    ):
        return "frontend-npm"
    if path.parts[:2] == ("src", "frontend") and path.name in _NODE_INPUTS:
        return "frontend-npm"
    if path.parts[:2] == ("infra", "blob-seed"):
        return "blob-seed-python"
    if value == "src/pipeline/science/geoid-evaluator-requirements.txt":
        return "pipeline-geoid-evaluator"
    if value in {"src/pipeline/pyproject.toml", "src/pipeline/requirements-pipeline.txt"}:
        return "pipeline-python-contributor"
    if path.name.startswith("requirements-release") or path.name.startswith(
        "requirements-phase1-final-"
    ):
        return "pipeline-python-release"
    if path.name.startswith("requirements-settlements-spatial"):
        return "settlement-spatial-python"
    if _is_opentofu_input(path):
        return "deployment-opentofu"
    raise SupplyChainContractError(f"unclassified dependency input: {value}")


def _role_for_input(path: PurePosixPath) -> str:
    if path.parts[:2] in {(".github", "actions"), (".github", "workflows")}:
        return "workflow"
    if path.name.startswith("Dockerfile") or path.suffix == ".sh":
        return "recipe"
    if path.name.endswith("build-receipt.json"):
        return "receipt"
    if path.parts[:4] == ("contracts", "supply-chain", "v1", "vendor"):
        return "lock" if path.name == "manifest.json" else "schema"
    if path.parts[:4] == ("contracts", "supply-chain", "v1", "python-graphs"):
        return "manifest"
    if path.parts[:4] == ("contracts", "supply-chain", "v1", "tools"):
        return "lock"
    if (
        path.name in {"package-lock.json", "packages.lock.json", ".terraform.lock.hcl"}
        or path.suffix == ".lock"
        or path.name == "geoid-evaluator-requirements.txt"
        or path.name == "duckdb-spatial-extensions.json"
    ):
        return "lock"
    return "manifest"


def _safe_inventory_path(repository_root: Path, value: str) -> Path:
    logical_path = PurePosixPath(value)
    if (
        not value
        or "\\" in value
        or logical_path.is_absolute()
        or value != logical_path.as_posix()
        or any(part in {"", ".", ".."} for part in logical_path.parts)
    ):
        raise SupplyChainContractError(f"unsafe dependency input path: {value}")

    root = repository_root.resolve()
    candidate = repository_root.joinpath(*logical_path.parts)
    cursor = repository_root
    for part in logical_path.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise SupplyChainContractError(f"dependency input path must not use symlinks: {value}")
    try:
        mode = candidate.stat().st_mode
        candidate.resolve().relative_to(root)
    except (FileNotFoundError, ValueError) as exc:
        raise SupplyChainContractError(f"dependency input is outside or missing: {value}") from exc
    if not stat.S_ISREG(mode):
        raise SupplyChainContractError(f"dependency input must be a regular file: {value}")
    return candidate


def _validate_npm_lock_integrity(lock_path: Path, logical_path: str) -> None:
    """Require immutable registry identities for every non-workspace package."""
    lock = load_json(lock_path)
    packages = lock.get("packages")
    if lock.get("lockfileVersion") != 3 or not isinstance(packages, dict):
        raise SupplyChainContractError(
            f"npm lock must use package-lock v3 with a packages map: {logical_path}"
        )
    root = packages.get("")
    if not isinstance(root, dict):
        raise SupplyChainContractError(f"npm lock root package is missing: {logical_path}")
    raw_workspaces = root.get("workspaces", [])
    if not isinstance(raw_workspaces, list) or not all(
        isinstance(value, str) and value and "*" not in value for value in raw_workspaces
    ):
        raise SupplyChainContractError(f"npm lock workspaces must be exact paths: {logical_path}")
    workspaces = set(raw_workspaces)

    for package_path, entry in packages.items():
        if not isinstance(package_path, str) or not isinstance(entry, dict):
            raise SupplyChainContractError(
                f"npm lock package entries must be objects: {logical_path}"
            )
        if package_path == "":
            continue
        if entry.get("link") is True:
            if entry.get("resolved") not in workspaces:
                raise SupplyChainContractError(
                    f"npm link must resolve to a declared workspace: {logical_path}:{package_path}"
                )
            continue
        if package_path in workspaces:
            continue
        if "node_modules" not in PurePosixPath(package_path).parts:
            raise SupplyChainContractError(
                f"npm package is neither registry, workspace, nor link: "
                f"{logical_path}:{package_path}"
            )
        resolved = entry.get("resolved")
        if not isinstance(resolved, str) or not resolved.startswith("https://registry.npmjs.org/"):
            raise SupplyChainContractError(
                f"npm registry package resolved URL is missing: {logical_path}:{package_path}"
            )
        integrity = entry.get("integrity")
        if not isinstance(integrity, str) or not integrity.startswith("sha512-"):
            raise SupplyChainContractError(
                f"npm registry package SHA-512 integrity is missing: {logical_path}:{package_path}"
            )
        try:
            digest = base64.b64decode(integrity.removeprefix("sha512-"), validate=True)
        except (binascii.Error, ValueError) as exc:
            raise SupplyChainContractError(
                f"npm registry package SHA-512 integrity is invalid: {logical_path}:{package_path}"
            ) from exc
        if len(digest) != 64:
            raise SupplyChainContractError(
                f"npm registry package SHA-512 integrity is invalid: {logical_path}:{package_path}"
            )


def validate_dependency_inventory(
    inventory_path: Path,
    *,
    repository_root: Path = REPOSITORY_ROOT,
) -> dict[str, Any]:
    """Validate exact dependency-input discovery and immutable byte bindings."""
    document = load_json(inventory_path)
    _validate_schema(document, "dependency-inventory.schema.json")
    components = document["components"]
    component_ids = [component["id"] for component in components]
    if len(component_ids) != len(set(component_ids)):
        raise SupplyChainContractError("dependency component identifiers must be unique")
    if component_ids != sorted(component_ids):
        raise SupplyChainContractError("dependency components must use stable sorted order")
    if component_ids != sorted(_EXPECTED_COMPONENTS):
        missing = sorted(set(_EXPECTED_COMPONENTS) - set(component_ids))
        extra = sorted(set(component_ids) - set(_EXPECTED_COMPONENTS))
        raise SupplyChainContractError(
            f"dependency component set mismatch; missing={missing}, extra={extra}"
        )

    recorded: dict[str, tuple[dict[str, Any], Path]] = {}
    for component in components:
        component_id = component["id"]
        status = (component["releaseUse"], component["coverage"])
        if status not in _ALLOWED_STATUS_COMBINATIONS:
            raise SupplyChainContractError(
                f"invalid dependency status combination for {component_id}: {status}"
            )
        actual_contract = (component["ecosystem"], *status)
        if actual_contract != _EXPECTED_COMPONENTS[component_id]:
            raise SupplyChainContractError(f"dependency component contract drift: {component_id}")
        inputs = component["inputs"]
        if (component["coverage"] == "not-present") != (not inputs):
            raise SupplyChainContractError(
                f"not-present dependency component must have no inputs: {component_id}"
            )
        paths = [item["path"] for item in inputs]
        if len(paths) != len(set(paths)):
            raise SupplyChainContractError(f"duplicate dependency input in {component_id}")
        if paths != sorted(paths):
            raise SupplyChainContractError(
                f"dependency inputs must use stable sorted order: {component_id}"
            )
        for item in inputs:
            value = item["path"]
            if value in recorded:
                raise SupplyChainContractError(
                    f"duplicate dependency input across components: {value}"
                )
            input_path = _safe_inventory_path(repository_root, value)
            logical_path = PurePosixPath(value)
            if item["role"] not in _ALLOWED_ROLES[component["ecosystem"]]:
                raise SupplyChainContractError(f"invalid dependency input role: {value}")
            if _component_for_input(logical_path) != component_id:
                raise SupplyChainContractError(f"dependency input component mismatch: {value}")
            if _role_for_input(logical_path) != item["role"]:
                raise SupplyChainContractError(f"dependency input role mismatch: {value}")
            recorded[value] = (item, input_path)

    discovered = set(discover_dependency_inputs(repository_root))
    recorded_paths = set(recorded)
    if discovered != recorded_paths:
        missing = sorted(discovered - recorded_paths)
        extra = sorted(recorded_paths - discovered)
        raise SupplyChainContractError(
            f"dependency discovery mismatch; unclassified={missing}, extra={extra}"
        )
    for value, (item, path) in recorded.items():
        if _sha256(path) != item["sha256"]:
            raise SupplyChainContractError(f"dependency input SHA-256 mismatch: {value}")
        if path.name == "package-lock.json":
            _validate_npm_lock_integrity(path, value)

    projects = {Path(path).parent for path in discovered if path.endswith(".csproj")}
    project_locks = {
        Path(path).parent for path in discovered if path.endswith("/packages.lock.json")
    }
    if projects != project_locks:
        raise SupplyChainContractError(
            "every NuGet project must have one sibling packages.lock.json"
        )
    npm_manifests = {Path(path).parent for path in discovered if Path(path).name == "package.json"}
    npm_locks = {Path(path).parent for path in discovered if Path(path).name == "package-lock.json"}
    workspace_manifests = npm_manifests - npm_locks
    if workspace_manifests:
        root_manifest = load_json(repository_root / "package.json")
        root_lock = load_json(repository_root / "package-lock.json")
        workspaces = root_manifest.get("workspaces")
        packages = root_lock.get("packages")
        declared_workspaces = (
            {
                Path(value)
                for value in workspaces
                if isinstance(value, str) and value and "*" not in value
            }
            if isinstance(workspaces, list)
            else set()
        )
        locked_workspaces = (
            {Path(value) for value in packages if isinstance(value, str) and value}
            if isinstance(packages, dict)
            else set()
        )
        if (
            Path(".") not in npm_locks
            or workspace_manifests != declared_workspaces
            or not workspace_manifests <= locked_workspaces
        ):
            raise SupplyChainContractError(
                "every npm manifest must have one sibling package-lock.json "
                "or one exact root workspace lock entry"
            )
    tofu_inputs = [
        PurePosixPath(path) for path in discovered if _is_opentofu_input(PurePosixPath(path))
    ]
    if tofu_inputs and not any(path.name == ".terraform.lock.hcl" for path in tofu_inputs):
        raise SupplyChainContractError("OpenTofu inputs require a provider lock file")

    vendor_root = repository_root / "contracts" / "supply-chain" / "v1" / "vendor"
    vendor_manifest = load_json(vendor_root / "manifest.json")
    if (vendor_manifest.get("standard"), vendor_manifest.get("specVersion")) != (
        "CycloneDX",
        "1.7",
    ):
        raise SupplyChainContractError("vendored schema manifest must identify CycloneDX 1.7")
    schema_records = vendor_manifest.get("schemas", [])
    schema_names = [record.get("path") for record in schema_records]
    if len(schema_names) != len(set(schema_names)) or schema_names != sorted(schema_names):
        raise SupplyChainContractError("vendored schema manifest paths must be unique and sorted")
    discovered_schemas = {
        PurePosixPath(path).name
        for path in discovered
        if path.startswith("contracts/supply-chain/v1/vendor/")
        and not path.endswith("/manifest.json")
    }
    if set(schema_names) != discovered_schemas:
        raise SupplyChainContractError("vendored schema manifest discovery mismatch")
    for record in schema_records:
        relative_path = PurePosixPath(record["path"])
        if len(relative_path.parts) != 1:
            raise SupplyChainContractError("vendored schema path must be one file name")
        if _sha256(vendor_root / relative_path.name) != record.get("sha256"):
            raise SupplyChainContractError(
                f"vendored schema SHA-256 mismatch: {relative_path.name}"
            )
    return document


def _reject_remote_schema(uri: str) -> Resource:
    raise SupplyChainContractError(f"remote schema retrieval is prohibited: {uri}")


def _validate_cyclonedx(document: Mapping[str, Any]) -> None:
    vendor_root = CONTRACT_ROOT / "vendor"
    manifest = load_json(vendor_root / "manifest.json")
    if (manifest.get("standard"), manifest.get("specVersion")) != ("CycloneDX", "1.7"):
        raise SupplyChainContractError("vendored CycloneDX identity is not version 1.7")

    schemas: list[dict[str, Any]] = []
    for record in manifest.get("schemas", []):
        relative_path = Path(record["path"])
        if relative_path.name != str(relative_path):
            raise SupplyChainContractError("vendored schema path must be one file name")
        schema_path = vendor_root / relative_path
        if _sha256(schema_path) != record["sha256"]:
            raise SupplyChainContractError(f"vendored schema SHA-256 mismatch: {relative_path}")
        schemas.append(load_json(schema_path))
    if len(schemas) != 4:
        raise SupplyChainContractError("vendored CycloneDX schema bundle is incomplete")

    bom_schema = next(
        schema for schema in schemas if schema["$id"].endswith("/bom-1.7.schema.json")
    )
    registry = Registry(retrieve=_reject_remote_schema)  # type: ignore[call-arg]
    for schema in schemas:
        registry = registry.with_resource(schema["$id"], Resource.from_contents(schema))
    Draft7Validator.check_schema(bom_schema)
    errors = sorted(
        Draft7Validator(
            bom_schema,
            registry=registry,
            format_checker=FormatChecker(),
        ).iter_errors(document),
        key=lambda error: tuple(str(part) for part in error.absolute_path),
    )
    if errors:
        error = errors[0]
        location = ".".join(str(part) for part in error.absolute_path) or "$"
        raise SupplyChainContractError(f"SBOM {location}: {error.message}")
    if document.get("specVersion") != "1.7":
        raise SupplyChainContractError("SBOM specVersion must be '1.7'")


def _validate_evidence_files(
    envelope_path: Path,
    identity_policy_path: Path,
    sbom_paths: Mapping[str, Path],
    *,
    allow_production_envelope: bool,
) -> dict[str, Any]:
    """Validate a candidate envelope and its exact local policy/SBOM bytes."""
    envelope = load_json(envelope_path)
    policy = load_json(identity_policy_path)
    _validate_schema(policy, "identity-policy.schema.json")
    _validate_schema(envelope, "evidence-envelope.schema.json")

    if envelope["identityPolicy"]["sha256"] != _sha256(identity_policy_path):
        raise SupplyChainContractError("identity policy SHA-256 does not match its bytes")
    verification = envelope["verification"]
    for field in ("certificateIdentity", "oidcIssuer"):
        if verification[field] != policy[field]:
            raise SupplyChainContractError(f"verification {field} violates identity policy")

    subjects = {
        envelope["candidateManifest"]["path"]: envelope["candidateManifest"]["sha256"],
        envelope["provenance"]["path"]: envelope["provenance"]["sha256"],
    }
    signed_subjects = {
        item["subjectPath"]: item["subjectSha256"] for item in envelope["signatures"]
    }
    if len(signed_subjects) != len(envelope["signatures"]):
        raise SupplyChainContractError("each signed subject must appear exactly once")
    if signed_subjects != subjects:
        raise SupplyChainContractError("signatures must bind the manifest and provenance hashes")

    artifact_paths = [
        envelope["candidateManifest"]["path"],
        envelope["provenance"]["path"],
    ]
    artifact_paths.extend(item["path"] for item in envelope["signatures"])
    artifact_paths.extend(item["path"] for item in envelope["softwareBillsOfMaterials"])
    if len(artifact_paths) != len(set(artifact_paths)):
        raise SupplyChainContractError("supply-chain artifact paths must be unique")

    descriptors = {item["path"]: item for item in envelope["softwareBillsOfMaterials"]}
    if set(descriptors) != set(sbom_paths):
        raise SupplyChainContractError("SBOM paths do not match the evidence envelope")
    for logical_path, descriptor in descriptors.items():
        file_path = sbom_paths[logical_path]
        if descriptor["sha256"] != _sha256(file_path):
            raise SupplyChainContractError(f"SBOM SHA-256 mismatch: {logical_path}")
        _validate_cyclonedx(load_json(file_path))

    if not verification["fixtureOnly"] and not allow_production_envelope:
        raise SupplyChainContractError(
            "production evidence requires the separate cryptographic verifier"
        )
    return envelope


def validate_evidence_files(
    envelope_path: Path,
    identity_policy_path: Path,
    sbom_paths: Mapping[str, Path],
) -> dict[str, Any]:
    """Validate synthetic evidence without crossing the cryptographic boundary."""
    return _validate_evidence_files(
        envelope_path,
        identity_policy_path,
        sbom_paths,
        allow_production_envelope=False,
    )


def _validate_real_source_unverified_evidence(
    envelope_raw: bytes,
    candidate_manifest: bytes,
    provenance: bytes,
    identity_policy: bytes,
    signature_bundles: Mapping[str, bytes],
    sboms: Mapping[str, bytes],
) -> dict[str, Any]:
    """Validate immutable pre-verification inputs for the private signing path."""
    envelope = _strict_json_bytes(envelope_raw, "real-source evidence envelope")
    policy = _strict_json_bytes(identity_policy, "identity policy")
    _validate_schema(policy, "identity-policy.schema.json")
    _validate_schema(envelope, "real-source-unverified-evidence-envelope.schema.json")

    if envelope["identityPolicy"]["sha256"] != hashlib.sha256(identity_policy).hexdigest():
        raise SupplyChainContractError("identity policy SHA-256 does not match its bytes")

    exact_bytes = (
        ("candidate manifest", envelope["candidateManifest"], candidate_manifest),
        ("provenance", envelope["provenance"], provenance),
    )
    for label, descriptor, raw in exact_bytes:
        if descriptor["sha256"] != hashlib.sha256(raw).hexdigest():
            raise SupplyChainContractError(f"{label} SHA-256 does not match its bytes")
        if descriptor["byteSize"] != len(raw):
            raise SupplyChainContractError(f"{label} byte size does not match its bytes")

    signature_descriptors = {item["path"]: item for item in envelope["signatures"]}
    if tuple(signature_descriptors) != _REAL_SOURCE_EVIDENCE_SIGNATURE_PATHS:
        raise SupplyChainContractError("signature paths do not match the evidence contract")
    if set(signature_bundles) != set(_REAL_SOURCE_EVIDENCE_SIGNATURE_PATHS):
        raise SupplyChainContractError("signature bundle inputs do not match the evidence envelope")
    subjects = {
        "manifest.sigstore.json": ("manifest.json", hashlib.sha256(candidate_manifest).hexdigest()),
        "provenance.sigstore.json": (
            "provenance.intoto.jsonl",
            hashlib.sha256(provenance).hexdigest(),
        ),
    }
    for logical_path, descriptor in signature_descriptors.items():
        raw = signature_bundles[logical_path]
        if descriptor["sha256"] != hashlib.sha256(raw).hexdigest():
            raise SupplyChainContractError(f"signature SHA-256 mismatch: {logical_path}")
        if descriptor["byteSize"] != len(raw):
            raise SupplyChainContractError(f"signature byte size mismatch: {logical_path}")
        if (descriptor["subjectPath"], descriptor["subjectSha256"]) != subjects[logical_path]:
            raise SupplyChainContractError(f"signature subject mismatch: {logical_path}")
        subject = candidate_manifest if logical_path == "manifest.sigstore.json" else provenance
        bundle = _strict_json_bytes(raw, f"signature bundle {logical_path}")
        _validate_sigstore_bundle(bundle, subject, f"signature bundle {logical_path}")

    artifact_paths = [
        envelope["candidateManifest"]["path"],
        envelope["provenance"]["path"],
    ]
    artifact_paths.extend(signature_descriptors)
    artifact_paths.extend(item["path"] for item in envelope["softwareBillsOfMaterials"])
    if len(artifact_paths) != len(set(artifact_paths)):
        raise SupplyChainContractError("supply-chain artifact paths must be unique")

    descriptors = {item["path"]: item for item in envelope["softwareBillsOfMaterials"]}
    if tuple(descriptors) != _REAL_SOURCE_EVIDENCE_SBOM_PATHS:
        raise SupplyChainContractError("SBOM paths are not the exact sorted canonical set")
    if set(sboms) != set(_REAL_SOURCE_EVIDENCE_SBOM_PATHS):
        raise SupplyChainContractError("SBOM paths do not match the evidence envelope")
    for logical_path, descriptor in descriptors.items():
        raw = sboms[logical_path]
        if descriptor["sha256"] != hashlib.sha256(raw).hexdigest():
            raise SupplyChainContractError(f"SBOM SHA-256 mismatch: {logical_path}")
        if descriptor["byteSize"] != len(raw):
            raise SupplyChainContractError(f"SBOM byte size mismatch: {logical_path}")
        sbom = _strict_json_bytes(raw, f"SBOM {logical_path}")
        _validate_cyclonedx(sbom)
    return envelope


def validate_dependency_exception(
    document: Mapping[str, Any],
    *,
    as_of: datetime,
) -> None:
    """Validate exception ownership and its deterministic effective interval."""
    if as_of.tzinfo is None:
        raise SupplyChainContractError("validation instant must include a timezone")
    _validate_schema(document, "dependency-exception.schema.json")
    approved_at = parse_timestamp(str(document["approvedAt"]))
    expires_at = parse_timestamp(str(document["expiresAt"]))
    if expires_at <= approved_at:
        raise SupplyChainContractError("dependency exception must expire after approval")
    if as_of < approved_at:
        raise SupplyChainContractError("dependency exception is not effective yet")
    if as_of >= expires_at:
        raise SupplyChainContractError("dependency exception is expired")
