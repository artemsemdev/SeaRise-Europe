"""Generate a synthetic demo exposure COG and upload it to Azurite.

DEV-ONLY. This service exists so that /v1/assess can return all five result
states without requiring the real geospatial pipeline to run. It creates a
single tiny COG covering Europe's bounding box with pixel value 1 (modeled
exposure) where latitude <= 53 and 0 elsewhere, then uploads it to the
Azurite blob emulator at 'geospatial/layers/v1.0/demo.tif'.

All nine (scenario, horizon) layer rows in init.sql point at this one file,
so the map overlay will look identical across scenarios -- that's expected
for this shortcut. Replace with real pipeline output when available.
"""

from __future__ import annotations

import os
import sys
import tempfile

import numpy as np
import rasterio
from azure.storage.blob import BlobServiceClient
from rasterio.transform import from_bounds
from rio_cogeo.cogeo import cog_translate
from rio_cogeo.profiles import cog_profiles

BBOX = (-25.0, 34.0, 45.0, 72.0)  # west, south, east, north
WIDTH = 700
HEIGHT = 380
EXPOSURE_LAT_CUTOFF = 53.0

BLOB_CONTAINER = "geospatial"
BLOB_PATH = "layers/v1.0/demo.tif"


def build_array() -> np.ndarray:
    _, south, _, north = BBOX
    lat_step = (north - south) / HEIGHT
    row_lats = north - (np.arange(HEIGHT) + 0.5) * lat_step
    exposed_rows = (row_lats <= EXPOSURE_LAT_CUTOFF).astype(np.uint8)
    return np.broadcast_to(exposed_rows[:, None], (HEIGHT, WIDTH)).copy()


def build_cog_bytes(array: np.ndarray) -> bytes:
    west, south, east, north = BBOX
    transform = from_bounds(west, south, east, north, WIDTH, HEIGHT)

    with tempfile.TemporaryDirectory() as tmp:
        src_path = os.path.join(tmp, "src.tif")
        dst_path = os.path.join(tmp, "dst.tif")

        with rasterio.open(
            src_path,
            "w",
            driver="GTiff",
            dtype="uint8",
            count=1,
            height=HEIGHT,
            width=WIDTH,
            crs="EPSG:4326",
            transform=transform,
            nodata=255,
        ) as dataset:
            dataset.write(array, 1)

        cog_translate(
            src_path,
            dst_path,
            cog_profiles.get("deflate"),
            in_memory=False,
            quiet=True,
        )

        with open(dst_path, "rb") as handle:
            return handle.read()


def upload(blob_bytes: bytes) -> None:
    connection_string = os.environ["AZURE_STORAGE_CONNECTION_STRING"]
    service = BlobServiceClient.from_connection_string(connection_string)
    container = service.get_container_client(BLOB_CONTAINER)

    try:
        container.create_container()
        print(f"created container '{BLOB_CONTAINER}'", flush=True)
    except Exception as exc:
        if "ContainerAlreadyExists" not in str(exc):
            raise
        print(f"container '{BLOB_CONTAINER}' already exists", flush=True)

    blob = container.get_blob_client(BLOB_PATH)
    blob.upload_blob(blob_bytes, overwrite=True)
    print(f"uploaded {BLOB_PATH} ({len(blob_bytes)} bytes)", flush=True)


def main() -> int:
    print("blob-seed: building synthetic demo COG ...", flush=True)
    array = build_array()
    cog_bytes = build_cog_bytes(array)
    print(f"blob-seed: COG built ({len(cog_bytes)} bytes)", flush=True)
    upload(cog_bytes)
    print("blob-seed: done.", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
