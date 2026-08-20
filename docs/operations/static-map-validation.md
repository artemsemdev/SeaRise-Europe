# Static map validation

The Phase 2 map is an optional visualization of immutable release artifacts.
It is not a scientific lookup surface: exact values are read from the analysis
artifact by the assessment engine, never from PMTiles properties, map pixels,
colour, or rendered features.

## Clean-clone fixture

The default build copies only the committed synthetic release fixture. Its
nine projection PMTiles files cover the three scenarios and three horizons.
The fixture does not yet declare separate support/coastal boundary artifacts;
the resolver will consume those roles from `ReleaseContext` when a later
fixture provides them. Private Phase 1 candidate bytes are neither needed nor
permitted for this validation.

## Commands

```sh
npm ci
npm run web:check
npm run web:e2e
```

`web:check` proves lint/type safety, all resolver and controlled-selection unit
tests, a production build, a 250 KiB Brotli initial-JavaScript budget, and that
both `MapExplorer` and the MapLibre/PMTiles runtime remain dynamic entries. The
build inspector also requires the exact restrictive CSP and `no-referrer`
policy on both static entry documents and rejects `frame-ancestors` in the meta
policy because that directive must be delivered as a deployment response
header.
Playwright uses the production static preview and verifies desktop/mobile
rendering, all nine visual artifact identities, bounded PMTiles `Range`
requests, rapid control changes, actual map-click selection, reduced motion,
axe accessibility, complete attribution, basemap failure, and zero legacy
application endpoint requests. It proves an unlisted connection is blocked
before leaving the page and that the exact OpenFreeMap origin remains usable.

## Expected evidence

- No PMTiles request occurs before **Open static visualization** is activated.
- Every PMTiles request stays under the pinned release path, has a byte range,
  and requests no more than 512 KiB.
- Only the current scenario/horizon overlay is mounted; stale style callbacks
  are rejected by the render token.
- OpenFreeMap failure leaves the release overlay, marker, controls, attribution,
  and text alternative usable.
- Scripts are same-origin, workers are same-origin or `blob:`, and the only
  cross-origin image/connect allowlist entry is
  `https://tiles.openfreemap.org`; objects, base changes, forms, frames, and
  media are denied.
- Both static routes enforce `no-referrer`; production hosting additionally
  supplies `frame-ancestors 'none'` in its CSP response header.
- The map emits the same immutable `SelectionCommand` used by other location
  inputs and never emits a scientific outcome.
