# Epic 03 — Geospatial Data Pipeline

| Field          | Value                                                                                              |
| -------------- | -------------------------------------------------------------------------------------------------- |
| Epic ID        | E-03                                                                                               |
| Phase          | 0 — Implementation Complete                                                                        |
| Status         | Done                                                                                               |
| Effort         | ~7 days                                                                                            |
| Dependencies   | Epic 01 (methodology decisions from OQ-02, OQ-04, OQ-05), Epic 02 (local PostgreSQL + local blob storage via Docker Compose) |
| Stories        | 8 (S03-01 through S03-08)                                                                          |
| Risk           | HIGHEST — produces the COG exposure layers that the entire application serves                      |

---

## 1  Objective

Build and execute the offline geospatial pipeline that transforms raw IPCC AR6 sea-level projections and Copernicus DEM elevation data into Cloud-Optimized GeoTIFF (COG) exposure layers, upload them to local blob storage (Azurite or filesystem), and register them in local PostgreSQL with a valid methodology version.

> **Local-first note (v0.2):** During this epic, all outputs go to the local Docker Compose environment (Azurite for blob storage, local PostgreSQL). The actual upload to Azure Blob Storage happens in Epic 08 (S08-03). References to "Azure Blob Storage" in this document describe the target path structure and contract — during development, the same structure is replicated locally.

---

## 2  Why This Epic Exists

Every user-facing result in SeaRise Europe is derived from precomputed COG layers. The API resolves exposure by reading pixel values from these layers via TiTiler. The frontend renders overlay tiles from these layers. If the layers do not exist, are malformed, or are incorrectly registered, the application has nothing to serve. This is the highest risk epic in Phase 0 because it sits on the critical path between raw climate data and a functioning product. Every downstream epic — backend API, frontend map, methodology panel — depends on the pipeline producing correct, validated, accessible COG files.

---

## 3  Scope

### 3.1 In Scope

- Pipeline project scaffolding (directory structure, dependencies, configuration).
- Download and local caching of IPCC AR6 NetCDF projections and Copernicus DEM GeoTIFF tiles.
- Reprojection and alignment of SLR data to DEM grid at 30m resolution.
- Binary exposure computation (SLR >= DEM) with coastal zone masking.
- COG conversion with deflate compression, 256x256 tiles, and overview levels.
- QA validation of all output COGs (5 checks per layer).
- Upload to Azure Blob Storage with correct paths, content-type, and cache-control headers.
- Layer registration in PostgreSQL with legend colormap.
- Methodology version seeding and atomic activation.
- Scenario, horizon, and geography boundary seeding from Epic 01 specifications.
- CLI orchestration for full pipeline execution.
- End-to-end validation including TiTiler spot-checks.

### 3.2 Out of Scope

- Runtime tile serving (Epic 04/05 concern — TiTiler configuration).
- Flood defense modeling, hydrodynamic connectivity, storm surge, tidal variation, local subsidence, or drainage infrastructure.
- Continuous or probabilistic exposure models (MVP uses binary).
- Automated scheduled re-runs (future concern).
- Non-European geographic coverage.
- COG serving via CDN (future optimization).

---

## 4  Blocking Open Questions

This epic consumes decisions made in Epic 01. It does not introduce new open questions but is blocked until the following are resolved:

| OQ   | Question                                    | Consumed From | Impact on This Epic                          |
| ---- | ------------------------------------------- | ------------- | -------------------------------------------- |
| OQ-02 | MVP scenario set (exact IDs)               | S01-01        | Determines which IPCC projections to download and how many COGs to produce |
| OQ-04 | Coastal analysis zone geometry             | S01-03        | Required for the coastal zone mask applied in Step 3 |
| OQ-05 | Exposure methodology (binary vs. continuous)| S01-04        | Determines the pixel comparison logic in Step 3 |

---

## 5  Traceability

### 5.1 Product Requirement Traceability

| Requirement | Description                                           |
| ----------- | ----------------------------------------------------- |
| FR-015      | Time horizons 2030, 2050, 2100                        |
| FR-035      | Methodology version visible to users                  |
| BR-010      | Result states depend on valid layers existing          |
| BR-011      | Exposure methodology — binary result interpretation    |
| BR-012      | Exposure methodology — threshold definition            |
| BR-014      | No substitution of scenario/horizon combinations       |
| BR-015      | Methodology version always present in responses        |
| NFR-020     | COG or PMTiles format for raster layers                |
| NFR-021     | Methodology versioning                                 |
| NFR-022     | Reproducibility of exposure results                    |

### 5.2 Architecture Traceability

| Architecture Document                                      | Relevance                                      |
| ---------------------------------------------------------- | ---------------------------------------------- |
| `docs/architecture/16-geospatial-data-pipeline.md`         | Primary reference — all pipeline logic          |
| `docs/architecture/05-data-architecture.md`                | Schema definitions for layers, methodology_versions, scenarios, horizons, geography_boundaries |
| `docs/architecture/08-deployment-topology.md`              | Blob Storage and PostgreSQL deployment targets  |
| `docs/architecture/07-security-architecture.md`            | Blob connection string and DB credentials       |
| `docs/architecture/13-domain-model.md`                     | ResultState and layer validity semantics        |

---

## 6  Implementation Plan

Work through stories in the following order. S03-01 is the foundation. S03-02 through S03-05 form a strict sequential chain (each step's output is the next step's input). S03-06 and S03-07 depend on S03-05 output. S03-08 ties everything together.

1. **S03-01 — Set Up Pipeline Project and Dependencies.** Scaffolding. Must be first.
2. **S03-02 — Download and Cache Source Data.** Requires S03-01 project structure.
3. **S03-03 — Reproject and Align SLR to DEM Grid.** Requires S03-02 downloaded data.
4. **S03-04 — Compute Binary Exposure Rasters.** Requires S03-03 aligned SLR output.
5. **S03-05 — COGify and QA Validate.** Requires S03-04 raw exposure rasters.
6. **S03-06 — Upload COGs to Azure Blob Storage.** Requires S03-05 validated COGs. Can start once first COG passes QA.
7. **S03-07 — Register Layers and Seed Metadata in PostgreSQL.** Requires S03-06 blob paths. Also seeds scenarios, horizons, geography boundaries, and methodology version.
8. **S03-08 — Pipeline Orchestration CLI and End-to-End Validation.** Integrates all steps. Must be last.

