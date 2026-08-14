#!/usr/bin/env python3
"""Derive corrected local-only Phase 1 candidate inputs without rebuilding data."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
INVENTORY = ROOT / "contracts/candidate-completeness/v2/required-artifacts.json"
SHA256 = re.compile(r"^[0-9a-f]{64}$")
COMMIT = re.compile(r"^[0-9a-f]{40}$")


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return value


def _write(path: Path, value: object) -> None:
    path.write_bytes(_canonical(value))


def _rewrite_metadata(
    root: Path,
    *,
    source_authority: dict[str, Any],
    code_revision: str,
    generated_at: str,
    environment_lock_path: str,
    environment_lock_sha256: str,
    parameters_sha256: str,
    pipeline_identity_sha256: str,
) -> None:
    archive_sha256 = source_authority["archiveSha256"]
    members = source_authority["memberSha256"]
    for path in sorted((root / "stac/items").glob("*.json")):
        document = _json(path)
        properties = document["properties"]
        scenario = properties["searise:scenario"]
        properties["searise:source_archive_sha256"] = archive_sha256
        properties["searise:source_member_sha256"] = members[scenario]
        _write(path, document)

    architecture = _json(root / "evidence/architecture.json")
    architecture["codeRevision"] = code_revision
    architecture["generatedAt"] = generated_at
    _write(root / "evidence/architecture.json", architecture)

    quality = _json(root / "evidence/quality-summary.json")
    quality["generatedAt"] = generated_at
    evidence_paths = {
        "schema": "config/scenarios.json",
        "rights": "config/source-attribution.json",
        "hash": "receipts/build.json",
        "matrix": "config/scenarios.json",
        "projection-parity": "analysis/projections.parquet",
        "search-reconciliation": "search/settlement-browser-search-shards.receipt.json",
        "stac": "stac/catalog.json",
        "provenance": "receipts/build.json",
    }
    for validation in quality["validations"]:
        validation["evidencePath"] = evidence_paths[validation["category"]]
    _write(root / "evidence/quality-summary.json", quality)

    attribution = _json(root / "config/source-attribution.json")
    project = next(
        record
        for record in attribution["records"]
        if record["attributionId"] == "searise-europe-candidate-completeness-v1"
    )
    project["sourceSha256"] = _sha256(INVENTORY)
    _write(root / "config/source-attribution.json", attribution)

    receipt_path = root / "receipts/build.json"
    receipt = _json(receipt_path)
    receipt["buildId"] = f"build-phase-1-private-final-{code_revision[:12]}"
    receipt["codeRevision"] = code_revision
    receipt["startedAt"] = generated_at
    receipt["completedAt"] = generated_at
    receipt["environment"] = {
        "platform": "darwin",
        "architecture": "x86_64",
        "pythonVersion": "3.11.15",
        "lock": {
            "path": environment_lock_path,
            "sha256": environment_lock_sha256,
        },
    }
    receipt["parametersSha256"] = parameters_sha256
    receipt["tools"] = [
        {
            "name": "searise-pipeline",
            "version": "0.1.0",
            "identitySha256": pipeline_identity_sha256,
        }
    ]
    for output in receipt["outputs"]:
        output_path = root / output["path"]
        output["byteSize"] = output_path.stat().st_size
        output["sha256"] = _sha256(output_path)
    for source_receipt in receipt["sourceReceipts"]:
        source_receipt["sha256"] = _sha256(root / source_receipt["path"])
    _write(receipt_path, receipt)


def derive(args: argparse.Namespace) -> dict[str, object]:
    if not COMMIT.fullmatch(args.code_revision):
        raise ValueError("code revision must be a lowercase 40-character Git SHA")
    if not SHA256.fullmatch(args.pipeline_identity_sha256):
        raise ValueError("pipeline identity must be a lowercase SHA-256")
    if args.output_root.exists() or args.parameters_output.exists():
        raise FileExistsError("derived inputs and parameters are no-overwrite outputs")
    environment_lock_path = args.environment_lock.resolve().relative_to(ROOT).as_posix()
    inventory = _json(INVENTORY)["requiredArtifacts"][:51]
    expected = {item["path"] for item in inventory}
    observed = {
        path.relative_to(args.source_root).as_posix()
        for path in args.source_root.rglob("*")
        if path.is_file()
    }
    if any(path.is_symlink() for path in args.source_root.rglob("*")):
        raise ValueError("source input tree contains a symbolic link")
    if observed != expected:
        raise ValueError(
            "source input tree differs from the exact 51-artifact inventory"
        )

    source_authority = _json(args.source_authority)
    parameters = {
        "schemaVersion": 1,
        "operation": "derive-phase-1-private-final-candidate-inputs",
        "privacy": "local-only",
        "codeRevision": args.code_revision,
        "generatedAt": args.generated_at,
        "sourceAuthority": {
            "path": str(args.source_authority),
            "sha256": _sha256(args.source_authority),
        },
        "environmentLock": {
            "path": environment_lock_path,
            "sha256": _sha256(args.environment_lock),
        },
        "pipelineIdentitySha256": args.pipeline_identity_sha256,
        "sourceInputInventory": [
            {"path": path, "sha256": _sha256(args.source_root / path)}
            for path in sorted(observed)
        ],
    }
    args.parameters_output.parent.mkdir(parents=True, exist_ok=True)
    _write(args.parameters_output, parameters)
    try:
        shutil.copytree(
            args.source_root, args.output_root, copy_function=shutil.copyfile
        )
        _rewrite_metadata(
            args.output_root,
            source_authority=source_authority,
            code_revision=args.code_revision,
            generated_at=args.generated_at,
            environment_lock_path=environment_lock_path,
            environment_lock_sha256=_sha256(args.environment_lock),
            parameters_sha256=_sha256(args.parameters_output),
            pipeline_identity_sha256=args.pipeline_identity_sha256,
        )
    except Exception:
        shutil.rmtree(args.output_root, ignore_errors=True)
        args.parameters_output.unlink(missing_ok=True)
        raise
    return {
        "output": str(args.output_root),
        "artifactCount": len(observed),
        "parameters": str(args.parameters_output),
        "parametersSha256": _sha256(args.parameters_output),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--source-authority", type=Path, required=True)
    parser.add_argument("--code-revision", required=True)
    parser.add_argument("--generated-at", required=True)
    parser.add_argument("--environment-lock", type=Path, required=True)
    parser.add_argument("--pipeline-identity-sha256", required=True)
    parser.add_argument("--parameters-output", type=Path, required=True)
    return parser


def main() -> int:
    print(json.dumps(derive(_parser().parse_args()), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
