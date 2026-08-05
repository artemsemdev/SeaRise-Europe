# Phase 0.12 Baltic and Black Sea source controls

## Decision

The source-pinning part of issue #96 is complete. Four real-source control
windows now extend the existing Atlantic/North Sea and
Mediterranean/Adriatic suite:

| Basin | Window | Source tile | Intended edge cases |
|---|---|---|---|
| Baltic Sea | Gdansk–Vistula | `N54_00_E018_00` | Low terrain, estuary/port, shoreline editing, disconnected inland terrain |
| Baltic Sea | Stockholm archipelago | `N59_00_E018_00` | Islands, narrow coastal water, source-mask disagreement, nodata |
| Black Sea | Constanta | `N44_00_E028_00` | Low terrain, port, lagoon/lakes, shoreline editing, disconnected inland terrain |
| Black Sea | Batumi boundary | `N41_00_E041_00` | Steep coast, port, eastern source boundary, unsupported geography |

The windows were selected from their geographic roles before measuring their
source values. They are controls, not a statistically representative sample
of every European coast and not a production mosaic.

The machine-readable contract is
[`basin-controls.json`](../../src/pipeline/science/basin-controls.json). It
binds every window to the exact AR6 projection members, the 240 monthly CMEMS
SLA inputs, static CMEMS MDT, GOCO06S and EGM2008 coefficients, five Copernicus
DEM layers, support/coastal geometry, and connectivity contract.

## Authoritative sources

Only primary publisher records define the source semantics and rights:

- [IPCC AR6 regional sea-level projections on Zenodo](https://zenodo.org/records/6382554)
- [Copernicus Marine European monthly SLA product](https://data.marine.copernicus.eu/product/SEALEVEL_EUR_PHY_L4_MY_008_068/description)
- [Copernicus Marine European MDT product](https://data.marine.copernicus.eu/product/SEALEVEL_EUR_PHY_MDT_L4_STATIC_008_070/description)
- [Copernicus Marine service licence](https://marine.copernicus.eu/user-corner/service-commitments-and-licence)
- [ICGEM gravity-model catalogue](https://icgem.gfz.de/tom_longtime)
- [NGA WGS 84 and EGM2008 release](https://earth-info.nga.mil/index.php?dir=wgs84&action=wgs84)
- [Copernicus DEM product record](https://dataspace.copernicus.eu/explore-data/data-collections/copernicus-contributing-missions/collections-description/COP-DEM)
- [Copernicus DEM Product Handbook, issue 5.0](https://dataspace.copernicus.eu/sites/default/files/media/files/2024-06/geo1988-copernicusdem-spe-002_producthandbook_i5.0.pdf)
- [Natural Earth terms of use](https://www.naturalearthdata.com/about/terms-of-use/)

Exact licence names, SPDX identifiers, attribution, redistribution status,
and required acknowledgements are pinned in the versioned contract and copied
into the compact evidence receipt. The basin DEM manifest is intentionally
self-contained: adding these controls does not mutate the central source lock
or any immutable Phase 0.7/0.9 receipt. Raw assets remain outside Git.

## Measured source coverage

Every byte in the 240-object, 1995–2014 monthly SLA manifest was downloaded
and SHA-256 verified. The static MDT and all twenty new DEM/EDM/FLM/HEM/WBM
assets were also verified against their locks. The monthly SLA grid is stable
at 0.0625 degrees for the entire reference period: no selected source cell was
valid for only part of the 240 months.

| Window | Native cells | Complete SLA + MDT | Unavailable | Complete SLA but MDT nodata | Partial-month SLA |
|---|---:|---:|---:|---:|---:|
| Gdansk–Vistula | 256 | 111 | 145 | 0 | 0 |
| Stockholm archipelago | 256 | 127 | 129 | 17 | 0 |
| Constanta | 256 | 73 | 183 | 1 | 0 |
| Batumi boundary | 256 | 123 | 133 | 5 | 0 |

These are source-native cell counts, not an estimate of exposed land. A cell
is baseline-ready only when every monthly SLA value and the static MDT exist.
Missing land, water-mask disagreements, and unsupported edge cells remain
`DataUnavailable:source-nodata`. No value is copied or interpolated across
land, nodata, or a source-domain boundary. The receipt records zero
extrapolated cells.

The Copernicus DEM checks prove that every control has an aligned one-arcsecond
GLO-30 DEM plus EDM, FLM, HEM, and WBM quality layers. The raw controls total
224,337,149 bytes; Git contains only their deterministic 1,641-byte compressed
manifest and compact measurements.

## Five-state and independence status

The combined nine-window suite has one explicit slot for each public state and
a stable reason-code expectation:

| State | Reason | Status |
|---|---|---|
| `ModeledExposureDetected` | `classified-connected-exposure` / classification code 0 | Reserved, not executed |
| `NoModeledExposureDetected` | `connectivity-rejected` / classification code 10 | Reserved, not executed |
| `DataUnavailable` | `source-nodata` / classification code 4 | Verified from independent CMEMS source masks |
| `OutOfScope` | `outside-coastal-scope` / classification code 1 | Verified from pinned geography |
| `UnsupportedGeography` | `outside-supported-geography` | Verified from pinned geography before vertical classification |

The first two rows are deliberately **not** claimed as scientific goldens.
Their coordinates and target states were hand-authored outside the vertical
classifier, but numeric expected intervals and connectivity outcomes require
approved #94, #95, and #97 evidence plus an independent reviewer. Their
evidence fields therefore contain `actualState: null` and `passed: null`.

Connectivity removals and disagreements are likewise not fabricated. Until
the vertical classifications and connectivity review exist, all comparison
counts remain `null` with `not-run-fail-closed` status.

## Reproduction

1. Download every URL from the locked monthly SLA and basin DEM manifests.
   Preserve the manifest filenames; do not substitute a newer product or
   release.
2. Download the exact static MDT asset from the source lock.
3. Run:

   ```bash
   PYTHONPATH=src/pipeline python scripts/science/build_basin_control_evidence.py \
     --dem-dir /path/to/dem-controls \
     --monthly-sla-dir /path/to/monthly-sla \
     --mdt /path/to/mdt_cmems_2024_europe.nc \
     --write-dem-manifest src/pipeline/sources/manifests/cop-dem-glo-30-baltic-black-sea-controls-v2021_1.jsonl.gz \
     --output src/pipeline/science/evidence/phase-0-12-basin-controls.json
   ```

The builder validates the strict standalone basin contract and its immutable
global source bindings first, rejects missing or extra monthly objects,
verifies all sizes, URLs, and SHA-256 digests,
checks source-grid identity, inspects aligned DEM quality layers, evaluates the
pinned geometry predicate, and emits canonical JSON. Repeated runs from the
same locked bytes are byte-identical.

## Gate disposition

This work removes the missing Baltic/Black Sea **source evidence** blocker. It
does not approve a Europe-wide scientific result by itself. Publication and
executable exposed/non-exposed goldens remain blocked until:

- #94 approves the vertical transform and geoid evaluator;
- #95 supplies accepted numerical uncertainty bounds;
- #97 approves product scope and independently reviews connectivity removals;
- an independent scientific/data reviewer approves the executable basin
  expectations.

Issue #98 must re-evaluate the complete Phase 0 gate from those approved
outputs. CI success alone cannot convert this blocked disposition into
scientific approval.
