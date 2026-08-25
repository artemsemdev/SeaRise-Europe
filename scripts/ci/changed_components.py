"""Classify changed repository paths into independently testable CI areas."""

from __future__ import annotations

import argparse
import fnmatch
import json
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FITNESS_CONTRACT = ROOT / "contracts/ci/v1/architecture-fitness.json"

OUTPUTS = (
    "docs",
    "web",
    "pipeline",
    "release",
    "repository_removal",
    "codeql_javascript",
    "heavy",
)


class ArchitectureFitnessContractError(ValueError):
    """The repository-owned routing contract is missing or malformed."""


class DeferredCapabilityError(RuntimeError):
    """A changed path needs an owner gate that has not been activated yet."""

# Changes to routing or either consuming workflow exercise every route. This is
# deliberately conservative because an incorrect filter can silently remove a
# required quality gate.
FORCE_ALL = (
    ".github/workflows/ci.yml",
    ".github/workflows/codeql.yml",
    "scripts/ci/**",
)


WEB = (
    ".nvmrc",
    ".github/workflows/**",
    "package.json",
    "package-lock.json",
    "contracts/repository-removal/v1/historical-allowlist*.json",
    "src/web/**",
    "tools/static-quality/**",
    "contracts/release/v1/**",
    "contracts/release/v2/**",
    "contracts/http-delivery/**",
    "contracts/supply-chain/v2/**",
    "docs/architecture/adr/ADR-024-ar6-regional-projection-contract.md",
    "docs/methodology.md",
    "docs/product/Mock/SeaRise-Flight.html",
    "docs/product/Mock/MOCK_REQUIREMENTS_MAP.md",
    "src/pipeline/evidence/phase-1/pmtiles-render-v1/**",
    "src/pipeline/evidence/ar6-regional-release/**",
    "src/pipeline/fixtures/ar6-regional-release/**",
)

DOCS = (
    "*.md",
    "docs/**",
    "contracts/**/*.md",
    "src/**/*.md",
)


PIPELINE = (
    ".github/workflows/offline-release-controlled.yml",
    ".github/workflows/phase-1-release-sign.yml",
    ".github/workflows/phase-0r-owner-promotion.yml",
    "docs/evidence/fixtures/offline-release-execution-receipt.example.json",
    "scripts/release/prepare_controlled_offline_inputs.py",
    "scripts/release/validate_supply_chain_contract.py",
    "scripts/science/promote_phase_0r_release.py",
    "scripts/science/validate_ar6_delivery_trace.py",
    "src/pipeline/**",
    ".env.pipeline.example",
    ".gitignore",
    "data/geometry/**",
    "data/settlements/**",
    "scripts/tests/**",
    "contracts/**",
    "tests/**",
)

# The release route is intentionally narrower than PIPELINE. It owns the
# pinned geospatial toolchain preflight, while the 9.24 GB real-source build is
# further isolated behind an explicit manual evidence dispatch.
RELEASE = (
    ".github/workflows/offline-release-controlled.yml",
    ".github/workflows/phase-1-release-sign.yml",
    ".github/workflows/phase-0r-owner-promotion.yml",
    "scripts/release/prepare_controlled_offline_inputs.py",
    "scripts/science/promote_phase_0r_release.py",
    "scripts/science/*ar6*release*.py",
    "scripts/science/build_ar6_lookup_goldens.py",
    "scripts/science/validate_ar6_delivery_trace.py",
    "package.json",
    "package-lock.json",
    "src/web/scripts/measure-ar6-release.mjs",
    "src/web/package.json",
    "src/web/scripts/verify-boundary-pmtiles-browser.mjs",
    "src/pipeline/fixtures/ar6-regional-release/**",
    "src/pipeline/requirements-release*.lock",
    "src/pipeline/science/ar6-regional-release*.json",
    "src/pipeline/science/ar6-release-promotion.schema.json",
    "src/pipeline/science/ar6-lookup-validation*.json",
    "src/pipeline/science/ar6-projection-contract*.json",
    "src/pipeline/science/evidence/ar6-lookup-goldens*.json",
    "src/pipeline/science/source-semantics*.json",
    "src/pipeline/searise_pipeline/release/**",
    "src/pipeline/searise_pipeline/science/ar6.py",
    "src/pipeline/searise_pipeline/science/ar6_lookup.py",
    "src/pipeline/tests/release/**",
    "src/pipeline/tests/science/test_ar6_regional_release_contract.py",
    "src/pipeline/toolchain/**",
    "src/pipeline/sources/source-lock*.json",
)





