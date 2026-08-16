"""Build committed browser integrity metadata from authoritative release inputs."""

from __future__ import annotations

import json
from pathlib import Path

from searise_pipeline.release import (
    RangeObject,
    load_release_contract,
    load_source_fixture,
    write_range_integrity_index,
    write_source_grid,
)

REPOSITORY_ROOT = Path(__file__).parents[2]
RELEASE_ID = "searise-europe-v1.0.0-20260810-c096aeab4e09"
SOURCE_ROOT = REPOSITORY_ROOT / "src/pipeline/fixtures/ar6-regional-release"
PAYLOAD_ROOT = REPOSITORY_ROOT / "contracts/release/v1/fixtures/release" / RELEASE_ID
OVERLAY_ROOT = (
    REPOSITORY_ROOT / "contracts/release/v2/fixtures/browser-release" / RELEASE_ID
)


def _read_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    """Write both scientific metadata artifacts using production writers."""
    contract = load_release_contract(
        REPOSITORY_ROOT / "src/pipeline/science/ar6-regional-release.json"
    )
    source = load_source_fixture(
        SOURCE_ROOT / "source-fixture.json.gz",
        receipt=_read_json(SOURCE_ROOT / "source-fixture-receipt.json"),
        release_contract=contract,
    )
    write_source_grid(
        source,
        OVERLAY_ROOT / "analysis/source-grid.json.gz",
        contract=contract,
    )

    manifest = _read_json(PAYLOAD_ROOT / "manifest.json")
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list):
        raise TypeError("The byte-sealed payload manifest has no artifact list")
    cogs = [item for item in artifacts if item.get("role") == "projection-analysis-cog"]
    write_range_integrity_index(
        PAYLOAD_ROOT,
        OVERLAY_ROOT / "analysis/cog-range-integrity.json",
        data_release_id=RELEASE_ID,
        artifact_path="analysis/cog-range-integrity.json",
        objects=(
            RangeObject(
                artifact_id=str(item["artifactId"]),
                path=str(item["path"]),
                byte_size=int(item["byteSize"]),
                sha256=str(item["sha256"]),
            )
            for item in cogs
        ),
    )


if __name__ == "__main__":
    main()
