"""Cross-field semantic validation for public settlement artifacts."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


class SettlementContractSemanticError(ValueError):
    """Raised when a schema-valid settlement artifact contradicts its semantics."""


def validate_settlement_search_shard_semantics(
    document: Mapping[str, Any],
) -> None:
    """Validate search-shard rules that JSON Schema cannot express."""

    records = document.get("documents", document.get("records"))
    if not isinstance(records, list) or document["recordCount"] != len(records):
        raise SettlementContractSemanticError(
            "search shard recordCount differs from records length"
        )
