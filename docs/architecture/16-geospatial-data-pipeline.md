# 16 — Geospatial Data Pipeline

> **Status:** Implemented
> **Scope:** The offline pipeline that transforms raw climate and elevation data into Cloud-Optimized GeoTIFF (COG) exposure layers. This is **not a runtime service** — it runs on demand before Phase 0 and on methodology version updates.
> **Dependencies:** ADR-015 (exposure methodology — binary v1.0), ADR-016 (scenario set — ssp1-26, ssp2-45, ssp5-85), ADR-018 (coastal analysis zone — Copernicus Coastal Zones 2018)

---

## 1. Pipeline Purpose and Context

The runtime API serves precomputed binary raster layers. These layers are the output of the offline pipeline. The pipeline:

1. Downloads raw data from public sources (IPCC AR6 projections, Copernicus DEM)
2. Processes the data to compute exposure zones per scenario × horizon
3. Converts the output to Cloud-Optimized GeoTIFF format
4. Uploads to Azure Blob Storage
5. Registers the layer metadata in PostgreSQL

**The pipeline runs:**
- Phase 0: Bootstrap (first data generation for all scenarios × horizons)
- On methodology version change (e.g., new IPCC data release, revised threshold)
- Optionally: on a schedule to incorporate updated source data

**The pipeline does NOT run at request time.** All assessment results are derived from precomputed layers.

---

## 2. Input Data Sources

### 2.1 IPCC AR6 Sea-Level Projections

| Property | Value |
|---|---|
| Source | NASA Sea Level Change Team |
| URL | https://sealevel.nasa.gov/ipcc-ar6-sea-level-projection-tool |
| Format | NetCDF (.nc) |
| Coverage | Global; Europe subset extracted |
| Scenarios | SSP1-2.6, SSP2-4.5, SSP5-8.5 (ADR-016: confirmed) |
| Time horizons | Median projections for 2030, 2050, 2100 (FR-015) |
| Units | Meters (sea-level rise above 2020 baseline) |
| License | CC BY 4.0 (cite in `methodology_versions.sea_level_source_name`) |

**Key value extracted:** For each scenario+horizon, a spatial grid of projected mean sea-level rise values (meters) at each grid point.

### 2.2 Copernicus Digital Elevation Model (DEM)

| Property | Value |
|---|---|
| Source | Copernicus Land Monitoring Service / DLR |
| URL | https://dataspace.copernicus.eu/explore-data/data-collections/copernicus-contributing-missions/collections-description/COP-DEM |
| Product | GLO-30 (30m resolution, global) |
| Format | GeoTIFF tiles |
| Coverage | Europe coverage used |
| Units | Meters above sea level (ellipsoidal height) |
| License | See Copernicus DEM license; attribution required |
| Note | This is a Digital Surface Model (DSM) — includes vegetation and buildings (documented in `resolutionNote`) |

**Key value:** Terrain elevation in meters at each ~30m grid cell.

---

## 3. Processing Logic (ADR-015 Confirmed)

> **Confirmed (ADR-015):** Binary exposure methodology approved. A location is "exposed" if the projected mean sea-level rise meets or exceeds the terrain elevation within the coastal analysis zone.

### 3.1 Conceptual Algorithm

```python
# For each scenario (e.g., ssp2-45) and horizon (e.g., 2050):
#
# 1. Get SLR value for this scenario+horizon at each grid point
#    slr_grid[lat, lon] = projected sea-level rise (meters)
#
# 2. Get terrain elevation at each grid point
#    dem[lat, lon] = terrain elevation (meters above sea level)
#
# 3. Compute exposure: location is exposed if SLR ≥ DEM elevation
#    exposure[lat, lon] = 1 if slr_grid[lat, lon] >= dem[lat, lon] else 0
#
# 4. Mask: apply coastal analysis zone mask (ADR-018: Copernicus Coastal Zones 2018)
#    NoData outside coastal_analysis_zone
#
# Result: binary raster (0 = not exposed, 1 = exposed, NoData = out of zone)
```

**Note on interpretation:** This is a simplified static inundation model. It does NOT account for flood defenses, hydrodynamic connectivity, or storm surge (documented in `whatItDoesNotAccountFor` — CONTENT_GUIDELINES §5).

