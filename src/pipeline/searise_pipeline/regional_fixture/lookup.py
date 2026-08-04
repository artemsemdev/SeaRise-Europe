"""Deterministic Python lookup for the shared regional-fixture contract."""

from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Mapping


class FixtureContractError(ValueError):
    """The fixture is malformed or would allow an ambiguous lookup."""


class DomainState(str, Enum):
    MODELED_EXPOSURE_DETECTED = "modeled-exposure-detected"
    NO_MODELED_EXPOSURE_DETECTED = "no-modeled-exposure-detected"
    DATA_UNAVAILABLE = "data-unavailable"
    OUT_OF_SCOPE = "out-of-scope"
    UNSUPPORTED_GEOGRAPHY = "unsupported-geography"


@dataclass(frozen=True)
class Cell:
    row: int
    column: int


@dataclass(frozen=True)
class LookupResult:
    state: DomainState
    cell: Cell | None


@dataclass(frozen=True)
class Grid:
    width: int
    height: int
    west: float
    south: float
    east: float
    north: float
    longitude_convention: str
    edge_rule: str

    def cell(self, longitude: float, latitude: float) -> Cell | None:
        """Map a point to a north-up grid using the contract's half-open edges."""
        if self.longitude_convention != "minus-180-to-180":
            raise FixtureContractError("unsupported longitude convention")
        if not -180.0 <= longitude <= 180.0:
            raise FixtureContractError("longitude is outside [-180, 180]")
        if not (self.west <= longitude < self.east):
            return None
        if not (self.south < latitude <= self.north):
            return None

        column = int((longitude - self.west) / ((self.east - self.west) / self.width))
        row = int((self.north - latitude) / ((self.north - self.south) / self.height))
        if row == self.height:  # Defensive guard against floating-point drift.
            return None
        return Cell(row=row, column=column)


@dataclass(frozen=True)
class Layer:
    status: str
    values: bytes | None
    blocked_by: tuple[str, ...]


@dataclass(frozen=True)
class RegionalFixture:
    fixture_id: str
    grid: Grid
    support_mask: bytes
    coastal_mask: bytes
    layers: Mapping[str, Layer]

    @classmethod
    def load(cls, path: Path) -> "RegionalFixture":
        raw = json.loads(path.read_text(encoding="utf-8"))
        if raw.get("schemaVersion") != 1:
            raise FixtureContractError("unsupported fixture schemaVersion")
        grid = Grid(**raw["grid"])
        if grid.edge_rule != "west-north-inclusive-east-south-exclusive":
            raise FixtureContractError("unsupported grid edge rule")
        cell_count = grid.width * grid.height
        support = _decode_array(raw["supportMask"], cell_count, "supportMask")
        coastal = _decode_array(raw["coastalMask"], cell_count, "coastalMask")
        if any(value not in (0, 1) for value in support + coastal):
            raise FixtureContractError("support and coastal masks must contain only 0 or 1")
        if any(coastal[index] and not support[index] for index in range(cell_count)):
            raise FixtureContractError("coastalMask must be a subset of supportMask")

        layers: dict[str, Layer] = {}
        for key, item in raw["layers"].items():
            status = item["status"]
            values = (
                _decode_array(item["values"], cell_count, f"layers.{key}.values")
                if status == "ready"
                else None
            )
            blocked_by = tuple(item.get("blockedBy", []))
            if status == "ready" and any(value not in (0, 1, 255) for value in values or b""):
                raise FixtureContractError(f"layer {key} contains an invalid class")
            if status == "blocked" and ("values" in item or not blocked_by):
                raise FixtureContractError(f"blocked layer {key} needs reasons and no values")
            if status not in ("ready", "blocked"):
                raise FixtureContractError(f"layer {key} has unsupported status {status}")
            layers[key] = Layer(status=status, values=values, blocked_by=blocked_by)

        return cls(raw["fixtureId"], grid, support, coastal, layers)

    def lookup(
        self, longitude: float, latitude: float, scenario: str, horizon: int
    ) -> LookupResult:
        cell = self.grid.cell(longitude, latitude)
        if cell is None:
            return LookupResult(DomainState.UNSUPPORTED_GEOGRAPHY, None)
        index = cell.row * self.grid.width + cell.column
        if self.support_mask[index] == 0:
            return LookupResult(DomainState.UNSUPPORTED_GEOGRAPHY, cell)
        if self.coastal_mask[index] == 0:
            return LookupResult(DomainState.OUT_OF_SCOPE, cell)

        key = f"{scenario}/{horizon}"
        layer = self.layers.get(key)
        if layer is None or layer.status == "blocked" or layer.values is None:
            return LookupResult(DomainState.DATA_UNAVAILABLE, cell)
        value = layer.values[index]
        states = {
            0: DomainState.NO_MODELED_EXPOSURE_DETECTED,
            1: DomainState.MODELED_EXPOSURE_DETECTED,
            255: DomainState.DATA_UNAVAILABLE,
        }
        return LookupResult(states[value], cell)


def _decode_array(raw: Mapping[str, Any], expected_length: int, label: str) -> bytes:
    if raw.get("encoding") != "base64-uint8-row-major":
        raise FixtureContractError(f"{label} has unsupported encoding")
    try:
        values = base64.b64decode(raw["data"], validate=True)
    except (KeyError, ValueError) as exc:
        raise FixtureContractError(f"{label} is not valid base64") from exc
    if len(values) != expected_length:
        raise FixtureContractError(f"{label} length does not match the grid")
    digest = hashlib.sha256(values).hexdigest()
    if digest != raw.get("sha256"):
        raise FixtureContractError(f"{label} SHA-256 mismatch")
    return values
