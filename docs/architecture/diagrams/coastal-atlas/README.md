# Coastal atlas architecture

![SeaRise Europe coastal atlas runtime](coastal-atlas.svg)

This is the runtime overview of the demo prerelease, pinned to
[`24d125c`](https://github.com/artemsemdev/SeaRise-Europe/tree/24d125c9810cfc20a370b133842296736d39f678).
Arrows indicate requests or reads. The interface uses one explicitly selected
provider: the default browser fixture or the provisioned real-local edition.
There is no automatic fixture fallback. Real-local point inspection samples a
native 25 m raster cell; display tiles do not define analytical resolution.
The separate projection reference retains its own resource storage. Its worker
is root-scoped but handles only allowlisted reference requests; private atlas
responses remain `no-store`.

## Explore and download

- [Interactive HTML](coastal-atlas.html): download the raw file and open it in a
  browser. GitHub displays its source rather than running the viewer.
- [SVG](coastal-atlas.svg): vector export that follows the host's light/dark theme.
- [PNG](coastal-atlas.png): light-theme image for slides or other documents.
- [Editable specification](coastal-atlas.architecture.json): components,
  relationships, layout, and source evidence.

The standalone HTML embeds its viewer and fonts. Select a component's `SRC`
control to inspect the source references; following a GitHub link needs an
internet connection. The viewer includes theme switching, zoom, and exports.
The public files contain architecture and code references, with no private
raster data, receipts, or real-data screenshots.

The overview intentionally omits the retained scientific build pipeline and
future public hosting. Consult the [architecture index](../../README.md),
[atlas development guide](../../../operations/coastal-atlas-development.md),
and [candidate runbook](../../../operations/local-demo-candidate.md) for those
separate scopes and operating details. This diagram is documentation, not an
additional scientific or release qualification.

## Generation and verification

Generated with [Archify](https://github.com/tt-a1i/archify) **v3.0.1**, pinned to
`2ab3cae7ac2c2a55d7386ca789d03c4fcd31816c` (the peeled release-tag commit).
No Archify runtime dependency is added to the application. The editable JSON
is the review source; HTML and SVG are mechanical generated artifacts. Their
bytes are preserved verbatim, including upstream trailing spaces; the directory's
Git attributes limit that whitespace exception to these generated files. Preserve
[Archify's MIT notice](ARCHIFY-LICENSE.txt) when redistributing the viewer; its
embedded font license is retained inside the generated files.

Verification on 2026-10-02:

- Archify `finalize`: **9/9 showcase**, zero errors or warnings; validation,
  generation, strict provenance checks, and real Chrome browser checks passed.
- Artifact-bound capture checks passed for light and dark themes at 1440×900
  and 2048×1320. Both themes were visually reviewed for node fit, readable
  labels, and unobstructed routes.
- PNG and automatic-theme SVG were downloaded through the viewer's canonical
  export menu rather than captured as screenshots.
- Two focused layout corrections retained all source references and semantics.

| File | SHA-256 |
| --- | --- |
| Specification | `3a000dfe9bab519098c4a7ac97cdedd611e9565b794dd07c15b9fe512a3f5fe2` |
| HTML | `abcaae9a4588fada175e53bf588633f38e0a94a389c8f14f206dbea6674b4dfb` |
| SVG | `86e54bb270967db2aec938ec041e6aa7aa22eb5bf0d2ab67189e4d76dec89524` |
| PNG | `c97dcb30fd699a7657b59eb81e514a8b1f283d97a2fe0c16dd8b994e4bea741b` |

Raw machine-local browser receipts and failed authoring attempts are kept out
of Git. The portable hashes above bind the reviewed specification and HTML.

## Rebuild

Use Node 20.20.1 and a full-history SeaRise checkout containing the pinned
source commit. Clone the tool separately and verify its revision:

```bash
git clone --branch v3.0.1 --depth 1 https://github.com/tt-a1i/archify.git /tmp/archify-v3.0.1
git -C /tmp/archify-v3.0.1 rev-parse HEAD
# 2ab3cae7ac2c2a55d7386ca789d03c4fcd31816c
```

From the SeaRise repository root, generate a new local artifact rather than
overwriting the reviewed files. The explicit output overrides the specification's
original authoring location. A supported Chrome installation is required for
the browser gate.

```bash
mkdir -p .cache/architecture-rebuild
ARCHIFY_UPDATE_CHECK_DISABLED=1 node /tmp/archify-v3.0.1/archify/bin/archify.mjs \
  finalize architecture \
  docs/architecture/diagrams/coastal-atlas/coastal-atlas.architecture.json \
  .cache/architecture-rebuild/coastal-atlas.html \
  --repo-root "$PWD" --quality showcase --json
```

Open the generated HTML and use **Export → PNG** or **Export → SVG · Auto** to
refresh image exports after changing the JSON. Rerun all gates and inspect both
themes before replacing the committed diagram. Source links deliberately remain
pinned; update them and check their line ranges when the runtime changes.