### 3.2 Spatial Resolution and Alignment

- IPCC AR6 projections are on a coarse grid (~0.25° or ~25km)
- Copernicus DEM is at 30m resolution
- Approach: interpolate IPCC SLR values to DEM grid resolution (nearest-neighbor or bilinear)
- Output CRS: **EPSG:4326** (WGS84 geographic) — required for TiTiler and MapLibre compatibility

---

## 4. Pipeline Technology Stack

| Component | Technology | Purpose |
|---|---|---|
| Runtime | Python 3.11+ | Scripting, orchestration |
| Raster I/O | `rasterio` | Read/write GeoTIFF; CRS handling |
| NetCDF I/O | `xarray` + `netCDF4` | Read IPCC AR6 projection data |
| Raster analysis | `numpy` | Array operations (SLR ≥ DEM comparison) |
| COG conversion | `rio-cogeo` | Validate and convert output to COG format |
| Geospatial | `GDAL` (via rasterio) | Reproject, resample, warp |
| Spatial analysis | `geopandas` / `shapely` | Coastal zone masking (ADR-018: Copernicus Coastal Zones 2018) |
| Upload | `azure-storage-blob` (Python SDK) | Upload COGs to Azure Blob Storage |
| DB registration | `psycopg2` or `asyncpg` | INSERT into `layers` table |

### 4.1 Environment Setup

```bash
# requirements-pipeline.txt
rasterio>=1.3
rio-cogeo>=3.0
xarray>=2024.0
netCDF4>=1.6
numpy>=1.26
geopandas>=0.14
shapely>=2.0
azure-storage-blob>=12.0
psycopg2-binary>=2.9
click>=8.0          # CLI argument parsing
```

---

## 5. Pipeline Steps (Detailed)

### Step 1: Download Source Data

```python
# pipeline/download.py

def download_ipcc_ar6(scenario: str, horizon: int, output_dir: Path) -> Path:
    """
    Download IPCC AR6 SLR projection data for a specific scenario.
    Source: NASA Sea Level Change portal (AR6 netCDF files).
    Returns: path to downloaded .nc file
    """
    ...

def download_copernicus_dem(bbox: tuple, output_dir: Path) -> Path:
    """
    Download Copernicus DEM GLO-30 tiles covering the bounding box.
    Mosaic tiles into a single GeoTIFF for the processing extent.
    Returns: path to mosaicked DEM GeoTIFF
    """
    ...
```

**Source data is cached locally** — re-running the pipeline does not re-download if files exist.

---

### Step 2: Reproject and Align

```python
# pipeline/preprocess.py

def align_to_dem_grid(slr_nc: Path, dem_tif: Path, output_tif: Path):
    """
    Interpolate IPCC SLR projection to match DEM spatial grid.
    - Reprojects SLR from WGS84 geographic to match DEM
    - Resamples to DEM resolution (~30m)
    - Output: SLR values (float32) on DEM grid
    """
    import rasterio
    from rasterio.warp import reproject, Resampling

    with rasterio.open(dem_tif) as dem:
        target_crs = dem.crs       # EPSG:4326
        target_transform = dem.transform
        target_shape = dem.shape

    # Read IPCC AR6 median SLR for this scenario+horizon from NetCDF
    slr_array = extract_slr_from_netcdf(slr_nc, scenario, horizon)  # [lat, lon] float array

    # Reproject SLR array to DEM grid
    reproject(
        source=slr_array,
        src_crs=source_crs,
        src_transform=source_transform,
        destination=aligned_slr,
        dst_crs=target_crs,
        dst_transform=target_transform,
        dst_shape=target_shape,
        resampling=Resampling.bilinear
    )
    ...
```

---

### Step 3: Compute Exposure

