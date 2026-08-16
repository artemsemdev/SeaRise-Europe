import type { DataReleaseId } from "../contracts/generated/release-contract";
import type { AssessmentResult } from "./scientific-lookup";
import {
  searchQueryKey,
  type SearchLifecycleEvent,
  type SearchOperationGuard,
  type SearchQueryOperation,
} from "./projection-search";
import {
  TechnicalFailure,
  validateCoordinates,
  type ReleaseContext,
  type Selection,
  type TechnicalError,
} from "./release";

export const PROJECTION_STATE_PHASES = [
  "booting", "ready", "searching", "evaluating", "updating", "result",
  "offline", "connection-required", "unsupported-browser", "integrity-error", "technical-error",
] as const;

export const PROJECTION_EVENT_TYPES = [
  "release-ready", "bootstrap-failed", "search-started", "search-completed",
  "search-failed", "search-cancelled",
  "evaluation-started", "update-started", "assessment-completed",
  "operation-unavailable", "operation-failed", "retry-started", "reset",
  "release-update-started",
] as const;

export interface ProjectionReleaseIdentity {
  readonly dataReleaseId: DataReleaseId;
  readonly methodologyVersion: "ar6-regional-projection-v1";
}

export interface OperationGuard {
  readonly operationToken: number;
  readonly selectionKey: string;
  readonly dataReleaseId: DataReleaseId;
}

export interface ProjectionOperation extends OperationGuard {
  readonly kind: "evaluation" | "update";
  readonly selection: Selection;
}

export type ActiveProjectionOperation = ProjectionOperation | (SearchQueryOperation & {
  readonly kind: "search";
});

/** The sole authority for a completed result, marker, layer, legend, and URL. */
export interface AcceptedProjection {
  readonly release: ProjectionReleaseIdentity;
  readonly selection: Selection;
  readonly selectionKey: string;
  readonly result: AssessmentResult;
}

type Loaded = {
  readonly release: ProjectionReleaseIdentity;
  readonly operationToken: number;
  readonly searchToken: number;
};
type FailurePhase =
  | "offline" | "connection-required" | "unsupported-browser" | "integrity-error" | "technical-error";
type FailureBase = {
  readonly release: ProjectionReleaseIdentity | null;
  readonly expectedDataReleaseId: DataReleaseId;
  readonly operationToken: number;
  readonly searchToken: number;
  readonly operation: ActiveProjectionOperation | null;
  readonly previous: AcceptedProjection | null;
};
type ErrorWithCode<C extends TechnicalError["code"]> = TechnicalError & { readonly code: C };
type IntegrityCode = "IntegrityFailed" | "ReleaseIdentityMismatch" | "SchemaInvalid";
type GeneralTechnicalCode = Exclude<TechnicalError["code"], "UnsupportedBrowser" | IntegrityCode>;
type FailureState = FailureBase & (
  | { readonly phase: "offline" | "connection-required"; readonly error: TechnicalError }
  | { readonly phase: "unsupported-browser"; readonly error: ErrorWithCode<"UnsupportedBrowser"> }
  | { readonly phase: "integrity-error"; readonly error: ErrorWithCode<IntegrityCode> }
  | { readonly phase: "technical-error"; readonly error: ErrorWithCode<GeneralTechnicalCode> }
);

export type ProjectionState =
  | { readonly phase: "booting"; readonly expectedDataReleaseId: DataReleaseId; readonly operationToken: number; readonly searchToken: number }
  | (Loaded & { readonly phase: "ready" })
  | (Loaded & { readonly phase: "searching"; readonly operation: SearchQueryOperation & { readonly kind: "search" }; readonly previous: AcceptedProjection | null })
  | (Loaded & { readonly phase: "evaluating"; readonly operation: ProjectionOperation & { readonly kind: "evaluation" } })
  | (Loaded & { readonly phase: "updating"; readonly operation: ProjectionOperation & { readonly kind: "update" }; readonly previous: AcceptedProjection })
  | (Loaded & { readonly phase: "result"; readonly accepted: AcceptedProjection })
  | FailureState;

