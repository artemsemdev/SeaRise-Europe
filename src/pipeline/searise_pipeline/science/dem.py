"""Inspect and compare checksum-pinned Copernicus DEM samples."""

from __future__ import annotations

import hashlib
import time
from contextlib import ExitStack
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import rasterio  # type: ignore[import-untyped]
from rasterio.io import MemoryFile  # type: ignore[import-untyped]
from rasterio.warp import Resampling, reproject  # type: ignore[import-untyped]

from .contracts import ScienceContractError

QUALITY_LAYER_NAMES = ("EDM", "FLM", "HEM", "WBM")
HEIGHT_ERROR_SENTINEL = -32767.0
ALLOWED_QUALITY_CODES = {
    "EDM": frozenset(range(14)),
    "FLM": frozenset((*range(10), 100, 101, 102)),
    "WBM": frozenset(range(4)),
}


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
        if not np.isclose(longitude_spacing, expected["sampleLongitudeSpacingArcSeconds"]):
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


def _aligned_layer(path: Path, dem: rasterio.io.DatasetReader, name: str) -> np.ndarray:
    with rasterio.open(path) as dataset:
        if dataset.count != 1 or dataset.shape != dem.shape:
            raise ScienceContractError(f"{name} grid does not match DEM shape")
        if dataset.crs != dem.crs or dataset.transform != dem.transform:
            raise ScienceContractError(f"{name} grid does not align with DEM")
        if dataset.tags().get("AREA_OR_POINT") != "Point":
            raise ScienceContractError(f"Unexpected {name} pixel interpretation")
        values = np.asarray(dataset.read(1))
    if name in {"EDM", "FLM", "WBM"} and values.dtype != np.uint8:
        raise ScienceContractError(f"Unexpected {name} data type")
    if name == "HEM" and values.dtype != np.float32:
        raise ScienceContractError("Unexpected HEM data type")
    return values


def _value_counts(values: np.ndarray) -> dict[str, int]:
    unique, counts = np.unique(values, return_counts=True)
    return {str(int(value)): int(count) for value, count in zip(unique, counts)}


def _validate_quality_codes(name: str, values: np.ndarray) -> None:
    observed = {int(value) for value in np.unique(values)}
    unexpected = observed - ALLOWED_QUALITY_CODES[name]
    if unexpected:
        codes = ", ".join(str(value) for value in sorted(unexpected))
        raise ScienceContractError(f"Unexpected {name} quality codes: {codes}")


def _lossless_class_bytes(
    dem: rasterio.io.DatasetReader,
    elevations: np.ndarray,
    land: np.ndarray,
) -> int:
    classes = ((elevations <= 2.0) & land).astype(np.uint8)
    profile = {
        "driver": "GTiff",
        "width": dem.width,
        "height": dem.height,
        "count": 1,
        "dtype": "uint8",
        "crs": dem.crs,
        "transform": dem.transform,
        "tiled": True,
        "blockxsize": 512,
        "blockysize": 512,
        "compress": "DEFLATE",
        "predictor": 1,
    }
    with MemoryFile() as memory:
        with memory.open(**profile) as output:
            output.write(classes, 1)
        return len(memory.read())