```python
# pipeline/compute_exposure.py

def compute_binary_exposure(
    dem_tif: Path,
    slr_tif: Path,        # SLR values aligned to DEM grid
    coastal_zone_geom,    # shapely geometry for coastal_analysis_zone (ADR-018)
    output_tif: Path
):
    """
    Compute binary exposure raster:
      1 = SLR projection >= terrain elevation (exposed)
      0 = SLR projection < terrain elevation (not exposed)
      NoData = outside coastal_analysis_zone
    """
    import numpy as np
    import rasterio
    from rasterio.mask import mask as raster_mask

    with rasterio.open(dem_tif) as dem_src, rasterio.open(slr_tif) as slr_src:
        dem = dem_src.read(1, masked=True)   # terrain elevation (masked array)
        slr = slr_src.read(1, masked=True)   # sea-level rise projection

        # Binary comparison: exposed where SLR >= terrain elevation
        # ADR-015: binary exposure — SLR >= DEM (no separate threshold)
        exposure = np.where(
            dem.mask | slr.mask,            # NoData regions
            np.nan,
            np.where(slr >= dem, 1, 0)     # 1 = exposed, 0 = not exposed
        ).astype('float32')

        profile = dem_src.profile.copy()
        profile.update(dtype='float32', nodata=np.nan)

    # Mask to coastal analysis zone only
    with rasterio.open(output_tif, 'w', **profile) as dst:
        dst.write(exposure, 1)

    apply_coastal_zone_mask(output_tif, coastal_zone_geom)
```

---

### Step 4: Convert to Cloud-Optimized GeoTIFF

```python
# pipeline/cogify.py
from rio_cogeo.cogeo import cog_translate
from rio_cogeo.profiles import cog_profiles

def cogify(input_tif: Path, output_cog: Path):
    """
    Convert GeoTIFF to Cloud-Optimized GeoTIFF with:
    - Internal overviews (for fast tile serving at all zoom levels)
    - Tiled layout (256x256 tiles, required for efficient range requests)
    - Deflate compression (lossless, small file size)
    - EPSG:4326 (required for TiTiler + MapLibre compatibility)
    """
    cog_profile = cog_profiles.get("deflate")
    cog_profile.update({
        "blockxsize": 256,
        "blockysize": 256,
        "overview_resampling": "nearest",  # Binary values — nearest is correct
        "overview_level": [2, 4, 8, 16, 32, 64, 128],
    })

    cog_translate(
        input=str(input_tif),
        output=str(output_cog),
        profile=cog_profile,
        in_memory=False,
        config={"GDAL_TIFF_INTERNAL_MASK": True}
    )

    # Validate the output is a valid COG
    from rio_cogeo.cogeo import cog_validate
    is_valid, errors, warnings = cog_validate(str(output_cog))
    if not is_valid:
        raise ValueError(f"COG validation failed: {errors}")
```

---

### Step 5: QA Validation

```python
# pipeline/validate.py

def validate_layer(cog_path: Path, scenario: str, horizon: int) -> bool:
    """
    QA checks before marking layer as valid in the database.
    Returns True if all checks pass.
    """
    import rasterio
    import numpy as np
    from rio_cogeo.cogeo import cog_validate

    # Check 1: Valid COG structure
    is_valid, errors, _ = cog_validate(str(cog_path))
    assert is_valid, f"Not a valid COG: {errors}"

    # Check 2: CRS is EPSG:4326
    with rasterio.open(cog_path) as src:
        assert src.crs.to_epsg() == 4326, f"Expected EPSG:4326, got {src.crs}"

        # Check 3: Binary pixel values (0, 1, NoData only)
        data = src.read(1, masked=True)
        unique_values = set(np.unique(data.compressed()).astype(int))
        assert unique_values.issubset({0, 1}), f"Non-binary pixel values: {unique_values}"

        # Check 4: File is not empty (has at least some exposure area)
        exposure_pixels = np.sum(data.compressed() == 1)
        assert exposure_pixels > 0, "No exposure pixels found — suspicious"

        # Check 5: Spatial extent covers expected area (Europe coastal zone)
        bounds = src.bounds
        assert bounds.left >= -30 and bounds.right <= 40, "Unexpected extent"
        assert bounds.bottom >= 30 and bounds.top <= 75, "Unexpected extent"

    return True
```

---

### Step 6: Upload to Azure Blob Storage