### Execution Order Map

```
S03-01 (Project Setup)
  │
  └──► S03-02 (Download Source Data)
         │
         └──► S03-03 (Reproject + Align)
                │
                └──► S03-04 (Compute Exposure)
                       │
                       └──► S03-05 (COGify + QA)
                              │
                              └──► S03-06 (Upload to Blob)
                                     │
                                     └──► S03-07 (Register in PostgreSQL)
                                            │
                                            └──► S03-08 (CLI Orchestration + E2E Validation)
```

**Rationale:** This is a strictly sequential pipeline — each step consumes the output of the previous step. There is no parallelism possible within this epic because the data flows linearly: raw download → aligned grid → exposure raster → COG → Blob → database → integration test. S03-08 must be last because it validates the integrated pipeline end-to-end including TiTiler spot-checks.

---

## 7  User Stories

---

### S03-01 — Set Up Pipeline Project and Dependencies

| Field          | Value                  |
| -------------- | ---------------------- |
| ID             | S03-01                 |
| Type           | Platform               |
| Effort         | ~0.5 days              |
| Dependencies   | Epic 02 S02-01 (local Docker Compose environment exists) |

**Statement**

As the engineer maintaining delivery quality, I want the pipeline project scaffolded with a clear directory structure, dependency file, and environment configuration template, so that all subsequent pipeline stories can be developed against a consistent, reproducible foundation.

**Why**

The pipeline is a standalone Python project with specific dependencies (rasterio, rio-cogeo, xarray, netCDF4, numpy, geopandas, shapely, azure-storage-blob, psycopg2, click). Without a clean project structure and pinned dependencies, each pipeline step risks incompatible library versions, missing imports, or configuration drift. Setting this up first avoids compounding problems across later stories.

**Scope Notes**

- Create `pipeline/` directory at the repository root.
- Create `pipeline/requirements-pipeline.txt` with all dependencies and minimum versions as specified in `docs/architecture/16-geospatial-data-pipeline.md` section 4.1.
- Create module stubs: `pipeline/download.py`, `pipeline/preprocess.py`, `pipeline/compute_exposure.py`, `pipeline/cogify.py`, `pipeline/validate.py`, `pipeline/upload.py`, `pipeline/register.py`, `pipeline/run_pipeline.py`.
- Create `.env.pipeline.example` documenting required environment variables: `AZURE_STORAGE_CONNECTION_STRING`, `POSTGRES_CONNECTION_STRING`, `DOWNLOAD_DIR`, `WORK_DIR`, `OUTPUT_DIR`.
- Verify all dependencies install cleanly in a fresh virtual environment.

**Traceability**

- Architecture: `docs/architecture/16-geospatial-data-pipeline.md` sections 4, 4.1

**Implementation Notes**

- Use Python 3.11+ as the minimum version.
- Pin minimum versions but allow patch-level flexibility (e.g., `rasterio>=1.3`).
- Include `click>=8.0` for CLI argument parsing.
- Do not install GDAL separately — rasterio bundles the required GDAL bindings.

**Acceptance Criteria**

1. `pipeline/` directory exists with all module stubs.
2. `pipeline/requirements-pipeline.txt` lists all dependencies from the architecture spec.
3. `.env.pipeline.example` documents all required environment variables.
4. `pip install -r pipeline/requirements-pipeline.txt` succeeds in a clean Python 3.11+ virtual environment without errors.
5. Each module stub is importable without runtime errors.

**Definition of Done**

- Pipeline project structure committed.
- Dependencies verified in a clean virtual environment.
- `.env.pipeline.example` committed with no actual secrets.

**Testing Approach**

- Environment verification: create a fresh venv, install requirements, import each module.

**Evidence Required**

- `pip install` terminal output (success, no errors).
- Directory listing of `pipeline/`.

---

### S03-02 — Download and Cache Source Data

| Field          | Value                                  |
| -------------- | -------------------------------------- |
| ID             | S03-02                                 |
| Type           | Data                                   |
| Effort         | ~1 day                                 |
| Dependencies   | S03-01 (project structure), Epic 01 S01-01 (confirmed scenario IDs) |

**Statement**

As the system, I need raw IPCC AR6 sea-level projection data and Copernicus DEM elevation tiles downloaded and cached locally, so that all subsequent pipeline steps can operate on local files without repeated network requests.

**Why**

The pipeline processes two large external datasets. IPCC AR6 projections are distributed as NetCDF files from NASA's Sea Level Change portal. Copernicus DEM GLO-30 is distributed as GeoTIFF tiles that must be mosaicked for the Europe extent. Downloading these datasets is the slowest pipeline step (network-bound). Local caching ensures re-runs skip the download step, which is critical during development and debugging of later pipeline steps.

**Scope Notes**

- Implement `pipeline/download.py` with two functions: `download_ipcc_ar6(scenario, horizon, output_dir)` and `download_copernicus_dem(bbox, output_dir)`.
- Download IPCC AR6 NetCDF files for all confirmed scenarios (from Epic 01 S01-01) and all three horizons (2030, 2050, 2100).
- Download Copernicus DEM GLO-30 tiles covering the Europe bounding box and mosaic into a single GeoTIFF.
- Implement local caching: if a file already exists at the expected path, skip download.
- Log download progress (file name, size, source URL).
- Handle download failures gracefully with clear error messages.

**Traceability**

- Open Questions consumed: OQ-02 (scenario set from S01-01)
- Requirements: FR-015 (time horizons)
- Architecture: `docs/architecture/16-geospatial-data-pipeline.md` sections 2.1, 2.2, 5 (Step 1)

**Implementation Notes**

