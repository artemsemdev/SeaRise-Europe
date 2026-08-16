# Atomic projection state

The framework-neutral reducer in `src/web/src/domain/projection-state.ts` owns
the complete projection journey. React components may dispatch commands and
render the returned state; they must not combine an accepted result with a
pending selection.

Search correlation contracts and deterministic query keys are domain-owned in
`src/web/src/domain/projection-search.ts`; the search package depends on that
contract only to normalize input and construct operations.

## Transition table

| Current state | Accepted event | Next state | Retained accepted tuple |
|---|---|---|---|
| `booting` | matching `release-ready` | `ready` | none |
| loaded state | newer matching-release `search-started` | `searching` | retained when present |
| `searching` | matching `search-completed` or `search-cancelled` | `ready` or prior `result` | retained unchanged when present |
| `searching` | matching `search-failed` | technical state | retained unchanged when present |
| settled search result | explicit immutable settlement selection | `evaluating` or `updating` | retained only for `updating` |
| loaded state without a result | newer `evaluation-started` | `evaluating` | none |
| loaded state with a result | newer `update-started` | `updating` | retained with its original selection |
| `evaluating` or `updating` | matching `assessment-completed` | `result` | replaced atomically |
| active operation | matching availability/failure event | technical state | retained when present |
| technical state | matching newer `retry-started` | prior active phase | retained when present |
| loaded state | matching newer `reset` | `ready` | none |
| any state | newer `release-update-started` | `booting` | none |

Assessment completions must match the controller-owned operation token,
deterministic selection key, and immutable `dataReleaseId`. Search uses a
separate controller-owned monotonic token plus the worker-client generation,
normalized query key, and immutable release identity. Worker tokens are never
assessment tokens. A replacement query, explicit selection, clear/cancel,
reset, retry, or release update invalidates the corresponding correlation, so
an older event returns the same state object and cannot alter the visible
tuple.

Text search completion—including zero matches—never creates a scientific
outcome and never starts assessment by itself. Only selecting a result hands
one immutable release-scoped `Selection` to the assessment controller. A
technical search failure enters a technical state and is never translated to
`DataUnavailable`.

`AcceptedProjection` is the sole render authority for a completed result. It
contains one release identity, one immutable selection, and one of the four
ADR-024 outcomes. Offline, connection-required, unsupported-browser,
integrity, and other failures are separate technical states.
