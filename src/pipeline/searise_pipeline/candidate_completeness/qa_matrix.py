"""Version-selected, fail-closed candidate QA routing authority."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, NoReturn

from .validator import CandidateContractError

REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
MATRIX_PATH = REPOSITORY_ROOT / "contracts/candidate-qa/v1/role-validator-matrix.json"
_EXPECTED_KEYS = {"schemaVersion", "matrixId", "candidateInventory", "routes"}
_ROUTE_KEYS = {"role", "mediaType", "contentEncoding", "validatorId"}
_VALIDATOR_ID = re.compile(r"[a-z][a-z0-9.-]{2,127}")


@dataclass(frozen=True, order=True)
class ArtifactSelector:
    role: str
    media_type: str
    content_encoding: str


@dataclass(frozen=True)
class ValidatorRoute:
    selector: ArtifactSelector
    validator_id: str


@dataclass(frozen=True)
class QaRoutingMatrix:
    matrix_id: str
    candidate_inventory: Path
    routes: tuple[ValidatorRoute, ...]


class _DuplicateKeyError(ValueError):
    pass


def _fail(code: str, message: str) -> NoReturn:
    raise CandidateContractError(code, message)


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateKeyError(f"duplicate object key: {key}")
        result[key] = value
    return result


def _load(path: Path, *, code: str) -> dict[str, Any]:
    try:
        document = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_strict_object,
            parse_constant=lambda value: (_ for _ in ()).throw(
                ValueError(f"non-standard JSON constant: {value}")
            ),
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        _fail(code, f"cannot read strict JSON object {path}: {exc}")
    if not isinstance(document, dict):
        _fail(code, "JSON root must be an object")
    return document


def _selector(value: Mapping[str, Any], *, code: str) -> ArtifactSelector:
    fields = (value.get("role"), value.get("mediaType"), value.get("contentEncoding"))
    if not all(isinstance(field, str) and field for field in fields):
        _fail(code, "artifact selector fields must be nonempty strings")
    return ArtifactSelector(fields[0], fields[1], fields[2])


def load_qa_routing_matrix(path: Path = MATRIX_PATH) -> QaRoutingMatrix:
    """Load the matrix and require exact coverage of its selected inventory."""
    document = _load(path, code="qa-matrix")
    if set(document) != _EXPECTED_KEYS or document.get("schemaVersion") != 1:
        _fail("qa-matrix", "matrix shape or schema version differs")
    matrix_id = document.get("matrixId")
    inventory_value = document.get("candidateInventory")
    if matrix_id != "phase-1-candidate-qa-role-validator-v1":
        _fail("qa-matrix", "matrix identity differs")
    if not isinstance(inventory_value, str) or Path(inventory_value).is_absolute():
        _fail("qa-matrix", "candidate inventory path must be repository-relative")
    inventory_path = REPOSITORY_ROOT / inventory_value
    expected_inventory = (
        REPOSITORY_ROOT / "contracts/candidate-completeness/v2/required-artifacts.json"
    )
    if inventory_path != expected_inventory:
        _fail("qa-matrix", "candidate inventory authority differs")

    raw_routes = document.get("routes")
    if not isinstance(raw_routes, list) or not raw_routes:
        _fail("qa-matrix", "routes must be a nonempty array")
    routes: list[ValidatorRoute] = []
    for raw in raw_routes:
        if not isinstance(raw, Mapping) or set(raw) != _ROUTE_KEYS:
            _fail("qa-matrix", "each route must have the exact supported shape")
        validator_id = raw.get("validatorId")
        if not isinstance(validator_id, str) or _VALIDATOR_ID.fullmatch(validator_id) is None:
            _fail("qa-matrix", "validator identity is invalid")
        routes.append(ValidatorRoute(_selector(raw, code="qa-matrix"), validator_id))
    selectors = [route.selector for route in routes]
    if selectors != sorted(selectors) or len(set(selectors)) != len(selectors):
        _fail("qa-matrix", "route selectors must be unique and sorted")

    inventory = _load(inventory_path, code="qa-inventory")
    artifacts = inventory.get("requiredArtifacts")
    if not isinstance(artifacts, list) or not all(isinstance(item, Mapping) for item in artifacts):
        _fail("qa-inventory", "required artifact inventory is invalid")
    expected = {_selector(item, code="qa-inventory") for item in artifacts}
    observed = set(selectors)
    if observed != expected:
        missing = sorted(expected - observed)
        unknown = sorted(observed - expected)
        _fail("qa-matrix-coverage", f"missing routes={missing}; unknown routes={unknown}")
    return QaRoutingMatrix(matrix_id, inventory_path, tuple(routes))
