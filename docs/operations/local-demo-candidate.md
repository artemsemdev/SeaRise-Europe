# Local demonstration candidate

This workflow prepares a private local demonstration of the Coastal Atlas with
provisioned CoCliCo data. It does not publish a scientific/MVP release or
qualify the public-delivery backlog. Keep source rasters, basemap archives and
local candidate output outside Git.

## Prepare

Use the official Node 20.20.1 distribution and npm 11.12.1. Homebrew builds with
the same Node version can have different Brotli/ICU/zlib values; the preflight
checks the exact byte-affecting contract. Install dependencies in each checkout
with `npm ci`, including when changing architecture. Provision the documented
atlas workspace and its compatible Python environment first; see
[Atlas development](coastal-atlas-development.md) and the
[real-local adapter](coastal-atlas-real-local-adapter.md).
Official Node 20.20.1 bundles npm 10.8.2, so select npm 11.12.1 separately on
`PATH`, including for nested npm commands, before installation or validation.

From the clean reviewed candidate checkout:

```bash
node --version # v20.20.1
npm --version  # 11.12.1
npm ci
npm run web:check
npm exec --workspace @searise/web -- playwright install chromium
npm run web:e2e
demo_data_root="/absolute/path/to/local-data/atlas/europe"
demo_candidate="$PWD/.cache/demo-candidates/rc-1"
npm run demo:preflight -- --data-root "$demo_data_root"
npm run demo:prepare -- --data-root "$demo_data_root" --output "$demo_candidate"
npm run demo:serve -- --data-root "$demo_data_root" --candidate "$demo_candidate"
```

Open `http://127.0.0.1:4181/` in a fresh browser profile. The candidate launcher
always binds `127.0.0.1` and refuses an occupied port; select another explicitly
with `--port`. Use explicit `--python /absolute/interpreter` when the compatible
environment differs from the main checkout's `.venv`. Unset existing
`SEARISE_*`/`VITE_*` variables before invoking `demo:preflight`, `demo:prepare`
or `demo:serve`. Keep this isolated checkout free of active `.env`,
`.env.local`, `.env.real-local` and `.env.real-local.local` files at its root
and under `src/web`; preserve needed configuration elsewhere instead of deleting
another checkout's files.

The candidate contains only the built app and a local-demo receipt: exact source
revision, pinned tool versions, six confined data-manifest/receipt hashes and a
sorted SHA256 file inventory. Its files are read-only and preparation never
overwrites an existing candidate. Private data remains separately provisioned
and read-only. This receipt is a local integrity/reproducibility record, not a
signature or scientific qualification. The raster service verifies raster bodies
against their declared SHA256 values at startup. Candidate identity checks pin
the basemap receipts. The launcher does not rehash PMTiles archives, fonts or
sprites against those receipts on each launch; a same-size body mutation can
therefore leave candidate identity unchanged. Provisioning integrity checks and
served basemap/range/browser checks remain part of acceptance.

The `/` atlas entry is built as `real-local`. Its `/atlas-data/` catalog, place
lookup, raster inspection/tiles and basemap routes use the same loopback origin
as the app; the launcher attaches the read-only local adapter rather than
exposing the data directory as a static file tree. `/projections/` remains the
separately labeled, committed synthetic AR6 reference fixture. It does not use
the provisioned CoCliCo atlas inputs, and the two data paths do not substitute
for one another.

## Validate the served artifact

Keep the candidate server running in one terminal, then run `npm run local:e2e`
in a second terminal from the same checkout. Use a distinct output directory
for each attempt, for example:

```bash
npm run e2e:real-local --workspace @searise/web -- --output "$PWD/.cache/atlas-qa/rc-1/playwright"
```

