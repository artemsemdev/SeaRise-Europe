"""Lossless three-band Cloud Optimized GeoTIFF output for AR6 projections."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import rasterio
from rasterio.transform import from_origin
from rio_cogeo.cogeo import cog_validate

from searise_pipeline.science.contracts import ScienceContractError

from .model import RegionalLayer


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class CogEvidence:
    """Deterministic identity and source-domain statistics for one COG."""

    path: str
    byte_size: int
    sha256: str
    valid_cells: int
    nodata_cells: int


def write_analysis_cog(
    layer: RegionalLayer,
    path: Path,
    *,
    contract: Mapping[str, Any],
) -> CogEvidence:
    """Write exact integer millimetres; no scientific resampling is performed."""
    grid = contract["grid"]
    values = contract["values"]
    cog = contract["artifacts"]["cog"]
    path.parent.mkdir(parents=True, exist_ok=True)
    bands = np.stack(
        [np.flipud(layer.lower_mm), np.flipud(layer.central_mm), np.flipud(layer.upper_mm)]
    )
    with rasterio.open(
        path,
        "w",
        driver="COG",
        width=grid["width"],
        height=grid["height"],
        count=3,
        dtype="int16",
        crs=grid["crs"],
        transform=from_origin(
            grid["bounds"][0],
            grid["bounds"][3],
            grid["nativeResolutionDegrees"],
            grid["nativeResolutionDegrees"],
        ),
        nodata=values["nodata"],
        blocksize=cog["blockSize"],
        compress=cog["compression"],
        predictor=cog["predictor"],
        overview_resampling=cog["overviewResampling"],
    ) as dataset:
        dataset.write(bands)
        dataset.descriptions = tuple(cog["bands"])
        dataset.update_tags(
            BASELINE=values["baseline"],
            HORIZON=str(layer.horizon),
            NATIVE_RESOLUTION_DEGREES=str(grid["nativeResolutionDegrees"]),
            SCALE_TO_METRES=str(values["scaleToMetres"]),
            SCENARIO=layer.scenario,
            UNITS=values["storageUnits"],
        )
    valid, errors, warnings = cog_validate(path, strict=True, quiet=True)
    if not valid or errors or warnings:
        raise ScienceContractError(
            f"Generated AR6 COG is invalid: errors={errors}, warnings={warnings}"
        )
    valid_cells = int(layer.valid.sum())
    return CogEvidence(
        path=f"analysis/{layer.scenario}/{layer.horizon}.tif",
        byte_size=path.stat().st_size,
        sha256=_sha256(path),
        valid_cells=valid_cells,
        nodata_cells=int(layer.valid.size - valid_cells),
    )


def validate_analysis_cog(
    path: Path,
    layer: RegionalLayer,
    *,
    contract: Mapping[str, Any],
) -> None:
    """Prove structural and bit-exact agreement with the source arrays."""
    valid, errors, warnings = cog_validate(path, strict=True, quiet=True)
    if not valid or errors or warnings:
        raise ScienceContractError("AR6 analysis COG fails structural validation")
    grid = contract["grid"]
    values = contract["values"]
    with rasterio.open(path) as dataset:
        if (
            dataset.count != 3
            or dataset.width != grid["width"]
            or dataset.height != grid["height"]
            or dataset.dtypes != ("int16", "int16", "int16")
            or dataset.nodata != values["nodata"]
            or dataset.descriptions != tuple(contract["artifacts"]["cog"]["bands"])
        ):
            raise ScienceContractError("AR6 analysis COG schema differs from the contract")
        expected = np.stack(
            [
                np.flipud(layer.lower_mm),
                np.flipud(layer.central_mm),
                np.flipud(layer.upper_mm),
            ]
        )
        if not np.array_equal(dataset.read(), expected):
            raise ScienceContractError("AR6 analysis COG values differ from source millimetres")
