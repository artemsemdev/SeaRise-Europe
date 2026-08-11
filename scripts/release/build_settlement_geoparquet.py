#!/usr/bin/env python3
"""Build and immutably publish one settlement GeoParquet artifact and receipt."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from searise_pipeline.settlements.spatial_geoparquet_publication import (
    SpatialGeoParquetPublicationError,
    build_spatial_geoparquet,
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spatial-db", type=Path, required=True)
    parser.add_argument("--spatial-receipt", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--output-receipt", type=Path, required=True)
    parser.add_argument("--data-release-id", required=True)
    parser.add_argument("--work-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        receipt = build_spatial_geoparquet(
            args.spatial_db,
            args.spatial_receipt,
            args.output,
            args.output_receipt,
            data_release_id=args.data_release_id,
            work_dir=args.work_dir,
        )
    except SpatialGeoParquetPublicationError as exc:
        parser.error(str(exc))
    print(receipt["deterministicIdentity"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
