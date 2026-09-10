"""Focused tests for the read-only European raster service."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import struct
import sys
import zlib
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
from rasterio.warp import transform, transform_bounds

ROOT = Path(__file__).resolve().parents[4]
SERVICE_PATH = ROOT / "scripts" / "atlas" / "europe_raster_service.py"
SPEC = importlib.util.spec_from_file_location("europe_raster_service", SERVICE_PATH)
assert SPEC is not None and SPEC.loader is not None
SERVICE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = SERVICE
SPEC.loader.exec_module(SERVICE)
Point = tuple[float, float]


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _make_data_root(root: Path) -> tuple[Path, tuple[Point, ...]]:
    """Create one tiny native grid shared by all six manifest layers."""
    x, y = transform("EPSG:4326", "EPSG:3035", [12.3155], [45.4408])
    raster = root / "rasters" / "venice.tif"
    raster.parent.mkdir(parents=True)
    values = np.array([[-9999.0, 0.0, 1.25]], dtype=np.float32)
    affine = from_origin(x[0] - 37.5, y[0] + 12.5, 25, 25)
    with rasterio.open(
        raster,
        "w",
        driver="GTiff",
        width=3,
        height=1,
        count=1,
        dtype="float32",
        crs="EPSG:3035",
        transform=affine,
        nodata=-9999,
    ) as dataset:
        dataset.write(values, 1)

    with rasterio.open(raster) as dataset:
        bounds = transform_bounds("EPSG:3035", "EPSG:4326", *dataset.bounds)
    source = {
        "file": "rasters/venice.tif",
        "bytes": raster.stat().st_size,
        "sha256": _digest(raster),
        "bounds": list(bounds),
        "overviews": [],
    }
    layers = [
        {
            "scenario": "ssp585",
            "year": year,
            "protection": protection,
            "inputs": [dict(source)],
        }
        for year in (2030, 2050, 2100)
        for protection in ("unprotected", "protected")
    ]
    (root / "manifest.json").write_text(
        json.dumps(
            {
                "version": 2,
                "scenario": "ssp585",
                "condition": "high-tide",
                "layers": layers,
            }
        )
    )
    centers_x = [x[0] - 25, x[0], x[0] + 25]
    longitudes, latitudes = transform(
        "EPSG:3035", "EPSG:4326", centers_x, [y[0], y[0], y[0]]
    )
    return raster, tuple(zip(longitudes, latitudes))


def _slippy_tile(lon: float, lat: float, zoom: int) -> tuple[int, int, int]:
    scale = 2**zoom
    x = int((lon + 180) / 360 * scale)
    y = int(
        (1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * scale
    )
    return zoom, x, y


def _alpha_count(png: bytes) -> int:
    position = 8
    compressed = bytearray()
    while position < len(png):
        length = struct.unpack("!I", png[position : position + 4])[0]
        kind = png[position + 4 : position + 8]
        content = png[position + 8 : position + 8 + length]
        position += 12 + length
        if kind == b"IDAT":
            compressed.extend(content)
    rows = zlib.decompress(compressed)
    return sum(
        rows[row * 1025 + 1 + pixel * 4 + 3] > 0
        for row in range(256)
        for pixel in range(256)
    )


@pytest.fixture()
def atlas_fixture(tmp_path: Path) -> tuple[object, Path, tuple[Point, ...]]:
    raster, points = _make_data_root(tmp_path)
    return SERVICE.Atlas(tmp_path), raster, points


def test_manifest_hashes_a_shared_raster_once_and_rejects_tampering(
    tmp_path: Path,
) -> None:
    raster, _ = _make_data_root(tmp_path)
    with patch.object(
        SERVICE, "stream_digest", wraps=SERVICE.stream_digest
    ) as stream_digest:
        SERVICE.Atlas(tmp_path)
    assert stream_digest.call_count == 1

    raster.write_bytes(raster.read_bytes() + b"tampered")
    with pytest.raises(ValueError, match="size differs"):
        SERVICE.Atlas(tmp_path)


def test_manifest_rejects_paths_outside_the_data_root(tmp_path: Path) -> None:
    _, _ = _make_data_root(tmp_path)
    manifest_path = tmp_path / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["layers"][0]["inputs"][0]["file"] = "../outside.tif"
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="metadata is invalid"):
        SERVICE.Atlas(tmp_path)


def test_inspection_preserves_unknown_zero_and_flooded(
    atlas_fixture: tuple[object, Path, tuple[Point, ...]],
) -> None:
    atlas, _, points = atlas_fixture
    unknown = atlas.inspect(*points[0], "unprotected")
    zero = atlas.inspect(*points[1], "unprotected")
    flooded = atlas.inspect(*points[2], "unprotected")

    assert [(item["status"], item["depthMeters"]) for item in unknown["results"]] == [
        ("unknown", None)
    ] * 3
    assert [(item["status"], item["depthMeters"]) for item in zero["results"]] == [
        ("zero", 0.0)
    ] * 3
    assert [
        (item["status"], item["depthMeters"]) for item in flooded["results"]
    ] == [("flooded", 1.25)] * 3


def test_tile_counts_valid_zero_separately_from_visible_flooding(
    atlas_fixture: tuple[object, Path, tuple[Point, ...]],
) -> None:
    atlas, _, points = atlas_fixture
    zoom, x, y = _slippy_tile(*points[1], 18)
    png, valid, flooded = atlas.tile(2030, "unprotected", zoom, x, y)

    assert png.startswith(b"\x89PNG\r\n\x1a\n")
    assert valid > flooded > 0
    assert _alpha_count(png) == flooded


def test_http_surface_exposes_only_health_inspection_and_tiles(
    atlas_fixture: tuple[object, Path, tuple[Point, ...]],
) -> None:
    atlas, _, points = atlas_fixture
    handler_type = SERVICE.handler_for(atlas)
    responses: list[tuple[object, ...]] = []
    handler = object.__new__(handler_type)
    handler.respond = lambda *response: responses.append(response)
    handler.log_error = lambda *_: None

    handler.path = "/health"
    handler.do_GET()
    assert responses[-1][0] == 200
    assert json.loads(responses[-1][1]) == {
        "ready": True,
        "version": 2,
        "layers": 6,
        "assets": 6,
    }
    assert "fingerprint" not in json.loads(responses[-1][1])

    lon, lat = points[1]
    handler.path = f"/inspect?lon={lon}&lat={lat}&defenses=unprotected"
    handler.do_GET()
    assert responses[-1][0] == 200
    assert json.loads(responses[-1][1])["results"][0]["status"] == "zero"

    zoom, x, y = _slippy_tile(lon, lat, 18)
    handler.path = f"/tiles/2030/unprotected/{zoom}/{x}/{y}.png"
    handler.do_GET()
    assert responses[-1][0] == 200
    assert responses[-1][2] == "image/png"
    assert responses[-1][3]["Cache-Control"] == "no-store"

    handler.path = "/own/inspect"
    handler.do_GET()
    assert responses[-1][0] == 404

    handler.path = "/health"
    handler.do_HEAD()
    assert responses[-1] == (405, b"", "text/plain", {"Allow": "GET"})
