#!/usr/bin/env python3
"""Build one verified normalized settlement catalogue and receipt."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from searise_pipeline.settlements.normalized_catalogue_stage import (
    CatalogueStageError,
    build_normalized_catalogue_stage,
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-stage-db", type=Path, required=True)
    parser.add_argument("--source-stage-receipt", type=Path, required=True)
    parser.add_argument("--output-db", type=Path, required=True)
    parser.add_argument("--output-receipt", type=Path, required=True)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--batch-size", type=int, default=None)
    args = parser.parse_args(argv)
    options = {} if args.batch_size is None else {"batch_size": args.batch_size}
    try:
        receipt = build_normalized_catalogue_stage(
            args.source_stage_db,
            args.source_stage_receipt,
            args.output_db,
            args.output_receipt,
            args.work_dir,
            **options,
        )
    except CatalogueStageError as exc:
        parser.error(str(exc))
    print(receipt["deterministicIdentity"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
