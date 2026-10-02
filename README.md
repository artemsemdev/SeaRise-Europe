# SeaRise Europe

[![CI](https://github.com/artemsemdev/SeaRise-Europe/actions/workflows/ci.yml/badge.svg)](https://github.com/artemsemdev/SeaRise-Europe/actions/workflows/ci.yml)
[![CodeQL](https://github.com/artemsemdev/SeaRise-Europe/actions/workflows/codeql.yml/badge.svg)](https://github.com/artemsemdev/SeaRise-Europe/actions/workflows/codeql.yml)

Explore modeled coastal inundation around European places. SeaRise Europe
compares **2030, 2050, and 2100** under CoCliCo's **SSP5-8.5 spring-high-tide**
condition, with **No additional defenses** and **High protection** assumptions.
The map and selected-point results move together as you change the year.

**[v0.1.0-rc.1](https://github.com/artemsemdev/SeaRise-Europe/releases/tag/v0.1.0-rc.1)
is a demo prerelease.** The public download contains repository source and
illustrative fixtures. CoCliCo raster packages, local basemap archives, sealed
app candidates, private receipts, and real-data screenshots are not included.
The [release notes](docs/releases/v0.1.0-rc.1.md) describe its contents,
verification, and remaining limitations. This is not the stable MVP or a
qualified public scientific release.

## Explore the atlas

- Find a coastal city and navigate within the European map.
- Inspect a point and compare its modeled depth across all three years.
- Switch the two modeled defense assumptions or enter comparison mode.
- Share a view and restore supported map, point, year, and comparison state.
- Use the search, results, and timeline on desktop or mobile.

The default edition is prominently labeled **Illustrative fixture**. A separate
provisioned local edition uses real CoCliCo data through a read-only loopback
adapter; missing local inputs produce a setup error rather than fixture fallback.

Depth is a source-model output in meters. A real-local selected point represents
one native **25 m cell**, not a city or property assessment. Valid zero, missing
coverage, and technical failures have distinct meanings. Neither uncolored land
nor zero depth means safe; these layers are not event probabilities, permanent
shorelines, or protection guarantees.

## Run the public fixture

Use the **official Node 20.20.1 distribution** and **npm 11.12.1**, as pinned
in `.nvmrc` and `package.json`, for reproducible fixture builds and candidate
preparation. Its bundled npm is 10.8.2, so select npm 11.12.1 separately on
`PATH`. Other Node builds with the same version can differ from the required
byte-affecting toolchain contract.

```bash
git clone --branch v0.1.0-rc.1 https://github.com/artemsemdev/SeaRise-Europe.git
cd SeaRise-Europe
node --version # v20.20.1
npm --version  # 11.12.1
npm ci
npm run web:dev
```

Open the URL printed by Vite. This clean-clone workflow needs no private raster
data, Python service, Docker, cloud account, or credentials. `web:dev` always
selects the fixture, even if local data is present. GitHub's automatic source
ZIP/TAR downloads contain the same source scope; they are not a packaged real-data
application.

For a checked production build and local preview:

```bash
npm run web:check
npm run web:serve
```

Open `http://127.0.0.1:4173/`. For fixture browser checks:

```bash
npm exec --workspace @searise/web -- playwright install chromium
npm run web:e2e
```

| Route | What it opens |
| --- | --- |
| `/` | Coastal atlas; illustrative fixture in the public workflow |
| `/projections/` | Separately labeled synthetic AR6 relative sea-level reference |
| `/about/architecture/` | Architecture reference page |

A short tour: search for Venice, select a point, switch between 2030, 2050, and
2100, change defenses, then compare and reload a shared view. Fixture values are
illustrations of application behavior and make no real-world claim.

## Run a provisioned private demo

Provision the verified six-layer CoCliCo workspace, local basemap/place data,
and compatible Python environment first. Follow the
[development quickstart](docs/operations/coastal-atlas-development.md) for those
prerequisites and the [candidate runbook](docs/operations/local-demo-candidate.md)
for the complete preparation and acceptance process.

From a clean checkout at the exact source you intend to seal, with the pinned
Node/npm tools and dependencies installed:

```bash
demo_data_root="/absolute/path/to/local-data/atlas/europe"
demo_candidate="$PWD/.cache/demo-candidates/v0.1.0-rc.1"
npm run demo:preflight -- --data-root "$demo_data_root"
npm run demo:prepare -- --data-root "$demo_data_root" --output "$demo_candidate"
npm run demo:serve -- --data-root "$demo_data_root" --candidate "$demo_candidate"
```

Open `http://127.0.0.1:4181/` in a fresh browser profile. Use an explicit
`--python /absolute/path/to/python` when the compatible interpreter is elsewhere.
Unset inherited `SEARISE_*`/`VITE_*` variables and keep active `.env` files out of
this candidate checkout, as the runbook specifies. Preparation does not download
inputs or overwrite an existing candidate. Stop the server with Ctrl+C.

The launcher verifies the recorded source, application, and external metadata
identities. A candidate sealed from another commit cannot be relabeled as this
tag, even when application files match: prepare a new candidate for the tagged
source. The previously qualified private `rc-2` remains bound to its original
source revision; its identity is recorded in the release notes.

Private `/atlas-data/` responses stay `no-store`. The local URL works only on the
computer running the server. Public hosting and dataset distribution remain
later work in [the atlas adoption epic](https://github.com/artemsemdev/SeaRise-Europe/issues/490).
Keep real-data screenshots and candidate artifacts local.

## Verification and limitations

The prerelease integrates reviewed fixture, adapter, browser, and local-demo
checks. Full evidence and its exact source scope are in the
[release notes](docs/releases/v0.1.0-rc.1.md).

Cold fixture Lighthouse performance remains below the raw 90-point target. A
separate owner-approved local-demo exception expires at
**2026-10-16 00:00 Europe/Berlin**; it does not qualify public hosting or a
scientific/MVP release. The retained synthetic projection reference may show an
update warning on first installation before an ordinary reload obtains the exact
verified controlling worker; follow-up is tracked in
[#531](https://github.com/artemsemdev/SeaRise-Europe/issues/531).

## Architecture at a glance

![Coastal atlas architecture](docs/architecture/diagrams/coastal-atlas/coastal-atlas.svg)

The same interface selects either the browser fixture or the explicitly
provisioned local CoCliCo edition. The local edition reads verified rasters
through loopback Node/Python processes; the retained projection reference has
its own data and storage.

[Explore the interactive diagram](docs/architecture/diagrams/coastal-atlas/README.md)
for source-linked components, light/dark themes, and image exports. The diagram
is pinned to the demo prerelease source; download its HTML to open it locally.

## Project documentation

Start with the [documentation index](docs/README.md),
[coastal atlas requirements](docs/product/COASTAL_ATLAS_PRD.md),
[design](docs/product/COASTAL_ATLAS_DESIGN.md), and
[adoption decision](docs/architecture/adr/ADR-028-coastal-atlas-adoption.md).
Ukraine, including Crimea, remains within the European geographic scope;
analytical source coverage is independent of display geometry.

The AR6 reference retains its own three-scenario, three-year relative-level
contract, Flight design, and scoped scientific/offline evidence.
[ADR-024](docs/architecture/adr/ADR-024-ar6-regional-projection-contract.md) and
the [projection methodology](docs/methodology.md) explain that reference; they
do not define CoCliCo inundation depth. Its service worker caches the projection
shell, not the atlas root or private `/atlas-data` responses. Historical approvals
and scientific decisions keep their original scope.

| Path | Purpose |
| --- | --- |
| `src/web/` | React, TypeScript, Vite, and MapLibre application |
| `scripts/atlas/` | Read-only local raster adapter |
| `scripts/demo/` | Source-bound candidate preparation and loopback launcher |
| `src/pipeline/` | Retained scientific/offline pipeline and deterministic adapter tests |
| `data/cartography/` | Versioned atlas cartographic inputs |
| `local-data/` | Ignored, separately provisioned local inputs |
| `docs/` | Product contracts, operations, release notes, and scoped evidence |

## Contributing and security

Read [CONTRIBUTING.md](CONTRIBUTING.md) and [AGENTS.md](AGENTS.md).
Keep fixture validation reproducible and private data out of commits and build
output. Changes are recorded in [CHANGELOG.md](CHANGELOG.md).

Report vulnerabilities according to [SECURITY.md](SECURITY.md).

## License

[MIT](LICENSE) — Copyright (c) 2026 Artem Sem.
The repository license does not grant distribution rights for separately
provisioned datasets; their source rights and qualification remain independent.
