from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

ROOT = Path(__file__).resolve().parents[4]
CONTRACT = ROOT / "contracts/release/v2"


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _validator(schema_name: str = "attribution.schema.json") -> Draft202012Validator:
    definitions = _read(CONTRACT / "defs.schema.json")
    selected = _read(CONTRACT / schema_name)
    registry = Registry().with_resources(
        (
            (definitions["$id"], Resource.from_contents(definitions)),
            (selected["$id"], Resource.from_contents(selected)),
        )
    )
    return Draft202012Validator(selected, registry=registry)


def test_v2_attribution_accepts_the_settlement_receipt_role() -> None:
    fixture = _read(CONTRACT / "fixtures/valid/attribution.json")
    _validator().validate(fixture)


def test_v2_attribution_still_fails_closed_on_unknown_roles_and_rights() -> None:
    fixture = _read(CONTRACT / "fixtures/valid/attribution.json")
    unknown = copy.deepcopy(fixture)
    unknown["records"][0]["appliesToRoles"].append("unknown-role")
    prohibited = copy.deepcopy(fixture)
    prohibited["records"][0]["redistribution"] = "unknown"
    assert list(_validator().iter_errors(unknown))
    assert list(_validator().iter_errors(prohibited))


def test_v2_build_receipt_accepts_settlement_receipt_output() -> None:
    fixture = _read(
        ROOT / "contracts/release/v1/fixtures/valid/build-receipt.json"
    )
    fixture["$schema"] = (
        "https://artemsemdev.github.io/SeaRise-Europe/contracts/"
        "release/v2/build-receipt.schema.json"
    )
    fixture["schemaVersion"] = "2.0.0"
    fixture["outputs"][0]["role"] = "settlement-search-receipt"
    fixture["outputs"][0]["mediaType"] = "application/json"
    validator = _validator("build-receipt.schema.json")
    validator.validate(fixture)

    unknown = copy.deepcopy(fixture)
    unknown["outputs"][0]["role"] = "unknown-role"
    assert list(validator.iter_errors(unknown))
