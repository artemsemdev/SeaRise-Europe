"""Build committed browser integrity metadata from authoritative release inputs."""

from __future__ import annotations

import gzip
import hashlib
import json
import shutil
import struct
import tempfile
from pathlib import Path

import rasterio
from rio_cogeo.cogeo import cog_validate
from searise_pipeline.release import (
    RangeObject,
    load_release_contract,
    load_source_fixture,
    write_range_integrity_index,
    write_source_grid,
)
from searise_pipeline.release.boundary_geoparquet import (
    _write_browser_fixture_boundary_geoparquet,
)

REPOSITORY_ROOT = Path(__file__).parents[2]
RELEASE_ID = "searise-europe-v1.0.0-20260810-c096aeab4e09"
SOURCE_ROOT = REPOSITORY_ROOT / "src/pipeline/fixtures/ar6-regional-release"
PAYLOAD_ROOT = REPOSITORY_ROOT / "contracts/release/v1/fixtures/release" / RELEASE_ID
OVERLAY_ROOT = (
    REPOSITORY_ROOT / "contracts/release/v2/fixtures/browser-release" / RELEASE_ID
)
MULTICHUNK_ARTIFACT_ID = "projection-ssp2-45-2050-cog"
RANGE_CHUNK_SIZE = 65_536
LATER_CHUNK_GAP_SIZE = 3 * RANGE_CHUNK_SIZE
NODATA_CONTROL_PATH = (
    REPOSITORY_ROOT
    / "src/pipeline/fixtures/browser-release/adr-024-nodata-control-v1.json"
)
BOUNDARY_ARROW_SCHEMAS_PATH = (
    REPOSITORY_ROOT
    / "src/pipeline/fixtures/browser-release/boundary-arrow-schemas-v1.json"
)
BOUNDARY_SOURCES = {
    "support-boundary": REPOSITORY_ROOT / "data/geometry/europe.geojson",
    "coastal-boundary": REPOSITORY_ROOT / "data/geometry/coastal_analysis_zone.geojson",
}
BOUNDARY_OUTPUTS = {
    "support-boundary": OVERLAY_ROOT / "boundaries/europe.parquet",
    "coastal-boundary": OVERLAY_ROOT / "boundaries/coastal-analysis-zone.parquet",
}


def _read_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _deterministic_fixture_gap() -> bytes:
    """Return deterministic synthetic spacing for the transport-only COG fixture."""
    gap = bytearray()
    counter = 0
    while len(gap) < LATER_CHUNK_GAP_SIZE:
        gap.extend(
            hashlib.sha256(
                b"SeaRise synthetic browser later-chunk COG spacing\0"
                + counter.to_bytes(4, "big")
            ).digest()
        )
        counter += 1
    return bytes(gap[:LATER_CHUNK_GAP_SIZE])


def _classic_tiff_tile_offset_positions(payload: bytes) -> list[int]:
    """Locate inline TileOffsets values in the fixture's little-endian TIFF IFDs."""
    if payload[:4] != b"II*\x00":
        raise ValueError(
            "The browser range fixture requires classic little-endian TIFF"
        )
    ifd_offset = struct.unpack_from("<I", payload, 4)[0]
    positions: list[int] = []
    visited: set[int] = set()
    while ifd_offset:
        if ifd_offset in visited or ifd_offset + 2 > len(payload):
            raise ValueError("The browser range fixture has an invalid TIFF IFD chain")
        visited.add(ifd_offset)
        entry_count = struct.unpack_from("<H", payload, ifd_offset)[0]
        entries_start = ifd_offset + 2
        next_ifd_position = entries_start + entry_count * 12
        if next_ifd_position + 4 > len(payload):
            raise ValueError("The browser range fixture has a truncated TIFF IFD")
        for index in range(entry_count):
            entry = entries_start + index * 12
            tag, value_type, count = struct.unpack_from("<HHI", payload, entry)
            if tag == 324:
                if value_type != 4 or count != 1:
                    raise ValueError(
                        "The browser range fixture requires one inline tile offset per IFD"
                    )
                positions.append(entry + 8)
        ifd_offset = struct.unpack_from("<I", payload, next_ifd_position)[0]
    if not positions:
        raise ValueError("The browser range fixture has no TIFF tile offsets")
    return positions


