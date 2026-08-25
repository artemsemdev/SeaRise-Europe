# Path-aware CI and architecture fitness routing

Issue #61 owns the path router, stable aggregate statuses, and activation boundary.
The machine-readable contract is [`architecture-fitness.json`](../../contracts/ci/v1/architecture-fitness.json).

## Stable required statuses

Branch protection requires these workflow job names:

- `CI Gate` for tests, builds, browser checks, and routed release preflights;
- `CodeQL Gate` for path-aware JavaScript/TypeScript analysis.

Conditional jobs are not branch-protection statuses. Each workflow creates its
detection job and aggregate gate. Selected jobs must be `success`, unselected
jobs `skipped`, and a failed detector fails the aggregate. Add new route jobs to `scripts/ci/verify_ci_gate.py` in the same PR.

Issue #74 must import these names before changing rulesets; this inventory does not claim that OpenTofu already manages them.

## Routes

The repository-owned router is `scripts/ci/changed_components.py`.

| Change | Selected validation |
|---|---|
| Tracked Markdown and `docs/**` | local-link and stale-target validation |
| `src/web/**` | lint, types, unit tests, production build, browser/accessibility, offline lifecycle, JavaScript CodeQL |
| Target release/delivery contracts | pipeline producer tests and static-web consumer tests |
| Pipeline, scientific, data, or test contracts | Python pipeline and inventory gates |
| Release-toolchain inputs | pinned Linux and macOS preflights |
| Repository-removal authorities | v2 removal and static-profile validation |
| Router or consuming workflow | every currently active route |

Renames route both paths; manual CI enables all active routes. Trusted full-source dispatch enables only its two exact evidence builders.

## Deferred owner capabilities

Cloudflare delivery IaC (#62) and platform controls (#74) remain `deferred`; their future paths fail detection and `CI Gate`.

Activation is one reviewed change that must:

1. implement the route and named CI job;
2. add exact aggregate expectations and routing tests;
3. change the capability to `active` in the machine contract;
4. add the owner-specific OpenTofu, policy, credential, and evidence gates.

Activation never authorizes apply, publication, signing, or production identity.

## Trust boundaries

Ordinary PR workflows are read-only. Only CodeQL receives
`security-events: write`, without deployment or signing credentials. Protected
release/signing/promotion workflows reject PR events, and no workflow executes
repository code through `pull_request_target`.

Release/publication workflows never use PR path shortcuts. Scientific,
integrity, licence, scenario, four-outcome, zero-API, public-delivery, and
provenance gates are non-waivable. A performance waiver records the measured
regression, rationale, owner, and expiry without changing release evidence.

## Evidence retention

- browser, build, range, failure, and Lighthouse evidence: 14 days;
- protected owner-promotion evidence: 90 days;
- manifests, checksums, licences, goldens, provenance, signatures, and owner
  decisions: immutable release/repository evidence.

A missing artifact fails the gate. Retries are not acceptance evidence; follow
the inventory rules in [`docs/testing/README.md`](../testing/README.md).

## Rollback

Restore the last reviewed router and verifier together after a false block or
green. Keep both aggregate names and all quality gates. The standalone
`static-quality.yml` remains a dispatchable generic-host/Lighthouse recovery.