- IPCC AR6 data source: NASA Sea Level Change portal (`https://sealevel.nasa.gov/ipcc-ar6-sea-level-projection-tool`). Data is CC BY 4.0 licensed.
- Copernicus DEM source: `https://dataspace.copernicus.eu`. Attribution required per license.
- Europe bounding box (approximate): longitude -30 to 40, latitude 30 to 75.
- Use `xarray` with `netCDF4` engine to verify downloaded NetCDF files are readable and contain expected variables.
- Use `rasterio` to verify downloaded DEM tiles are valid GeoTIFFs.
- Mosaic DEM tiles using `rasterio.merge.merge`.

**Acceptance Criteria**

1. `download_ipcc_ar6` downloads NetCDF files for each confirmed scenario and stores them in `DOWNLOAD_DIR`.
2. `download_copernicus_dem` downloads DEM tiles for the Europe bounding box and produces a single mosaicked GeoTIFF.
3. Re-running either function with existing files skips the download (caching works).
4. Downloaded NetCDF files are readable by `xarray` and contain sea-level rise projection variables.
5. The mosaicked DEM GeoTIFF is readable by `rasterio` and covers the Europe extent.
6. Download errors produce clear error messages with the source URL and HTTP status.

**Definition of Done**

- `pipeline/download.py` implemented and committed.
- All source data downloaded and verified for at least one scenario/horizon combination.
- Caching behavior verified (second run skips download).

**Testing Approach**

- Functional test: run download for one scenario/horizon, verify file exists and is readable.
- Caching test: run download again, verify no network request is made (file size and timestamp unchanged).
- Data validation: open downloaded NetCDF with xarray, confirm expected variables exist; open DEM with rasterio, confirm CRS and extent.

**Evidence Required**

- Terminal output showing successful download with file sizes.
- Terminal output showing cached skip on second run.
- `xarray` dataset summary for one downloaded NetCDF.
- `rasterio` metadata for the mosaicked DEM (CRS, bounds, shape).

---

### S03-03 — Reproject and Align SLR to DEM Grid

| Field          | Value                  |
| -------------- | ---------------------- |
| ID             | S03-03                 |
| Type           | Data Processing        |
| Effort         | ~1 day                 |
| Dependencies   | S03-02 (downloaded source data) |

**Statement**

As the system, I need IPCC AR6 sea-level rise projections interpolated to the Copernicus DEM grid resolution, so that the binary exposure comparison in the next step operates on spatially aligned arrays.

**Why**

The IPCC AR6 projections are on a coarse grid (~0.25 degrees, approximately 25 km), while the Copernicus DEM is at 30m resolution. A pixel-by-pixel comparison (SLR >= DEM) requires both datasets to share the same grid. Without alignment, the comparison is meaningless. Bilinear resampling interpolates the coarse SLR values smoothly to the fine DEM grid, which is appropriate for a slowly varying field like sea-level rise.

**Scope Notes**

- Implement `pipeline/preprocess.py` with function `align_to_dem_grid(slr_nc, dem_tif, output_tif)`.
- Extract median SLR values for a specific scenario and horizon from the NetCDF file using `xarray`.
- Reproject SLR array to match the DEM grid's CRS (EPSG:4326), transform, and shape using `rasterio.warp.reproject` with `Resampling.bilinear`.
- Output: one aligned SLR GeoTIFF per scenario/horizon combination with Float32 values in meters.
- Verify output grid dimensions match the DEM grid exactly.

**Traceability**

- Requirements: NFR-022 (reproducibility)
- Architecture: `docs/architecture/16-geospatial-data-pipeline.md` section 3.2, section 5 (Step 2)

**Implementation Notes**

- Use `xarray.open_dataset` with the `netCDF4` engine to read IPCC AR6 files.
- The NetCDF variable name for median SLR projection will need to be identified from the actual file structure during implementation. Document the variable name once confirmed.
- `rasterio.warp.reproject` handles CRS transformation and resampling in a single call.
- Bilinear resampling is correct for SLR (continuous, slowly varying field). Do not use nearest-neighbor (introduces discontinuities) or cubic (unnecessary complexity).
- Output file naming convention: `{scenario}_{horizon}_slr_aligned.tif`.

**Acceptance Criteria**

1. `align_to_dem_grid` produces a GeoTIFF for each scenario/horizon combination.
2. Output GeoTIFF has the same CRS (EPSG:4326), transform, and shape as the DEM.
3. Output pixel values are Float32 representing sea-level rise in meters.
4. Bilinear resampling is used (not nearest-neighbor or cubic).
5. Output file is readable by `rasterio` and pixel values are within a physically plausible range (0 to ~2 meters for 2100 high-emission scenarios).

**Definition of Done**

- `pipeline/preprocess.py` implemented and committed.
- Alignment verified for at least one scenario/horizon combination.
- Output grid dimensions confirmed to match DEM.

**Testing Approach**

- Data validation: compare output grid shape and transform against DEM metadata.
- Value range check: verify SLR values are positive and within expected physical range.
- Visual spot-check: plot aligned SLR raster to confirm spatial coherence (no obvious artifacts or misalignment).

**Evidence Required**

- `rasterio` metadata for one aligned SLR output (CRS, bounds, shape, dtype).
- Comparison of output shape vs. DEM shape (must match exactly).
- Sample pixel value range (min, max, mean).

---

### S03-04 — Compute Binary Exposure Rasters

| Field          | Value                                  |
| -------------- | -------------------------------------- |
| ID             | S03-04                                 |
| Type           | Data Processing                        |
| Effort         | ~1 day                                 |
| Dependencies   | S03-03 (aligned SLR GeoTIFFs), Epic 01 S01-03 (coastal zone geometry), Epic 01 S01-04 (confirmed binary methodology) |

**Statement**

As the system, I need binary exposure rasters computed for each scenario/horizon combination, so that the output correctly classifies every coastal pixel as exposed (1) or not exposed (0) based on the confirmed methodology.

**Why**

This is the core scientific computation of the pipeline. It translates two raw datasets (projected sea-level rise and terrain elevation) into the binary classification that drives every user-facing result. The coastal zone mask ensures that inland pixels are set to NoData rather than misleading "not exposed" values. Correctness here is non-negotiable — an error in this step propagates silently to every assessment the application serves.

