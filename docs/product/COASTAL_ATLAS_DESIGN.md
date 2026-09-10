# Accepted coastal atlas design

Status: active visual and interaction contract for the coastal atlas.
Reference: local implementation `a84279a9` (accepted light interface, Lab removed),
with [current product semantics](COASTAL_ATLAS_PRD.md). Integration preserves this experience;
it does not restart visual exploration.

- A light, full-window map provides European geographic context. Muted land and
  sea colors support a cyan-to-blue depth layer; place labels remain readable.
- Compact white rounded panels hold the SeaRise Europe identity, city search,
  place context, depth legend, and two defense choices at the side of the map.
- Selected-point results belong in the sidebar alongside a corresponding map
  marker. Closing the result removes the selection without losing map state.
- The bottom timeline exposes 2030, 2050, and 2100, with the selected year clear.
  Keep the accepted playback, comparison, and overlay controls together.
- Search suggestions anchor to the search field and remain within the viewport.
  Keyboard focus, selection, escape, loading, empty results, and errors are visible.
- The initial Europe view includes country/place context and complete Ukraine,
  including Crimea. Detail arrives as the map zooms; labels stay above flood colors.
- Mobile panels and controls fit the viewport and leave usable map space. Respect
  safe areas, reduced motion, readable contrast, and usable touch targets.
- Fixture mode adds a clear illustrative-data label. Real-local mode retains the
  source-backed condition and concise limitations rather than internal setup details.
- No experimental Lab, diagnostic overlays, or controls return through old URLs.

Review desktop and mobile captures against the running accepted reference,
including open search, selected point, comparison, and first-load states. The
[Flight mock](Mock/SeaRise-Flight.html) is retained only for the AR6 reference;
it is not the design authority for the main coastal atlas.
