"""Characterize the measured Phase 0.8 terrain decision evidence."""

from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).parents[4]
CONTRACT_DIR = REPO_ROOT / "src" / "pipeline" / "science"
EVIDENCE_PATH = CONTRACT_DIR / "evidence" / "phase-0-8-terrain-geography.json"


def test_five_quality_aware_windows_support_the_glo30_selection() -> None:
    evidence = json.loads(EVIDENCE_PATH.read_text(encoding="utf-8"))
    terrain = evidence["terrain"]

    assert terrain["decision"] == "select GLO-30 for external review"
    assert len(terrain["windows"]) == 5
    assert terrain["aggregateChecks"] == {
        "classifiedByteRatioGlo30ToGlo90": 6.731247708664304,
        "glo30P95HemLowerInEveryWindow": True,
        "rawPixelCountRatioGlo30ToGlo90": 9,
        "sourceByteRatioGlo30ToGlo90": 8.05949786285182,
        "thresholdDisagreementObservedInEveryWindow": True,
        "totalFiveLayerSourceBytes": {
            "GLO-30": 165670216,
            "GLO-90": 20555898,
        },
        "totalGlo90WaterCellsContainingGlo30LandPresence": 35891,
        "totalLosslessLandElevationClass2mGeoTiffBytes": {
            "GLO-30": 550818,
            "GLO-90": 81830,
        },
        "windowCount": 5,
    }
    for window in terrain["windows"]:
        assert set(window["resolutions"]) == {"GLO-30", "GLO-90"}
        for resolution in window["resolutions"].values():
            assert set(resolution["assets"]) == {"DEM", "EDM", "FLM", "HEM", "WBM"}
            assert all(len(asset["sha256"]) == 64 for asset in resolution["assets"].values())
