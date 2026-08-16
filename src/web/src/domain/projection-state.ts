import type { DataReleaseId } from "../contracts/generated/release-contract";
import type { AssessmentResult } from "./scientific-lookup";
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
  readonly kind: "search" | "evaluation" | "update";
  readonly selection: Selection;
}

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
};
type FailurePhase =
  | "offline" | "connection-required" | "unsupported-browser" | "integrity-error" | "technical-error";
type FailureBase = {
  readonly release: ProjectionReleaseIdentity | null;
  readonly expectedDataReleaseId: DataReleaseId;
  readonly operationToken: number;
  readonly operation: ProjectionOperation | null;
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
  | { readonly phase: "booting"; readonly expectedDataReleaseId: DataReleaseId; readonly operationToken: number }
  | (Loaded & { readonly phase: "ready" })
  | (Loaded & { readonly phase: "searching"; readonly operation: ProjectionOperation & { readonly kind: "search" }; readonly previous: AcceptedProjection | null })
  | (Loaded & { readonly phase: "evaluating"; readonly operation: ProjectionOperation & { readonly kind: "evaluation" } })
  | (Loaded & { readonly phase: "updating"; readonly operation: ProjectionOperation & { readonly kind: "update" }; readonly previous: AcceptedProjection })
  | (Loaded & { readonly phase: "result"; readonly accepted: AcceptedProjection })
  | FailureState;

type Completion = OperationGuard;
export type ProjectionEvent =
  | { readonly type: "release-ready"; readonly operationToken: number; readonly release: ProjectionReleaseIdentity }
  | { readonly type: "bootstrap-failed"; readonly operationToken: number; readonly expectedDataReleaseId: DataReleaseId; readonly error: TechnicalError; readonly availability?: "offline" | "connection-required" }
  | { readonly type: "search-started"; readonly operationToken: number; readonly selection: Selection }
  | ({ readonly type: "search-completed" } & Completion)
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
): ProjectionState {
  return Object.freeze({ phase: "booting", expectedDataReleaseId, operationToken });
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

function operationOf(state: ProjectionState): ProjectionOperation | null {
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
  return active !== null
    && active.operationToken === completion.operationToken
    && active.selectionKey === completion.selectionKey
    && active.dataReleaseId === completion.dataReleaseId;
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
  phase: "searching" | "evaluating" | "updating",
  state: ProjectionState,
  token: number,
  selection: Selection,
): ProjectionState {
  const release = releaseOf(state);
  const previous = visibleAcceptedProjection(state);
  if (!release || !newer(state, token) || selection.dataReleaseId !== release.dataReleaseId
      || (phase === "updating") !== (previous !== null)) return state;
  const operation = makeOperation(phase === "searching" ? "search" : phase === "updating" ? "update" : "evaluation", token, selection);
  if (phase === "searching") return Object.freeze({ phase, release, operationToken: token, operation: operation as ProjectionOperation & { kind: "search" }, previous });
  if (phase === "updating") return Object.freeze({ phase, release, operationToken: token, operation: operation as ProjectionOperation & { kind: "update" }, previous: previous! });
  return Object.freeze({ phase, release, operationToken: token, operation: operation as ProjectionOperation & { kind: "evaluation" } });
}

function assertNever(value: never): never {
  throw new Error(`Unhandled projection event: ${JSON.stringify(value)}`);
}

export function projectionReducer(state: ProjectionState, event: ProjectionEvent): ProjectionState {
  switch (event.type) {
    case "release-ready":
      if (state.phase !== "booting" || event.operationToken !== state.operationToken
          || event.release.dataReleaseId !== state.expectedDataReleaseId) return state;
      return Object.freeze({ phase: "ready", release: Object.freeze({ ...event.release }), operationToken: state.operationToken });
    case "bootstrap-failed":
      if (state.phase !== "booting" || event.operationToken !== state.operationToken
          || event.expectedDataReleaseId !== state.expectedDataReleaseId) return state;
      return event.availability ? failed(event.availability, state, event.error) : technicalFailure(state, event.error);
    case "search-started":
      return begin("searching", state, event.operationToken, event.selection);
    case "search-completed": {
      if (state.phase !== "searching" || !matches(state, event)) return state;
      const kind = state.previous ? "update" : "evaluation";
      const operation = Object.freeze({ ...state.operation, kind });
      return state.previous
        ? Object.freeze({ phase: "updating", release: state.release, operationToken: state.operationToken, operation: operation as ProjectionOperation & { kind: "update" }, previous: state.previous })
        : Object.freeze({ phase: "evaluating", release: state.release, operationToken: state.operationToken, operation: operation as ProjectionOperation & { kind: "evaluation" } });
    }
    case "evaluation-started":
      return begin("evaluating", state, event.operationToken, event.selection);
    case "update-started":
      return begin("updating", state, event.operationToken, event.selection);
    case "assessment-completed":
      if ((state.phase !== "evaluating" && state.phase !== "updating") || !matches(state, event)) return state;
      try {
        return Object.freeze({ phase: "result", release: state.release, operationToken: state.operationToken, accepted: accept(state.release, state.operation.selection, event.result) });
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
      if (!newer(state, event.operationToken) || event.dataReleaseId !== failure.expectedDataReleaseId
          || event.selectionKey !== (failure.operation?.selectionKey ?? null)) return state;
      if (!failure.operation) return createBootingProjectionState(failure.expectedDataReleaseId, event.operationToken);
      if (failure.operation.kind === "search") return begin("searching", state, event.operationToken, failure.operation.selection);
      return begin(failure.previous ? "updating" : "evaluating", state, event.operationToken, failure.operation.selection);
    }
    case "reset": {
      const release = releaseOf(state);
      if (!release || !newer(state, event.operationToken) || event.dataReleaseId !== release.dataReleaseId) return state;
      return Object.freeze({ phase: "ready", release, operationToken: event.operationToken });
    }
    case "release-update-started":
      return newer(state, event.operationToken)
        ? createBootingProjectionState(event.expectedDataReleaseId, event.operationToken)
        : state;
    default:
      return assertNever(event);
  }
}
