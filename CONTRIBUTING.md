# Contributing

SeaRise Europe adopts the coastal atlas under
[ADR-028](docs/architecture/adr/ADR-028-coastal-atlas-adoption.md) and
[epic #490](https://github.com/artemsemdev/SeaRise-Europe/issues/490). Read the
[atlas requirements](docs/product/COASTAL_ATLAS_PRD.md) and
[development quickstart](docs/operations/coastal-atlas-development.md) before
implementation work. [ADR-021](docs/architecture/adr/ADR-021-static-first-offline-geospatial-architecture.md)
and the [earlier delivery plan](docs/delivery/README.md) retain their scope for
the AR6 reference and subsequent public-delivery work.

## Working rules

- Follow `AGENTS.md`, including attribution, focused pull requests, the pull
  request template, and Conventional Commits.
- Keep product, architecture, data contracts, implementation, and tests aligned.
- Do not describe synthetic fixtures as validated scientific data.
- Record source version, URL, licence, attribution, size, and SHA-256 for every
  acquired dataset.
- Keep raw/large datasets, build outputs, credentials, and local state out of
  Git unless a reviewed fixture or public contract explicitly belongs here.
- The atlas permits the explicit read-only loopback raster/place adapter in
  real-local mode. Normal fixture development needs no local data service.
  This exception does not authorize a public backend or change the retained
  AR6 reference's static browser architecture.
- Make scientific assumptions and uncertainty explicit.

## Pull requests

Prefer one coherent change, normally 100–400 changed lines. Separate data
contracts, pipeline logic, frontend features, infrastructure, documentation,
and legacy removal unless the change cannot be tested independently.

Use the repository pull request template and include:

- what changed and why;
- the ADR, requirement, or delivery gate it implements;
- exact verification commands and results;
- screenshots or recordings for UI work;
- source/checksum/licence and before/after statistics for data work;
- performance, cost, security, or accessibility impact where relevant;
- the passed gate that authorizes any legacy deletion.

## Local verification

Normal verification exercises the illustrative atlas at `/` and the retained
AR6 reference at `/projections/`. With Node 20.20.1 and npm 11.12.1, run from
the repository root:

```bash
npm ci
npm run web:check
npm exec --workspace @searise/web -- playwright install chromium
npm run web:e2e
npm run web:serve
```

`web:serve` serves the built fixture edition. Clean-clone builds use only
committed illustrative inputs and the retained projection release fixture;
they never discover or copy private data. `npm run web:dev` also selects the
fixture explicitly.

For provisioned CoCliCo data, follow the [atlas quickstart](docs/operations/coastal-atlas-development.md):
start `npm run local:start`, then run `npm run local:e2e` separately against
that service. These manual checks require ignored local inputs; they are not
ordinary CI. Missing real-local data must fail without fixture fallback.

The [private candidate binding](docs/operations/phase-2-private-release-binding.md)
remains a separate read-only AR6 reference workflow. Its release manifest is
the browser entry point for that reference's data. Regenerate schema-derived
browser types after release-contract changes with
`npm run generate:contracts --workspace @searise/web`; `web:check` detects stale
generated types. Local validation does not qualify a public or scientific release.

Run the checks relevant to the files you changed:

```bash
# Static browser application
npm run web:check

# Pipeline
python -m pytest src/pipeline/tests
```

The static browser and release pipeline's checked-in scripts and CI jobs are
authoritative. Do not rely on documentation-only
claims when an executable check can enforce the contract.

## TDD and test migration

Before implementation, identify in the PR:

- the invariant and first target test;
- the command/output proving the intended red failure;
- the legacy test, if any, that characterizes the same behavior;
- the approved issue gate and target evidence that would later permit deletion.

Then run red, green, refactor, and independent compare before promoting a target
suite. The executable rules and examples are in
[`docs/testing/README.md`](docs/testing/README.md). For focused feedback:

```bash
python scripts/tests/validate_test_inventory.py
python scripts/tests/changed_suites.py --changed path/to/changed-file
python scripts/tests/changed_suites.py --base-ref origin/master
```

Use `--run` only for the listed credential-free fast suites. Regional, release,
browser, public-delivery, and scheduled gates remain separate and mandatory for
their promotion stage.

Test retirement is an explicit lifecycle transition. Keep retired suite and
baseline records for audit history, set both to `status: retired`, cite the
approved removal issue, and record equivalent-or-stronger target evidence.
Retired suites are never selected or executed. Do not mark a suite or baseline
retired while any declared test remains on disk, and do not assign an active
baseline test to a retired suite.

Do not delete or disable a useful test when adding its replacement. A later
retirement PR must update the exact suite and `baselineTests` entries in
`tests/test-inventory.json`, cite the approved removal issue, and link
equivalent-or-stronger evidence. A flake needs an owner, defect issue, expiry,
and inventory record; retrying until green is not an acceptance result.

## Documentation

- `docs/architecture/` distinguishes the current atlas, retained AR6 reference,
  and historical decisions.
- `docs/delivery/README.md` records migration order and exit evidence.
- `README.md` is the honest current/target status summary.
- Update status and dates when meaning changes.
- Delete superseded delivery documents instead of maintaining contradictory
  plans.
- Verify relative links after renaming or deleting files.

## Security and data safety

Never commit API keys, tokens, cloud credentials, connection strings with real
passwords, signing keys, or raw private user data. Use ignored local files and
protected CI environments. See [SECURITY.md](SECURITY.md).
