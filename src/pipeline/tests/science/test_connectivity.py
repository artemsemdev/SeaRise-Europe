"""Tests for the explicit eight-neighbour connectivity candidate."""

import numpy as np
import pytest

from searise_pipeline.science import connectivity_comparison, ocean_connected_cells


def test_diagonal_cells_connect_under_eight_neighbour_rule() -> None:
    eligible = np.array(
        [
            [True, False, False],
            [False, True, False],
            [False, False, True],
        ]
    )
    seeds = np.zeros_like(eligible)
    seeds[0, 0] = True

    connected = ocean_connected_cells(eligible, seeds)

    np.testing.assert_array_equal(connected, eligible)


def test_nodata_barrier_leaves_inland_basin_disconnected() -> None:
    eligible = np.array(
        [
            [True, True, False, False, False],
            [True, True, False, True, True],
            [False, False, False, True, True],
        ]
    )
    seeds = np.zeros_like(eligible)
    seeds[0, 0] = True

    report = connectivity_comparison(eligible, seeds)

    assert report == {
        "eligibleCellCount": 8,
        "connectedCellCount": 4,
        "disconnectedCellCount": 4,
        "disconnectedFraction": 0.5,
    }


def test_seed_must_be_eligible() -> None:
    eligible = np.zeros((2, 2), dtype=np.bool_)
    seeds = np.zeros_like(eligible)
    seeds[0, 0] = True

    with pytest.raises(ValueError, match="eligible"):
        ocean_connected_cells(eligible, seeds)
