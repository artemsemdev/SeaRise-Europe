"""Build and validate a small real-source fixture without classifying exposure."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import platform
import resource
import tempfile
import time
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import rasterio
from rasterio.features import geometry_mask
from rio_cogeo.cogeo import cog_translate, cog_validate
from rio_cogeo.profiles import cog_profiles

from searise_pipeline.science.contracts import (
    load_science_contracts,
    verify_geometry_assets,
)

from .gate import evaluate_methodology_gate
from .lookup import RegionalFixture

ATTRIBUTION = (
    "produced using Copernicus WorldDEM-30 © DLR e.V. 2010-2014 and "
    "© Airbus Defence and Space GmbH 2014-2018 provided under COPERNICUS "
    "by the European Union and ESA; all rights reserved"
)
LIABILITY = (
    "The organisations in charge of the Copernicus programme by law or by "
    "delegation do not incur any liability for any use of the Copernicus WorldDEM-30."
)


class FixtureBuildError(RuntimeError):
    """Real-source bytes or generated evidence do not match the contracts."""


def build_fixture(repo_root: Path, dem_path: Path, fixture_dir: Path) -> Mapping[str, Any]:
    """Build the checked-in mechanics fixture from the exact locked GLO-30 tile."""
    started = time.perf_counter()
    contracts = load_science_contracts(repo_root / "src/pipeline/science")
    verify_geometry_assets(contracts, repo_root)
    gate = evaluate_methodology_gate(contracts)
    if gate.state != "blocked":
        raise FixtureBuildError("this evidence recipe is only valid for the blocked gate")

    recipe_path = fixture_dir / "recipe.json"
    recipe = json.loads(recipe_path.read_text(encoding="utf-8"))
    source = contracts.source_semantics["terrain"]["instances"]["GLO-30"]
    source_size, source_sha = _hash_file(dem_path)
    if source_size != source["sampleByteSize"] or source_sha != source["sampleSha256"]:
        raise FixtureBuildError("DEM source size or SHA-256 differs from the science contract")

    window_spec = recipe["sourceWindow"]
    window = rasterio.windows.Window(
        window_spec["columnOffset"],
        window_spec["rowOffset"],
        window_spec["width"],
        window_spec["height"],
    )
    fixture_dir.mkdir(parents=True, exist_ok=True)
    dem_output = fixture_dir / recipe["outputs"]["demCog"]
    temporary_path: Path | None = None
    with rasterio.open(dem_path) as dataset:
        horizontal_overflow = window.col_off + window.width > dataset.width
        vertical_overflow = window.row_off + window.height > dataset.height
        if horizontal_overflow or vertical_overflow:
            raise FixtureBuildError("source window exceeds the locked DEM tile")
        dem = dataset.read(1, window=window)
        transform = dataset.window_transform(window)
        profile = dataset.profile.copy()
        profile.update(
            driver="GTiff",
            width=int(window.width),
            height=int(window.height),
            transform=transform,
            count=1,
        )
        with tempfile.NamedTemporaryFile(
            dir=fixture_dir, suffix=".tif", delete=False
        ) as temporary:
            temporary_path = Path(temporary.name)
        with rasterio.open(temporary_path, "w", **profile) as output:
            output.write(dem, 1)
            output.update_tags(
                AREA_OR_POINT="Point",
                source_sha256=source_sha,
                source_release=contracts.source_semantics["terrain"]["release"],
                derivative_notice=ATTRIBUTION,
                liability_notice=LIABILITY,
                scientific_use="blocked-domain-mechanics-only",
            )

    assert temporary_path is not None
    cog_profile = cog_profiles.get("deflate")
    cog_profile.update(blockxsize=128, blockysize=128, predictor=3)
    try:
        cog_translate(
            str(temporary_path),
            str(dem_output),
            cog_profile,
            in_memory=False,
            overview_level=0,
            config={"GDAL_TIFF_INTERNAL_MASK": True},
        )
    finally:
        temporary_path.unlink(missing_ok=True)

    cog_valid, cog_errors, cog_warnings = cog_validate(str(dem_output))
    if not cog_valid:
        raise FixtureBuildError(f"derived DEM is not a valid COG: {cog_errors}")
    bounds = rasterio.transform.array_bounds(dem.shape[0], dem.shape[1], transform)
    support_path = repo_root / contracts.geography_rules["support"]["path"]
    coastal_path = repo_root / contracts.geography_rules["coastal"]["path"]
    support = _geometry_mask(support_path, transform, dem.shape)
    coastal = _geometry_mask(coastal_path, transform, dem.shape)
    if np.any(coastal & ~support):
        raise FixtureBuildError("derived coastal mask is not a subset of support")

    fixture = _fixture_document(recipe, source_sha, bounds, support, coastal, gate.to_dict())
    fixture_path = fixture_dir / recipe["outputs"]["lookupFixture"]
    _write_json(fixture_path, fixture)
    RegionalFixture.load(fixture_path)

    golden = _golden_document(recipe["fixtureId"], bounds, support, coastal)
    golden_path = fixture_dir / recipe["outputs"]["goldenVectors"]
    _write_json(golden_path, golden)

    dem_size, dem_sha = _hash_file(dem_output)
    receipt = {
        "schemaVersion": 1,
        "fixtureId": recipe["fixtureId"],
        "buildKind": "real-source-domain-mechanics-only",
        "methodologyGate": _gate_receipt(gate.to_dict()),
        "source": {
            "sourceId": contracts.source_semantics["terrain"]["sourceId"],
            "release": contracts.source_semantics["terrain"]["release"],
            "asset": source["sampleAsset"],
            "byteSize": source_size,
            "sha256": source_sha,
            "verticalCrs": contracts.source_semantics["terrain"]["verticalCrs"],
            "attribution": ATTRIBUTION,
            "liability": LIABILITY,
        },
        "window": window_spec,
        "demStatistics": {
            "minimumMetres": float(np.min(dem)),
            "medianMetres": float(np.median(dem)),
            "maximumMetres": float(np.max(dem)),
            "negativeCellCount": int(np.count_nonzero(dem < 0)),
            "cellCount": int(dem.size),
        },
        "outputs": {
            recipe["outputs"]["demCog"]: {
                "byteSize": dem_size,
                "sha256": dem_sha,
                "cogValid": True,
                "cogWarnings": list(cog_warnings),
            },
            recipe["outputs"]["lookupFixture"]: _file_record(fixture_path),
            recipe["outputs"]["goldenVectors"]: _file_record(golden_path),
        },
        "measurements": {
            "sourceBytes": source_size,
            "workingArrayBytes": int(dem.nbytes + support.nbytes + coastal.nbytes),
            "elapsedSeconds": round(time.perf_counter() - started, 6),
            "peakResidentBytes": _peak_resident_bytes(),
        },
        "software": {
            "python": platform.python_version(),
            "numpy": np.__version__,
            "rasterio": rasterio.__version__,
        },
    }
    _write_json(fixture_dir / recipe["outputs"]["buildReceipt"], receipt)
    return receipt


def validate_fixture(fixture_dir: Path) -> None:
    """Validate checksums, the COG, and the fail-closed lookup artifact."""
    recipe = json.loads((fixture_dir / "recipe.json").read_text(encoding="utf-8"))
    receipt = json.loads(
        (fixture_dir / recipe["outputs"]["buildReceipt"]).read_text(encoding="utf-8")
    )
    if receipt["methodologyGate"]["state"] != "blocked":
        raise FixtureBuildError("committed fixture must record the current blocked gate")
    if receipt["methodologyGate"]["generatedScientificArtifacts"]:
        raise FixtureBuildError("blocked fixture must not contain scientific classifications")
    for name, record in receipt["outputs"].items():
        size, digest = _hash_file(fixture_dir / name)
        if size != record["byteSize"] or digest != record["sha256"]:
            raise FixtureBuildError(f"output checksum mismatch: {name}")
    valid, errors, _ = cog_validate(str(fixture_dir / recipe["outputs"]["demCog"]))
    if not valid:
        raise FixtureBuildError(f"invalid committed DEM COG: {errors}")
    RegionalFixture.load(fixture_dir / recipe["outputs"]["lookupFixture"])


def _geometry_mask(path: Path, transform: rasterio.Affine, shape_: tuple[int, int]) -> np.ndarray:
    document = json.loads(path.read_text(encoding="utf-8"))
    return np.asarray(
        geometry_mask(
            [feature["geometry"] for feature in document["features"]],
            out_shape=shape_,
            transform=transform,
            all_touched=False,
            invert=True,
        ),
        dtype=np.bool_,
    )


def _fixture_document(
    recipe: Mapping[str, Any],
    source_sha: str,
    bounds: tuple[float, float, float, float],
    support: np.ndarray,
    coastal: np.ndarray,
    gate: Mapping[str, Any],
) -> Mapping[str, Any]:
    west, south, east, north = bounds
    blocked_by = gate["blockers"]
    layers = {
        f"{item['scenario']}/{item['horizon']}": {
            "status": "blocked",
            "blockedBy": blocked_by,
        }
        for item in gate["layers"]
    }
    return {
        "schemaVersion": 1,
        "fixtureId": recipe["fixtureId"],
        "purpose": "real-source-domain-mechanics-only-not-scientific-classification",
        "sourceSha256": source_sha,
        "grid": {
            "width": int(support.shape[1]),
            "height": int(support.shape[0]),
            "west": west,
            "south": south,
            "east": east,
            "north": north,
            "longitude_convention": "minus-180-to-180",
            "edge_rule": "west-north-inclusive-east-south-exclusive",
        },
        "supportMask": _encode(support.astype(np.uint8).tobytes()),
        "coastalMask": _encode(coastal.astype(np.uint8).tobytes()),
        "layers": layers,
    }


def _gate_receipt(gate: Mapping[str, Any]) -> Mapping[str, Any]:
    first_layer = gate["layers"][0]
    return {
        "state": gate["state"],
        "decision": gate["decision"],
        "blockers": gate["blockers"],
        "missingEvidence": gate["missingEvidence"],
        "sourceLineage": first_layer["sourceLineage"],
        "layerMatrix": [
            {
                "scenario": item["scenario"],
                "horizon": item["horizon"],
                "status": item["status"],
            }
            for item in gate["layers"]
        ],
        "generatedScientificArtifacts": gate["generatedScientificArtifacts"],
        "unlocksPhase1": gate["unlocksPhase1"],
    }


def _golden_document(
    fixture_id: str,
    bounds: tuple[float, float, float, float],
    support: np.ndarray,
    coastal: np.ndarray,
) -> Mapping[str, Any]:
    west, south, east, north = bounds
    candidates = np.argwhere(support & coastal)
    if len(candidates) == 0:
        raise FixtureBuildError("regional window has no in-scope real-source cell")
    row, column = (int(value) for value in candidates[len(candidates) // 2])
    longitude = west + (column + 0.5) * (east - west) / support.shape[1]
    latitude = north - (row + 0.5) * (north - south) / support.shape[0]
    vectors = [
        {
            "id": f"blocked-{scenario}-{horizon}",
            "longitude": longitude,
            "latitude": latitude,
            "scenario": scenario,
            "horizon": horizon,
            "expectedState": "data-unavailable",
            "expectedCell": {"row": row, "column": column},
            "purpose": "blocked-layer-parity-only",
        }
        for scenario in ("ssp1-26", "ssp2-45", "ssp5-85")
        for horizon in (2030, 2050, 2100)
    ]
    vectors.extend(
        [
            {
                "id": "west-outside-regional-artifact",
                "longitude": west - (east - west) / support.shape[1],
                "latitude": latitude,
                "scenario": "ssp2-45",
                "horizon": 2050,
                "expectedState": "unsupported-geography",
                "expectedCell": None,
                "purpose": "regional-grid-edge-parity-only",
            },
            {
                "id": "east-exclusive-edge",
                "longitude": east,
                "latitude": latitude,
                "scenario": "ssp2-45",
                "horizon": 2050,
                "expectedState": "unsupported-geography",
                "expectedCell": None,
                "purpose": "regional-grid-edge-parity-only",
            },
        ]
    )
    return {
        "schemaVersion": 1,
        "fixtureId": fixture_id,
        "classificationStatus": "blocked",
        "review": {"status": "pending", "requiredRole": "scientific/data reviewer"},
        "vectors": vectors,
    }


def _encode(values: bytes) -> Mapping[str, Any]:
    return {
        "encoding": "base64-uint8-row-major",
        "data": base64.b64encode(values).decode("ascii"),
        "sha256": hashlib.sha256(values).hexdigest(),
    }


def _file_record(path: Path) -> Mapping[str, Any]:
    size, digest = _hash_file(path)
    return {"byteSize": size, "sha256": digest}


def _hash_file(path: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            size += len(chunk)
            digest.update(chunk)
    return size, digest.hexdigest()


def _write_json(path: Path, document: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _peak_resident_bytes() -> int:
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(peak if platform.system() == "Darwin" else peak * 1024)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--fixture-dir", type=Path, required=True)
    parser.add_argument("--dem", type=Path)
    parser.add_argument("--validate", action="store_true")
    args = parser.parse_args()
    if args.validate:
        validate_fixture(args.fixture_dir)
    elif args.dem:
        build_fixture(args.repo_root, args.dem, args.fixture_dir)
    else:
        parser.error("--dem is required unless --validate is used")


if __name__ == "__main__":
    main()
