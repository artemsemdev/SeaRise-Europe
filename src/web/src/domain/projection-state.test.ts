import fc from "fast-check";
import { describe, expect, it } from "vitest";
import type { AssessmentResult } from "./scientific-lookup";
import type { Selection, TechnicalError } from "./release";
import {
  PROJECTION_EVENT_TYPES,
  PROJECTION_STATE_PHASES,
  createBootingProjectionState,
  projectionReducer,
  selectionKey,
  visibleAcceptedProjection,
  type OperationGuard,
  type ProjectionReleaseIdentity,
  type ProjectionState,
} from "./projection-state";

const RELEASE = "searise-europe-v1.0.0-20260810-c096aeab4e09";
const OTHER_RELEASE = "searise-europe-v1.0.1-20260816-aaaaaaaaaaaa";
const release: ProjectionReleaseIdentity = {
  dataReleaseId: RELEASE,
  methodologyVersion: "ar6-regional-projection-v1",
};
const technical = (code: TechnicalError["code"] = "DecodeFailed"): TechnicalError => ({
  kind: "technical-error", code, message: `${code} test`, recoverable: true,
});
const selected = (latitude = 51.9, scenario: Selection["scenario"] = "ssp2-45"): Selection => ({
  dataReleaseId: RELEASE,
  scenario,
  horizon: 2050,
  location: { kind: "coordinate", coordinates: { latitude, longitude: 4.5 } },
});
const settlement = (placeId = "geonames:2747891"): Selection => ({
  ...selected(),
  location: { kind: "settlement", placeId, coordinates: { latitude: 51.9, longitude: 4.5 } },
});

const identity = (selection: Selection) => ({
  dataReleaseId: selection.dataReleaseId,
  methodologyVersion: "ar6-regional-projection-v1" as const,
  scenario: selection.scenario,
  horizon: selection.horizon,
  analysisArtifactId: `analysis-${selection.scenario}-${selection.horizon}`,
  analysisArtifactSha256: "a".repeat(64),
  visualArtifactId: `visual-${selection.scenario}-${selection.horizon}`,
  visualArtifactSha256: "b".repeat(64),
  visualArtifactUrl: `https://fixture.invalid/${selection.scenario}/${selection.horizon}.pmtiles`,
});
const source = { locationId: 1, latitude: 52, longitude: 4, distanceKilometres: 36 };
const outcome = (state: AssessmentResult["resultState"], selection = selected()): AssessmentResult => {
  const common = identity(selection);
  switch (state) {
    case "ProjectionAvailable":
      return { ...common, resultState: state, reason: "projection-available", source,
        lowerMillimetres: 156, medianMillimetres: 247, upperMillimetres: 351,
        lowerMetres: 0.156, medianMetres: 0.247, upperMetres: 0.351, units: "m",
        baseline: "1995-2014 mean", confidence: "medium", sourceRelease: "20210809",
        sourceMemberSha256: "c".repeat(64), nativeResolutionDegrees: 1 };
    case "DataUnavailable":
      return { ...common, resultState: state, reason: "source-value-nodata", source };
    case "OutOfScope":
      return { ...common, resultState: state, reason: "outside-coastal-scope" };
    case "UnsupportedGeography":
      return { ...common, resultState: state, reason: "outside-europe-support" };
  }
};

function ready(token = 0): ProjectionState {
  return projectionReducer(createBootingProjectionState(RELEASE, token), {
    type: "release-ready", operationToken: token, release,
  });
}

function evaluating(selection = selected(), token = 1): ProjectionState {
  return projectionReducer(ready(), { type: "evaluation-started", operationToken: token, selection });
}

function guard(state: ProjectionState): OperationGuard {
  if (state.phase !== "searching" && state.phase !== "evaluating" && state.phase !== "updating") {
    throw new Error("test expected an active operation");
  }
  return state.operation;
}

function completed(selection = selected(), token = 1, state: AssessmentResult["resultState"] = "ProjectionAvailable"): ProjectionState {
  const active = evaluating(selection, token);
  return projectionReducer(active, { type: "assessment-completed", ...guard(active), result: outcome(state, selection) });
}