**Scope Notes**

- Implement `pipeline/compute_exposure.py` with function `compute_binary_exposure(dem_tif, slr_tif, coastal_zone_geom, output_tif)`.
- Comparison logic: `exposure = 1 where SLR >= DEM, else 0` (per confirmed OQ-05 methodology from Epic 01 S01-04).
- Apply coastal analysis zone mask (from Epic 01 S01-03 geometry): pixels outside the coastal zone are set to NoData (NaN).
- Output pixel values: Float32 — 0.0 (not exposed), 1.0 (exposed), NaN (outside coastal zone).
- Handle DEM NoData regions (e.g., ocean areas in the DEM) by propagating NoData.
- Output one binary raster per scenario/horizon combination.

**Traceability**

- Open Questions consumed: OQ-04 (coastal zone from S01-03), OQ-05 (methodology from S01-04)
- Requirements: BR-011, BR-012 (exposure methodology), BR-014 (no substitution)
- Architecture: `docs/architecture/16-geospatial-data-pipeline.md` section 3.1, section 5 (Step 3)

**Implementation Notes**

- Use `numpy.where` for the binary comparison: `np.where(slr >= dem, 1.0, 0.0)`.
- Use `rasterio.mask.mask` with the coastal zone geometry to apply the spatial mask.
- The coastal zone geometry should be loaded from the GeoJSON produced in Epic 01 S01-03 using `geopandas` and `shapely`.
- Be careful with masked array handling: both DEM and SLR may have their own NoData masks. Combine masks before comparison.
- Output file naming convention: `{scenario}_{horizon}_exposure_raw.tif`.
- This is a simplified static inundation model. It does NOT account for flood defenses, hydrodynamic connectivity, storm surge, tidal variation, local subsidence, or drainage infrastructure. This limitation is documented in the methodology panel text (Epic 01 S01-04).

**Acceptance Criteria**

1. `compute_binary_exposure` produces one output raster per scenario/horizon combination.
2. Output pixel values are strictly 0.0, 1.0, or NaN (no other values).
3. Pixels where SLR >= DEM are 1.0; pixels where SLR < DEM are 0.0.
4. Pixels outside the coastal analysis zone geometry are NaN.
5. DEM NoData regions are propagated as NaN in the output.
6. A known-exposed location (Amsterdam, elevation ~-2m ASL) has pixel value 1.0 for all scenarios.
7. A known-inland location outside the coastal zone has pixel value NaN.

**Definition of Done**

- `pipeline/compute_exposure.py` implemented and committed.
- Binary exposure verified for at least one scenario/horizon combination.
- Amsterdam and inland spot-checks pass.

**Testing Approach**

- Data validation: read output raster, verify unique pixel values are a subset of {0.0, 1.0, NaN}.
- Spot-check: extract pixel value at Amsterdam coordinates (52.37 N, 4.90 E) — expect 1.0.
- Spot-check: extract pixel at a known inland location outside the coastal zone — expect NaN.
- Spot-check: extract pixel at a known elevated coastal location — expect 0.0 for low-emission scenarios.

**Evidence Required**

- Unique pixel value listing for one output raster.
- Spot-check results table: coordinate, expected value, actual value, pass/fail.
- `rasterio` metadata for one output raster (CRS, bounds, dtype, nodata).

---

### S03-05 — COGify and QA Validate

| Field          | Value                  |
| -------------- | ---------------------- |
| ID             | S03-05                 |
| Type           | Data Processing        |
| Effort         | ~1 day                 |
| Dependencies   | S03-04 (raw binary exposure rasters) |

**Statement**

As the system, I need each raw exposure raster converted to Cloud-Optimized GeoTIFF format and validated against all QA checks, so that the output files are servable by TiTiler and guaranteed to meet the layer specification.

**Why**

TiTiler requires COG files with internal tiling and overviews to serve XYZ map tiles efficiently via HTTP range requests. A standard GeoTIFF without these properties would force TiTiler to download and process the entire file for every tile request, which is unacceptable for performance. The QA validation step is the last gate before upload — it catches format errors, CRS mismatches, non-binary pixel values, empty layers, and incorrect spatial extents before they reach production.

**Scope Notes**

- Implement `pipeline/cogify.py` with function `cogify(input_tif, output_cog)`.
- COG profile: deflate compression, 256x256 tile size, nearest-neighbor overview resampling (correct for binary values), overview levels [2, 4, 8, 16, 32, 64, 128].
- Use `rio-cogeo` for conversion and validation.
- Implement `pipeline/validate.py` with function `validate_layer(cog_path, scenario, horizon)`.
- Five QA checks, all must pass:
  1. Valid COG structure (`rio-cogeo validate` returns no errors).
  2. CRS is EPSG:4326.
  3. Pixel values are binary only (0, 1, NoData — no other values).
  4. Layer has exposure pixels (at least some pixels with value 1).
  5. Spatial extent is within the expected Europe bounds (lon: -30 to 40, lat: 30 to 75).
- QA failure for any check halts the pipeline for that layer with a clear error message.

**Traceability**

- Requirements: NFR-020 (COG format), NFR-022 (reproducibility)
- Architecture: `docs/architecture/16-geospatial-data-pipeline.md` sections 5 (Steps 4, 5), 8, 12

**Implementation Notes**

- Use `cog_profiles.get("deflate")` from `rio-cogeo` as the base profile.
- Override tile size to 256x256 and add overview levels.
- Use `nearest` resampling for overviews because the data is binary — bilinear or cubic resampling would create non-binary intermediate values.
- Enable `GDAL_TIFF_INTERNAL_MASK` for proper NoData handling.
- Expected file size per COG: 1-10 MB depending on coastal zone extent.
- Output file naming convention: `{scenario}_{horizon}.tif` (final COG name).

**Acceptance Criteria**

