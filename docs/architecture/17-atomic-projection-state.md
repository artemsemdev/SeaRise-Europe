# Atomic projection state

The framework-neutral reducer in `src/web/src/domain/projection-state.ts` owns
the complete projection journey. React components may dispatch commands and
render the returned state; they must not combine an accepted result with a
pending selection.

## Transition table

| Current state | Accepted event | Next state | Retained accepted tuple |
|---|---|---|---|
| `booting` | matching `release-ready` | `ready` | none |
| loaded state | newer `search-started` | `searching` | retained when present |
| `searching` | matching `search-completed` | `evaluating` or `updating` | retained only for `updating` |
| loaded state without a result | newer `evaluation-started` | `evaluating` | none |
| loaded state with a result | newer `update-started` | `updating` | retained with its original selection |
| `evaluating` or `updating` | matching `assessment-completed` | `result` | replaced atomically |
| active operation | matching availability/failure event | technical state | retained when present |
| technical state | matching newer `retry-started` | prior active phase | retained when present |
| loaded state | matching newer `reset` | `ready` | none |
| any state | newer `release-update-started` | `booting` | none |

Every asynchronous completion must match the current operation token,
deterministic selection key, and immutable `dataReleaseId`. A reset, retry,
rapid selection change, or release update advances the token, so an older
completion returns the same state object and cannot alter the visible tuple.

`AcceptedProjection` is the sole render authority for a completed result. It
contains one release identity, one immutable selection, and one of the four
ADR-024 outcomes. Offline, connection-required, unsupported-browser,
integrity, and other failures are separate technical states.
