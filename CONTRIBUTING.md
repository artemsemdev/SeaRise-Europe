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

Run the checks relevant to the files you changed. The current legacy baseline
uses:

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
