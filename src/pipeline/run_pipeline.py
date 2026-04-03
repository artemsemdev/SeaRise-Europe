"""Pipeline orchestration CLI (S03-08).

Executes the full geospatial pipeline from download through activation
for all requested scenario x horizon combinations.

Example:
    python -m pipeline.run_pipeline \\
        --scenario ssp1-26 --scenario ssp2-45 --scenario ssp5-85 \\
        --horizon 2030 --horizon 2050 --horizon 2100 \\
        --methodology-version v1.0 \\
        --activate
"""

from __future__ import annotations

import logging
import sys
import time
from pathlib import Path

import click

from .config import (
    BLOB_CONTAINER,
    EUROPE_BBOX,
    LEGEND_COLORMAP,
    get_blob_connection_string,
    get_coastal_zone_path,
    get_download_dir,
    get_output_dir,
    get_postgres_connection_string,
    get_work_dir,
)
from .cogify import cogify
from .compute_exposure import compute_binary_exposure
from .download import download_copernicus_dem, download_ipcc_ar6
from .preprocess import align_to_dem_grid
from .register import (
    activate_methodology_version,
    mark_layer_valid,
    register_layer,
    seed_all,
)
from .upload import upload_cog
from .validate import validate_layer

logger = logging.getLogger("pipeline")

# Status tracking for the summary report.
_STATUS_OK = "PASS"
_STATUS_FAIL = "FAIL"


def _titiler_spot_check(
    blob_path: str, lat: float, lon: float, tiler_url: str
) -> int | None:
    """Query TiTiler /point endpoint for a pixel value.  Returns None if
    TiTiler is unavailable."""
    import urllib.request
    import json as _json

    # Build the TiTiler point URL.
    # TiTiler expects the COG URL — in local dev this is the Azurite URL.
    point_url = (
        f"{tiler_url}/cog/point/{lon},{lat}"
        f"?url=az://{BLOB_CONTAINER}/{blob_path}"
    )
    try:
        with urllib.request.urlopen(point_url, timeout=10) as resp:
            data = _json.loads(resp.read())
            values = data.get("values", data.get("band1"))
            if isinstance(values, list) and values:
                return int(values[0])
            return None
    except Exception as exc:
        logger.warning("TiTiler spot-check unavailable: %s", exc)
        return None


