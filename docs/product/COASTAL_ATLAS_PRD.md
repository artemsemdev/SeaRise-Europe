# SeaRise Europe — Coastal atlas requirements

Status: active product contract; engineering adoption in [#490](https://github.com/artemsemdev/SeaRise-Europe/issues/490).
The main route runs the coastal atlas with an explicitly selected fixture or
real-local edition. The retained projection reference is at `/projections/`.
Local functionality does not establish a public or scientific release.

## Purpose

Help people explore how modeled coastal inundation changes around familiar
European places in 2030, 2050, and 2100. Moving the timeline changes the visible
flood-depth layer and the selected point's result together. Preserve the accepted
light, map-first experience; the interface uses US English.

The implementation reference is local commit `a84279a9`, after removal of the
experimental Lab. [Design contract](COASTAL_ATLAS_DESIGN.md) records the accepted
behavior. [Adoption decision](../architecture/adr/ADR-028-coastal-atlas-adoption.md)
defines the boundary with the retained AR6 application.

## Data meaning

- Main source: the existing CoCliCo SSP5-8.5 spring-high-tide layers, with
  **2030 / 2050 / 2100** and **No additional defenses / High protection**.
  These are six year/defense combinations under one emissions scenario.
- Display modeled flood depth in meters. A selected point represents one native
  **25 m** model cell, not the whole city or a property assessment. Additional
  zoom improves map context, not the source model's spatial resolution.
- A valid positive depth is `flooded`; a valid measured zero is `zero`; missing
  source coverage or nodata is `unknown`. Technical loading failures remain
  errors with recovery, never valid zero or scientific unknown results.
- Uncolored land may lack data. Neither it nor a zero value implies safety.
- The map depicts the source's high-tide condition; it does not establish a
  permanent future shoreline or a probability of a particular event.
- The UI shows source, year, defense assumption, units, and limitations. It must
  not substitute another year or defense layer when a requested layer is absent.
- Synthetic test fixtures are prominently labeled **Illustrative fixture** and
  carry `synthetic-fixture` identity. They make no CoCliCo or real-world claim.
  Missing real-local inputs cause a clear setup error, never silent fixture fallback.

## Accepted journeys

| Journey | Required behavior |
| --- | --- |
| First visit | Fit the European context; show readable place/country labels before detailed basemap loading completes. |
| Navigation | Constrain camera navigation to Europe. Include all of Ukraine, including Crimea, in display geometry. Analytical source coverage remains independent. |
| Find a place | Search coastal European cities with useful context, keyboard navigation, and explicit empty/error states. Select a place and reveal its coast. |
| Zoom | Load progressively detailed local basemap context; retain readable labels above inundation colors. |
| Change year | Synchronize 2030, 2050, or 2100 across timeline, layer, legend, comparison, point values, and share state. |
| Change defenses | Switch the source's two assumptions without presenting either as a protection guarantee. |
| Inspect a point | Anchor its marker on the map and show the three year values in the sidebar; the panel must not float in the center of the map. |
| Compare | Preserve the accepted comparison behavior and make the compared years/assumptions visible. |
| Share or reload | Restore supported camera, place, point, year, defenses, comparison, and overlay state. |
| Mobile and keyboard | Keep map, search, results, and timeline usable without overlap, pointer-only controls, or motion delays. |

## Scope boundaries

The experimental Lab is excluded: no source switch, own-calculation runtime,
study-area outlines, experimental overlays, baseline/additional-land controls,
or Lab metrics. Legacy Lab URLs retain supported atlas state and discard Lab
parameters. The product makes no requests to experimental data endpoints.
Original research scripts and datasets can remain outside the product.

River hazards, live alerts, property advice, storm-event forecasting, a new
terrain computation, and a worldwide map are outside this adoption scope.
No invented inundation extent or unsupported scenario may fill missing coverage.

## Runtime and verification

The same application has two explicit data editions: `real-local` for the
existing read-only datasets and `synthetic-fixture` for a small reproducible
clean-clone development/test setup. Browser-facing contracts expose supported
values and source meaning, not disk paths or private candidate metadata.

A loopback Python raster adapter is permitted for local development. It is not
a decision to deploy a production server. The public delivery design, rights
review, and source release qualification remain subsequent work. The atlas
must not register a service worker or persist private local-derived data.

Each migration PR updates its relevant documentation and passes its checks.
Completion requires normal build/CI to exercise the atlas, fixture browser
journeys from a clean clone, real-local browser regressions, desktop/mobile
visual review, and explicit source error/unknown handling. Successful UI tests
do not independently validate the source model or qualify a scientific release.

The [AR6 projection requirements](PRD.md) continue to govern the
retained projection reference, including its four outcomes and nine scenario/year
combinations. They do not redefine the coastal atlas's six combinations.
