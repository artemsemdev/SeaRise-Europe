"""Deterministic evidence receipts for vertical-reference transformations."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from jsonschema import Draft202012Validator, FormatChecker  # type: ignore[import-untyped]

from .contracts import ScienceContractError


def _default_schema_path() -> Path:
    return Path(__file__).parents[2] / "science" / "vertical-transformation-receipt.schema.json"


def _format_error(error: Any) -> str:
    location = ".".join(str(part) for part in error.absolute_path) or "<root>"
    return f"{location}: {error.message}"


def validate_vertical_receipt(
    receipt: Mapping[str, Any], schema_path: Path | None = None
) -> None:
    """Validate one receipt without inferring or filling missing evidence."""
    path = schema_path or _default_schema_path()
    try:
        schema = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ScienceContractError(f"Cannot read vertical receipt schema: {exc}") from exc
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    errors = sorted(validator.iter_errors(receipt), key=lambda item: list(item.path))
    if errors:
        details = "; ".join(_format_error(error) for error in errors)
        raise ScienceContractError(f"Invalid vertical transformation receipt: {details}")


def canonical_vertical_receipt_bytes(receipt: Mapping[str, Any]) -> bytes:
    """Return stable UTF-8 JSON bytes after complete schema validation."""
    validate_vertical_receipt(receipt)
    try:
        text = json.dumps(
            receipt,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as exc:
        raise ScienceContractError(f"Vertical receipt is not canonical JSON: {exc}") from exc
    return (text + "\n").encode("utf-8")


def vertical_receipt_sha256(receipt: Mapping[str, Any]) -> str:
    """Hash the canonical receipt rather than source-file formatting."""
    return hashlib.sha256(canonical_vertical_receipt_bytes(receipt)).hexdigest()


def load_vertical_receipt(path: Path) -> Mapping[str, Any]:
    """Read and validate a receipt from disk."""
    try:
        receipt = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ScienceContractError(f"Cannot read vertical transformation receipt: {exc}") from exc
    if not isinstance(receipt, dict):
        raise ScienceContractError("Vertical transformation receipt must be an object")
    validate_vertical_receipt(receipt)
    return receipt


def assert_vertical_receipt_publishable(receipt: Mapping[str, Any]) -> None:
    """Reject receipts that retain a blocker or incomplete independent evidence."""
    validate_vertical_receipt(receipt)
    required_checks = ("automatedTests", "independentReview", "crossEnvironment", "basinControls")
    incomplete = [
        check for check in required_checks if receipt["validation"][check] != "passed"
    ]
    blockers = [str(item["id"]) for item in receipt["blockers"]]
    if receipt["status"] != "publishable" or blockers or incomplete:
        details = blockers + incomplete
        raise ScienceContractError(
            "Vertical transformation receipt is not publishable: " + ", ".join(details)
        )