@click.command("run-pipeline")
@click.option(
    "--scenario", "scenarios", multiple=True, required=True,
    help="Scenario ID(s) to process (repeat for multiple).",
)
@click.option(
    "--horizon", "horizons", multiple=True, required=True, type=int,
    help="Horizon year(s) to process (repeat for multiple).",
)
@click.option(
    "--methodology-version", required=True,
    help="Methodology version string (e.g. v1.0).",
)
@click.option(
    "--activate", is_flag=True, default=False,
    help="Activate the methodology version after pipeline completes.",
)
@click.option(
    "--tiler-url", default="http://localhost:8000",
    help="TiTiler base URL for spot-checks.",
)
def run(
    scenarios: tuple[str, ...],
    horizons: tuple[int, ...],
    methodology_version: str,
    activate: bool,
    tiler_url: str,
) -> None:
    """Run the geospatial data pipeline for the specified scenarios and horizons."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    t0 = time.time()
    download_dir = get_download_dir()
    work_dir = get_work_dir()
    output_dir = get_output_dir()
    blob_conn = get_blob_connection_string()
    db_conn = get_postgres_connection_string()
    coastal_zone = get_coastal_zone_path()

    combinations = [(sc, yr) for sc in scenarios for yr in horizons]
    results: list[dict] = []

    click.echo(
        f"Pipeline: {len(combinations)} layers "
        f"({len(scenarios)} scenarios x {len(horizons)} horizons)"
    )
    click.echo(f"Methodology version: {methodology_version}")
    click.echo("")

    # -- Seed metadata -------------------------------------------------------
    click.echo("Seeding reference data ...")
    try:
        seed_all(db_conn, coastal_zone_geojson=coastal_zone)
        click.echo("  Seed data: OK")
    except Exception as exc:
        click.echo(f"  Seed data: FAILED ({exc})", err=True)
        sys.exit(1)

    # -- Download DEM (shared across all combinations) -----------------------
    click.echo("Downloading Copernicus DEM ...")
    try:
        dem_tif = download_copernicus_dem(EUROPE_BBOX, download_dir)
        click.echo(f"  DEM: {dem_tif}")
    except Exception as exc:
        click.echo(f"  DEM download failed: {exc}", err=True)
        sys.exit(1)

    # -- Process each scenario x horizon ------------------------------------
    for sc, yr in combinations:
        label = f"{sc}/{yr}"
        click.echo(f"\n--- {label} ---")
        entry = {"scenario": sc, "horizon": yr, "step": "", "status": ""}

        try:
            # Step 1: Download SLR
            entry["step"] = "download"
            slr_nc = download_ipcc_ar6(sc, yr, download_dir)
            click.echo(f"  1/7 Download:  {slr_nc.name}")

            # Step 2: Align
            entry["step"] = "align"
            aligned_path = work_dir / f"{sc}_{yr}_slr_aligned.tif"
            align_to_dem_grid(slr_nc, dem_tif, sc, yr, aligned_path)
            click.echo(f"  2/7 Align:     {aligned_path.name}")

            # Step 3: Compute exposure
            entry["step"] = "compute"
            raw_path = work_dir / f"{sc}_{yr}_exposure_raw.tif"
            compute_binary_exposure(dem_tif, aligned_path, coastal_zone, raw_path)
            click.echo(f"  3/7 Exposure:  {raw_path.name}")

            # Step 4: COGify
            entry["step"] = "cogify"
            cog_path = output_dir / f"{sc}_{yr}.tif"
            cogify(raw_path, cog_path)
            click.echo(f"  4/7 COGify:    {cog_path.name}")

            # Step 5: Validate
            entry["step"] = "validate"
            validate_layer(cog_path, sc, yr)
            click.echo(f"  5/7 Validate:  PASS")

            # Step 6: Upload
            entry["step"] = "upload"
            blob_path = upload_cog(
                cog_path, sc, yr, methodology_version, blob_conn
            )
            click.echo(f"  6/7 Upload:    {blob_path}")

            # Step 7: Register
            entry["step"] = "register"
            layer_id = register_layer(
                db_conn, sc, yr, methodology_version, blob_path, LEGEND_COLORMAP
            )
            mark_layer_valid(db_conn, layer_id)
            click.echo(f"  7/7 Register:  {layer_id} (valid=true)")

            entry["status"] = _STATUS_OK

        except Exception as exc:
            entry["status"] = _STATUS_FAIL
            entry["error"] = str(exc)
            click.echo(
                f"  FAILED at step '{entry['step']}': {exc}", err=True
            )

        results.append(entry)

    # -- Activation ----------------------------------------------------------
    if activate:
        if all(r["status"] == _STATUS_OK for r in results):
            click.echo(f"\nActivating methodology version {methodology_version} ...")
            activate_methodology_version(db_conn, methodology_version)
            click.echo(f"  Activated: {methodology_version}")
        else:
            click.echo(
                "\nSkipping activation — not all layers passed.", err=True
            )

    # -- TiTiler spot-checks -------------------------------------------------
    click.echo("\n--- TiTiler spot-checks ---")
    # Amsterdam (52.37 N, 4.90 E) — expected: 1 (exposed)
    amsterdam_blob = f"layers/{methodology_version}/ssp2-45/2050.tif"
    amsterdam_val = _titiler_spot_check(
        amsterdam_blob, 52.37, 4.90, tiler_url
    )
    click.echo(
        f"  Amsterdam (52.37, 4.90):  "
        f"{'value=' + str(amsterdam_val) if amsterdam_val is not None else 'TiTiler unavailable (manual check needed)'}"
    )

    # Inland location: Prague (50.08, 14.43) — expected: 0 or NoData
    inland_blob = f"layers/{methodology_version}/ssp2-45/2050.tif"
    inland_val = _titiler_spot_check(
        inland_blob, 50.08, 14.43, tiler_url
    )
    click.echo(
        f"  Prague (50.08, 14.43):    "
        f"{'value=' + str(inland_val) if inland_val is not None else 'TiTiler unavailable (manual check needed)'}"
    )

    # -- Summary report ------------------------------------------------------
    elapsed = time.time() - t0
    passed = sum(1 for r in results if r["status"] == _STATUS_OK)
    failed = sum(1 for r in results if r["status"] == _STATUS_FAIL)

    click.echo(f"\n{'=' * 60}")
    click.echo("PIPELINE SUMMARY")
    click.echo(f"{'=' * 60}")
    click.echo(f"  Total layers:  {len(results)}")
    click.echo(f"  Passed:        {passed}")
    click.echo(f"  Failed:        {failed}")
    click.echo(f"  Elapsed:       {elapsed:.1f}s")
    click.echo(f"{'=' * 60}")

    click.echo(f"\n{'Scenario':<12} {'Horizon':<10} {'Status':<8} {'Note'}")
    click.echo(f"{'-' * 12} {'-' * 10} {'-' * 8} {'-' * 30}")
    for r in results:
        note = r.get("error", "") if r["status"] == _STATUS_FAIL else ""
        click.echo(
            f"{r['scenario']:<12} {r['horizon']:<10} {r['status']:<8} {note}"
        )

    if failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    run()
