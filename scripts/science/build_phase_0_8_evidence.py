#!/usr/bin/env python3
"""Rebuild the deterministic Phase 0.8 evidence report from pinned samples."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from searise_pipeline.science import (
    compare_dem_windows,
    evaluate_connectivity_controls,
    inspect_geometry_assets,
    load_science_contracts,
)

WINDOWS = {
    "malta-small-islands": "N35_00_E014_00",
    "lisbon-steep-estuary": "N38_00_W010_00",
    "venice-lagoon": "N45_00_E012_00",
    "netherlands-low-coast": "N52_00_E004_00",
    "reykjavik-steep-island": "N64_00_W022_00",
}
LAYERS = ("DEM", "EDM", "FLM", "HEM", "WBM")


def _paths(root: Path, prefix: str, tile: str) -> dict[str, Path]:
    return {layer: root / f"{prefix}_{tile}_{layer}.tif" for layer in LAYERS}


def _window_summary(name: str, report: dict[str, Any]) -> dict[str, Any]:
    comparison = report["comparison"]
    resolutions: dict[str, Any] = {}
    for resolution in ("GLO-30", "GLO-90"):
        data = report[resolution]
        resolutions[resolution] = {
            "assets": data["assets"],
            "grid": data["grid"],
            "quality": data["quality"],
            "losslessLandElevationClass2mGeoTiffBytes": data["delivery"][
                "losslessLandElevationClass2mGeoTiffBytes"
            ],
        }
    return {
        "id": name,
        "resolutions": resolutions,
        "comparison": comparison,
    }


def build_report(repo_root: Path, dem_root: Path) -> dict[str, Any]:
    """Build stable evidence without runtime-dependent measurements."""
    contract_dir = repo_root / "src" / "pipeline" / "science"
    contracts = load_science_contracts(contract_dir)
    windows = [
        _window_summary(
            name,
            compare_dem_windows(
                _paths(dem_root, "10", tile),
                _paths(dem_root, "30", tile),
            ),
        )
        for name, tile in WINDOWS.items()
    ]
    connectivity_document = json.loads(
        (contract_dir / "connectivity-controls.json").read_text(encoding="utf-8")
    )
    p95_is_lower = all(
        item["resolutions"]["GLO-30"]["quality"]["heightError"]["p95SigmaMetres"]
        < item["resolutions"]["GLO-90"]["quality"]["heightError"]["p95SigmaMetres"]
        for item in windows
    )
    source_bytes = {
        resolution: sum(
            sum(
                asset["byteSize"]
                for asset in item["resolutions"][resolution]["assets"].values()
            )
            for item in windows
        )
        for resolution in ("GLO-30", "GLO-90")
    }
    classified_bytes = {
        resolution: sum(
            item["resolutions"][resolution]["losslessLandElevationClass2mGeoTiffBytes"]
            for item in windows
        )
        for resolution in ("GLO-30", "GLO-90")
    }
    return {
        "schemaVersion": 1,
        "evidenceDate": "2026-08-05",
        "issue": "https://github.com/artemsemdev/SeaRise-Europe/issues/84",
        "primaryReferences": [
            {
                "title": "Copernicus DEM product page",
                "url": "https://dataspace.copernicus.eu/explore-data/data-collections/copernicus-contributing-missions/collections-description/COP-DEM",
            },
            {
                "title": "Copernicus DEM Product Handbook, issue 5.0",
                "url": "https://dataspace.copernicus.eu/sites/default/files/media/files/2024-06/geo1988-copernicusdem-spe-002_producthandbook_i5.0.pdf",
            },
            {
                "title": "Copernicus Coastal Zones 2018",
                "url": "https://land.copernicus.eu/en/products/coastal-zones/coastal-zones-2018",
            },
            {
                "title": "Copernicus Land Monitoring Service data policy",
                "url": "https://land.copernicus.eu/en/data-policy",
            },
        ],
        "terrain": {
            "sampleDesign": (
                "Five coastal one-degree windows selected before comparison to cover "
                "low coast, lagoon, steep estuary, small islands, and steep island terrain."
            ),
            "windows": windows,
            "aggregateChecks": {
                "windowCount": len(windows),
                "rawPixelCountRatioGlo30ToGlo90": 9,
                "glo30P95HemLowerInEveryWindow": p95_is_lower,
                "totalGlo90WaterCellsContainingGlo30LandPresence": sum(
                    item["comparison"]["glo30LandPresenceLostByGlo90WaterMaskCells"]
                    for item in windows
                ),
                "thresholdDisagreementObservedInEveryWindow": all(
                    any(item["comparison"]["thresholdClassDisagreement"].values())
                    for item in windows
                ),
                "totalFiveLayerSourceBytes": source_bytes,
                "sourceByteRatioGlo30ToGlo90": (
                    source_bytes["GLO-30"] / source_bytes["GLO-90"]
                ),
                "totalLosslessLandElevationClass2mGeoTiffBytes": classified_bytes,
                "classifiedByteRatioGlo30ToGlo90": (
                    classified_bytes["GLO-30"] / classified_bytes["GLO-90"]
                ),
            },
            "decision": "select GLO-30 for external review",
            "limitations": [
                "The compared grids are not independent vertical truth.",
                "HEM excludes systematic, editing, filling, and DSM representation errors.",
                "The sample supports resolution selection but cannot bound U_DSM or U_edit.",
            ],
        },
        "geography": inspect_geometry_assets(
            repo_root,
            contracts.geography_rules,
            contract_dir / "geography-controls.json",
        ),
        "connectivity": evaluate_connectivity_controls(connectivity_document),
        "review": {
            "status": "pending-external",
            "requiredRoles": ["scientific/data reviewer", "product owner"],
        },
        "publicationGate": {
            "status": "blocked",
            "reason": "Terrain uncertainty bounds and external terrain/geography/connectivity approvals are not complete.",
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--dem-dir", type=Path, required=True)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("src/pipeline/science/evidence/phase-0-8-terrain-geography.json"),
    )
    args = parser.parse_args()
    output = args.output if args.output.is_absolute() else args.repo_root / args.output
    report = build_report(args.repo_root, args.dem_dir)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