describe("atomic projection state", () => {
  it("publishes the complete state and event discriminants", () => {
    expect(PROJECTION_STATE_PHASES).toEqual([
      "booting", "ready", "searching", "evaluating", "updating", "result",
      "offline", "connection-required", "unsupported-browser", "integrity-error", "technical-error",
    ]);
    expect(PROJECTION_EVENT_TYPES).toHaveLength(12);
    expect(new Set(PROJECTION_EVENT_TYPES).size).toBe(PROJECTION_EVENT_TYPES.length);
  });

  it("creates a deterministic identity for every immutable selection field", () => {
    expect(selectionKey(selected())).toBe(selectionKey({ ...selected(), location: { ...selected().location } }));
    expect(selectionKey(settlement())).not.toBe(selectionKey(selected()));
    expect(selectionKey(settlement("geonames:1"))).not.toBe(selectionKey(settlement("geonames:2")));
    expect(selectionKey(selected(50))).not.toBe(selectionKey(selected(51)));
    expect(selectionKey(selected(51.9, "ssp1-26"))).not.toBe(selectionKey(selected()));
  });

  it("transitions through search and evaluation without publishing a pending tuple", () => {
    const searching = projectionReducer(ready(), { type: "search-started", operationToken: 1, selection: selected() });
    expect(searching.phase).toBe("searching");
    expect(visibleAcceptedProjection(searching)).toBeNull();
    const evaluation = projectionReducer(searching, { type: "search-completed", ...guard(searching) });
    expect(evaluation.phase).toBe("evaluating");
    const result = projectionReducer(evaluation, {
      type: "assessment-completed", ...guard(evaluation), result: outcome("ProjectionAvailable"),
    });
    expect(result.phase).toBe("result");
    expect(visibleAcceptedProjection(result)?.selectionKey).toBe(selectionKey(selected()));
  });

  it("rejects stale search completions by token, selection, and release", () => {
    const searching = projectionReducer(ready(), { type: "search-started", operationToken: 1, selection: selected() });
    const current = guard(searching);
    for (const stale of [
      { ...current, operationToken: 0 },
      { ...current, selectionKey: `${current.selectionKey}:old` },
      { ...current, dataReleaseId: OTHER_RELEASE },
    ]) {
      expect(projectionReducer(searching, { type: "search-completed", ...stale })).toBe(searching);
    }
  });

  it.each(["ProjectionAvailable", "DataUnavailable", "OutOfScope", "UnsupportedGeography"] as const)(
    "accepts the ADR-024 %s outcome",
    (resultState) => {
      const result = completed(selected(), 1, resultState);
      expect(result.phase).toBe("result");
      expect(visibleAcceptedProjection(result)?.result.resultState).toBe(resultState);
    },
  );

  it("retains the exact prior tuple while an update is pending", () => {
    const first = completed();
    const previous = visibleAcceptedProjection(first)!;
    const nextSelection = selected(53, "ssp5-85");
    const updating = projectionReducer(first, { type: "update-started", operationToken: 2, selection: nextSelection });
    expect(updating.phase).toBe("updating");
    expect(visibleAcceptedProjection(updating)).toBe(previous);
    if (updating.phase !== "updating") throw new Error("expected update");
    expect(updating.previous.selectionKey).not.toBe(updating.operation.selectionKey);
  });

  it("rejects stale update completions after rapid selection changes", () => {
    const first = completed();
    const second = projectionReducer(first, { type: "update-started", operationToken: 2, selection: selected(52) });
    const third = projectionReducer(second, { type: "update-started", operationToken: 3, selection: selected(53) });
    const stale = projectionReducer(third, {
      type: "assessment-completed", ...guard(second), result: outcome("OutOfScope", selected(52)),
    });
    expect(stale).toBe(third);
    expect(visibleAcceptedProjection(stale)).toBe(visibleAcceptedProjection(first));
  });

  it("rejects token, selection, and release guard mismatches", () => {
    const active = evaluating();
    const valid = guard(active);
    const mutations: OperationGuard[] = [
      { ...valid, operationToken: valid.operationToken + 1 },
      { ...valid, selectionKey: `${valid.selectionKey}:stale` },
      { ...valid, dataReleaseId: OTHER_RELEASE },
    ];
    for (const mutation of mutations) {
      expect(projectionReducer(active, {
        type: "assessment-completed", ...mutation, result: outcome("ProjectionAvailable"),
      })).toBe(active);
    }
  });

  it("rejects completions invalidated by reset or release update", () => {
    const active = evaluating();
    const staleGuard = guard(active);
    const reset = projectionReducer(active, { type: "reset", operationToken: 2, dataReleaseId: RELEASE });
    expect(reset.phase).toBe("ready");
    expect(projectionReducer(reset, {
      type: "assessment-completed", ...staleGuard, result: outcome("ProjectionAvailable"),
    })).toBe(reset);
    const booting = projectionReducer(active, {
      type: "release-update-started", operationToken: 3, expectedDataReleaseId: OTHER_RELEASE,
    });
    expect(booting.phase).toBe("booting");
    expect(projectionReducer(booting, {
      type: "assessment-completed", ...staleGuard, result: outcome("ProjectionAvailable"),
    })).toBe(booting);
  });

  it.each([
    ["offline", "offline"],
    ["connection-required", "connection-required"],
  ] as const)("keeps %s separate from scientific outcomes", (_name, availability) => {
    const active = evaluating();
    const failure = projectionReducer(active, {
      type: "operation-unavailable", availability, error: technical("FetchFailed"), ...guard(active),
    });
    expect(failure.phase).toBe(availability);
    expect(visibleAcceptedProjection(failure)).toBeNull();
  });

  it.each([
    ["UnsupportedBrowser", "unsupported-browser"],
    ["IntegrityFailed", "integrity-error"],
    ["SchemaInvalid", "integrity-error"],
    ["DecodeFailed", "technical-error"],
  ] as const)("maps %s to the %s technical state", (code, phase) => {
    const active = evaluating();
    const failure = projectionReducer(active, {
      type: "operation-failed", error: technical(code), ...guard(active),
    });
    expect(failure.phase).toBe(phase);
    expect("accepted" in failure).toBe(false);
  });

  it("never translates a technical failure into DataUnavailable", () => {
    const active = evaluating();
    const failure = projectionReducer(active, {
      type: "operation-failed", error: technical("DecodeFailed"), ...guard(active),
    });
    expect(JSON.stringify(failure)).not.toContain('"resultState":"DataUnavailable"');
  });

  it("retries only the exact failed selection with a newer token", () => {
    const active = evaluating();
    const failed = projectionReducer(active, {
      type: "operation-failed", error: technical(), ...guard(active),
    });
    const mismatch = projectionReducer(failed, {
      type: "retry-started", operationToken: 2, dataReleaseId: RELEASE, selectionKey: "different",
    });
    expect(mismatch).toBe(failed);
    const retried = projectionReducer(failed, {
      type: "retry-started", operationToken: 2, dataReleaseId: RELEASE, selectionKey: guard(active).selectionKey,
    });
    expect(retried.phase).toBe("evaluating");
    expect(guard(retried).operationToken).toBe(2);
    expect(projectionReducer(retried, {
      type: "assessment-completed", ...guard(active), result: outcome("ProjectionAvailable"),
    })).toBe(retried);
  });

  it("handles matching bootstrap failures and retry without inventing a result", () => {
    const booting = createBootingProjectionState(RELEASE, 4);
    const failure = projectionReducer(booting, {
      type: "bootstrap-failed", operationToken: 4, expectedDataReleaseId: RELEASE,
      availability: "connection-required", error: technical("FetchFailed"),
    });
    expect(failure.phase).toBe("connection-required");
    const retry = projectionReducer(failure, {
      type: "retry-started", operationToken: 5, dataReleaseId: RELEASE, selectionKey: null,
    });
    expect(retry).toEqual(createBootingProjectionState(RELEASE, 5));
  });

  it("turns a matching but cross-release result into integrity error", () => {
    const active = evaluating();
    const wrong = { ...outcome("ProjectionAvailable"), dataReleaseId: OTHER_RELEASE };
    const result = projectionReducer(active, {
      type: "assessment-completed", ...guard(active), result: wrong,
    });
    expect(result.phase).toBe("integrity-error");
    expect(visibleAcceptedProjection(result)).toBeNull();
  });

  it("enforces monotonic operation tokens for arbitrary command sequences", () => {
    fc.assert(fc.property(
      fc.integer({ min: 1, max: 10_000 }),
      fc.integer({ min: 0, max: 10_000 }),
      (currentToken, candidateToken) => {
        const current = ready(currentToken);
        const next = projectionReducer(current, {
          type: "evaluation-started", operationToken: candidateToken, selection: selected(),
        });
        expect(next === current).toBe(candidateToken <= currentToken);
      },
    ));
  });

  it("snapshots accepted selections and results", () => {
    const input = selected();
    const inputResult = outcome("ProjectionAvailable", input);
    const active = evaluating(input);
    const result = projectionReducer(active, {
      type: "assessment-completed", ...guard(active), result: inputResult,
    });
    const accepted = visibleAcceptedProjection(result)!;
    expect(Object.isFrozen(accepted)).toBe(true);
    expect(Object.isFrozen(accepted.selection.location.coordinates)).toBe(true);
    expect(Object.isFrozen(accepted.result)).toBe(true);
  });
});
