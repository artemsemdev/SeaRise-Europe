"""Classify changed repository paths into independently testable CI areas."""

from __future__ import annotations

import argparse
import fnmatch
import json
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

OUTPUTS = (
    "frontend",
    "api",
    "pipeline",
    "release",
    "infrastructure",
    "docker_frontend",
    "docker_api",
    "compose",
    "codeql_javascript",
    "codeql_csharp",
    "heavy",
)

# Changes to routing or either consuming workflow exercise every route. This is
# deliberately conservative because an incorrect filter can silently remove a
# required quality gate.
FORCE_ALL = (
    ".github/workflows/ci.yml",
    ".github/workflows/codeql.yml",
    "scripts/ci/**",
)

FRONTEND = (
    "src/frontend/**",
    "contracts/**",
    "tests/fixtures/tdd/**",
)

API = (
    "src/api/**",
    "SeaRise Europe.sln",
    "infra/db/**",
    "tests/fixtures/tdd/**",
)

PIPELINE = (
    ".github/workflows/offline-release-controlled.yml",
    ".github/workflows/phase-0r-owner-promotion.yml",
    "docs/evidence/fixtures/offline-release-execution-receipt.example.json",
    "scripts/release/prepare_controlled_offline_inputs.py",
    "scripts/science/promote_phase_0r_release.py",
    "scripts/science/validate_ar6_delivery_trace.py",
    "src/pipeline/**",
    ".env.pipeline.example",
    ".gitignore",
    "data/geometry/**",
    "scripts/tests/**",
    "contracts/**",
    "tests/**",
)

# The release route is intentionally narrower than PIPELINE. It owns the
# pinned geospatial toolchain preflight, while the 9.24 GB real-source build is
# further isolated behind an explicit manual evidence dispatch.
RELEASE = (
    ".github/workflows/offline-release-controlled.yml",
    ".github/workflows/phase-0r-owner-promotion.yml",
    "scripts/release/prepare_controlled_offline_inputs.py",
    "scripts/science/promote_phase_0r_release.py",
    "scripts/science/*ar6*release*.py",
    "scripts/science/build_ar6_lookup_goldens.py",
    "scripts/science/validate_ar6_delivery_trace.py",
    "src/frontend/package.json",
    "src/frontend/package-lock.json",
    "src/frontend/scripts/measure-ar6-release.mjs",
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

INFRASTRUCTURE = (
    "infra/**",
    "data/geometry/**",
    "docker-compose.yml",
    ".env.local.example",
    "scripts/compose-smoke.sh",
)

FRONTEND_IMAGE = (
    "src/frontend/Dockerfile",
    "src/frontend/package.json",
    "src/frontend/package-lock.json",
    "src/frontend/next.config.js",
    "src/frontend/postcss.config.mjs",
    "src/frontend/tsconfig.json",
    "src/frontend/src/**",
)

API_IMAGE = (
    "src/api/Dockerfile",
    "src/api/Directory.Build.props",
    "src/api/*.sln",
    "src/api/**/*.csproj",
    "src/api/**/*.cs",
    "src/api/**/appsettings*.json",
)

COMPOSE = (
    "docker-compose.yml",
    ".env.local.example",
    "scripts/compose-smoke.sh",
    "infra/**",
    "data/geometry/**",
    "src/frontend/Dockerfile",
    "src/frontend/package.json",
    "src/frontend/package-lock.json",
    "src/frontend/next.config.js",
    "src/frontend/src/app/api/health/route.ts",
    "src/api/Dockerfile",
    "src/api/Directory.Build.props",
    "src/api/**/*.csproj",
    "src/api/SeaRise.Api/Program.cs",
    "src/api/SeaRise.Api/appsettings*.json",
)

CODEQL_JAVASCRIPT = ("src/frontend/**",)

CODEQL_CSHARP = ("src/api/**",)


def _normalize(path: str) -> str:
    return path.replace("\\", "/").removeprefix("./")


def _matches(path: str, patterns: Sequence[str]) -> bool:
    return any(fnmatch.fnmatchcase(path, pattern) for pattern in patterns)


def _is_frontend_test(path: str) -> bool:
    return "/__tests__/" in path or ".test." in path or ".spec." in path


def _is_api_test(path: str) -> bool:
    return "/SeaRise.Api.Tests/" in path


def classify_paths(changed_paths: Sequence[str]) -> dict[str, bool]:
    """Return stable GitHub-output flags for the supplied changed paths."""
    paths = sorted({_normalize(path) for path in changed_paths if path.strip()})
    if any(_matches(path, FORCE_ALL) for path in paths):
        return {name: True for name in OUTPUTS}

    result = {
        "frontend": any(_matches(path, FRONTEND) for path in paths),
        "api": any(_matches(path, API) for path in paths),
        "pipeline": any(_matches(path, PIPELINE) for path in paths),
        "release": any(_matches(path, RELEASE) for path in paths),
        "infrastructure": any(_matches(path, INFRASTRUCTURE) for path in paths),
        "docker_frontend": any(
            _matches(path, FRONTEND_IMAGE) and not _is_frontend_test(path)
            for path in paths
        ),
        "docker_api": any(
            _matches(path, API_IMAGE) and not _is_api_test(path) for path in paths
        ),
        "compose": any(_matches(path, COMPOSE) for path in paths),
        "codeql_javascript": any(_matches(path, CODEQL_JAVASCRIPT) for path in paths),
        "codeql_csharp": any(_matches(path, CODEQL_CSHARP) for path in paths),
    }
    result["heavy"] = any(result.values())
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
