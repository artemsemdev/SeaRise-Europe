# Production browser retention and cleanup

This runbook describes local browser-storage retention for the public static
application. It does not authorize deletion of a deployed release, cloud
object, source archive, or local Phase 1 Candidate.

## Retention invariant

The browser retains exactly the active complete app/data pair and, when one
exists, the immediately previous complete recoverable pair. Rotation from A to
B to C therefore changes A to `cleanup-pending`, keeps B as `previous`, and
keeps C as `active`. A cleanup run may consider A only.

Private Candidate mode is excluded. It uses session-memory stores, creates no
retention coordinator, and never writes Candidate bytes to persistent browser
storage.

## Production trigger and authority

Cleanup starts only after a fresh page boot has completed both checks:

1. the page challenges `navigator.serviceWorker.controller` and matches its
   exact app build, data release, and precache digest;
2. the verified resource router admits the same pair and records matching
   resource-plan and admission-receipt digests as the active lifecycle record.

The production factory passes the current `WorkerClientAuthority` census and a
Web Locks adapter into the lifecycle store. The retention coordinator does not
invent a second client inventory or trust `registration.active`.

## Cleanup sequence

For each exact `cleanup-pending` pair, in deterministic lifecycle-inventory
order:

1. acquire the pair-specific exclusive admission Web Lock;
2. request a stable two-pass current-worker client census;
3. fail closed for any active, unknown, or unresponsive observation;
4. atomically publish the durable cleanup fence only when no unexpired stored
   lease or active/previous range authority protects the pair;
5. remove whole-resource receipts and lease authority;
6. remove exact shell/release Cache Storage namespaces;
7. remove exact range records and update range counters transactionally;
8. remove the lifecycle record last.

The durable fence survives successful cleanup so a stale tab cannot recreate
accepted state for the removed pair. Records for other pairs are never selected
by a prefix wider than the exact app/data pair namespace.

## Failure and retry

Client-census refusal, unknown client state, Web Lock failure, quota/storage
failure, corrupt lifecycle authority, and partial deletion all stop the run.
The coordinator reports `retryable-technical-failure`, the still-pending exact
pairs, and any pairs removed earlier in that run. This is operational state,
not a fifth scientific outcome.

After a partial failure, the lifecycle remains `cleanup-pending` with
`cleanup-failed` evidence. A later capability or retention inspection retries
the same operation. Already removed receipts, caches, leases, or ranges make
the retry idempotent, and the lifecycle record remains the final commit point.
Do not manually delete IndexedDB databases or caches to bypass a blocked
census.

## Verification

Run the focused retention and production composition evidence:

```bash
npm run test --workspace @searise/web -- \
  src/offline/production-retention-coordinator.test.ts \
  src/offline/pair-lifecycle-store.test.ts \
  src/offline/production-default-update.integration.test.ts \
  src/offline/service-worker-client-authority.test.ts \
  src/offline/worker-client-authority.test.ts \
  src/offline/range-store.test.ts
npm run type-check --workspace @searise/web
npm run lint --workspace @searise/web
python3 scripts/tests/validate_test_inventory.py
```

The focused suites cover A/B/C rotation, preservation of the previous complete
pair, active/unknown/unresponsive client blocking, stored-lease races, exact
physical deletion order, partial-failure retry, range quota/eviction atomicity,
Candidate memory-only isolation, and production-factory wiring.