1. `cogify` converts each raw exposure raster to COG format.
2. `rio-cogeo validate` returns valid (no errors) for every output COG.
3. Every output COG has CRS EPSG:4326.
4. Every output COG has deflate compression, 256x256 tiles, and overview levels [2, 4, 8, 16, 32, 64, 128].
5. `validate_layer` runs all 5 QA checks and returns True for valid layers.
6. `validate_layer` raises a clear error for any failing check, identifying which check failed and why.
7. All 9 COGs (3 scenarios x 3 horizons) pass all 5 QA checks.

**Definition of Done**

- `pipeline/cogify.py` and `pipeline/validate.py` implemented and committed.
- All 9 COGs generated and passing QA validation.

**Testing Approach**

- Structural test: run `rio-cogeo validate` on each output COG.
- CRS test: read CRS with rasterio, assert EPSG:4326.
- Value test: read pixel values, assert unique values are subset of {0.0, 1.0}.
- Exposure test: count exposure pixels, assert > 0.
- Extent test: read bounds, assert within Europe range.
- Failure test: feed a deliberately malformed file (wrong CRS or non-binary values) to `validate_layer` and verify it raises an error.

**Evidence Required**

- `rio-cogeo validate` output for all 9 COGs (all valid).
- QA summary table: scenario, horizon, COG valid, CRS correct, values binary, has exposure pixels, extent correct, overall pass/fail.

---

### S03-06 — Upload COGs to Azure Blob Storage

| Field          | Value                                  |
| -------------- | -------------------------------------- |
| ID             | S03-06                                 |
| Type           | Infrastructure                         |
| Effort         | ~0.5 days                              |
| Dependencies   | S03-05 (validated COGs), Epic 02 S02-01 (Blob Storage account and `geospatial` container) |

**Statement**

As the system, I need all validated COG files uploaded to Azure Blob Storage at the correct paths with proper content-type and cache-control headers, so that TiTiler can serve tiles from these files at runtime.

**Why**

COG files must be in Azure Blob Storage for TiTiler to access them via HTTP range requests. The blob path structure (`layers/{version}/{scenario}/{horizon}.tif`) is a contract shared between the pipeline, the `layers` table in PostgreSQL, and the API's layer resolution logic. Incorrect paths or missing headers degrade performance or break tile serving entirely.

**Scope Notes**

- Implement `pipeline/upload.py` with function `upload_cog(cog_path, scenario, horizon, methodology_version, connection_string)`.
- Blob path convention: `layers/{methodology_version}/{scenario_id}/{horizon_year}.tif`.
- Container: `geospatial` (private).
- Set `Content-Type: image/tiff`.
- Set `Cache-Control: max-age=86400, public`.
- Overwrite existing blobs if re-uploading (idempotent).
- Return the blob path string for use in database registration.
- Upload all 9 COGs.

**Traceability**

- Requirements: NFR-020 (COG format), BR-014 (no substitution — all 9 combinations must be uploaded)
- Architecture: `docs/architecture/16-geospatial-data-pipeline.md` section 5 (Step 6), section 9; `docs/architecture/05-data-architecture.md` section 3

**Implementation Notes**

- Use `azure-storage-blob` Python SDK.
- Use `BlobServiceClient.from_connection_string` with the connection string from environment variables.
- Use `ContentSettings(content_type="image/tiff", cache_control="max-age=86400, public")` on upload.
- Use `overwrite=True` to make re-uploads idempotent.
- Log each upload with the blob path and file size.

**Acceptance Criteria**

1. All 9 COGs are uploaded to the `geospatial` container.
2. Each blob is at the correct path: `layers/{methodology_version}/{scenario_id}/{horizon_year}.tif`.
3. Each blob has `Content-Type: image/tiff`.
4. Each blob has `Cache-Control: max-age=86400, public`.
5. Re-running the upload overwrites existing blobs without error (idempotent).
6. `upload_cog` returns the blob path string for each uploaded file.

**Definition of Done**

- `pipeline/upload.py` implemented and committed.
- All 9 COGs uploaded to Azure Blob Storage.
- Blob listing confirms correct paths and headers.

**Testing Approach**

- Infrastructure verification: list blobs in the `geospatial` container, verify all 9 paths exist.
- Header verification: read blob properties, verify content-type and cache-control.
- Idempotency test: re-upload one COG, verify no error and blob is updated.

**Evidence Required**

- Blob listing output showing all 9 paths.
- Blob properties output for one file showing content-type and cache-control headers.

---

### S03-07 — Register Layers and Seed Metadata in PostgreSQL

| Field          | Value                                  |
| -------------- | -------------------------------------- |
| ID             | S03-07                                 |
| Type           | Data                                   |
| Effort         | ~1 day                                 |
| Dependencies   | S03-06 (blob paths), Epic 02 S02-03 (schema deployed), Epic 01 S01-07 (seed data specification) |

**Statement**

As the system, I need all layer records inserted into PostgreSQL with the correct metadata, and all seed data (scenarios, horizons, geography boundaries, methodology version) populated, so that the API can resolve layers and serve assessment results.

**Why**

The API discovers available layers by querying the `layers` table filtered on `layer_valid = true` and the active methodology version. If layer rows are missing, have incorrect blob paths, or reference nonexistent scenarios or methodology versions, the API cannot resolve any assessment. This story also seeds the reference data tables — scenarios, horizons, geography boundaries, and methodology version — that every API endpoint depends on. Without seed data, even a correctly deployed schema is an empty shell.

**Scope Notes**

- Implement `pipeline/register.py` with functions:
  - `register_layer(conn_string, scenario_id, horizon_year, methodology_version, blob_path, legend_colormap)` — INSERT into `layers` with `layer_valid=false`, return UUID.
  - `mark_layer_valid(conn_string, layer_id)` — UPDATE `layer_valid = true` after QA passes.
  - `activate_methodology_version(conn_string, version)` — atomic transaction: deactivate all, activate target.