def inspect_dem_window(paths: Mapping[str, Path]) -> dict[str, Any]:
    """Inspect one DEM and all quality masks required by the terrain decision."""
    required = {"DEM", *QUALITY_LAYER_NAMES}
    if set(paths) != required:
        missing = ", ".join(sorted(required - set(paths)))
        raise ScienceContractError(f"DEM window is missing required layers: {missing}")
    identities = {
        name: {
            "asset": path.name,
            "byteSize": path.stat().st_size,
            "sha256": _digest(path),
        }
        for name, path in paths.items()
    }
    with rasterio.open(paths["DEM"]) as dem:
        if dem.count != 1 or dem.dtypes != ("float32",):
            raise ScienceContractError("Unexpected DEM band schema")
        if dem.crs is None or dem.crs.to_epsg() != 4326:
            raise ScienceContractError("Unexpected DEM horizontal CRS")
        if dem.tags().get("AREA_OR_POINT") != "Point":
            raise ScienceContractError("Unexpected DEM pixel interpretation")
        elevations = dem.read(1)
        layers = {name: _aligned_layer(paths[name], dem, name) for name in QUALITY_LAYER_NAMES}
        for name in ("EDM", "FLM", "WBM"):
            _validate_quality_codes(name, layers[name])
        land = layers["WBM"] == 0
        invalid_negative_error = (layers["HEM"] < 0) & (layers["HEM"] != HEIGHT_ERROR_SENTINEL)
        if np.any(invalid_negative_error):
            raise ScienceContractError("Unexpected negative HEM values")
        valid_error = np.isfinite(layers["HEM"]) & (layers["HEM"] >= 0)
        valid_land_error = land & valid_error
        height_error = layers["HEM"][valid_land_error]
        if not height_error.size:
            raise ScienceContractError("DEM window has no valid land HEM samples")
        percentiles = np.percentile(height_error, (50, 90, 95, 99))
        return {
            "assets": identities,
            "grid": {
                "shape": list(dem.shape),
                "horizontalCrs": str(dem.crs),
                "pixelInterpretation": dem.tags()["AREA_OR_POINT"],
                "latitudeSpacingArcSeconds": abs(dem.transform.e) * 3600,
                "longitudeSpacingArcSeconds": dem.transform.a * 3600,
                "pixelCount": dem.width * dem.height,
            },
            "elevation": {
                "minimumMetres": float(elevations.min()),
                "maximumMetres": float(elevations.max()),
                "negativePixelCount": int((elevations < 0).sum()),
            },
            "quality": {
                "editingMaskCounts": _value_counts(layers["EDM"]),
                "fillingMaskCounts": _value_counts(layers["FLM"]),
                "waterBodyMaskCounts": _value_counts(layers["WBM"]),
                "shorelineEditedPixelCount": int((layers["EDM"] == 11).sum()),
                "voidPixelCount": int(((layers["EDM"] == 0) | (layers["FLM"] == 0)).sum()),
                "uneditedUnfilledLandPixelCount": int(
                    ((layers["EDM"] == 1) & (layers["FLM"] == 2) & land).sum()
                ),
                "editedOrFilledLandPixelCount": int(
                    ((layers["FLM"] != 0) & (layers["FLM"] != 2) & land).sum()
                ),
                "heightError": {
                    "sentinelPixelCount": int((~valid_error).sum()),
                    "validLandPixelCount": int(valid_land_error.sum()),
                    "meanSigmaMetres": float(height_error.mean()),
                    "p50SigmaMetres": float(percentiles[0]),
                    "p90SigmaMetres": float(percentiles[1]),
                    "p95SigmaMetres": float(percentiles[2]),
                    "p99SigmaMetres": float(percentiles[3]),
                    "maximumSigmaMetres": float(height_error.max()),
                },
            },
            "delivery": {
                "losslessLandElevationClass2mGeoTiffBytes": _lossless_class_bytes(
                    dem, elevations, land
                )
            },
        }


def compare_dem_windows(
    glo30_paths: Mapping[str, Path],
    glo90_paths: Mapping[str, Path],
) -> dict[str, Any]:
    """Compare representative quality-aware GLO-30 and GLO-90 windows."""
    glo30 = inspect_dem_window(glo30_paths)
    glo90 = inspect_dem_window(glo90_paths)
    with ExitStack() as stack:
        source = stack.enter_context(rasterio.open(glo30_paths["DEM"]))
        target = stack.enter_context(rasterio.open(glo90_paths["DEM"]))
        source_water = stack.enter_context(rasterio.open(glo30_paths["WBM"]))
        target_water = stack.enter_context(rasterio.open(glo90_paths["WBM"]))
        source_values = source.read(1)
        target_values = target.read(1)
        aligned = np.full(target.shape, np.nan, dtype=np.float32)
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
        source_water_nearest = np.zeros(target.shape, dtype=np.uint8)
        reproject(
            source_water.read(1),
            source_water_nearest,
            src_transform=source_water.transform,
            src_crs=source_water.crs,
            dst_transform=target_water.transform,
            dst_crs=target_water.crs,
            resampling=Resampling.nearest,
        )
        source_land_presence = np.zeros(target.shape, dtype=np.uint8)
        reproject(
            (source_water.read(1) == 0).astype(np.uint8),
            source_land_presence,
            src_transform=source_water.transform,
            src_crs=source_water.crs,
            dst_transform=target_water.transform,
            dst_crs=target_water.crs,
            resampling=Resampling.max,
        )
        target_water_values = target_water.read(1)

    common_land = (
        np.isfinite(aligned)
        & np.isfinite(target_values)
        & (source_water_nearest == 0)
        & (target_water_values == 0)
    )
    difference = aligned[common_land] - target_values[common_land]
    absolute = np.abs(difference)
    if not difference.size:
        raise ScienceContractError("DEM windows have no common valid land samples")
    return {
        "GLO-30": glo30,
        "GLO-90": glo90,
        "comparison": {
            "validCommonLandPixelCount": int(common_land.sum()),
            "signedMeanDifferenceMetres": float(difference.mean()),
            "meanAbsoluteDifferenceMetres": float(absolute.mean()),
            "rootMeanSquareDifferenceMetres": float(np.sqrt(np.mean(difference**2))),
            "p95AbsoluteDifferenceMetres": float(np.percentile(absolute, 95)),
            "p99AbsoluteDifferenceMetres": float(np.percentile(absolute, 99)),
            "maximumAbsoluteDifferenceMetres": float(absolute.max()),
            "glo30LandPresenceLostByGlo90WaterMaskCells": int(
                ((source_land_presence == 1) & (target_water_values != 0)).sum()
            ),
            "thresholdClassDisagreement": {
                str(threshold): int(
                    (((aligned <= threshold) != (target_values <= threshold)) & common_land).sum()
                )
                for threshold in (0, 1, 2, 5)
            },
        },
    }
