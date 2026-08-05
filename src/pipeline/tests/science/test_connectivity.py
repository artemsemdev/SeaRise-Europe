"""Tests for the explicit eight-neighbour connectivity candidate."""

import json
from pathlib import Path

import numpy as np
import pytest

from searise_pipeline.science import (
    connectivity_comparison,
    evaluate_connectivity_controls,
    ocean_connected_cells,
)

CONTRACT_DIR = Path(__file__).parents[2] / "science"


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


def test_nodata_and_quality_masks_are_not_traversed() -> None:
    eligible = np.ones((3, 3), dtype=np.bool_)
    seeds = np.zeros_like(eligible)
    seeds[0, 0] = True
    nodata = np.zeros_like(eligible)
    nodata[1, :] = True
    barriers = np.zeros_like(eligible)
    barriers[0, 2] = True

    connected = ocean_connected_cells(
        eligible,
        seeds,
        nodata=nodata,
        barriers=barriers,
    )

    np.testing.assert_array_equal(
        connected,
        np.array(
            [
                [True, True, False],
                [False, False, False],
                [False, False, False],
            ]
        ),
    )


def test_four_neighbour_rule_rejects_diagonal_connection() -> None:
    eligible = np.eye(3, dtype=np.bool_)
    seeds = np.zeros_like(eligible)
    seeds[0, 0] = True

    connected = ocean_connected_cells(eligible, seeds, neighbourhood=4)

    assert int(connected.sum()) == 1


def test_independent_control_corpus_passes() -> None:
    document = json.loads(
        (CONTRACT_DIR / "connectivity-controls.json").read_text(encoding="utf-8")
    )

    report = evaluate_connectivity_controls(document)

    assert report["passed"] == report["count"] == 9
