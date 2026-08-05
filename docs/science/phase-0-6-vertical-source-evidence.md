# Phase 0.6 — Vertical Source Evidence

> **Issue:** #82
>
> **Evidence date:** 2026-08-05
>
> **Input disposition:** Exact source inputs locked
>
> **Publication disposition:** Blocked pending implementation, controls, and independent review

## Outcome

Phase 0.6 closes the source-identity and source-semantics gaps required by the
selected vertical methodology. The source registry now fails closed over exact
AR6 projection members, a complete 1995–2014 water-baseline series, the MDT and
its formal error, both gravity models, and representative Copernicus DEM
terrain/auxiliary controls.

This is not approval of the numerical transform. Phase 0.7 must implement and
validate the tide/epoch/datum reconciliation and uncertainty bounds. Phase 0.8
must approve terrain, coastal-scope, and connectivity controls. Phase 0.9 must
rebuild and independently review the regional release.

The machine-readable inspection receipt is
[`vertical-source-inspection.json`](../../src/pipeline/science/evidence/vertical-source-inspection.json).

## Locked input set

| Role | Locked input | Exact identity |
|---|---|---|
| Projection | IPCC AR6 regional confidence archive | version `20210809`; 9,243,771,601 bytes; SHA-256 `d3b1c2ed…94e91`; upstream MD5 matched |
| Baseline time series | Copernicus Marine European monthly SLA | product `008_068`, dataset `P1M-m`, version `202411`; 240 objects; 137,971,876 bytes; 7,305 calendar-day weight |
| Mean dynamic topography | Copernicus Marine European MDT | product `008_070`, version `202411`; 22,840,797 bytes; SHA-256 `397cdca0…9682` |
| Source geoid | GOCO06S coefficients | ICGEM release dated 2019-12-13; degree 300; archive SHA-256 `980e00ab…00b6` |
| Target geoid | EGM2008 spherical harmonics | NGA release; degree 2190/order 2159; archive SHA-256 `65a9072f…0fbd` |
| Terrain controls | Copernicus DEM GLO-30 and GLO-90 | release `2021_1`; 25 locked assets per resolution across five European coastal controls |

Raw scientific inputs are not committed. Git contains only compact manifests,
contracts, checksums, licensing evidence, and inspection results.

## AR6 member selection

The archive checksum is now closed and all three selected members were
range-extracted and inspected independently:

| Scenario | Exact archive member | Uncompressed bytes | SHA-256 |
|---|---|---:|---|
| `ssp1-26` | `regional/confidence_output_files/medium_confidence/ssp126/total_ssp126_medium_confidence_values.nc` | 72,061,982 | `28ca163c…b716` |
| `ssp2-45` | `regional/confidence_output_files/medium_confidence/ssp245/total_ssp245_medium_confidence_values.nc` | 72,943,754 | `3f31aadb…cb8` |
| `ssp5-85` | `regional/confidence_output_files/medium_confidence/ssp585/total_ssp585_medium_confidence_values.nc` | 74,968,632 | `b3bcf98c…07e0` |

Each member exposes `sea_level_change(quantiles, years, locations)` with
107 quantiles, 14 years, 66,190 locations, millimetres, and fill value
`-32768`. The interval coordinates are exactly `0.167`, `0.500`, and `0.833`.
`q17` and `q83` remain readable labels; code must not request absent rounded
coordinates `0.17` or `0.83`.

## Baseline source decision

The official monthly `008_068` dataset contains `sla`, not `adt`. Its locked
Product User Manual states that the monthly field is a simple temporal average
of the available daily L4 product. The exact European MDT is static and the
daily relationship is `ADT = SLA + MDT`. Therefore:

```text
mean_1995_2014(ADT_GOCO06S)
  = sum(monthly_SLA * calendar_days) / 7305 + MDT_GOCO06S
```

This is algebraically the selected daily-ADT mean when the interval is
complete. The manifest proves exactly 240 consecutive months from January 1995
through December 2014 and records each month's calendar-day weight. Any gap,
duplicate, invalid timestamp, invalid weight, nodata value, or unsupported
interpolation neighbour returns `DataUnavailable`.

