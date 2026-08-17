# Projection PMTiles render evidence

This directory records deterministic QA renders for issue #51. The input
PMTiles SHA-256 is present in both the checked-in public-release fixture and
the owner-approved Phase 0R reproducibility report. The generator verifies
that binding before decoding or rendering any tile.

The three samples cover zooms 0, 3, and 6 and exercise `lower_mm`,
`median_mm`, and `upper_mm`. A fixed QA-only palette makes representative
integer value bins visible. Every sample also binds a source-grid location
whose three quantiles are the exact `-32768` nodata value, proves that the
location is absent from the decoded MVT features, and verifies alpha `0` at
its rendered pixel.

These images are review evidence, not the browser's final visual design and
not a scientific lookup source. Exact projection values continue to come from
the analysis COG; rendered colours must never be reverse-engineered into a
value.

From the repository root, verify the committed receipt and PNG bytes with:

```bash
npm run evidence:pmtiles-render --workspace @searise/web
```

Intentional updates use
`node src/web/scripts/render-pmtiles-evidence.mjs --write` and require review
of the input binding, receipt, PNGs, changelog, and CI.
