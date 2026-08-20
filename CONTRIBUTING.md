# Contributing

SeaRise Europe is migrating from its legacy distributed implementation to the
static-first architecture accepted in
[ADR-021](docs/architecture/adr/ADR-021-static-first-offline-geospatial-architecture.md).
Read that decision and the [active delivery plan](docs/delivery/README.md)
before proposing implementation work.

## Working rules

- Follow `AGENTS.md`, including attribution, focused pull requests, the pull
  request template, and Conventional Commits.
- Keep product, architecture, data contracts, implementation, and tests aligned.
- Do not describe synthetic fixtures as validated scientific data.
- Record source version, URL, licence, attribution, size, and SHA-256 for every
  acquired dataset.
- Keep raw/large datasets, build outputs, credentials, and local state out of
  Git unless a reviewed fixture or public contract explicitly belongs here.
- New product flows must not add dependencies to the retiring backend,
  database, tile server, or runtime geocoder.
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

The static application is the authoritative target workflow. From the
repository root:

```bash
npm ci
npm run web:check
npm run web:e2e
npm run web:serve
```

`web:serve` serves only the generated static output. Clean-clone builds copy the
committed synthetic release fixture into that output; they never discover or
copy the ignored private Phase 1 candidate. The manifest is the only browser
entry point for a data release. Regenerate schema-derived browser types after a
contract change with `npm run generate:contracts --workspace @searise/web`;
`web:check` fails if the committed generated file is stale.

An operator may bind the ignored private candidate read-only for an explicit
local test by following
[`docs/operations/phase-2-private-release-binding.md`](docs/operations/phase-2-private-release-binding.md).
That workflow serves the existing directory in place and is never part of a
production build or CI.

Run the checks relevant to the files you changed. Until #70 and #71 remove the
legacy baseline, its focused compatibility commands remain:

```bash
# Frontend
cd src/frontend
npm ci
npm run type-check
npm test
npm run build

# API
cd src/api
dotnet test SeaRise.sln -c Release

# Pipeline
python -m pytest src/pipeline/tests
```

As the static frontend and release pipeline are introduced, their checked-in
scripts and CI jobs become authoritative. Do not rely on documentation-only
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

- `docs/architecture/` describes the accepted target, not the legacy runtime.
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
