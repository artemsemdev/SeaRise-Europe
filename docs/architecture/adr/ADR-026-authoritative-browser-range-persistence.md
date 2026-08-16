# ADR-026 — Authoritative browser range persistence

> **Status:** Accepted
>
> **Decision date:** 2026-08-16
>
> **Decision owner:** Project owner
>
> **Scope:** Browser persistence for complete resources and HTTP byte ranges
>
> **Evidence:** [Issue #60 range-cache compatibility measurement](../../evidence/phase-2/issue-60-range-cache-compatibility.md)

## Context

Issue #60 measured real COG and PMTiles range responses in Chromium, Firefox,
and WebKit. Every engine rejected `Cache.put()` for an HTTP `206` response. A
range-bearing request could also match a cached complete `200`, so Cache
Storage cannot establish which interval its returned bytes authorize.

The same spike proved that IndexedDB can retain bytes and return an exact
contained slice. That is a storage capability, not sufficient integrity
authority. Production persistence additionally requires a release-bound digest
for the complete admitted interval. The current release contracts provide that
authority for fixed COG chunks. They do not provide authoritative interval
digests for PMTiles.

ADR-024 makes the analysis COG the only scientific raster input and keeps
PMTiles visual-only. Storage behavior must preserve that separation and must
not turn a cache or delivery failure into a scientific result.

## Decision

Use the following fail-closed storage boundary:

| Resource | Allowed storage | Required authority |
|---|---|---|
| Complete shell and explicitly approved complete release resources | Cache Storage in the exact app/release namespace | Exact canonical URL, MIME type, byte size, SHA-256, and cache policy |
| Analysis COG ranges | Bounded IndexedDB only | Exact app/release/artifact identity and one complete integrity-authorized chunk digest before admission |
| Visual PMTiles ranges | Network only; fetch and response caching policy must be `no-store` | No browser range persistence is authorized by the current release contract |
| Private Candidate-v7 inputs | Session-only local handling | Explicit local invocation; no durable browser, CI, build, or external storage |

Cache Storage must never store a `206` response. Range requests must never use
an arbitrary complete-response match as proof of interval coverage.

Only a complete COG chunk whose bytes match the release-authorized interval
SHA-256 may enter IndexedDB. Reads may return the exact chunk or one
half-open slice contained by that single chunk. Adjacent records are not
assembled to manufacture authority that no individual record possesses.

PMTiles fetches and responses must use a `no-store` caching policy. PMTiles
must not enter Cache Storage, IndexedDB, or the session-memory range store.
This applies even though the compatibility spike demonstrated that an untyped
PMTiles byte sample can round-trip through IndexedDB. PMTiles range
persistence remains disabled until a separate, reviewed promotion contract:

1. defines canonical PMTiles intervals and supplies their exact digests;
2. binds those intervals to one app/release/artifact identity;
3. specifies admission, corruption, quota, eviction, and update behavior;
4. adds cross-engine deterministic tests; and
5. confirms that PMTiles remains visual-only and cannot become scientific
   lookup authority.

Candidate-v7 and its TAR remain ignored local artifacts. An explicit local
test may read authorized COG bytes into session memory, but it must not register
a persistent worker, write durable range records, copy candidate bytes into a
static build, or upload them.

## Coordinated admission and receipt authority

Cache Storage and IndexedDB do not provide a shared browser transaction. The
static application therefore makes one narrower guarantee: a resource set is
logically available only after all exact whole resources and authorized COG
chunks have been admitted, read back, and bound by a versioned admission
receipt published last. The receipt binds the exact app/release pair and
deterministic hashes of the complete-resource and range-identity sets. It
contains no query, coordinates, location, selection, scientific outcome, or
other personal state.

Batch adapters label newly written records with an opaque operation identity.
Before receipt publication, cancellation, quota, integrity, or storage failure
triggers conditional rollback of only records still owned by that operation;
pre-existing verified records are retained. Cache Storage and IndexedDB cannot
guarantee cross-store physical rollback after a browser crash, so cleanup of
orphan bytes is conditional and best-effort. Such bytes remain unreceipted and
must never be returned by authoritative reads or used for an offline
availability claim.

Private engineering releases and explicit local Candidates use bounded process
memory for complete resources and COG chunks. They do not open Cache Storage or
IndexedDB. PMTiles bypasses coordinated admission entirely and remains
network-only with `no-store`; it never enters persistent or Candidate memory
stores. Admission, quota, cancellation, and integrity failures remain technical
failures and never become an ADR-024 scientific outcome.

## Scientific and failure boundary

The scientific domain continues to expose exactly the four ADR-024 outcomes:
`ProjectionAvailable`, `DataUnavailable`, `OutOfScope`, and
`UnsupportedGeography`.

Missing cache entries, unavailable network ranges, quota errors, transaction
aborts, integrity mismatches, corruption, unsupported storage, and update
failures are technical states. They are not a fifth scientific outcome and
must not replace or mutate the last accepted projection result.

PMTiles rendering remains non-authoritative visual context. Neither cached nor
network-delivered PMTiles pixels may be sampled or interpreted as science.

## Consequences

Positive consequences:

- the persisted scientific bytes have exact release-supplied interval
  authority;
- complete-response and range-response storage use primitives that match their
  measured browser behavior;
- PMTiles cannot acquire accidental scientific or offline authority;
- cache failures remain separate from ADR-024 outcomes; and
- private candidate bytes remain local and non-durable.

Trade-offs:

- the visual PMTiles layer requires a network connection;
- complete offline map visuals are deferred;
- COG persistence needs bounded accounting, deterministic eviction, lease and
  active/previous-pair protection, and corruption quarantine; and
- a future PMTiles offline feature requires a new reviewed promotion contract,
  not an implementation-only change.

## Alternatives considered

### Persist both COG and PMTiles samples because the IndexedDB probe passed

Rejected. The probe measured byte-storage mechanics but did not provide
PMTiles interval authority. Persisting those samples would exceed the current
release contract.

### Store range responses in Cache Storage

Rejected. All measured engines rejected direct `206` admission, and a range
request matched an unrelated complete `200` response.

### Keep PMTiles ranges in the session-memory range store

Rejected. Changing durability does not create interval integrity authority.
The same promotion gate applies to memory and persistent range stores.

### Disable all browser data persistence

Rejected. Exact authorized COG chunks and approved complete resources can be
stored safely within bounded, release-isolated contracts.

## Migration and rollback

Implementation and documentation that previously described PMTiles range
persistence must be narrowed to COG-only persistence. Existing unpromoted
PMTiles range records, if any are encountered during development, are
untrusted and must be ignored or quarantined; they must not be migrated into an
active namespace.

Rollback uses the previous complete app/release pair. It does not relax the
storage authority boundary. Git history retains the prior implementation and
evidence text, while this ADR is the active owner decision.

## Acceptance criteria

- Cache Storage admits only complete, byte-verified resources and rejects or
  bypasses every `206`.
- IndexedDB admits only release-authorized complete COG chunks and returns only
  exact or single-containing half-open slices.
- PMTiles fetches and responses use `no-store`, and PMTiles cannot enter Cache
  Storage, IndexedDB, or the session-memory range store.
- Cache namespaces and range records are isolated by exact app/release
  identity, bounded, and fail closed on corruption or quota/transaction error.
- Authoritative offline reads require an exact verified resource-plan receipt
  published only after complete cross-store readback; unreceipted physical
  bytes are unavailable.
- Conditional rollback deletes only records still owned by the failed or
  cancelled operation and never removes pre-existing accepted resources.
- Candidate-v7 tests remain explicit, local, read-only, and session-only.
- Tests keep technical failures separate from all four ADR-024 outcomes.
- The compatibility evidence continues to report the original browser
  observations without rewriting them as scientific or persistence authority.

## Relationship to earlier decisions

ADR-026 refines ADR-021's offline storage design and the owner implementation
scope inferred from the Issue #60 compatibility spike. It does not change the
measured browser results. It does not amend ADR-024's scientific method,
outcomes, or prohibition on using PMTiles as science. ADR-025's repository
cutover and external-resource boundaries remain unchanged.