- Seed the following tables using the specification from Epic 01 S01-07:
  - `scenarios` — all confirmed scenarios with IDs, display names, descriptions, sort order, `is_default`.
  - `horizons` — 2030, 2050, 2100 with display labels, sort order, `is_default`.
  - `geography_boundaries` — `europe` and `coastal_analysis_zone` rows with geometries from Epic 01 S01-03.
  - `methodology_versions` — v1.0 with all required metadata fields (sea_level_source_name, elevation_source_name, what_it_does, limitations, resolution_note, exposure_threshold, exposure_threshold_desc).
- Legend colormap for all layers: `{"colorStops": [{"value": 1, "color": "#E85D04", "label": "Modeled exposure zone"}]}`.
- All 9 layer rows registered and marked valid.
- Methodology version activated atomically.

**Traceability**

- Open Questions consumed: OQ-02, OQ-04, OQ-05 (all via Epic 01 seed data spec)
- Requirements: BR-010 (result states depend on valid layers), BR-015 (methodology version present), FR-035 (methodology version visible), NFR-021 (methodology versioning)
- Architecture: `docs/architecture/16-geospatial-data-pipeline.md` sections 5 (Step 7), 10, 11; `docs/architecture/05-data-architecture.md` section 2 (full schema)

**Implementation Notes**

- Use `psycopg2` for database operations.
- INSERT layers with `ON CONFLICT ... DO UPDATE` to make re-registration idempotent (as specified in the architecture doc).
- Methodology version activation is an atomic transaction: `BEGIN; UPDATE ... SET is_active = false WHERE is_active = true; UPDATE ... SET is_active = true WHERE version = 'v1.0'; COMMIT;`.
- Seed data INSERTs should use `ON CONFLICT DO NOTHING` or `ON CONFLICT DO UPDATE` to be idempotent.
- Load coastal zone geometry from the GeoJSON file (Epic 01 S01-03) using `geopandas` and insert into `geography_boundaries` using PostGIS `ST_GeomFromGeoJSON`.
- Close database connections properly after each operation.

**Acceptance Criteria**

1. `scenarios` table contains all confirmed scenarios with correct IDs, display names, descriptions, sort order, and `is_default` flags.
2. `horizons` table contains 2030, 2050, 2100 with correct display labels, sort order, and `is_default` flags.
3. `geography_boundaries` table contains `europe` and `coastal_analysis_zone` rows with valid PostGIS geometries.
4. `methodology_versions` table contains v1.0 with all required fields populated.
5. `layers` table contains 9 rows (3 scenarios x 3 horizons), all with `layer_valid = true`.
6. Each layer row has the correct `blob_path` matching the uploaded COG path.
7. Each layer row has the correct `legend_colormap` JSON.
8. Methodology version v1.0 is the only active version (`is_active = true`).
9. Re-running the seeding and registration is idempotent (no duplicate key errors).

**Definition of Done**

- `pipeline/register.py` implemented and committed.
- All seed data and layer rows verified in PostgreSQL.
- Methodology version v1.0 is active.

**Testing Approach**

- Database verification: query each table and verify row counts and key field values.
- Idempotency test: run registration twice, verify no errors and data is correct.
- Foreign key test: verify all `layers.scenario_id` values exist in `scenarios`, all `layers.methodology_version` values exist in `methodology_versions`.
- Activation test: verify exactly one methodology version has `is_active = true`.

**Evidence Required**

- SQL query results: `SELECT * FROM scenarios`, `SELECT * FROM horizons`, `SELECT version, is_active FROM methodology_versions`, `SELECT scenario_id, horizon_year, layer_valid, blob_path FROM layers`.
- Row counts for each table.

---

### S03-08 — Pipeline Orchestration CLI and End-to-End Validation

| Field          | Value                                  |
| -------------- | -------------------------------------- |
| ID             | S03-08                                 |
| Type           | Integration                            |
| Effort         | ~1 day                                 |
| Dependencies   | S03-01 through S03-07 (all pipeline steps) |

**Statement**

As the engineer maintaining delivery quality, I want a Click-based CLI that orchestrates the full pipeline from download through activation, and I want end-to-end validation confirming all 9 COGs are correct and servable, so that the pipeline can be executed reproducibly and the pipeline checklist is fully satisfied.

**Why**

Individual pipeline steps are necessary but insufficient. The pipeline must be executable as a single command that chains all steps for all scenario/horizon combinations, handles errors at each step, and produces a clear pass/fail report. Without orchestration, running the pipeline requires manually invoking 7 steps for 9 combinations — 63 manual operations that are error-prone and unrepeatable. The end-to-end validation, including TiTiler spot-checks, is the final proof that the pipeline output is production-ready.

**Scope Notes**

- Implement `pipeline/run_pipeline.py` as a Click CLI with the following options:
  - `--scenario` (multiple, required): scenario IDs to process.
  - `--horizon` (multiple, required, type=int): horizon years to process.
  - `--methodology-version` (required): version string.
  - `--activate` (flag): activate the methodology version after pipeline completes.
- The CLI iterates all scenario x horizon combinations and executes Steps 1-7 for each.
- Pipeline halts on first failure with a clear error identifying the failing step, scenario, and horizon.
- After all layers are processed, run the pipeline checklist from `docs/architecture/16-geospatial-data-pipeline.md` section 12:
  - All 9 COGs generated.
  - All pass `rio-cogeo validate`.
  - All EPSG:4326.
  - All binary values.
  - All have exposure pixels.
  - All uploaded to Blob Storage.
  - All layers registered with `layer_valid = true`.
  - `methodology_versions` row exists.
  - TiTiler spot-checks pass (Amsterdam returns 1, inland location returns 0, tile renders visible overlay).
- If `--activate` flag is set and all checks pass, activate the methodology version.
- Print a summary report at the end: per-layer status and overall pass/fail.

**Traceability**

- Requirements: NFR-022 (reproducibility), BR-010 (valid layers), BR-014 (no substitution — all 9 must exist)
- Architecture: `docs/architecture/16-geospatial-data-pipeline.md` sections 6, 7, 12

**Implementation Notes**

