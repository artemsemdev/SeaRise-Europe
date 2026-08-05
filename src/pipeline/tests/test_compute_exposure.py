"""Regression tests for the prohibited legacy exposure operation."""

import ast
import inspect
from pathlib import Path

import pytest

from pipeline.compute_exposure import compute_binary_exposure
from searise_pipeline.science import ScienceContractError


def test_legacy_exposure_inputs_are_always_rejected(
    dem_tif: Path, slr_tif: Path, coastal_zone_geojson: Path, tmp_path: Path
) -> None:
    with pytest.raises(ScienceContractError, match="relative sea-level change"):
        compute_binary_exposure(
            dem_tif,
            slr_tif,
            coastal_zone_geojson,
            tmp_path / "blocked.tif",
        )


def test_no_opt_in_or_direct_relative_change_comparison_remains() -> None:
    signature = inspect.signature(compute_binary_exposure)
    source = inspect.getsource(compute_binary_exposure)
    tree = ast.parse(source)

    assert "allow_blocked_methodology" not in signature.parameters
    assert not any(isinstance(node, ast.Compare) for node in ast.walk(tree))
