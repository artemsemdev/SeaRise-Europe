# Static offline client lifecycle runbook

This runbook describes the public static application's source-bound browser
leases and the fail-closed client census used before exact-pair cleanup. It is
an application-storage safety mechanism, not scientific authority and not a
deployment rollback mechanism.

## Scope and invariants

- Only the exact verified service worker may mint, renew, or release a
  persistent lease.
- The service worker derives the owner from
  `ExtendableMessageEvent.source.id`. A page cannot submit or override that
  client identity.
- Lease expiry is worker-minted: 120 seconds, renewed by the page every 30
  seconds. A failed renewal makes the page fail closed.
- A heartbeat or release from another browser client is refused even if that
  client knows the lease UUID.
- Cleanup requires an exclusive exact-pair lock and a stable two-pass
  `clients.matchAll({ type: "window", includeUncontrolled: true })` census.
- Every enumerated window is challenged through a dedicated `MessageChannel`.
  Active, unknown, unresponsive, or unstable client evidence blocks cleanup.
- The IndexedDB cleanup fence is the sole durable commit point. A census never
  overrides a live lease or permits acquisition after the fence is established.
- The service worker does not call `skipWaiting()` or `clients.claim()`.
- Git/deployment history remains the application rollback authority.

Private Candidate sessions are outside this mechanism. They remain memory-only
and must create no service-worker authority port, challenge listener, lease
UUID, IndexedDB lease, heartbeat timer, or census request. Candidate-v7 and its
TAR stay in their ignored local paths and are never copied into a build or test
artifact.

## Durable records

Public leases live in IndexedDB database `searise-offline:v1`, schema version
4, object store `leases`. Each valid record binds:

- the exact application/release pair;
- the controller-generated lease UUID;
- the service-worker-observed `sourceClientId`;
- the worker-minted expiry time.

The unique `by-pair-source` index prevents one browser client from holding two
live leases for the same pair. Legacy records without a valid source identity
are treated conservatively: while live, they block cleanup.

## Cleanup decision sequence

1. Acquire the exact-pair Web Lock.
2. Ask the exact verified worker for a census of the target pair.
3. Enumerate all window clients, challenge them in parallel, and enumerate a
   second time.
4. Abort if enumeration changes or any observation is active, unknown, or
   unresponsive.
5. Establish the durable cleanup fence atomically with the final lease check.
6. Delete receipt authority, pair-scoped cache/ranges, and finally the lifecycle
   record. A partial failure remains retryable and does not remove the fence.

The census is advisory safety evidence up to step 4. Step 5 is the race-safe
authority that prevents a lease from appearing between observation and cleanup.

## Reproducible validation

From `src/web` in a clean clone using the committed synthetic fixture:

```bash
npm ci
npm run lint
npm run type-check
npm test -- --run
npm run build
npx playwright test tests/client-lease-lifecycle.spec.ts --project=chromium
```

The focused Chromium test opens two same-origin tabs and verifies:

- two leases have distinct lease UUIDs and distinct worker-derived client IDs;
- the worker census reports both clients as active;
- census client IDs exactly match the durable source bindings;
- closing one tab releases only its own lease.

Unit coverage additionally proves cross-client spoof refusal, worker-minted
renewal, malformed-source refusal, cleanup-fence refusal, unresponsive-client
handling, census-set instability, strict protocol validation, and Candidate
memory-only behavior.

## Failure handling

- `lease-refused`: keep the resource router unavailable or fail the active page
  closed. Do not manufacture a local expiry or retry under a different identity.
- `census-refused` or timeout: report cleanup as blocked and retain all pair
  storage.
- active, unknown, or unresponsive observation: retain all pair storage and
  retry only after the client situation is understood.
- database or fence failure: retain lifecycle authority and retry; never bypass
  the fence with manual record deletion.
- schema upgrade blocked by another page: close stale tabs, then retry normally.

Do not inspect, modify, upload, or publish Candidate-v7 while diagnosing these
public static lifecycle failures.