REPOSITORY_REMOVAL = (
    "contracts/repository-removal/**",
    "contracts/supply-chain/v2/static-target-profile.json",
    "scripts/repository/**",
    "tests/repository-removal/**",
    "tests/test-inventory.json",
    ".env.local.example",
    "docker-compose.yml",
    "scripts/compose-smoke.sh",
    "src/api/.dockerignore",
    "src/api/Dockerfile",
    "tests/harness/test_changed_components.py",
    "tests/harness/test_immutable_dependencies.py",
)

CODEQL_JAVASCRIPT = (
    'src/web/**',
    'tools/static-quality/**',
)



def _normalize(path: str) -> str:
    return path.replace("\\", "/").removeprefix("./")


def _matches(path: str, patterns: Sequence[str]) -> bool:
    return any(fnmatch.fnmatchcase(path, pattern) for pattern in patterns)


def _load_fitness_contract(path: Path = FITNESS_CONTRACT) -> dict[str, object]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ArchitectureFitnessContractError(
            f"cannot load architecture fitness contract {path}: {error}"
        ) from error
    if document.get("schemaVersion") != 1:
        raise ArchitectureFitnessContractError("unsupported fitness contract version")
    required_document_fields = {
        "schemaVersion",
        "requiredStatuses",
        "nonWaivableGates",
        "capabilities",
    }
    if set(document) != required_document_fields:
        raise ArchitectureFitnessContractError(
            f"fitness contract fields must be exactly {sorted(required_document_fields)}"
        )
    if document["requiredStatuses"] != ["CI Gate", "CodeQL Gate"]:
        raise ArchitectureFitnessContractError(
            "fitness contract must retain the stable CI Gate and CodeQL Gate statuses"
        )
    gates = document["nonWaivableGates"]
    if (
        not isinstance(gates, list)
        or not gates
        or not all(isinstance(gate, str) and gate for gate in gates)
        or len(gates) != len(set(gates))
    ):
        raise ArchitectureFitnessContractError(
            "non-waivable fitness gates must be unique non-empty strings"
        )
    capabilities = document.get("capabilities")
    if not isinstance(capabilities, list):
        raise ArchitectureFitnessContractError("fitness capabilities must be a list")
    capability_ids: set[str] = set()
    for capability in capabilities:
        if not isinstance(capability, dict):
            raise ArchitectureFitnessContractError("fitness capability must be an object")
        required = {"id", "ownerIssue", "status", "paths", "activation"}
        if set(capability) != required:
            raise ArchitectureFitnessContractError(
                f"fitness capability fields must be exactly {sorted(required)}"
            )
        if capability["status"] not in {"deferred", "active"}:
            raise ArchitectureFitnessContractError(
                f"invalid status for capability {capability['id']}"
            )
        if not isinstance(capability["id"], str) or not capability["id"]:
            raise ArchitectureFitnessContractError("capability id must be non-empty")
        if capability["id"] in capability_ids:
            raise ArchitectureFitnessContractError(
                f"duplicate fitness capability {capability['id']}"
            )
        capability_ids.add(capability["id"])
        if not isinstance(capability["ownerIssue"], int):
            raise ArchitectureFitnessContractError(
                f"capability {capability['id']} needs an integer owner issue"
            )
        if not isinstance(capability["paths"], list) or not capability["paths"]:
            raise ArchitectureFitnessContractError(
                f"capability {capability['id']} needs path patterns"
            )
        if not all(isinstance(pattern, str) and pattern for pattern in capability["paths"]):
            raise ArchitectureFitnessContractError(
                f"capability {capability['id']} path patterns must be strings"
            )
        activation = capability["activation"]
        if not isinstance(activation, dict) or set(activation) != {
            "requiredRoute",
            "requiredCiJob",
        }:
            raise ArchitectureFitnessContractError(
                f"capability {capability['id']} needs exact activation fields"
            )
        if not all(isinstance(value, str) and value for value in activation.values()):
            raise ArchitectureFitnessContractError(
                f"capability {capability['id']} activation values must be strings"
            )
        if capability["status"] == "active" and activation["requiredRoute"] not in OUTPUTS:
            raise ArchitectureFitnessContractError(
                f"active capability {capability['id']} has no implemented route"
            )
    return document


