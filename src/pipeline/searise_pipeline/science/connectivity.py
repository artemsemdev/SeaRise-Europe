"""Candidate ocean-connectivity filter defined by the geography contract."""

from __future__ import annotations

from collections import deque
from typing import Any, Mapping

import numpy as np
from numpy.typing import NDArray


def ocean_connected_cells(
    eligible: NDArray[np.bool_],
    ocean_seeds: NDArray[np.bool_],
    *,
    nodata: NDArray[np.bool_] | None = None,
    barriers: NDArray[np.bool_] | None = None,
    neighbourhood: int = 8,
) -> NDArray[np.bool_]:
    """Return eligible cells connected to a seed through eight neighbours.

    Nodata and explicit barriers are never traversable. The filter operates on
    the post-vertical, confidently exposed interval only; it does not alter
    the vertical interval and is not a hydrodynamic flood model.
    """
    if eligible.ndim != 2 or ocean_seeds.ndim != 2:
        raise ValueError("Connectivity inputs must be two-dimensional")
    if eligible.shape != ocean_seeds.shape:
        raise ValueError("Connectivity inputs must have identical shapes")
    if neighbourhood not in (4, 8):
        raise ValueError("Connectivity neighbourhood must be 4 or 8")
    blocked = np.zeros_like(eligible)
    for name, mask in (("nodata", nodata), ("barriers", barriers)):
        if mask is None:
            continue
        if mask.ndim != 2 or mask.shape != eligible.shape:
            raise ValueError(f"Connectivity {name} must match the eligible grid")
        blocked |= mask
    traversable = eligible & ~blocked
    if np.any(ocean_seeds & ~traversable):
        raise ValueError("Every ocean seed must be eligible and traversable")

    connected = np.zeros(eligible.shape, dtype=np.bool_)
    queue: deque[tuple[int, int]] = deque()
    for row, column in np.argwhere(ocean_seeds):
        connected[row, column] = True
        queue.append((int(row), int(column)))

    height, width = eligible.shape
    while queue:
        row, column = queue.popleft()
        for row_offset in (-1, 0, 1):
            for column_offset in (-1, 0, 1):
                if row_offset == 0 and column_offset == 0:
                    continue
                if neighbourhood == 4 and abs(row_offset) + abs(column_offset) != 1:
                    continue
                neighbour_row = row + row_offset
                neighbour_column = column + column_offset
                if not (0 <= neighbour_row < height and 0 <= neighbour_column < width):
                    continue
                if (
                    traversable[neighbour_row, neighbour_column]
                    and not connected[neighbour_row, neighbour_column]
                ):
                    connected[neighbour_row, neighbour_column] = True
                    queue.append((neighbour_row, neighbour_column))
    return connected


def connectivity_comparison(
    eligible: NDArray[np.bool_],
    ocean_seeds: NDArray[np.bool_],
    *,
    nodata: NDArray[np.bool_] | None = None,
    barriers: NDArray[np.bool_] | None = None,
    neighbourhood: int = 8,
) -> dict[str, int | float]:
    """Summarize cells removed as disconnected by the candidate rule."""
    blocked = np.zeros_like(eligible)
    if nodata is not None:
        blocked |= nodata
    if barriers is not None:
        blocked |= barriers
    traversable = eligible & ~blocked
    connected = ocean_connected_cells(
        eligible,
        ocean_seeds,
        nodata=nodata,
        barriers=barriers,
        neighbourhood=neighbourhood,
    )
    eligible_count = int(traversable.sum())
    connected_count = int(connected.sum())
    disconnected_count = eligible_count - connected_count
    return {
        "eligibleCellCount": eligible_count,
        "connectedCellCount": connected_count,
        "disconnectedCellCount": disconnected_count,
        "disconnectedFraction": (
            disconnected_count / eligible_count if eligible_count else 0.0
        ),
    }


def evaluate_connectivity_controls(
    document: Mapping[str, Any],
) -> dict[str, Any]:
    """Execute the independent symbolic control grids in a reviewed corpus."""
    neighbourhood = int(document["neighbourhood"])
    outcomes: list[dict[str, Any]] = []
    for control in document["controls"]:
        rows = control["grid"]
        expected_rows = control["expectedConnected"]
        if len({len(row) for row in rows}) != 1 or len(rows) != len(expected_rows):
            raise ValueError(f"Invalid connectivity control grid: {control['id']}")
        if any(len(row) != len(rows[0]) for row in expected_rows):
            raise ValueError(f"Invalid expected control grid: {control['id']}")

        symbols = np.array([list(row) for row in rows])
        eligible = np.isin(symbols, ("O", "L", "B"))
        seeds = symbols == "O"
        nodata = symbols == "N"
        barriers = symbols == "B"
        expected = np.array(
            [[value == "C" for value in row] for row in expected_rows],
            dtype=np.bool_,
        )
        actual = ocean_connected_cells(
            eligible,
            seeds,
            nodata=nodata,
            barriers=barriers,
            neighbourhood=neighbourhood,
        )
        outcomes.append(
            {
                "id": control["id"],
                "passed": bool(np.array_equal(actual, expected)),
                "connectedCellCount": int(actual.sum()),
            }
        )
    return {
        "count": len(outcomes),
        "passed": sum(item["passed"] for item in outcomes),
        "outcomes": outcomes,
    }