This choice replaces a 7,305-file daily lock with a 240-file lock without
changing the statistic. It also makes the static MDT and its `err_mdt` field an
explicit input rather than an undocumented component hidden inside ADT.

## Datum, tide, and epoch semantics

| Input | Native semantics | Binding rule |
|---|---|---|
| European MDT | Height above the GOCO06S geoid; 1993–2012 reference period | Add to the day-weighted SLA mean before geoid conversion |
| GOCO06S | Fully normalized, degree 300, zero-tide, reference epoch 2010-01-01, formal coefficient errors | Evaluate at the locked epoch and convert to tide-free before differencing |
| EGM2008 | Fully normalized, tide-free, degree 2190/order 2159, calibrated coefficient errors | Evaluate on the same ellipsoid/tide convention as GOCO06S |
| Copernicus DEM | EGM2008 orthometric DSM height, EPSG:3855 | Never compare directly with relative AR6 change |

The required transform remains:

```text
B_EGM2008 = mean(ADT_GOCO06S)
          + N_GOCO06S_tide_free
          - N_EGM2008_tide_free
```

Native zero-tide GOCO06S values must never be subtracted directly from
tide-free EGM2008 values.

## Error evidence

- AR6 supplies the exact likely interval coordinates `0.167` and `0.833`.
- `err_mdt` is a formal MDT mapping error. It is not a complete ADT or datum
  uncertainty term.
- The monthly SLA product does not include the daily `err_sla` field. The
  locked QUID is therefore the evidence source from which Phase 0.7 must derive
  a conservative mapping/validation bound. Absence of that bound is nodata.
- GOCO06S supplies formal coefficient errors; EGM2008 supplies calibrated
  coefficient standard deviations and the required `zeta`-to-`N` terms.
- Copernicus DEM HEM is required together with EDM, FLM, and WBM. HEM does not
  remove the separate DSM representation-bias term.

No implementation may collapse these terms into a single unexplained accuracy
number or assume statistical independence to reduce the bound.

## Coverage and gaps

| Region/type | Projection | SLA/MDT baseline | Gravity models | Terrain evidence |
|---|---|---|---|---|
| Atlantic | Covered | Covered at valid ocean cells | Global | Lisbon control |
| North Sea | Covered | Covered at valid ocean cells | Global | Netherlands control |
| Baltic | Covered | Covered at valid ocean cells | Global | Not sampled in Phase 0.6 |
| Mediterranean / Adriatic | Covered | Covered at valid ocean cells | Global | Malta and Venice controls |
| Black Sea | Covered | Covered at valid ocean cells | Global | Not sampled in Phase 0.6 |
| Islands | Covered | Partial near narrow coastlines | Global | Reykjavik and Malta controls |
| Ports / estuaries | Covered by AR6 grid | Partial at 0.0625° water grids | Global | Partial; must fail closed outside masks |
| North of 66.03125°N | Covered by AR6 grid | SLA unavailable; MDT only to 66.96875°N | Global | Reykjavik control only |

The coverage matrix is a stop condition, not an invitation to extrapolate.

## Licensing and redistribution

- IPCC AR6 and GOCO06S are CC BY 4.0 with citations and acknowledgements
  retained in the source lock.
- Copernicus Marine use, adaptation, distribution, and reproduction are
  approved with the required EU/Copernicus Marine identification and DOI
  wording.
- NGA publishes EGM2008 as an official free public United States Government
  release; source identification and the scientific citation are retained.
- Copernicus DEM derivatives must carry the instance-specific mandatory notice
  already recorded in the source lock.

No raw upstream bytes are redistributed through this repository.

## Fail-closed validation

Loading the source registry verifies the source-lock schema, manifest byte
size, compressed and payload SHA-256, object count, total byte size, URL/key
identity, unique objects, exact monthly continuity, calendar-day weights, and
all mandatory DEM/AUX roles before any acquisition or derived write.

Generic single-file acquisition rejects a logical object set with
`manifest-driven-object-set-required`; it cannot accidentally download an HTML
listing or treat a source prefix as one verified file.

## Review disposition

The evidence package is complete for implementation review. Independent
scientific/data approval is deliberately not claimed here. It remains a named
publication blocker and must review the implemented transform and uncertainty
controls in the later Phase 0 gate before Phase 1 can start.