type Completion = OperationGuard;
export type ProjectionEvent =
  | { readonly type: "release-ready"; readonly operationToken: number; readonly release: ProjectionReleaseIdentity }
  | { readonly type: "bootstrap-failed"; readonly operationToken: number; readonly expectedDataReleaseId: DataReleaseId; readonly error: TechnicalError; readonly availability?: "offline" | "connection-required" }
  | SearchLifecycleEvent
  | { readonly type: "evaluation-started"; readonly operationToken: number; readonly selection: Selection }
  | { readonly type: "update-started"; readonly operationToken: number; readonly selection: Selection }
  | ({ readonly type: "assessment-completed"; readonly result: AssessmentResult } & Completion)
  | ({ readonly type: "operation-unavailable"; readonly availability: "offline" | "connection-required"; readonly error: TechnicalError } & Completion)
  | ({ readonly type: "operation-failed"; readonly error: TechnicalError } & Completion)
  | { readonly type: "retry-started"; readonly operationToken: number; readonly dataReleaseId: DataReleaseId; readonly selectionKey: string | null }
  | { readonly type: "reset"; readonly operationToken: number; readonly dataReleaseId: DataReleaseId }
  | { readonly type: "release-update-started"; readonly operationToken: number; readonly expectedDataReleaseId: DataReleaseId };

export function projectionReleaseIdentity(context: ReleaseContext): ProjectionReleaseIdentity {
  return Object.freeze({ dataReleaseId: context.dataReleaseId, methodologyVersion: context.methodologyVersion });
}

export function selectionKey(selection: Selection): string {
  const point = validateCoordinates(selection.location.coordinates);
  return `selection-v1:${JSON.stringify([
    selection.dataReleaseId, selection.scenario, selection.horizon, selection.location.kind,
    selection.location.kind === "settlement" ? selection.location.placeId : null,
    point.latitude, point.longitude,
  ])}`;
}

export function createBootingProjectionState(
  expectedDataReleaseId: DataReleaseId,
  operationToken = 0,
  searchToken = 0,
): ProjectionState {
  return Object.freeze({ phase: "booting", expectedDataReleaseId, operationToken, searchToken });
}

function freezeSelection(selection: Selection): Selection {
  const coordinates = validateCoordinates(selection.location.coordinates);
  const location = selection.location.kind === "settlement"
    ? Object.freeze({ kind: "settlement" as const, placeId: selection.location.placeId, coordinates })
    : Object.freeze({ kind: "coordinate" as const, coordinates });
  return Object.freeze({ ...selection, location });
}

function freezeResult(result: AssessmentResult): AssessmentResult {
  return result.resultState === "ProjectionAvailable" || result.resultState === "DataUnavailable"
    ? Object.freeze({ ...result, source: Object.freeze({ ...result.source }) })
    : Object.freeze({ ...result });
}

function makeOperation(
  kind: ProjectionOperation["kind"],
  operationToken: number,
  selection: Selection,
): ProjectionOperation {
  const stable = freezeSelection(selection);
  return Object.freeze({
    kind, operationToken, selection: stable, selectionKey: selectionKey(stable),
    dataReleaseId: stable.dataReleaseId,
  });
}

function releaseOf(state: ProjectionState): ProjectionReleaseIdentity | null {
  return state.phase === "booting" ? null : state.release;
}

export function visibleAcceptedProjection(state: ProjectionState): AcceptedProjection | null {
  switch (state.phase) {
    case "result":
      return state.accepted;
    case "searching":
    case "updating":
    case "offline":
    case "connection-required":
    case "unsupported-browser":
    case "integrity-error":
    case "technical-error":
      return state.previous;
    case "booting":
    case "ready":
    case "evaluating":
      return null;
    default:
      return assertNever(state);
  }
}