Preserve failed logs before another run. Invoke the workspace command directly
when passing Playwright options so the root script's nested npm invocation does
not consume them.
The original browser specs also write screenshots to fixed
`.cache/atlas-qa/screenshots`, `experience` and `no-lab` directories. Move those
directories into the attempt's archive after each run, before starting another
attempt; `--output` alone does not isolate these screenshots.
If the server uses an explicitly
chosen alternate port, pass its URL to the browser suite for that command only,
for example `SEARISE_ATLAS_URL=http://127.0.0.1:4187 npm run local:e2e`. Do not
export this variable into the candidate-launch terminal: the CLI rejects
inherited `SEARISE_*` overrides. The suite's viewport skips are intentional and
reported separately from passes. Check a fresh browser entry and reload, all six
year/defense combinations, point inspection, search, comparison, share/reload,
mobile controls and explicit unknown/error handling. Preserve failed logs before
fixing a defect; do not retry until green without diagnosis.

The atlas entry does not register a service worker or implement persistent
storage of its private derived raster data; tile responses are `no-store`. The
retained `/projections/` fixture can register a root-scoped service worker for
its static application/fixture resources, so use a fresh browser profile when
validating a candidate rather than inheriting an earlier edition's caches. A
local URL works while this server is running on this computer; it does not let
another viewer access the data.

## Demonstration, 3–5 minutes

1. Start with Europe, explain the source's SSP5-8.5 high-tide condition and the
   two modeled defense assumptions.
2. Find Venice and inspect a verified coastal model cell. Compare 2030, 2050 and
   2100 in the sidebar and timeline.
3. Switch defense assumptions, then enter comparison mode and describe the
   displayed year labels.
4. Show one distinct second place, such as Rotterdam, and explain that a
   selected point represents a native 25 m cell, not the whole city.
5. Reload a prepared shared view. Explain that uncolored land may lack coverage,
   zero does not mean safe, and the map is not a property forecast.

Use the verified candidate's screenshots and point URLs as operator references.
Keep real-data screenshots local unless distribution is separately qualified.

## Stop and return to an earlier candidate

Stop with Ctrl+C and wait for the launcher and its raster child to exit.
Ctrl+C or SIGTERM also cleans up an owned native child during preflight/startup.
Preserve the sealed earlier candidate directory: its `candidate.json` records
the full `sourceRevision` and external data-manifest identities.

Use a separate clean checkout or detached worktree at that exact recorded
commit. Install that revision's pinned dependencies with `npm ci`, select the
compatible Python environment, and restore/provision the dataset whose six
manifest/receipt hashes match the earlier candidate. Git checkout does not
restore ignored CoCliCo/basemap data; restoring the earlier data pair is a
separate prerequisite. Do not edit manifests or candidate receipts to make
mismatches disappear.

From that exact clean checkout, invoke `npm run demo:serve -- --data-root
"$demo_data_root" --candidate "$demo_candidate"`, using absolute paths to the
matching external dataset and the preserved earlier candidate directory. The
candidate can remain in its original checkout; `demo:serve` accepts that
explicit path. Rebuilding in place is not rollback, and `demo:prepare` refuses
to overwrite the old directory. Use a fresh browser profile for the restored
candidate. Source/data/app mismatches and occupied ports must fail before the
new launcher accepts visitors. Preserve the previous compatible app/data pair
rather than mixing files across candidates. Do not copy the real-local app to a
public static host: its read-only loopback adapter and private data are still
required.

## Acceptance evidence

Final evidence and the PR identify the exact tested source, candidate receipt,
fixture and real-local results, measured startup timings and remaining
limitations. Lighthouse raw results remain visible; any owner-approved local
exception is explicitly bounded and does not satisfy the public >=90/MVP release
requirement. A failing required check blocks integration.

On 2026-10-02 the owner approved a temporary local-demo exception: each of
three cold fixture audits must score at least 50 for performance and at least
90 for accessibility, best practices and SEO, with no render errors. The
exception expires at 2026-10-16 00:00 Europe/Berlin. It admits labeled fixture
evidence for local-demo preparation; real/private scientific or public release
qualification cannot consume it. Raw performance failures against 90 remain
visible. The expiry controls CI acceptance, not the operation of an already
prepared local artifact.
