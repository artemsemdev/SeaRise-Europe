"""Checksum-pinned, bounded validation of Brotli settlement search shards."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Mapping

from jsonschema import Draft202012Validator

from searise_pipeline.settlements.contract_semantics import (
    SettlementContractSemanticError,
    validate_settlement_search_shard_semantics,
)

from .qa_dispatch import ArtifactValidator, QaValidationOutcome, QaValidationRequest

REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
SETTLEMENT_SCHEMA = REPOSITORY_ROOT / "contracts/settlements/v4/search-artifact.schema.json"
_MAX_SEARCH_SHARD_BYTES = 256 * 1024 * 1024


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("search shard is not strict UTF-8 JSON") from exc
    if not isinstance(document, dict):
        raise ValueError("search shard JSON root is not an object")
    return document


def validate_search_document(document: Mapping[str, Any]) -> QaValidationOutcome:
    """Validate one decompressed v4 search shard with schema and semantics."""
    schema = _load_json(SETTLEMENT_SCHEMA)
    errors = sorted(
        Draft202012Validator(schema).iter_errors(document),
        key=lambda error: list(error.path),
    )
    if errors:
        return QaValidationOutcome("fail", "search-shard-schema", errors[0].message)
    try:
        validate_settlement_search_shard_semantics(document)
    except SettlementContractSemanticError as exc:
        return QaValidationOutcome("fail", "search-shard-semantics", str(exc))
    return QaValidationOutcome("pass", "search-shard-valid", "search shard contract is valid")


def search_shard_validator(
    *, brotli_path: Path, brotli_sha256: str, work_directory: Path
) -> ArtifactValidator:
    """Build a validator around one checksum-pinned Brotli executable."""

    def validate(request: QaValidationRequest) -> QaValidationOutcome:
        try:
            valid_tool = (
                brotli_path.is_file()
                and not brotli_path.is_symlink()
                and os.access(brotli_path, os.X_OK)
                and _sha256(brotli_path) == brotli_sha256
            )
        except OSError:
            valid_tool = False
        if not valid_tool:
            return QaValidationOutcome(
                "fail", "search-shard-tool", "Brotli validator identity differs"
            )
        work_directory.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(
            prefix="search-shard-", suffix=".json", dir=work_directory
        )
        path = Path(temporary)
        try:
            with os.fdopen(descriptor, "wb") as output:
                try:
                    completed = subprocess.run(
                        [
                            str(brotli_path),
                            "--decompress",
                            "--stdout",
                            str(request.artifact_path),
                        ],
                        stdout=output,
                        stderr=subprocess.PIPE,
                        check=False,
                        timeout=120,
                    )
                except (OSError, subprocess.TimeoutExpired):
                    return QaValidationOutcome(
                        "fail", "search-shard-decompression", "Brotli decoding failed"
                    )
            if completed.returncode != 0 or path.stat().st_size > _MAX_SEARCH_SHARD_BYTES:
                return QaValidationOutcome(
                    "fail", "search-shard-decompression", "Brotli output is invalid or oversized"
                )
            try:
                document = _load_json(path)
            except ValueError as exc:
                return QaValidationOutcome("fail", "search-shard-json", str(exc))
            outcome = validate_search_document(document)
            if outcome.status != "pass":
                return outcome
            context = request.candidate
            if (
                document.get("dataReleaseId") != context.data_release_id
                or document.get("dataProvenanceClass") != context.data_provenance_class
            ):
                return QaValidationOutcome(
                    "fail", "search-shard-binding", "search shard candidate binding differs"
                )
            expected_membership = request.artifact_path.name.removesuffix(
                ".codepoint-trie.json.br"
            )
            if document.get("catalogMembership") != expected_membership:
                return QaValidationOutcome(
                    "fail",
                    "search-shard-binding",
                    "search shard membership differs from its candidate path",
                )
            return outcome
        finally:
            try:
                path.unlink()
            except FileNotFoundError:
                pass

    return validate