- Use `click.echo` for progress output, not `print`.
- Estimated runtime: 30-90 minutes for all 9 combinations (dominated by DEM download and raster computation).
- TiTiler spot-checks require TiTiler to be running and configured to access the Blob Storage. Use the `/point` endpoint for pixel value checks and a `/tiles` request for visual verification.
- If TiTiler is not yet available (Epic 04 dependency), document the spot-checks as manual verification steps and skip them in the automated pipeline. Do not block pipeline completion on TiTiler availability.
- Example invocation:
  ```
  python pipeline/run_pipeline.py \
      --scenario ssp1-26 --scenario ssp2-45 --scenario ssp5-85 \
      --horizon 2030 --horizon 2050 --horizon 2100 \
      --methodology-version v1.0 \
      --activate
  ```

**Acceptance Criteria**

1. `run_pipeline.py` accepts `--scenario`, `--horizon`, `--methodology-version`, and `--activate` arguments.
2. The CLI processes all scenario x horizon combinations (9 total for default configuration).
3. Each combination executes all 7 pipeline steps in order (download, align, compute, cogify, validate, upload, register).
4. A failure at any step halts processing for that combination with a clear error message.
5. After all layers are processed, the pipeline checklist is evaluated and results are printed.
6. If `--activate` is set and all checks pass, the methodology version is activated.
7. A summary report is printed showing per-layer status (scenario, horizon, step reached, pass/fail).
8. TiTiler spot-check for Amsterdam (52.37 N, 4.90 E) returns pixel value 1 for at least one scenario.
9. TiTiler spot-check for a known inland location returns pixel value 0.
10. Full pipeline executes end-to-end without error for all 9 combinations.

**Definition of Done**

- `pipeline/run_pipeline.py` implemented and committed.
- Full pipeline executed successfully for all 9 combinations.
- Pipeline checklist from architecture doc section 12 is fully satisfied.
- Summary report committed or screenshotted as evidence.

**Testing Approach**

- End-to-end test: run the full pipeline for all 9 combinations and verify the summary report shows all passing.
- Failure handling test: introduce a deliberate error (e.g., corrupt a downloaded file) and verify the pipeline halts with a clear error.
- Spot-check test: query TiTiler `/point` endpoint for Amsterdam and an inland location, verify expected values.
- Checklist verification: walk through every item in the pipeline checklist (section 12 of the architecture doc) and confirm it is satisfied.

**Evidence Required**

- Full pipeline terminal output showing all 9 combinations processed.
- Summary report (per-layer status table).
- TiTiler spot-check results: Amsterdam pixel value, inland pixel value, tile render screenshot.
- Completed pipeline checklist (all items checked).

---

## 8  Technical Deliverables

| Deliverable                          | Format                         | Produced By |
| ------------------------------------ | ------------------------------ | ----------- |
| Pipeline project structure           | Python project (committed)     | S03-01      |
| `requirements-pipeline.txt`          | pip requirements (committed)   | S03-01      |
| `.env.pipeline.example`              | Environment template (committed)| S03-01     |
| `pipeline/download.py`               | Python module (committed)      | S03-02      |
| `pipeline/preprocess.py`             | Python module (committed)      | S03-03      |
| `pipeline/compute_exposure.py`       | Python module (committed)      | S03-04      |
| `pipeline/cogify.py`                 | Python module (committed)      | S03-05      |
| `pipeline/validate.py`              | Python module (committed)      | S03-05      |
| `pipeline/upload.py`                 | Python module (committed)      | S03-06      |
| `pipeline/register.py`               | Python module (committed)      | S03-07      |
| `pipeline/run_pipeline.py`           | Python CLI (committed)         | S03-08      |
| 9 COG files in Azure Blob Storage    | Cloud-Optimized GeoTIFF        | S03-06      |
| 9 layer rows in PostgreSQL           | Database records               | S03-07      |
| Seed data in PostgreSQL              | Database records               | S03-07      |
| Pipeline execution report            | Terminal output / Markdown      | S03-08      |

---

## 9  Data, API, and Infrastructure Impact

This epic produces the data foundation that all runtime components depend on:

- **Azure Blob Storage:** 9 COG files written to `geospatial/layers/v1.0/{scenario}/{horizon}.tif`. Estimated total storage: 9-90 MB.
- **PostgreSQL:** 9 rows in `layers`, 3 rows in `scenarios`, 3 rows in `horizons`, 1 row in `methodology_versions`, 2 rows in `geography_boundaries`. All seed data and layer metadata required for API operation.
- **Epic 04 (Backend API)** depends on layer rows with `layer_valid = true` and an active methodology version to resolve exposure assessments.
- **Epic 05 (Frontend)** depends on TiTiler being able to serve tiles from the uploaded COGs.
- **No API changes** in this epic. The API is not built yet. This epic populates the data that the API will read.

---

## 10  Security and Privacy

- **Blob Storage connection string** is read from environment variables, sourced from Azure Key Vault in production. Never committed to source code.
- **PostgreSQL connection string** is read from environment variables, sourced from Key Vault. Never committed.
- **No user data** is processed or stored by the pipeline.
- **Source data licenses:** IPCC AR6 data is CC BY 4.0 (attribution stored in `methodology_versions.sea_level_source_name`). Copernicus DEM has its own attribution requirement (stored in `methodology_versions.elevation_source_name`). Both are documented in the methodology version metadata.
- **`.env.pipeline.example`** contains variable names only, no values.

---

## 11  Observability

The pipeline is an offline batch process, not a runtime service. Observability is limited to:

- **CLI output:** Progress logging for each step, each scenario/horizon combination.
- **Error messages:** Clear identification of failing step, scenario, horizon, and error detail.
- **Summary report:** Per-layer status table printed at pipeline completion.
- **No runtime metrics or alerting** — the pipeline runs on demand, not continuously.

Future enhancement (post-MVP): if the pipeline is moved to GitHub Actions or Azure Container Instance, stdout should be captured and retained as a build artifact.

---

## 12  Testing

