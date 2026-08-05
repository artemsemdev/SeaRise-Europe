#!/usr/bin/env python3
"""Rebuild or verify the canonical Phase 0.8 geography byte-for-byte."""

from __future__ import annotations

import argparse
import json
import tempfile
import zipfile
from pathlib import Path

from searise_pipeline.science import canonical_geojson_bytes, rebuild_approximation


def _extract_shapefile(archive: Path, destination: Path) -> Path:
    with zipfile.ZipFile(archive) as package:
        package.extractall(destination)
    candidates = sorted(destination.rglob("*.shp"))
    if len(candidates) != 1:
        raise ValueError(f"Expected one shapefile in {archive}, found {len(candidates)}")
    return candidates[0]


def rebuild(repo_root: Path, admin_archive: Path, ocean_archive: Path) -> dict[str, bytes]:
    """Return canonical outputs from the caller-supplied pinned archives."""
    contract_path = repo_root / "src" / "pipeline" / "science" / "geography-rules.json"
    rules = json.loads(contract_path.read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory() as temporary:
        temp_root = Path(temporary)
        admin = _extract_shapefile(admin_archive, temp_root / "admin")
        ocean = _extract_shapefile(ocean_archive, temp_root / "ocean")
        candidate = rebuild_approximation(admin, ocean, rules)
    return {
        "support": canonical_geojson_bytes(
            "europe",
            candidate.support,
            {
                "hazardExtentClaim": False,
                "source": "natural-earth-10m/5.1.1:admin-0-countries",
                "status": rules["support"]["status"],
                "version": rules["support"]["version"],
            },
        ),
        "coastal": canonical_geojson_bytes(
            "coastal_analysis_zone",
            candidate.coastal,
            {
                "hazardExtentClaim": False,
                "role": "product-eligibility-only",
                "source": "natural-earth-10m/5.1.1:ocean",
                "status": rules["coastal"]["status"],
                "version": rules["coastal"]["version"],
            },
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--admin-archive", type=Path, required=True)
    parser.add_argument("--ocean-archive", type=Path, required=True)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    outputs = rebuild(args.repo_root, args.admin_archive, args.ocean_archive)
    rules = json.loads(
        (
            args.repo_root
            / "src"
            / "pipeline"
            / "science"
            / "geography-rules.json"
        ).read_text(encoding="utf-8")
    )
    for key, content in outputs.items():
        path = args.repo_root / rules[key]["path"]
        if args.write:
            path.write_bytes(content)
        elif path.read_bytes() != content:
            raise SystemExit(f"{key} geography does not match deterministic rebuild")


if __name__ == "__main__":
    main()
