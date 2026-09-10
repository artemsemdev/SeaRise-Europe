# Application content contract

[ADR-028](../architecture/adr/ADR-028-coastal-atlas-adoption.md) defines the
accepted main coastal atlas target. ADR-024 continues to define the retained
AR6 projection reference with its four scientific outcomes. Source-backed
CoCliCo depth values and AR6 regional relative-level values are different
contracts, not interchangeable result states.

`src/web/scripts/check-target-content.mjs` runs during lint and production
build. The explicit `src/web/src/atlas/` source and named active atlas documents
may describe source-backed coastal inundation. The projection source,
projection reference documents, and all other paths retain projection-only
terminology checks. Noncanonical paths cannot acquire atlas scope.

Legacy binary outcome identifiers, property-risk scores, and unsupported
certainty remain prohibited in both products. Product copy also rejects
fabricated flood probability, safety or precision guarantees, unqualified
coverage/offline/cost promises, and relative year horizons. Tests demonstrate
both the permitted source-backed terms and continued rejection of unsafe claims.

The current emitted build still belongs to the projection application and is
scanned under its existing rules. The primary-entry migration must explicitly
update emitted-artifact scope and output isolation together. Adding a source
exception does not change the application entry or approve any published data.

## Retained Flight reference

`docs/product/Mock/SeaRise-Flight.html` is scoped to the retained AR6 projection
application. The coastal atlas uses its separate accepted design contract.
The mock body still contains rejected prototype science; its exact-byte SHA-256
and annotation must preserve the four-outcome interpretation before the scanner
excludes the mock body. It is never copied into the application build.

The annotation identifies the AR6 reference, preserves its layout/interaction
character, maps the old mock cards to the four AR6 outcomes, and keeps technical
failures outside the scientific outcome domain. `MOCK_REQUIREMENTS_MAP.md`
records the same scope and digest. Mutation checks reject broadened authority,
missing semantic mappings, and a digest that no longer matches the mock bytes.

## Historical evidence allowlist

Historical terminology is never exempted by directory. Readiness may read
`contracts/repository-removal/v1/historical-allowlist.preapproval.json`, but
final mode refuses preapproval authority. Final mode requires the committed
`historical-allowlist.json` and integrity verification against the pinned
completed removal evidence. CI separately revalidates the complete approval
chain, including live owner comments. Preapproval binds each exact repository
path to its current Git blob only and deliberately carries no commit/tree
audit claim. Final approval binds that path to both the current and audited Git
blob SHA plus one constrained rule. The scanner rejects schema-shape, ID,
commit/tree, duplicate,
active-authority, and rule/path drift.

The current source gate invokes `validate_post_cutover.py --evidence-only` with
standard-library Python and local Git. It recomputes authority blob digests,
requires unchanged historical authority and absent retired-runtime paths, and
fails on missing historical objects without fetching. It proves integrity
relative to the reviewed completed receipt; it performs no live attestation.
CI explicitly uses `--verify-owner-comment` for repository-authority or web
changes, retaining the unchanged historical validator and live GitHub check.

The preapproval document is evidence classification only. It does not approve
deletion, publication, or an inventory disposition. The final repository-
removal validator remains the authority for the owner-approved hash chain.
Neither document can allow historical terminology in `src/web` or the active
pipeline. Rules name explicit allowed claim IDs; they never suppress certainty,
property-risk, inundation, or other product claims. The separately marked
historical section of `docs/methodology.md` continues to use its narrow in-file
boundary.

ADR-024 remains authoritative for its projection release contract, never a
blanket atlas content prohibition or historical terminology exemption. Its
two obsolete outcome identifiers are accepted only inside the exact sentence
that says they do not appear in an ADR-024 release. The loader is prepared for
the schema's forthcoming exact `canonical-design-reference` rule for
`docs/product/Mock/SeaRise-Flight.html`; that rule preserves design authority
but cannot place the mock in built output.

## Runtime and dependency gates

`static-repository-gates.mjs` rejects legacy application dependencies from
three scopes:

- target source rejects Next.js, .NET/C#/NuGet, PostgreSQL/PostGIS/Npgsql,
  TiTiler, Azurite, runtime Azure geocoding, legacy Compose services, and a Node
  production server;
- emitted output applies the same rules without any tooling exception;
- repository readiness scans tracked source, HTML/CSS/SVG/XML, JSON, workflow,
  environment, Terraform, Docker/Compose, and extensionless configuration
  paths. Presence under a must-delete root fails final mode even when a survivor
  contains no legacy token. Shared workflows and retained local server tools
  use exact path/rule/matched-text purpose selectors rather than directory or
  filename wildcards. A package-level structural check separately rejects
  production HTTP-server dependencies, including a dependency whose name is
  also used by a retained test script. Before scanning dependency terms, target,
  readiness, and final modes also require the current v2 transition profile's
  exact 14 components and 57 inputs. Every input must occupy its exact
  component and role, match its recorded SHA-256 before its tracked Git mode is
  checked, and use the bound profile schema; extra, missing, reordered,
  symlinked, or mode-mutated authority fails closed. Repository and built-output
  traversal uses non-following metadata checks before every read.

Readiness classification is not removal approval. `--repository-final` changes
every remaining pending-removal reference into a failure and also rejects any
unclassified reference. It is the Phase 2 final clean-repository gate. Printed
occurrence counts are diagnostics only; they are not an inventory-completeness
claim. The scanner and its mutation suite necessarily contain the literal
policy tokens they reject. They remain the only executable policy-definition
exceptions. Under [ADR-027](../architecture/adr/ADR-027-post-cutover-application-evolution.md),
their approved historical versions remain bound to the completed removal
receipt, while their current versions may evolve through reviewed changes and
mutation tests. The shared post-cutover adapter verifies unchanged current
historical authority and continued absence of the removed runtime; its live CI
mode also revalidates the original approval chain. Neither mode waives any
current content or dependency rule.

Static-output isolation independently rejects both unversioned and `/v1/`
forms of `/assess`, `/geocode`, and `/config`. Only exact
`/releases/<dataReleaseId>/config/*.json` references named by the loaded release
manifest are allowed. Candidate/local-data/archive paths and the canonical
Flight path are rejected through every Vite, shell, release-manifest, and
actual-output authorization channel before bytes are read. Every authorized
output is then inspected as text or extracted ASCII/UTF-16 strings; exact
Flight bytes are rejected even under a renamed manifest-authorized path. The
digest is recalculated from the current canonical mock and must be declared by
`MOCK_REQUIREMENTS_MAP.md`; it is never a stale constant in the output gate.

## Commands

```bash
cd src/web
node scripts/check-target-content.mjs
node scripts/static-repository-gates.mjs --target
node scripts/static-repository-gates.mjs --repository-readiness
npm run build
# Run only after approved Phase 2 removal is complete:
node scripts/static-repository-gates.mjs --repository-final
```

The build command invokes the emitted-asset scan automatically.
