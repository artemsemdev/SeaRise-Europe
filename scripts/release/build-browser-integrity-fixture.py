"""Build committed browser integrity metadata from authoritative release inputs."""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
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
MULTICHUNK_ARTIFACT_ID = "projection-ssp2-45-2050-cog"
MULTICHUNK_TARGET_SIZE = 2 * 65_536 + 8_192


def _read_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_multichunk_cog(source: Path, target: Path) -> None:
    """Keep the valid COG byte stream and add deterministic inert fixture padding."""
    payload = source.read_bytes()
    if len(payload) >= MULTICHUNK_TARGET_SIZE:
        raise ValueError("The source fixture COG no longer needs multichunk padding")
    padding = bytearray()
    counter = 0
    while len(payload) + len(padding) < MULTICHUNK_TARGET_SIZE:
        padding.extend(
            hashlib.sha256(
                b"SeaRise synthetic browser multichunk COG fixture\0"
                + counter.to_bytes(4, "big")
            ).digest()
        )
        counter += 1
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(payload + padding[: MULTICHUNK_TARGET_SIZE - len(payload)])


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
    target = next(item for item in cogs if item["artifactId"] == MULTICHUNK_ARTIFACT_ID)
    _write_multichunk_cog(
        PAYLOAD_ROOT / str(target["path"]),
        OVERLAY_ROOT / str(target["path"]),
    )
    with tempfile.TemporaryDirectory(prefix="searise-browser-cogs-") as temporary:
        assembled_root = Path(temporary)
        identities = []
        for item in cogs:
            relative_path = str(item["path"])
            overlay = OVERLAY_ROOT / relative_path
            source = overlay if overlay.is_file() else PAYLOAD_ROOT / relative_path
            destination = assembled_root / relative_path
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
            payload = source.read_bytes()
            identities.append(
                RangeObject(
                    artifact_id=str(item["artifactId"]),
                    path=relative_path,
                    byte_size=len(payload),
                    sha256=hashlib.sha256(payload).hexdigest(),
                )
            )
        write_range_integrity_index(
            assembled_root,
            OVERLAY_ROOT / "analysis/cog-range-integrity.json",
            data_release_id=RELEASE_ID,
            artifact_path="analysis/cog-range-integrity.json",
            objects=identities,
        )


if __name__ == "__main__":
    main()
