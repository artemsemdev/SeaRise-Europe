"""Inspect and compare checksum-pinned Copernicus DEM samples."""

from __future__ import annotations

import hashlib
import time
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import rasterio  # type: ignore[import-untyped]
from rasterio.warp import Resampling, reproject  # type: ignore[import-untyped]

from .contracts import ScienceContractError


def _digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def inspect_dem_sample(
    path: Path,
    terrain: Mapping[str, Any],
    instance_name: str,
) -> dict[str, Any]:
    """Validate source identity, grid semantics, and masks for one DEM tile."""
    try:
        expected = terrain["instances"][instance_name]
    except KeyError as exc:
        raise ScienceContractError(f"Unknown DEM instance: {instance_name}") from exc
    byte_size = path.stat().st_size
    digest = _digest(path)
    if byte_size != expected["sampleByteSize"] or digest != expected["sampleSha256"]:
        raise ScienceContractError(f"{instance_name} sample identity does not match contract")

    with rasterio.open(path) as dataset:
        if dataset.crs is None or dataset.crs.to_epsg() != 4326:
            raise ScienceContractError(f"Unexpected {instance_name} horizontal CRS")
        if dataset.tags().get("AREA_OR_POINT") != "Point":
            raise ScienceContractError(f"Unexpected {instance_name} pixel interpretation")
        if dataset.tags(ns="IMAGE_STRUCTURE").get("LAYOUT") != "COG":
            raise ScienceContractError(f"Unexpected {instance_name} storage layout")
        if dataset.count != 1 or dataset.dtypes != ("float32",):
            raise ScienceContractError(f"Unexpected {instance_name} band schema")
        if list(dataset.shape) != expected["sampleShape"]:
            raise ScienceContractError(f"Unexpected {instance_name} sample shape")

        latitude_spacing = abs(dataset.transform.e) * 3600
        longitude_spacing = dataset.transform.a * 3600
        if not np.isclose(latitude_spacing, expected["latitudeSpacingArcSeconds"]):
            raise ScienceContractError(f"Unexpected {instance_name} latitude spacing")
        if not np.isclose(
            longitude_spacing, expected["sampleLongitudeSpacingArcSeconds"]
        ):
            raise ScienceContractError(f"Unexpected {instance_name} longitude spacing")

        values = dataset.read(1, masked=True)
        return {
            "asset": expected["sampleAsset"],
            "sha256": digest,
            "byteSize": byte_size,
            "shape": list(dataset.shape),
            "pixelCount": dataset.width * dataset.height,
            "bounds": list(dataset.bounds),
            "horizontalCrs": str(dataset.crs),
            "verticalCrs": terrain["verticalCrs"],
            "units": terrain["verticalUnits"],
            "pixelInterpretation": dataset.tags()["AREA_OR_POINT"],
            "latitudeSpacingArcSeconds": latitude_spacing,
            "longitudeSpacingArcSeconds": longitude_spacing,
            "nodata": dataset.nodata,
            "maskedPixelCount": int(np.ma.count_masked(values)),
            "minimumMetres": float(values.min()),
            "maximumMetres": float(values.max()),
            "meanMetres": float(values.mean()),
            "blockShapes": [list(shape) for shape in dataset.block_shapes],
            "overviewFactors": dataset.overviews(1),
        }


def compare_dem_samples(
    glo30_path: Path,
    glo90_path: Path,
    terrain: Mapping[str, Any],
) -> dict[str, Any]:
    """Compare the same source window without treating either grid as truth."""
    glo30 = inspect_dem_sample(glo30_path, terrain, "GLO-30")
    glo90 = inspect_dem_sample(glo90_path, terrain, "GLO-90")
    with rasterio.open(glo30_path) as source, rasterio.open(glo90_path) as target:
        source_values = source.read(1)
        target_values = target.read(1)
        aligned = np.full(target.shape, np.nan, dtype=np.float32)
        started = time.perf_counter()
        reproject(
            source_values,
            aligned,
            src_transform=source.transform,
            src_crs=source.crs,
            dst_transform=target.transform,
            dst_crs=target.crs,
            resampling=Resampling.bilinear,
            dst_nodata=np.nan,
        )
        elapsed = time.perf_counter() - started

    valid = np.isfinite(aligned) & np.isfinite(target_values)
    difference = aligned[valid] - target_values[valid]
    absolute = np.abs(difference)
    return {
        "schemaVersion": 1,
        "window": "N52 E004",
        "comparison": "GLO-30 bilinear resampled to the GLO-90 native grid",
        "instances": {"GLO-30": glo30, "GLO-90": glo90},
        "metrics": {
            "validPixelCount": int(valid.sum()),
            "pixelCountRatioGlo30ToGlo90": glo30["pixelCount"] / glo90["pixelCount"],
            "sourceByteRatioGlo30ToGlo90": glo30["byteSize"] / glo90["byteSize"],
            "resampleWallSeconds": elapsed,
            "signedMeanDifferenceMetres": float(difference.mean()),
            "meanAbsoluteDifferenceMetres": float(absolute.mean()),
            "rootMeanSquareDifferenceMetres": float(np.sqrt(np.mean(difference**2))),
            "p95AbsoluteDifferenceMetres": float(np.percentile(absolute, 95)),
            "p99AbsoluteDifferenceMetres": float(np.percentile(absolute, 99)),
            "maximumAbsoluteDifferenceMetres": float(absolute.max()),
        },
        "decision": {
            "status": "pending-scientific-review",
            "reason": (
                "One source window and no independent vertical truth cannot establish "
                "the production DEM resolution."
            ),
        },
    }
