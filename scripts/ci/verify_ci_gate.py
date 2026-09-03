"""Fail closed when routed GitHub Actions jobs do not match route selection."""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping, Sequence
from typing import Any, Optional


class GateVerificationError(RuntimeError):
    """A selected job did not succeed or an unselected job unexpectedly ran."""


CI_ROUTE_JOBS = {
    "docs": ("docs",),
    "web": ("web",),
    "pipeline": (
        "pipeline",
        "settlement-spatial-toolchain-macos",
        "offline-release-fixture",
    ),
    "repository_removal": ("repository-removal-v2",),
    "static_delivery_iac": ("static-delivery-iac",),
}


def _selected(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.lower() in {"true", "false"}:
        return value.lower() == "true"
    raise GateVerificationError(f"invalid route selection value: {value!r}")


def _job_result(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, Mapping) and isinstance(value.get("result"), str):
        return value["result"]
    raise GateVerificationError(f"invalid job result value: {value!r}")


def _require_result(
    errors: list[str], jobs: Mapping[str, Any], job: str, expected: str
) -> None:
    if job not in jobs:
        errors.append(f"{job}: missing from aggregate needs")
        return
    actual = _job_result(jobs[job])
    if actual != expected:
        errors.append(f"{job}: expected {expected}, got {actual}")


def verify_gate_results(
    profile: str,
    routes: Mapping[str, Any],
    jobs: Mapping[str, Any],
    *,
    release_evidence: bool = False,
) -> None:
    """Verify exact selected/success and unselected/skipped aggregate states."""
    errors: list[str] = []
    _require_result(errors, jobs, "changes", "success")

    if profile == "codeql":
        selected = _selected(routes.get("codeql_javascript", False))
        _require_result(
            errors,
            jobs,
            "analyze-javascript",
            "success" if selected else "skipped",
        )
    elif profile == "ci":
        for route, routed_jobs in CI_ROUTE_JOBS.items():
            selected = _selected(routes.get(route, False))
            for job in routed_jobs:
                _require_result(
                    errors, jobs, job, "success" if selected else "skipped"
                )

        release_selected = _selected(routes.get("release", False))
        ordinary_release = release_selected and not release_evidence
        trusted_release = release_selected and release_evidence
        for job in ("release-toolchain", "release-toolchain-macos"):
            _require_result(
                errors, jobs, job, "success" if ordinary_release else "skipped"
            )
        for job in ("ar6-release-evidence", "ar6-release-evidence-macos"):
            _require_result(
                errors, jobs, job, "success" if trusted_release else "skipped"
            )
    else:
        raise GateVerificationError(f"unknown aggregate profile: {profile}")

    if errors:
        raise GateVerificationError("; ".join(errors))


def _object(raw: str, label: str) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as error:
        raise GateVerificationError(f"invalid {label} JSON: {error}") from error
    if not isinstance(value, dict):
        raise GateVerificationError(f"{label} JSON must be an object")
    return value


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", choices=("ci", "codeql"), required=True)
    parser.add_argument("--routes-json", required=True)
    parser.add_argument("--jobs-json", required=True)
    parser.add_argument("--release-evidence", action="store_true")
    args = parser.parse_args(argv)
    try:
        verify_gate_results(
            args.profile,
            _object(args.routes_json, "routes"),
            _object(args.jobs_json, "jobs"),
            release_evidence=args.release_evidence,
        )
    except GateVerificationError as error:
        print(f"ERROR: {error}")
        return 1
    print(f"{args.profile} aggregate gate matched every routed job")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
