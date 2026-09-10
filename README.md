# SeaRise Europe

[![CI](https://github.com/artemsemdev/SeaRise-Europe/actions/workflows/ci.yml/badge.svg)](https://github.com/artemsemdev/SeaRise-Europe/actions/workflows/ci.yml)
[![CodeQL](https://github.com/artemsemdev/SeaRise-Europe/actions/workflows/codeql.yml/badge.svg)](https://github.com/artemsemdev/SeaRise-Europe/actions/workflows/codeql.yml)

SeaRise Europe is a coastal inundation atlas for exploring modeled water depth
across Europe. The accepted product compares CoCliCo SSP5-8.5 layers for 2030,
2050, and 2100, with and without modeled coastal defenses, under the source's
high-tide condition. Search, map inspection, year comparison, and shareable views
use the same application in both development editions.

**The default application uses an explicitly labeled illustrative fixture.**
Real source data requires a separately provisioned local workspace. Neither
edition constitutes approval of a public scientific release. Public deployment
is a later workstream in [the atlas adoption epic](https://github.com/artemsemdev/SeaRise-Europe/issues/490).

## Start from a clean clone

Use the Node version in `.nvmrc` (20.20.1) and npm 11.12.1:

```bash
npm ci
npm run web:dev
```

Open the URL printed by Vite. No private raster data, Python service, Docker,
cloud account, or credentials are needed for the fixture application.

For a checked production build and local preview:

```bash
npm run web:check
npm run web:serve
```

Open `http://127.0.0.1:4173/`. After installing the pinned Playwright Chromium
browser, run `npm run web:e2e` for fixture browser checks.

| Route | Scope |
|---|---|
| `/` | Coastal atlas; illustrative fixture by default |
| `/projections/` | Retained AR6 relative sea-level projection reference |
| `/about/architecture/` | Architecture reference page |

## Use provisioned local data

With the verified local atlas data and Python environment already provisioned:

```bash
npm run local:start
```

Open `http://127.0.0.1:4181/`. This explicit mode starts a read-only loopback
raster adapter and serves local basemap and place data. It does not download or
publish data. The adapter's private manifests and raster paths are not part of
the browser catalog or static output.

See the [development quickstart](docs/operations/coastal-atlas-development.md)
for data roots, Python selection, local build/preview commands, and the separate
manual browser journeys. `npm run web:dev` always selects the fixture, even when
private data is present on disk.

## Product and reference contracts

The current application follows the [coastal atlas requirements](docs/product/COASTAL_ATLAS_PRD.md),
[design](docs/product/COASTAL_ATLAS_DESIGN.md), and
[adoption decision](docs/architecture/adr/ADR-028-coastal-atlas-adoption.md).
Depth displays are source-model outputs, not property forecasts, probabilities,
or safety guarantees. Missing coverage and technical failures remain distinct.
Ukraine, including Crimea, remains within the European geographic scope.

The AR6 reference at `/projections/` retains its own three-scenario, three-year
relative-level contract, Flight design, scientific evidence, and offline
validation. [ADR-024](docs/architecture/adr/ADR-024-ar6-regional-projection-contract.md)
and the [projection methodology](docs/methodology.md) describe that reference;
they do not define CoCliCo inundation depth. The retained service worker caches
the projection shell, not the atlas root or private `/atlas-data` responses.

## Repository

| Path | Purpose |
|---|---|
| `src/web/` | React, TypeScript, Vite, and MapLibre application; fixture and local providers |
| `scripts/atlas/` | Read-only local raster adapter |
| `src/pipeline/` | Retained scientific/offline pipeline and deterministic adapter tests |
| `data/cartography/` | Versioned atlas cartographic inputs |
| `local-data/` | Ignored, separately provisioned local data |
| `docs/` | Current product contracts, scoped references, and historical evidence |

Start with the [documentation index](docs/README.md). Historical approvals,
removal receipts, and scientific source evidence keep their original scope;
application development does not reopen or replace those approvals.

## Contributing

Read [CONTRIBUTING.md](CONTRIBUTING.md) and `AGENTS.md` before changing the
repository. Contributions should keep fixture validation reproducible and
private data out of commits and build output.

Report vulnerabilities according to [SECURITY.md](SECURITY.md).

## License

[MIT](LICENSE) — Copyright (c) 2026 Artem Sem