| Story   | Testing Approach                                                                         |
| ------- | ---------------------------------------------------------------------------------------- |
| S03-01  | Environment verification — clean venv install, module imports                            |
| S03-02  | Functional test — download one scenario/horizon, verify readability; caching test         |
| S03-03  | Data validation — compare output grid against DEM, verify value ranges                   |
| S03-04  | Data validation — verify binary values, spot-check Amsterdam and inland locations         |
| S03-05  | Structural test — `rio-cogeo validate`; value, CRS, exposure, extent checks              |
| S03-06  | Infrastructure verification — blob listing, header verification, idempotency              |
| S03-07  | Database verification — query all tables, verify row counts, foreign keys, activation     |
| S03-08  | End-to-end test — full pipeline run, checklist verification, TiTiler spot-checks          |

---

## 13  Risks and Assumptions

### Risks

| Risk | Impact | Likelihood | Mitigation |
| ---- | ------ | ---------- | ---------- |
| IPCC AR6 NetCDF file format changes or download URL breaks | High — pipeline cannot produce COGs | Low | Cache downloaded files in version control or a persistent storage location. Document the exact download URL and file checksums. |
| Copernicus DEM download requires authentication or rate-limits aggressively | High — pipeline blocked at Step 1 | Medium | Register for Copernicus data access in advance. Test download before committing to the full pipeline implementation. |
| SLR-to-DEM alignment produces artifacts at coastlines | Medium — incorrect exposure classification near coasts | Medium | Visual spot-check aligned SLR at coastline boundaries. Compare against known sea-level rise values from IPCC reports. |
| Binary exposure model produces counter-intuitive results (e.g., river valleys far inland show as exposed due to low elevation) | Medium — misleading results for users | Medium | Coastal zone mask limits exposure to the defined coastal analysis zone. Document the limitation clearly in methodology panel text. |
| Pipeline runtime exceeds estimate (>90 minutes) | Low — delays pipeline execution, not a structural problem | Medium | Process one scenario/horizon first to calibrate timing. Consider reducing DEM resolution if runtime is excessive. |
| Azure Blob Storage upload fails mid-pipeline | Medium — partial upload state | Low | Uploads are idempotent (overwrite=True). Re-run uploads for failed combinations without re-processing. |

### Assumptions

| Assumption | Impact if Wrong |
| ---------- | --------------- |
| IPCC AR6 sea-level projection data is freely downloadable from NASA without institutional access. | Pipeline is blocked. Escalate immediately. Alternative: use locally archived copies if available. |
| Copernicus DEM GLO-30 is accessible without paid subscription for the Europe extent. | Pipeline is blocked at DEM download. Alternative: use SRTM 30m (less accurate at high latitudes). |
| Binary exposure methodology is confirmed by Epic 01 S01-04. | If continuous methodology is selected, S03-04 comparison logic changes and COG pixel values are no longer binary. Rework estimate: ~1 day. |
| Epic 02 has provisioned the local Docker Compose environment (PostgreSQL + local blob storage) before this epic begins. | Pipeline cannot store COGs or register layers locally. Complete Epic 02 first. Azure Blob Storage is not needed until Epic 08. |
| The coastal zone geometry from Epic 01 S01-03 is available as a GeoJSON file in the repository. | S03-04 cannot apply the coastal mask. Block until S01-03 is complete. |
| 30m DEM resolution is sufficient for MVP-quality exposure results. | If higher resolution is needed, file sizes and processing time increase significantly. 30m is the architecture baseline. |

---

## 14  Epic Acceptance Criteria

1. Pipeline project is scaffolded with all modules, dependencies, and environment configuration.
2. IPCC AR6 and Copernicus DEM source data is downloaded and cached locally.
3. SLR projections are aligned to DEM grid at 30m resolution using bilinear resampling.
4. Binary exposure rasters are computed for all 9 scenario/horizon combinations.
5. All 9 COGs pass `rio-cogeo validate` with no errors.
6. All 9 COGs are EPSG:4326 with deflate compression, 256x256 tiles, and overview levels.
7. All 9 COGs contain only binary pixel values (0.0, 1.0, NaN).
8. All 9 COGs have exposure pixels (non-empty).
9. All 9 COGs are uploaded to Azure Blob Storage at correct paths with correct headers.
10. All 9 layer rows exist in PostgreSQL with `layer_valid = true`.
11. `scenarios`, `horizons`, `geography_boundaries`, and `methodology_versions` tables are seeded.
12. Methodology version v1.0 is the only active version.
13. TiTiler spot-check confirms Amsterdam returns pixel value 1.
14. TiTiler spot-check confirms an inland location returns pixel value 0.
15. Full pipeline is executable via a single CLI command.
16. Pipeline checklist (architecture doc section 12) is fully satisfied.

---

## 15  Definition of Done

- All 8 user stories completed with evidence committed or documented.
- All 9 COGs generated, validated, uploaded, and registered.
- All seed data populated in PostgreSQL.
- Methodology version v1.0 activated.
- Pipeline checklist fully satisfied.
- TiTiler spot-checks pass.
- No unresolved blocker remains within this epic's scope.

---

## 16  Demo and Evidence Required

| Evidence                                                   | Location (expected)                                    |
| ---------------------------------------------------------- | ------------------------------------------------------ |
| Pipeline project structure                                 | `pipeline/` directory in repository                    |
| `requirements-pipeline.txt`                                | `pipeline/requirements-pipeline.txt`                   |
| Environment variable template                              | `.env.pipeline.example`                                |
| Full pipeline CLI output (all 9 combinations)              | Terminal output or `docs/delivery/artifacts/pipeline-run-report.md` |
| QA validation summary (9 COGs, 5 checks each)             | Included in pipeline run report                        |
| Azure Blob Storage listing (9 COGs at correct paths)       | `az storage blob list` output                          |
| PostgreSQL table contents (scenarios, horizons, layers, methodology_versions) | `psql` query output                  |
| TiTiler spot-check: Amsterdam pixel value                  | `/point` endpoint response                             |
| TiTiler spot-check: inland pixel value                     | `/point` endpoint response                             |
| TiTiler spot-check: tile render screenshot                 | Screenshot of map tile with visible exposure overlay    |
| Completed pipeline checklist                               | Checked-off version of architecture doc section 12     |