function operationOf(state: ProjectionState): ActiveProjectionOperation | null {
  switch (state.phase) {
    case "searching":
    case "evaluating":
    case "updating":
      return state.operation;
    case "booting":
    case "ready":
    case "result":
    case "offline":
    case "connection-required":
    case "unsupported-browser":
    case "integrity-error":
    case "technical-error":
      return null;
    default:
      return assertNever(state);
  }
}

function newer(state: ProjectionState, token: number): boolean {
  return Number.isSafeInteger(token) && token > state.operationToken;
}

function matches(state: ProjectionState, completion: Completion): boolean {
  const active = operationOf(state);
  return active !== null && active.kind !== "search"
    && active.operationToken === completion.operationToken
    && active.selectionKey === completion.selectionKey
    && active.dataReleaseId === completion.dataReleaseId;
}

function matchesSearch(state: ProjectionState, completion: SearchOperationGuard): boolean {
  return state.phase === "searching"
    && state.operation.searchToken === completion.searchToken
    && state.operation.searchGeneration === completion.searchGeneration
    && state.operation.queryKey === completion.queryKey
    && state.operation.dataReleaseId === completion.dataReleaseId;
}

function accept(
  release: ProjectionReleaseIdentity,
  selection: Selection,
  result: AssessmentResult,
): AcceptedProjection {
  if (selection.dataReleaseId !== release.dataReleaseId
      || result.dataReleaseId !== release.dataReleaseId
      || result.methodologyVersion !== release.methodologyVersion
      || result.scenario !== selection.scenario
      || result.horizon !== selection.horizon) {
    throw new TechnicalFailure({
      kind: "technical-error", code: "ReleaseIdentityMismatch",
      message: "The completed projection does not match its immutable release selection.", recoverable: false,
    });
  }
  const stable = freezeSelection(selection);
  return Object.freeze({ release, selection: stable, selectionKey: selectionKey(stable), result: freezeResult(result) });
}

function failed(
  phase: FailurePhase,
  state: ProjectionState,
  error: TechnicalError,
): FailureState {
  const release = releaseOf(state);
  return Object.freeze({
    phase, release,
    expectedDataReleaseId: release?.dataReleaseId
      ?? (state as Extract<ProjectionState, { expectedDataReleaseId: DataReleaseId }>).expectedDataReleaseId,
    operationToken: state.operationToken,
    searchToken: state.searchToken,
    operation: operationOf(state),
    previous: visibleAcceptedProjection(state),
    error: Object.freeze({ ...error }),
  }) as FailureState;
}

function technicalFailure(state: ProjectionState, error: TechnicalError): FailureState {
  if (error.code === "UnsupportedBrowser") return failed("unsupported-browser", state, error);
  if (error.code === "IntegrityFailed" || error.code === "ReleaseIdentityMismatch" || error.code === "SchemaInvalid") {
    return failed("integrity-error", state, error);
  }
  return failed("technical-error", state, error);
}

function begin(
  phase: "evaluating" | "updating",
  state: ProjectionState,
  token: number,
  selection: Selection,
): ProjectionState {
  const release = releaseOf(state);
  const previous = visibleAcceptedProjection(state);
  if (!release || !newer(state, token) || selection.dataReleaseId !== release.dataReleaseId
      || (phase === "updating") !== (previous !== null)) return state;
  const operation = makeOperation(phase === "updating" ? "update" : "evaluation", token, selection);
  if (phase === "updating") return Object.freeze({ phase, release, operationToken: token, searchToken: state.searchToken, operation: operation as ProjectionOperation & { kind: "update" }, previous: previous! });
  return Object.freeze({ phase, release, operationToken: token, searchToken: state.searchToken, operation: operation as ProjectionOperation & { kind: "evaluation" } });
}

function beginSearch(state: ProjectionState, input: SearchQueryOperation): ProjectionState {
  const release = releaseOf(state);
  const previous = visibleAcceptedProjection(state);
  if (!release || !Number.isSafeInteger(input.searchToken) || input.searchToken <= state.searchToken
      || !Number.isSafeInteger(input.searchGeneration) || input.searchGeneration < 1
      || input.dataReleaseId !== release.dataReleaseId || !input.normalizedQuery
      || input.queryKey !== searchQueryKey(input.dataReleaseId, input.normalizedQuery)) return state;
  const operation = Object.freeze({ ...input, kind: "search" as const });
  return Object.freeze({
    phase: "searching", release, operationToken: state.operationToken,
    searchToken: input.searchToken, operation, previous,
  });
}

