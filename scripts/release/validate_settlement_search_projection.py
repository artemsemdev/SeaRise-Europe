"""Replay a settlement projection and emit its exact public build authority."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from searise_pipeline.settlements.search_projection import (
    SearchProjectionError,
    validated_search_projection_authority,
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spatial-database", type=Path, required=True)
    parser.add_argument("--spatial-receipt", type=Path, required=True)
    parser.add_argument("--projection", type=Path, required=True)
    parser.add_argument("--data-release-id", required=True)
    parser.add_argument("--work-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        authority = validated_search_projection_authority(
            args.spatial_database,
            args.spatial_receipt,
            args.projection,
            args.data_release_id,
            work_dir=args.work_dir,
        )
    except SearchProjectionError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(authority, ensure_ascii=False, separators=(",", ":"), sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