def _enforce_deferred_capabilities(paths: Sequence[str]) -> None:
    contract = _load_fitness_contract()
    blocked = []
    for capability in contract["capabilities"]:  # type: ignore[index]
        if capability["status"] != "deferred":
            continue
        if any(_matches(path, capability["paths"]) for path in paths):
            blocked.append(f"{capability['id']} (issue #{capability['ownerIssue']})")
    if blocked:
        raise DeferredCapabilityError(
            "changed paths require deferred owner capabilities: " + ", ".join(blocked)
        )






def classify_paths(changed_paths: Sequence[str]) -> dict[str, bool]:
    """Return stable GitHub-output flags for the supplied changed paths."""
    paths = sorted({_normalize(path) for path in changed_paths if path.strip()})
    _enforce_deferred_capabilities(paths)
    if any(_matches(path, FORCE_ALL) for path in paths):
        return {name: True for name in OUTPUTS}

    result = {
        "docs": any(_matches(path, DOCS) for path in paths),
        "web": any(_matches(path, WEB) for path in paths),
        "pipeline": any(_matches(path, PIPELINE) for path in paths),
        "release": any(_matches(path, RELEASE) for path in paths),
        "repository_removal": any(_matches(path, REPOSITORY_REMOVAL) for path in paths),
        "codeql_javascript": any(_matches(path, CODEQL_JAVASCRIPT) for path in paths),
    }
    result["heavy"] = any(
        result[name]
        for name in ("web", "pipeline", "release", "repository_removal")
    )
    return result


def release_only_outputs() -> dict[str, bool]:
    """Route a manual full-source build without fanning out ordinary CI."""
    return {name: name in {"release", "heavy"} for name in OUTPUTS}


def parse_name_status(output: str) -> list[str]:
    """Include both sides of renames/copies so removed ownership is routed."""
    paths: list[str] = []
    for line in output.splitlines():
        fields = line.split("\t")
        if len(fields) < 2:
            continue
        status = fields[0][0]
        paths.extend(fields[1:] if status in {"R", "C"} else fields[1:2])
    return paths


def git_changed_paths(base: str, head: str, repo_root: Path = ROOT) -> list[str]:
    """Read a merge-base diff, with a safe fallback for an all-zero base."""
    if base and set(base) == {"0"}:
        command = [
            "git",
            "diff-tree",
            "--root",
            "--no-commit-id",
            "--name-status",
            "-r",
            head,
        ]
    else:
        command = ["git", "diff", "--name-status", "--find-renames", f"{base}...{head}"]
    result = subprocess.run(
        command,
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    )
    return parse_name_status(result.stdout)


def write_github_outputs(path: Path, outputs: Mapping[str, bool]) -> None:
    with path.open("a", encoding="utf-8") as handle:
        for name in OUTPUTS:
            handle.write(f"{name}={'true' if outputs[name] else 'false'}\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--all", action="store_true", help="Enable every route")
    source.add_argument(
        "--release-only",
        action="store_true",
        help="Enable only the AR6 release-evidence route",
    )
    source.add_argument("--changed", nargs="+", help="Explicit repository paths")
    source.add_argument("--base", help="Git base revision for BASE...HEAD")
    parser.add_argument("--head", default="HEAD")
    parser.add_argument("--repo-root", type=Path, default=ROOT)
    parser.add_argument("--github-output", type=Path)
    args = parser.parse_args()

    paths = (
        []
        if args.all or args.release_only
        else (args.changed or git_changed_paths(args.base, args.head, args.repo_root))
    )
    if args.all:
        outputs = {name: True for name in OUTPUTS}
    elif args.release_only:
        outputs = release_only_outputs()
    else:
        outputs = classify_paths(paths)
    if args.github_output:
        write_github_outputs(args.github_output, outputs)
    print(json.dumps({"changedPaths": sorted(paths), "outputs": outputs}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
