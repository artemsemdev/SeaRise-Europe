"""Prove the committed browser range fixture is a valid, deterministic later-chunk COG."""

from __future__ import annotations

import json
import runpy
import struct
from pathlib import Path

ROOT = Path(__file__).parents[4]
RELEASE_ID = "searise-europe-v1.0.0-20260810-c096aeab4e09"
SOURCE = ROOT / "contracts/release/v1/fixtures/release" / RELEASE_ID / "analysis/ssp2-45/2050.tif"
OVERLAY_ROOT = ROOT / "contracts/release/v2/fixtures/browser-release" / RELEASE_ID
COMMITTED = OVERLAY_ROOT / "analysis/ssp2-45/2050.tif"
BUILDER = runpy.run_path(str(ROOT / "scripts/release/build-browser-integrity-fixture.py"))


def test_committed_browser_cog_is_deterministic_and_moves_real_tiles_later(
    tmp_path: Path,
) -> None:
    rebuilt = tmp_path / "later-chunk.tif"
    BUILDER["_write_later_chunk_cog"](SOURCE, rebuilt)
    assert rebuilt.read_bytes() == COMMITTED.read_bytes()

    payload = COMMITTED.read_bytes()
    positions = BUILDER["_classic_tiff_tile_offset_positions"](payload)
    tile_offsets = [struct.unpack_from("<I", payload, position)[0] for position in positions]
    assert min(tile_offsets) >= 3 * 65_536
    assert max(tile_offsets) < len(payload)

    range_index = json.loads(
        (OVERLAY_ROOT / "analysis/cog-range-integrity.json").read_text(encoding="utf-8")
    )
    identity = next(
        item
        for item in range_index["artifacts"]
        if item["artifactId"] == "projection-ssp2-45-2050-cog"
    )
    assert identity["byteSize"] == len(payload)
    assert len(identity["chunks"]) == 4
    assert identity["chunks"][-1]["start"] == 3 * 65_536
