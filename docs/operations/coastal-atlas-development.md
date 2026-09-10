# Coastal atlas development

The main route `/` is the coastal atlas. Standard development and CI use a small,
committed illustrative fixture; the UI identifies that edition prominently.
The real-local edition uses separately provisioned source data through a
read-only loopback adapter. These are engineering workflows, not public
publication or scientific-release approvals.

## Fixture workflow

From the repository root, use Node 20.20.1 and npm 11.12.1:

```bash
npm ci
npm run web:dev
```

Vite prints the development URL. For validation and a production preview:

```bash
npm run web:check
npm run web:serve
```

The preview listens at `http://127.0.0.1:4173/`. `web:check` runs lint, type
checking, unit/contract tests, and the build's content and output checks. It
requires no private atlas files or local raster service. Installing dependencies
and the managed browser can require network access; runtime fixture data does
not require an external data service.

Install Chromium once, then run the ordinary browser suite:

```bash
npm exec --workspace @searise/web -- playwright install chromium
npm run web:e2e
```

The fixture browser suite includes `tests/atlas-fixture.spec.ts`. It excludes
`tests/real-local/`; those source files are still typechecked. AR6 reference
checks use `/projections/`, and the architecture page remains at
`/about/architecture/`.

## Provisioned local workflow

Provision the existing verified atlas workspace before selecting real-local
mode. Startup validates it; it does not acquire, rebuild, or publish the inputs.
The default data root is `local-data/atlas/europe` in the main repository
checkout, including when the application runs from a Git worktree.

That root must contain the version-2 `manifest.json` and its confined CoCliCo
rasters for the exact six SSP585 year/defense combinations, plus the local
`basemap/` resources and `context/manifest.json` with its verified place index.
The browser receives a public catalog rather than this private disk manifest.
Do not copy these inputs into `src/web/public`, `dist`, or a commit.

The adapter defaults to the main checkout's `.venv/bin/python`. It needs the
pipeline's compatible NumPy and Rasterio environment. Explicit overrides are
available when the data or interpreter lives elsewhere:

```bash
export SEARISE_ATLAS_ROOT="/absolute/path/to/local-data/atlas/europe"
export SEARISE_ATLAS_PYTHON="/absolute/path/to/python"
npm run local:start
```

Omit the exports when using the defaults. On Apple Silicon the default
interpreter is launched with the native architecture; an explicit interpreter
must itself be usable in the selected environment. The application listens
only on `http://127.0.0.1:4181/`. Keep that server running while using the UI.

To inspect the built real-local edition instead:

```bash
npm run local:build
npm run local:serve
```

Stop the development server first because both use port 4181. The built local
edition still needs its provisioned data and adapter; copying `dist` to a public
static host does not provide the local dataset. Run `npm run web:build` again
when returning to fixture preview. Use matching build and serve commands for
each edition.

## Manual real-local browser checks

Start either the real-local development server or its built preview in a
separate terminal, install Chromium as above, and run:

```bash
npm run local:e2e
```

The dedicated Playwright configuration runs the four
`tests/real-local/local-inundation-{atlas,experience,source,zoom}.spec.ts`
journeys against the already running service. `SEARISE_ATLAS_URL` can select
another explicitly started local URL. These checks require the provisioned
inputs and are not ordinary clean-clone CI gates. Their desktop, mobile, and
boundary projects do not establish public delivery or scientific approval.

CI runs the fixture browser suite, injected-provider unit tests, and the
adapter's deterministic raster tests in `src/pipeline/tests/atlas/`. Changes to
`scripts/atlas/` trigger both web and pipeline validation; changes to
`data/cartography/` trigger web validation. The pipeline lints the adapter along
with its retained Python package. Existing scientific and repository-history
checks retain their independent authority.

The projection service worker remains at `/service-worker.js`, but its sealed
precache contains `/projections/index.html` and projection resources. It does
not precache `/`, `/index.html`, or private `/atlas-data` responses. Atlas
fixture development does not imply an offline real-data atlas guarantee.
