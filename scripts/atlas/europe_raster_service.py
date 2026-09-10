#!/usr/bin/env python3
"""Read-only loopback tile service for verified local European depth rasters."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import struct
import threading
import zlib
from collections import OrderedDict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.transform import from_bounds
from rasterio.vrt import WarpedVRT
from rasterio.warp import transform, transform_bounds
from rasterio.windows import Window

SIZE = 256
WORLD = 20037508.342789244
WARP_TOLERANCE = 1e-9
COLORS = np.array(
    [
        [123, 220, 241, 195],
        [82, 198, 231, 205],
        [45, 167, 219, 215],
        [29, 128, 198, 225],
        [31, 91, 170, 235],
        [40, 60, 127, 245],
    ],
    dtype=np.uint8,
)
SHA256 = re.compile(r"^[a-f0-9]{64}$")


def stream_digest(path: Path) -> str:
    """Hash one raster in bounded memory."""
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def tile_bounds(z: int, x: int, y: int) -> tuple[float, float, float, float]:
    if not (0 <= z <= 18 and 0 <= x < 2**z and 0 <= y < 2**z):
        raise ValueError("Tile coordinate outside supported range")
    span = 2 * WORLD / 2**z
    return (
        -WORLD + x * span,
        WORLD - (y + 1) * span,
        -WORLD + (x + 1) * span,
        WORLD - y * span,
    )


def overlaps(a: tuple[float, ...], b: list[float]) -> bool:
    return a[0] < b[2] and a[2] > b[0] and a[1] < b[3] and a[3] > b[1]


def validate_point(lon: float, lat: float, protection: str) -> None:
    if (
        not math.isfinite(lon)
        or not math.isfinite(lat)
        or not -180 <= lon <= 180
        or not -90 <= lat <= 90
        or protection not in ("unprotected", "protected")
    ):
        raise ValueError(
            "Expected finite geographic coordinates and a supported defense setting"
        )


def inspection_query(query: str) -> tuple[float, float, str]:
    parameters = parse_qs(query, keep_blank_values=True)
    if set(parameters) != {"lon", "lat", "defenses"} or any(
        len(values) != 1 for values in parameters.values()
    ):
        raise ValueError("Expected exactly one lon, lat, and defenses parameter")
    lon, lat = float(parameters["lon"][0]), float(parameters["lat"][0])
    protection = parameters["defenses"][0]
    validate_point(lon, lat, protection)
    return lon, lat, protection


def colorize(
    values: np.ndarray[Any, Any], valid: np.ndarray[Any, Any]
) -> tuple[np.ndarray[Any, Any], int, int]:
    if np.any(valid & (~np.isfinite(values) | (values < 0))):
        raise ValueError("Unexpected nonfinite or negative valid flood depth")
    positive = valid & (values > 0)
    rgba = np.zeros((*values.shape, 4), dtype=np.uint8)
    bins = np.digitize(values[positive], [0.25, 0.5, 1, 2, 5], right=True)
    rgba[positive] = COLORS[bins]
    return rgba, int(valid.sum()), int(positive.sum())


def png_bytes(rgba: np.ndarray[Any, Any]) -> bytes:
    height, width, channels = rgba.shape
    if channels != 4 or rgba.dtype != np.uint8:
        raise ValueError("PNG requires RGBA uint8")

    def chunk(kind: bytes, content: bytes) -> bytes:
        checksum = zlib.crc32(kind + content) & 0xFFFFFFFF
        return struct.pack("!I", len(content)) + kind + content + struct.pack("!I", checksum)

    rows = b"".join(b"\x00" + row.tobytes() for row in rgba)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack("!2I5B", width, height, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(rows, 6))
        + chunk(b"IEND", b"")
    )


def confined_raster(root: Path, source: dict[str, Any]) -> Path:
    relative = source.get("file")
    expected_size = source.get("bytes")
    expected_digest = source.get("sha256")
    if (
        not isinstance(relative, str)
        or not relative
        or Path(relative).is_absolute()
        or ".." in Path(relative).parts
        or Path(relative).suffix.lower() not in {".tif", ".tiff"}
        or not isinstance(expected_size, int)
        or expected_size <= 0
        or not isinstance(expected_digest, str)
        or SHA256.fullmatch(expected_digest) is None
    ):
        raise ValueError("Raster integrity metadata is invalid")
    path = (root / relative).resolve(strict=True)
    try:
        path.relative_to(root)
    except ValueError as error:
        raise ValueError("Raster integrity path escapes the data root") from error
    if not path.is_file() or path.stat().st_size != expected_size:
        raise ValueError("Raster integrity size differs from the manifest")
    return path


class Atlas:
    """Verified immutable raster inventory with bounded tile and point reads."""

    def __init__(self, root: Path):
        self.root = root.resolve(strict=True)
        manifest_bytes = (self.root / "manifest.json").read_bytes()
        self.manifest = json.loads(manifest_bytes)
        if (
            self.manifest.get("version") != 2
            or self.manifest.get("scenario") != "ssp585"
            or self.manifest.get("condition") != "high-tide"
        ):
            raise ValueError("Expected European SSP585 high-tide manifest v2")
        self.layers: dict[tuple[int, str], dict[str, Any]] = {}
        self.limit = threading.BoundedSemaphore(4)
        self._cache_lock = threading.Lock()
        self._tile_cache: OrderedDict[
            tuple[int, str, int, int, int], tuple[bytes, int, int]
        ] = OrderedDict()
        verified: dict[Path, tuple[int, str]] = {}
        for layer in self.manifest.get("layers", []):
            key = (layer.get("year"), layer.get("protection"))
            inputs = layer.get("inputs")
            if (
                key[0] not in (2030, 2050, 2100)
                or key[1] not in ("unprotected", "protected")
                or layer.get("scenario") != "ssp585"
                or key in self.layers
                or not isinstance(inputs, list)
                or not inputs
            ):
                raise ValueError("Invalid layer identity")
            for source in inputs:
                path = confined_raster(self.root, source)
                identity = (source["bytes"], source["sha256"])
                previous = verified.get(path)
                if previous is not None and previous != identity:
                    raise ValueError("Raster integrity identity conflicts across layers")
                if previous is None:
                    if stream_digest(path) != source["sha256"]:
                        raise ValueError("Raster integrity digest differs from the manifest")
                    verified[path] = identity
                source["_path"] = path
            self.layers[key] = layer
        if len(self.layers) != 6:
            raise ValueError("All six European layers are required")

    def inspect(self, lon: float, lat: float, protection: str) -> dict[str, Any]:
        """Sample the containing native cell without interpolation."""
        validate_point(lon, lat, protection)
        results: list[dict[str, Any]] = []
        with self.limit, rasterio.Env(
            GDAL_CACHEMAX=64 * 1024 * 1024, GDAL_NUM_THREADS="1"
        ):
            for year in (2030, 2050, 2100):
                depths: list[float] = []
                for source in self.layers[(year, protection)]["inputs"]:
                    west, south, east, north = source["bounds"]
                    if not (west <= lon <= east and south <= lat <= north):
                        continue
                    with rasterio.open(source["_path"]) as dataset:
                        grid = dataset.transform
                        if dataset.crs != rasterio.crs.CRS.from_epsg(3035) or (
                            grid.a,
                            grid.b,
                            grid.d,
                            grid.e,
                        ) != (25, 0, 0, -25):
                            raise RuntimeError(
                                "Point inspection requires the original 25 m EPSG:3035 grid"
                            )
                        xs, ys = transform("EPSG:4326", dataset.crs, [lon], [lat])
                        row, column = dataset.index(xs[0], ys[0])
                        if not (0 <= row < dataset.height and 0 <= column < dataset.width):
                            continue
                        sample = dataset.read(
                            1, window=Window(column, row, 1, 1), masked=True
                        )
                        value = float(sample.data[0, 0])
                        if (
                            not np.ma.getmaskarray(sample)[0, 0]
                            and math.isfinite(value)
                            and value >= 0
                        ):
                            depths.append(value)
                depth = max(depths) if depths else None
                status = "unknown" if depth is None else "flooded" if depth > 0 else "zero"
                results.append(
                    {"year": year, "status": status, "depthMeters": depth}
                )
        return {
            "coordinates": [lon, lat],
            "protection": protection,
            "cellSizeMeters": 25,
            "results": results,
        }

    def tile(
        self, year: int, protection: str, z: int, x: int, y: int
    ) -> tuple[bytes, int, int]:
        key = (year, protection, z, x, y)
        with self._cache_lock:
            cached = self._tile_cache.get(key)
            if cached is not None:
                self._tile_cache.move_to_end(key)
                return cached
        rendered = self._render_tile(year, protection, z, x, y)
        with self._cache_lock:
            self._tile_cache[key] = rendered
            self._tile_cache.move_to_end(key)
            if len(self._tile_cache) > 256:
                self._tile_cache.popitem(last=False)
        return rendered

    def _render_tile(
        self, year: int, protection: str, z: int, x: int, y: int
    ) -> tuple[bytes, int, int]:
        bounds = tile_bounds(z, x, y)
        geographic = transform_bounds(
            "EPSG:3857", "EPSG:4326", *bounds, densify_pts=21
        )
        layer = self.layers[(year, protection)]
        values = np.zeros((SIZE, SIZE), dtype=np.float32)
        valid = np.zeros((SIZE, SIZE), dtype=bool)
        with self.limit, rasterio.Env(
            GDAL_CACHEMAX=64 * 1024 * 1024, GDAL_NUM_THREADS="1"
        ):
            for source in layer["inputs"]:
                if not overlaps(geographic, source["bounds"]):
                    continue
                latitude = min(85.0, max(abs(geographic[1]), abs(geographic[3])))
                ground_pixel = (bounds[2] - bounds[0]) / SIZE * math.cos(
                    math.radians(latitude)
                )
                factors = source.get("overviews", [])
                eligible = [
                    index
                    for index, factor in enumerate(factors)
                    if factor * 25 <= ground_pixel
                ]
                options = {"overview_level": eligible[-1]} if eligible else {}
                with (
                    rasterio.open(source["_path"], **options) as dataset,
                    WarpedVRT(
                        dataset,
                        crs="EPSG:3857",
                        transform=from_bounds(*bounds, SIZE, SIZE),
                        width=SIZE,
                        height=SIZE,
                        resampling=Resampling.nearest,
                        src_nodata=dataset.nodata,
                        nodata=-9999,
                        warp_mem_limit=32,
                        tolerance=WARP_TOLERANCE,
                    ) as vrt,
                ):
                    data = vrt.read(1, masked=True)
                present = ~np.ma.getmaskarray(data) & np.isfinite(data.data)
                if np.any(present & (data.data < 0)) and not eligible:
                    raise ValueError("Unexpected negative native source depth")
                present &= data.data >= 0
                values[present] = np.maximum(values[present], data.data[present])
                valid |= present
        rgba, valid_count, flooded_count = colorize(values, valid)
        return png_bytes(rgba), valid_count, flooded_count


def handler_for(atlas: Atlas) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            url = urlsplit(self.path)
            if url.path == "/inspect":
                try:
                    point = inspection_query(url.query)
                except (TypeError, ValueError) as error:
                    self.respond(
                        400,
                        json.dumps({"error": str(error)}).encode(),
                        "application/json",
                    )
                    return
                try:
                    result = atlas.inspect(*point)
                except Exception as error:  # noqa: BLE001
                    self.log_error("Native point inspection failed: %s", error)
                    self.respond(
                        500,
                        b'{"error":"Native flood source unavailable"}',
                        "application/json",
                    )
                    return
                self.respond(
                    200,
                    json.dumps(result, allow_nan=False).encode(),
                    "application/json",
                    {"Cache-Control": "no-store"},
                )
                return
            if url.path == "/health" and not url.query:
                payload = json.dumps(
                    {
                        "ready": True,
                        "version": 2,
                        "layers": len(atlas.layers),
                        "assets": sum(
                            len(layer["inputs"]) for layer in atlas.layers.values()
                        ),
                    }
                ).encode()
                self.respond(
                    200,
                    payload,
                    "application/json",
                    {"Cache-Control": "no-store"},
                )
                return
            match = re.fullmatch(
                r"/tiles/(2030|2050|2100)/(unprotected|protected)/(\d+)/(\d+)/(\d+)\.png",
                url.path,
            )
            if not match or url.query:
                self.respond(404, b"Unknown route", "text/plain")
                return
            year, protection, z, x, y = match.groups()
            try:
                payload, valid, flooded = atlas.tile(
                    int(year), protection, int(z), int(x), int(y)
                )
            except ValueError as error:
                self.respond(400, str(error).encode(), "text/plain")
                return
            except Exception as error:  # noqa: BLE001
                self.log_error("Raster tile failed: %s", error)
                self.respond(500, b"Raster tile unavailable", "text/plain")
                return
            self.respond(
                200,
                payload,
                "image/png",
                {
                    "X-Valid-Pixels": str(valid),
                    "X-Flood-Pixels": str(flooded),
                    "Cache-Control": "no-store",
                },
            )

        def do_HEAD(self) -> None:
            self.respond(405, b"", "text/plain", {"Allow": "GET"})

        def respond(
            self,
            status: int,
            body: bytes,
            content_type: str,
            headers: dict[str, str] | None = None,
        ) -> None:
            try:
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("X-Content-Type-Options", "nosniff")
                for key, value in (headers or {}).items():
                    self.send_header(key, value)
                self.end_headers()
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                self.close_connection = True

        def log_message(self, format: str, *args: object) -> None:
            return

    return Handler


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", required=True, type=Path)
    parser.add_argument("--port", default=0, type=int)
    parser.add_argument(
        "--host", default="127.0.0.1", choices=("127.0.0.1", "localhost")
    )
    args = parser.parse_args()
    atlas = Atlas(args.data_root)
    server = ThreadingHTTPServer((args.host, args.port), handler_for(atlas))
    print(
        json.dumps(
            {
                "ready": True,
                "host": args.host,
                "port": server.server_port,
                "layers": len(atlas.layers),
            }
        ),
        flush=True,
    )
    server.serve_forever()


if __name__ == "__main__":
    main()
