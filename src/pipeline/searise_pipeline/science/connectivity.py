"""Candidate ocean-connectivity filter defined by the geography contract."""

from __future__ import annotations

from collections import deque

import numpy as np
from numpy.typing import NDArray


def ocean_connected_cells(
    eligible: NDArray[np.bool_],
    ocean_seeds: NDArray[np.bool_],
) -> NDArray[np.bool_]:
    """Return eligible cells connected to a seed through eight neighbours.

    False cells, including nodata encoded as ineligible, are barriers. This is
    the deterministic Phase 0 comparison candidate, not an approved flood
    model.
    """
    if eligible.ndim != 2 or ocean_seeds.ndim != 2:
        raise ValueError("Connectivity inputs must be two-dimensional")
    if eligible.shape != ocean_seeds.shape:
        raise ValueError("Connectivity inputs must have identical shapes")
    if np.any(ocean_seeds & ~eligible):
        raise ValueError("Every ocean seed must be an eligible cell")

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
                neighbour_row = row + row_offset
                neighbour_column = column + column_offset
                if not (0 <= neighbour_row < height and 0 <= neighbour_column < width):
                    continue
                if (
                    eligible[neighbour_row, neighbour_column]
                    and not connected[neighbour_row, neighbour_column]
                ):
                    connected[neighbour_row, neighbour_column] = True
                    queue.append((neighbour_row, neighbour_column))
    return connected


def connectivity_comparison(
    eligible: NDArray[np.bool_],
    ocean_seeds: NDArray[np.bool_],
) -> dict[str, int | float]:
    """Summarize cells removed as disconnected by the candidate rule."""
    connected = ocean_connected_cells(eligible, ocean_seeds)
    eligible_count = int(eligible.sum())
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
