"""Validate the Issue #62 Cloudflare delivery configuration without credentials."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Sequence


ROOT = Path(__file__).resolve().parents[2]
IAC_ROOT = ROOT / "infra/cloudflare"
CONTRACT_PATH = IAC_ROOT / "delivery-contract.json"
ENVIRONMENTS = ("fixture", "production", "staging")
EXPECTED_METHODS = ["GET", "HEAD"]
EXPECTED_REQUEST_HEADERS = ["If-Match", "If-None-Match", "Range"]
EXPECTED_EXPOSED_HEADERS = [
    "Accept-Ranges",
    "Cache-Control",
    "Content-Length",
    "Content-Range",
    "Content-Type",
    "ETag",
]
FORBIDDEN_VALUE = re.compile(
    r"candidate-v7|\.tar(?:\b|\.)|access[_-]?key|secret[_-]?access[_-]?key",
    re.IGNORECASE,
)
SECRET_NAME = re.compile(
    r"(?:api|auth|access|secret|private)[_-]?(?:key|token)|password|credential",
    re.IGNORECASE,
)


class DeliveryContractError(RuntimeError):
    """The checked-in delivery plane or a plan violates its safe contract."""


def _strict_json(path: Path) -> dict[str, Any]:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise DeliveryContractError(f"duplicate JSON key in {path}: {key}")
            result[key] = value
        return result

    try:
        value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=pairs)
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise DeliveryContractError(f"invalid JSON: {path}") from error
    if not isinstance(value, dict):
        raise DeliveryContractError(f"JSON root must be an object: {path}")
    return value


def _hcl_string(path: Path, name: str) -> str:
    match = re.search(
        rf"(?m)^\s*{re.escape(name)}\s*=\s*\"([^\"]+)\"\s*$",
        path.read_text(encoding="utf-8"),
    )
    if match is None:
        raise DeliveryContractError(f"missing explicit {name} in {path}")
    return match.group(1)


def _hcl_string_list(path: Path, name: str) -> list[str]:
    match = re.search(
        rf"(?m)^\s*{re.escape(name)}\s*=\s*\[([^\]]*)\]\s*$",
        path.read_text(encoding="utf-8"),
    )
    if match is None:
        raise DeliveryContractError(f"missing explicit {name} in {path}")
    values = re.findall(r'"([^\"]+)"', match.group(1))
    if not values or "*" in match.group(1):
        raise DeliveryContractError(f"{name} must not be empty or contain wildcards")
    return values


def _assert_unique(values: list[str], label: str) -> None:
    if len(values) != len(set(values)):
        raise DeliveryContractError(f"{label} must be isolated across environments")


def validate_repository(root: Path = ROOT) -> dict[str, Any]:
    iac = root / "infra/cloudflare"
    contract = _strict_json(iac / "delivery-contract.json")
    if contract.get("schemaVersion") != 1:
        raise DeliveryContractError("unsupported delivery contract version")
    if list(contract.get("environments", {})) != list(ENVIRONMENTS):
        raise DeliveryContractError("delivery environments must be exact and sorted")
    if (iac / ".opentofu-version").read_text(encoding="utf-8") != "1.12.6\n":
        raise DeliveryContractError("OpenTofu pin must be exactly 1.12.6")
    versions = (iac / "versions.tf").read_text(encoding="utf-8")
    for fragment in (
        'required_version = "= 1.12.6"',
        'source  = "cloudflare/cloudflare"',
        'version = "= 5.23.0"',
        'backend "s3" {}',
    ):
        if fragment not in versions:
            raise DeliveryContractError(f"missing toolchain/backend pin: {fragment}")
    lock = (iac / ".terraform.lock.hcl").read_text(encoding="utf-8")
    if 'version     = "5.23.0"' not in lock or len(re.findall(r'\n\s+"h1:', lock)) < 4:
        raise DeliveryContractError("provider lock must pin 5.23.0 for multiple platforms")

    http = contract.get("http", {})
    expected_http = {
        "allowedMethods": EXPECTED_METHODS,
        "allowedRequestHeaders": EXPECTED_REQUEST_HEADERS,
        "exposedResponseHeaders": EXPECTED_EXPOSED_HEADERS,
        "immutableCacheControl": "public, max-age=31536000, immutable",
        "visualPmtilesCacheControl": "public, max-age=31536000, immutable",
        "visualPmtilesRationale": (
            "Issue #62 public-delivery acceptance applies the immutable policy to "
            "every versioned object, including PMTiles and COG; no-store is limited "
            "to the unversioned mutable release alias."
        ),
        "mutableAliasCacheControl": "no-store",
        "strongEtagAuthority": "fixture-sha256",
    }
    if http != expected_http:
        raise DeliveryContractError("HTTP delivery policy differs from ADR-021/Issue #62")

    expected_pricing = {
        "sourceDate": "2026-08-07",
        "currency": "USD",
        "standardStoragePerGbMonth": 0.015,
        "classAPerMillion": 4.5,
        "classBPerMillion": 0.36,
        "internetEgressPerGb": 0,
        "monthlyFree": {
            "storageGbMonth": 10,
            "classAOperations": 1000000,
            "classBOperations": 10000000,
        },
        "scenarios": [
            {
                "id": "reference-mvp",
                "storageGbMonth": 1,
                "classAOperations": 500000,
                "classBOperations": 5000000,
                "estimatedMonthlyUsd": 0,
            },
            {
                "id": "mandatory-review-guardrail",
                "storageGbMonth": 100,
                "classAOperations": 5000000,
                "classBOperations": 50000000,
                "estimatedMonthlyUsd": 33.75,
            },
        ],
        "idleCostClaim": "target-zero-within-free-allowances-not-guaranteed",
    }
    if contract.get("pricing") != expected_pricing:
        raise DeliveryContractError("dated R2 cost model or review guardrail drifted")

    buckets: list[str] = []
    domains: list[str] = []
    workers: list[str] = []
    state_buckets: list[str] = []
    states: list[str] = []
    credentials: list[str] = []
    for environment in ENVIRONMENTS:
        record = contract["environments"][environment]
        variables = iac / record["variables"]
        backend = iac / record["backend"]
        expected = {
            "environment": environment,
            "release_bucket_name": record["bucket"],
            "data_domain": record["dataDomain"],
            "static_worker_name": record["worker"],
        }
        for name, value in expected.items():
            if _hcl_string(variables, name) != value:
                raise DeliveryContractError(f"{environment} {name} differs from contract")
        if _hcl_string_list(variables, "approved_origins") != record["approvedOrigins"]:
            raise DeliveryContractError(
                f"{environment} approved origins differ from contract"
            )
        if _hcl_string(backend, "bucket") != record["stateBucket"]:
            raise DeliveryContractError(f"{environment} state bucket differs from contract")
        if _hcl_string(backend, "key") != record["stateKey"]:
            raise DeliveryContractError(f"{environment} state key differs from contract")
        backend_text = backend.read_text(encoding="utf-8")
        if "endpoint" in backend_text:
            raise DeliveryContractError(
                f"{environment} backend endpoint must come from its protected account"
            )
        for fragment in ("encrypt                     = true", "use_lockfile                = true"):
            if fragment not in backend_text:
                raise DeliveryContractError(f"{environment} backend lacks {fragment.strip()}")
        buckets.append(record["bucket"])
        domains.append(record["dataDomain"])
        workers.append(record["worker"])
        state_buckets.append(record["stateBucket"])
        states.append(record["stateKey"])
        credentials.extend(
            record[name]
            for name in (
                "planCredentialScope",
                "applyCredentialScope",
                "stateCredentialScope",
            )
        )
    for values, label in (
        (buckets, "buckets"),
        (domains, "data domains"),
        (workers, "static Workers"),
        (state_buckets, "state buckets"),
        (states, "state keys"),
        (credentials, "credential scopes"),
    ):
        _assert_unique(values, label)

    main = (iac / "main.tf").read_text(encoding="utf-8")
    if main.count("prevent_destroy = true") < 7:
        raise DeliveryContractError("release resources need explicit deletion protection")
    for fragment in (
        'methods = ["GET", "HEAD"]',
        'headers = ["If-Match", "If-None-Match", "Range"]',
        'value     = "public, max-age=31536000, immutable"',
        'value     = "no-store"',
        'respect_strong_etags = true',
        'run_worker_first   = false',
    ):
        if fragment not in main:
            raise DeliveryContractError(f"missing delivery invariant: {fragment}")
    safety = contract.get("safety", {})
    expected_safety = {
        "candidateV7BytesUsed": False,
        "tarBytesUsed": False,
        "publicationAuthorized": False,
        "publicationRequiresIssue64Gate": True,
        "externalResourceMutationAuthorizedByRepositoryState": False,
        "dataUploadAuthoritySeparated": True,
    }
    if any(safety.get(name) != value for name, value in expected_safety.items()):
        raise DeliveryContractError("delivery safety/non-publication boundary drifted")
    prohibited = safety["prohibitedResourceTypes"]
    if any(re.search(rf'\bresource\s+"{re.escape(value)}"', main) for value in prohibited):
        raise DeliveryContractError("prohibited Cloudflare runtime/upload resource exists")
    if re.search(r"run_worker_first\s*=\s*true", main):
        raise DeliveryContractError("Worker business-logic routing is forbidden")
    for path in [*sorted((iac / "environments").glob("*.tfvars")), iac / "fixtures/static-site/index.html"]:
        relative = path.relative_to(root).as_posix()
        if FORBIDDEN_VALUE.search(path.read_text(encoding="utf-8")):
            raise DeliveryContractError(f"forbidden private or secret value: {relative}")
    return contract


def _walk(value: Any, path: tuple[str, ...] = ()) -> list[tuple[tuple[str, ...], Any]]:
    items = [(path, value)]
    if isinstance(value, dict):
        for key, child in value.items():
            items.extend(_walk(child, (*path, str(key))))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            items.extend(_walk(child, (*path, str(index))))
    return items


def validate_plan(plan_path: Path, output_path: Path | None = None) -> dict[str, Any]:
    plan = _strict_json(plan_path)
    if plan.get("format_version") is None:
        raise DeliveryContractError("OpenTofu JSON plan lacks format_version")
    findings: list[str] = []
    for path, value in _walk(plan):
        joined = ".".join(path)
        if SECRET_NAME.search(joined) and value not in (None, "", False, [], {}):
            findings.append(f"secret-like field has a value: {joined}")
        if isinstance(value, str) and re.search(
            r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|(?:api|secret)[_-]?token\s*[:=]",
            value,
            re.IGNORECASE,
        ):
            findings.append(f"secret-like value: {joined}")
    changes: list[dict[str, Any]] = []
    allowed_types = {
        "cloudflare_r2_bucket",
        "cloudflare_r2_bucket_cors",
        "cloudflare_r2_bucket_lifecycle",
        "cloudflare_r2_custom_domain",
        "cloudflare_ruleset",
        "cloudflare_workers_script",
    }
    for change in plan.get("resource_changes", []):
        resource_type = change.get("type")
        actions = change.get("change", {}).get("actions", [])
        address = change.get("address", "<unknown>")
        if resource_type not in allowed_types:
            findings.append(f"unapproved resource type: {resource_type}")
        if "delete" in actions:
            findings.append(f"destructive plan action: {address} {actions}")
        changes.append({"address": address, "actions": actions})
    if findings:
        raise DeliveryContractError("; ".join(sorted(findings)))
    summary = {
        "schemaVersion": 1,
        "planSha256": hashlib.sha256(plan_path.read_bytes()).hexdigest(),
        "resourceChanges": sorted(changes, key=lambda item: item["address"]),
        "secretScan": "passed",
        "destructiveChangeScan": "passed",
        "publicationAuthorized": False,
    }
    if output_path is not None:
        output_path.write_text(
            json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    return summary


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    repository = commands.add_parser("repository")
    repository.add_argument("--repository-root", type=Path, default=ROOT)
    plan = commands.add_parser("plan")
    plan.add_argument("--plan-json", type=Path, required=True)
    plan.add_argument("--summary", type=Path)
    arguments = parser.parse_args(argv)
    try:
        if arguments.command == "repository":
            validate_repository(arguments.repository_root.resolve())
        else:
            validate_plan(arguments.plan_json.resolve(), arguments.summary)
    except DeliveryContractError as error:
        print(f"ERROR: {error}")
        return 1
    print("Cloudflare delivery contract passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