def _write_later_chunk_cog(source: Path, target: Path) -> None:
    """Write a valid COG whose real imagery is stored beyond the first range chunk."""
    source_payload = source.read_bytes()
    tile_offset_positions = _classic_tiff_tile_offset_positions(source_payload)
    tile_offsets = [
        struct.unpack_from("<I", source_payload, position)[0]
        for position in tile_offset_positions
    ]
    insertion_offset = min(tile_offsets)
    if any(position >= insertion_offset for position in tile_offset_positions):
        raise ValueError(
            "The browser range fixture cannot safely relocate TIFF offsets"
        )
    rendered = bytearray(
        source_payload[:insertion_offset]
        + _deterministic_fixture_gap()
        + source_payload[insertion_offset:]
    )
    for position, offset in zip(tile_offset_positions, tile_offsets):
        struct.pack_into("<I", rendered, position, offset + LATER_CHUNK_GAP_SIZE)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(rendered)
    valid, errors, warnings = cog_validate(target, strict=True, quiet=True)
    if not valid or errors or warnings:
        raise ValueError(
            f"The browser later-chunk fixture is not a valid COG: "
            f"errors={errors}, warnings={warnings}"
        )
    with rasterio.open(source) as expected, rasterio.open(target) as observed:
        if observed.read().tobytes() != expected.read().tobytes():
            raise ValueError("The browser later-chunk COG changed scientific values")
        if (
            observed.descriptions != expected.descriptions
            or observed.tags() != expected.tags()
            or observed.transform != expected.transform
            or observed.crs != expected.crs
        ):
            raise ValueError("The browser later-chunk COG changed scientific metadata")
    relocated_offsets = [offset + LATER_CHUNK_GAP_SIZE for offset in tile_offsets]
    if min(relocated_offsets) < 3 * RANGE_CHUNK_SIZE:
        raise ValueError(
            "The browser later-chunk COG did not relocate real imagery past 192 KiB"
        )


def _validate_nodata_control(
    control: dict[str, object],
    cogs: list[dict[str, object]],
) -> None:
    """Prove the browser-only control is the same nodata cell in all 27 bands."""
    evidence = control["sourceGridEvidence"]
    if not isinstance(evidence, dict):
        raise TypeError("The browser nodata control has no source-grid evidence")
    expected_combinations = {
        (item["scenario"], item["horizon"])
        for item in evidence["scenarioHorizonCombinations"]
    }
    actual_combinations = {
        (
            item["projectionContext"]["scenario"],
            item["projectionContext"]["horizon"],
        )
        for item in cogs
    }
    if actual_combinations != expected_combinations or len(cogs) != 9:
        raise ValueError("The browser nodata control does not bind all nine COGs")

    row = int(evidence["row"])
    column = int(evidence["column"])
    latitude = float(evidence["latitude"])
    longitude = float(evidence["longitude"])
    expected_values = list(evidence["expectedBandValuesForEveryCombination"])
    with gzip.open(OVERLAY_ROOT / "analysis/source-grid.json.gz", "rt", encoding="utf-8") as stream:
        source_grid = json.load(stream)
    source_row = int(source_grid["height"]) - 1 - row
    source_index = source_row * int(source_grid["width"]) + column
    if (
        source_grid["cogCellMapping"]
        != {"sourceColumn": "cogColumn", "sourceRow": "height - 1 - cogRow"}
        or source_grid["locationIds"][source_index] != evidence["locationId"]
    ):
        raise ValueError("The browser nodata control source-grid identity differs")

    for item in cogs:
        relative_path = str(item["path"])
        overlay = OVERLAY_ROOT / relative_path
        artifact = overlay if overlay.is_file() else PAYLOAD_ROOT / relative_path
        with rasterio.open(artifact) as dataset:
            if dataset.index(longitude, latitude) != (row, column):
                raise ValueError(f"The browser nodata control moved in {relative_path}")
            values = dataset.read(window=((row, row + 1), (column, column + 1)))[
                :, 0, 0
            ].tolist()
            if dataset.nodata != evidence["storedNodata"] or values != expected_values:
                raise ValueError(
                    f"The browser nodata control is not nodata in all bands of {relative_path}"
                )


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
    for role, source_path in BOUNDARY_SOURCES.items():
        _write_browser_fixture_boundary_geoparquet(
            source_path,
            BOUNDARY_OUTPUTS[role],
            role=role,
            control_path=NODATA_CONTROL_PATH,
            arrow_schema_path=BOUNDARY_ARROW_SCHEMAS_PATH,
        )

    manifest = _read_json(PAYLOAD_ROOT / "manifest.json")
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list):
        raise TypeError("The byte-sealed payload manifest has no artifact list")
    cogs = [item for item in artifacts if item.get("role") == "projection-analysis-cog"]
    target = next(item for item in cogs if item["artifactId"] == MULTICHUNK_ARTIFACT_ID)
    _write_later_chunk_cog(
        PAYLOAD_ROOT / str(target["path"]),
        OVERLAY_ROOT / str(target["path"]),
    )
    _validate_nodata_control(_read_json(NODATA_CONTROL_PATH), cogs)
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
