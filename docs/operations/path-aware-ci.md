# Path-aware CI and architecture fitness routing

Issue #61 owns the path router, stable aggregate statuses, and activation
boundary. The machine-readable source is the
[`architecture-fitness.json`](../../contracts/ci/v1/architecture-fitness.json)
contract.

## Stable required statuses

When Issue #74 activates managed branch protection, its ruleset must require
these workflow job names:

- `CI Gate` for tests, builds, browser checks, and routed release preflights;
- `CodeQL Gate` for path-aware JavaScript/TypeScript analysis.

Conditional jobs are not branch-protection statuses. Each workflow creates a
detection job and an aggregate gate. A selected job must report `success`, an
unselected job must report `skipped`, and a failed detector fails the
aggregate. Add a new route and its exact job expectations to
`scripts/ci/changed_components.py` and `scripts/ci/verify_ci_gate.py` in the
same reviewed change.

Until that owner slice activates, these names are a normative contract only;
this inventory does not claim that OpenTofu already manages them.

## Routes

The repository-owned router is `scripts/ci/changed_components.py`.

| Change | Selected validation |
|---|---|
| Tracked Markdown and `docs/**` | Local-link and stale-target validation |
| `src/web/**` and static consumer contracts | Lint, types, unit tests, production build, browser/accessibility, and offline lifecycle |
| Pipeline, scientific, data, or test contracts | Python pipeline, macOS settlement preflight, offline fixture, and inventory gates |
| Release-toolchain inputs | Pinned Linux and macOS release preflights |
| Repository-removal authorities | Repository-removal and static-profile validation, plus overlapping pipeline ownership |
| `src/web/**` and static-quality code | JavaScript/TypeScript CodeQL |
| Router or consuming workflow | Every currently active route |

Renames route both paths, and manual CI enables every active route. The trusted
full-source dispatch enables only its two exact evidence builders; ordinary
pull requests cannot select those builders.

## Sealed correction authority

The completed v4 lifecycle is stored under
[`contracts/repository-removal/v4/phase-3-issue-61`](../../contracts/repository-removal/v4/phase-3-issue-61/):

| Stage | Immutable commit | Record |
|---|---|---|
| P2 | `e49398964790c949fc9d64010d8fe7416bf90ba3` | Exact corrected before/after states and approval template |
| D2 | `b9aab46abfd18ecad3f54394e4a5b90681c6677b` | Live OWNER decision bound to P2 |
| A2 | `236ed27ad54d02b8665fee4c803329c2c88ef5e5` | Complete 15-path governed application |
| R2 | `c5ae8de77cef991dd21f3b7956b2b2cb23ac2918` | Application receipt binding the A2 tree and governed-state digest |

The earlier v3 P/D authority is explicitly `superseded-before-application` and
authorizes no repository state. The v4 validator replays Issue #71 P/D/A/R at
its historical commits, verifies the correction OWNER comment, checks the
exact P2/D2/A2/R2 topology, and requires both authority and governed state to
remain immutable through `HEAD`.

Every safety field remains false: the lifecycle did not inspect Candidate-v7
or TAR bytes and did not authorize publication or external-resource mutation.

## Deferred owner capabilities

Cloudflare delivery IaC (#62) and managed-platform controls (#74) remain
`deferred`. Changes below their declared path patterns fail during detection
because their required routes and CI jobs do not yet exist.

Activation is one reviewed change that must:

1. implement the route and named CI job;
2. add exact aggregate expectations and routing tests;
3. change the capability to `active` in the machine contract;
4. add the owner-specific OpenTofu, policy, credential, and evidence gates.

Activation never authorizes apply, publication, signing, production identity,
or mutation of an external resource.

## Trust boundaries and evidence

Ordinary pull-request workflows are read-only. Only CodeQL receives
`security-events: write`, without deployment or signing credentials. Protected
release, signing, and promotion workflows reject pull-request events, and no
workflow executes repository code through `pull_request_target`.

Release and publication workflows never use pull-request path shortcuts.
Scientific regression, integrity, licence, scenario, four-outcome, zero-API,
public-delivery, and provenance gates are non-waivable.

- Browser, build, range, failure, and Lighthouse evidence is retained for 14
  days.
- Protected owner-promotion evidence is retained for 90 days.
- Manifests, checksums, licences, goldens, provenance, signatures, and owner
  decisions remain immutable release or repository evidence.

A missing artifact fails its gate. Retries are not acceptance evidence; follow
the inventory rules in the [testing guide](../testing/README.md).

## Rollback

Restore the last reviewed router and verifier together after a false block or
false green. Preserve both aggregate names and every quality gate. The
standalone `static-quality.yml` workflow remains the generic-host and
Lighthouse recovery path.