```python
# pipeline/upload.py
from azure.storage.blob import BlobServiceClient

def upload_cog(
    cog_path: Path,
    scenario: str,
    horizon: int,
    methodology_version: str,
    connection_string: str
) -> str:
    """
    Upload COG to Azure Blob Storage.
    Returns: blob_path for registration in database.
    """
    # Blob path convention: layers/{version}/{scenario}/{horizon}.tif
    blob_path = f"layers/{methodology_version}/{scenario}/{horizon}.tif"

    client = BlobServiceClient.from_connection_string(connection_string)
    blob = client.get_blob_client(container="geospatial", blob=blob_path)

    blob.upload_blob(
        cog_path.read_bytes(),
        overwrite=True,
        content_settings=ContentSettings(
            content_type="image/tiff",
            cache_control="max-age=86400, public"
        )
    )

    return blob_path
```

---

### Step 7: Register Layer in PostgreSQL

```python
# pipeline/register.py
import psycopg2

def register_layer(
    conn_string: str,
    scenario_id: str,
    horizon_year: int,
    methodology_version: str,
    blob_path: str,
    legend_colormap: dict
) -> str:
    """
    Insert layer record into PostgreSQL with layer_valid=False.
    Returns: UUID of inserted layer row.
    """
    conn = psycopg2.connect(conn_string)
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO layers
                (scenario_id, horizon_year, methodology_version, blob_path, generated_at, legend_colormap)
            VALUES (%s, %s, %s, %s, now(), %s)
            ON CONFLICT (scenario_id, horizon_year, methodology_version)
            DO UPDATE SET
                blob_path = EXCLUDED.blob_path,
                generated_at = EXCLUDED.generated_at,
                layer_valid = false,
                legend_colormap = EXCLUDED.legend_colormap
            RETURNING id
        """, (scenario_id, horizon_year, methodology_version, blob_path,
              json.dumps(legend_colormap)))
        layer_id = cur.fetchone()[0]
    conn.commit()
    return str(layer_id)


def mark_layer_valid(conn_string: str, layer_id: str):
    """Called after QA validation passes."""
    conn = psycopg2.connect(conn_string)
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE layers SET layer_valid = true WHERE id = %s",
            (layer_id,)
        )
    conn.commit()
```

---

## 6. Pipeline Orchestration

The full pipeline is orchestrated by a CLI script:

```python
# pipeline/run_pipeline.py
import click

@click.command()
@click.option('--scenario', multiple=True, help='Scenario ID(s) to process')
@click.option('--horizon', multiple=True, type=int, help='Horizon year(s) to process')
@click.option('--methodology-version', required=True)
@click.option('--activate', is_flag=True, help='Activate new version after pipeline completes')
def run(scenario, horizon, methodology_version, activate):
    """
    Run the geospatial data pipeline for the specified scenarios and horizons.

    Example:
        python run_pipeline.py \\
            --scenario ssp1-26 --scenario ssp2-45 --scenario ssp5-85 \\
            --horizon 2030 --horizon 2050 --horizon 2100 \\
            --methodology-version v1.0
    """
    for sc in scenario:
        for yr in horizon:
            click.echo(f"Processing {sc} / {yr}...")

            # Step 1: Download
            slr_nc = download_ipcc_ar6(sc, yr, DOWNLOAD_DIR)
            dem_tif = download_copernicus_dem(EUROPE_BBOX, DOWNLOAD_DIR)

            # Step 2: Preprocess
            aligned_slr = align_to_dem_grid(slr_nc, dem_tif, WORK_DIR / f"{sc}_{yr}_slr.tif")

            # Step 3: Compute exposure
            raw_exposure = compute_binary_exposure(
                dem_tif, aligned_slr, COASTAL_ZONE_GEOM, WORK_DIR / f"{sc}_{yr}_raw.tif")

            # Step 4: COGify
            cog_path = OUTPUT_DIR / f"{sc}_{yr}.tif"
            cogify(raw_exposure, cog_path)

            # Step 5: QA
            assert validate_layer(cog_path, sc, yr), f"QA failed for {sc}/{yr}"

            # Step 6: Upload
            blob_path = upload_cog(cog_path, sc, yr, methodology_version, BLOB_CONN_STR)

            # Step 7: Register
            layer_id = register_layer(DB_CONN_STR, sc, yr, methodology_version, blob_path,
                                       LEGEND_COLORMAP)
            mark_layer_valid(DB_CONN_STR, layer_id)
            click.echo(f"  ✓ Layer {layer_id} registered and validated")

    if activate:
        activate_methodology_version(DB_CONN_STR, methodology_version)
        click.echo(f"✓ Methodology version {methodology_version} activated")
```