function settleSearch(state: Extract<ProjectionState, { phase: "searching" }>): ProjectionState {
  return state.previous
    ? Object.freeze({
      phase: "result", release: state.release, operationToken: state.operationToken,
      searchToken: state.searchToken, accepted: state.previous,
    })
    : Object.freeze({
      phase: "ready", release: state.release, operationToken: state.operationToken,
      searchToken: state.searchToken,
    });
}

function assertNever(value: never): never {
  throw new Error(`Unhandled projection event: ${JSON.stringify(value)}`);
}

export function projectionReducer(state: ProjectionState, event: ProjectionEvent): ProjectionState {
  switch (event.type) {
    case "release-ready":
      if (state.phase !== "booting" || event.operationToken !== state.operationToken
          || event.release.dataReleaseId !== state.expectedDataReleaseId) return state;
      return Object.freeze({ phase: "ready", release: Object.freeze({ ...event.release }), operationToken: state.operationToken, searchToken: state.searchToken });
    case "bootstrap-failed":
      if (state.phase !== "booting" || event.operationToken !== state.operationToken
          || event.expectedDataReleaseId !== state.expectedDataReleaseId) return state;
      return event.availability ? failed(event.availability, state, event.error) : technicalFailure(state, event.error);
    case "search-started":
      return beginSearch(state, event.operation);
    case "search-completed":
    case "search-cancelled":
      return state.phase === "searching" && matchesSearch(state, event)
        ? settleSearch(state)
        : state;
    case "search-failed":
      return matchesSearch(state, event) ? technicalFailure(state, event.error) : state;
    case "evaluation-started":
      return begin("evaluating", state, event.operationToken, event.selection);
    case "update-started":
      return begin("updating", state, event.operationToken, event.selection);
    case "assessment-completed":
      if ((state.phase !== "evaluating" && state.phase !== "updating") || !matches(state, event)) return state;
      try {
        return Object.freeze({ phase: "result", release: state.release, operationToken: state.operationToken, searchToken: state.searchToken, accepted: accept(state.release, state.operation.selection, event.result) });
      } catch (error) {
        if (error instanceof TechnicalFailure) return technicalFailure(state, error.detail);
        throw error;
      }
    case "operation-unavailable":
      return matches(state, event) ? failed(event.availability, state, event.error) : state;
    case "operation-failed":
      return matches(state, event) ? technicalFailure(state, event.error) : state;
    case "retry-started": {
      if (!["offline", "connection-required", "unsupported-browser", "integrity-error", "technical-error"].includes(state.phase)) return state;
      const failure = state as FailureState;
      const failedSelectionKey = failure.operation?.kind === "search"
        ? null
        : failure.operation?.selectionKey ?? null;
      if (!newer(state, event.operationToken) || event.dataReleaseId !== failure.expectedDataReleaseId
          || event.selectionKey !== failedSelectionKey) return state;
      if (!failure.operation) return createBootingProjectionState(failure.expectedDataReleaseId, event.operationToken);
      if (failure.operation.kind === "search") return state;
      return begin(failure.previous ? "updating" : "evaluating", state, event.operationToken, failure.operation.selection);
    }
    case "reset": {
      const release = releaseOf(state);
      if (!release || !newer(state, event.operationToken) || event.dataReleaseId !== release.dataReleaseId) return state;
      return Object.freeze({ phase: "ready", release, operationToken: event.operationToken, searchToken: state.searchToken });
    }
    case "release-update-started":
      return newer(state, event.operationToken)
        ? createBootingProjectionState(event.expectedDataReleaseId, event.operationToken)
        : state;
    default:
      return assertNever(event);
  }
}
