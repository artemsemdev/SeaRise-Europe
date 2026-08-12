#!/usr/bin/env python3
"""Build one receipt-bound settlement reconciliation report."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from searise_pipeline.settlements.reconciliation import (
    SettlementReconciliationError,
    build_settlement_reconciliation_report,
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalogue-db", type=Path, required=True)
    parser.add_argument("--catalogue-receipt", type=Path, required=True)
    parser.add_argument("--spatial-db", type=Path, required=True)
    parser.add_argument("--spatial-receipt", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--data-release-id", required=True)
    parser.add_argument("--work-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        report = build_settlement_reconciliation_report(
            args.catalogue_db,
            args.catalogue_receipt,
            args.spatial_db,
            args.spatial_receipt,
            args.output,
            data_release_id=args.data_release_id,
            work_dir=args.work_dir,
        )
    except SettlementReconciliationError as exc:
        parser.error(str(exc))
    print(report["deterministicIdentity"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