---

## 7. Pipeline Execution Environments

| Environment | When | How |
|---|---|---|
| Developer workstation | Phase 0 bootstrap, testing | `python run_pipeline.py ...` with local `.env` |
| GitHub Actions (manual trigger) | Data refresh | `workflow_dispatch` event; Azure credentials via repository secrets |
| Azure Container Instance | Scheduled run | Disposable container; run-to-completion |

**Estimated run time:** Downloading and processing 9 combinations (3 scenarios × 3 horizons) at 30m resolution for Europe: approximately 30–90 minutes (dominated by DEM download and raster computation).

---

## 8. COG File Properties

Each output COG must have:

| Property | Value | Reason |
|---|---|---|
| CRS | EPSG:4326 (WGS84) | TiTiler requires geographic CRS for XYZ tile serving |
| Pixel type | Float32 (0.0, 1.0, NaN) | Rasterio binary; NaN = NoData |
| Compression | Deflate | Lossless; good compression ratio for binary rasters |
| Tile size | 256×256 | Standard for HTTP range request efficiency |
| Overview levels | 2, 4, 8, 16, 32, 64, 128 | Zoom levels 0–14 served efficiently |
| File size (estimate) | 1–10 MB per scenario+horizon | Depends on coastal zone extent |
| Spatial extent | Europe coastal zone | No global data needed |

---

## 9. Blob Storage Layout

```
Container: geospatial (private)
  layers/
    v1.0/                         ← methodology_version
      ssp1-26/                    ← scenario_id
        2030.tif                  ← COG for horizon 2030
        2050.tif
        2100.tif
      ssp2-45/
        2030.tif
        2050.tif
        2100.tif
      ssp5-85/
        2030.tif
        2050.tif
        2100.tif
    v2.0/                         ← future methodology version
      ...
```

**Path construction** (used by both pipeline upload and API layer resolution):
```python
blob_path = f"layers/{methodology_version}/{scenario_id}/{horizon_year}.tif"
```

---

## 10. Legend Colormap

Each layer is stored with a `legend_colormap` (JSONB in `layers` table) used by:
- The API to return `legendSpec` in the assess response
- TiTiler URL parameters (`colormap` param for tile colorization)

**Default colormap for binary exposure:**
```json
{
  "colorStops": [
    { "value": 1, "color": "#E85D04", "label": "Modeled exposure zone" }
  ]
}
```

**TiTiler colormap URL parameter:**
```
&colormap={"1":[232,93,4,255]}    ← RGB(A) for value 1
```

The colormap is stored per-layer (not hardcoded in the API) so it can be updated when a new methodology version introduces a different visual convention.

---

## 11. Methodology Version Activation

After all layers for a new version are uploaded and validated, the version is activated atomically:

```sql
BEGIN;
  UPDATE methodology_versions SET is_active = false WHERE is_active = true;
  UPDATE methodology_versions SET is_active = true WHERE version = 'v1.0';
COMMIT;
```

This is the **only** step that makes new layers visible to users. No container restart required.

To roll back: run the same transaction swapping the version strings.

---

## 12. Pipeline Checklist (Pre-Activation)

- [ ] All 9 COG files generated (3 scenarios × 3 horizons: ssp1-26, ssp2-45, ssp5-85 — ADR-016)
- [ ] All COGs pass `rio-cogeo validate` (no errors)
- [ ] All COGs are EPSG:4326
- [ ] All COGs contain only binary pixel values (0, 1, NoData)
- [ ] All COGs have exposure pixels (non-empty)
- [ ] All COGs uploaded to `geospatial` container in correct paths
- [ ] All `layers` rows in PostgreSQL have `layer_valid = true`
- [ ] `methodology_versions` row for `v1.0` exists with all required fields populated
- [ ] Spot-check: TiTiler `/point` returns expected pixel value for Amsterdam (should be 1)
- [ ] Spot-check: TiTiler `/point` returns 0 for an inland coastal zone location
- [ ] Spot-check: tile request returns visible red overlay for known exposure location
- [ ] Methodology version activated atomically
