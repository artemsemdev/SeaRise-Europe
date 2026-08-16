import { technicalErrorFrom } from "../data/manifest-repository";
import {
  createBootingProjectionState,
  projectionReducer,
  projectionReleaseIdentity,
  selectionKey,
  visibleAcceptedProjection,
  type OperationGuard,
  type ProjectionEvent,
  type ProjectionOperation,
  type ProjectionState,
} from "../domain/projection-state";
import type { AssessmentEvaluation } from "../domain/scientific-lookup";
import {
  TechnicalFailure,
  type ReleaseContext,
  type Selection,
  type TechnicalError,
} from "../domain/release";

export type DeliveryAvailability = "offline" | "connection-required";

export interface AssessmentService {
  evaluate(
    context: ReleaseContext,
    selection: Selection,
    signal: AbortSignal,
  ): Promise<AssessmentEvaluation>;
  cancel(): void;
}

export interface AssessmentControllerOptions {
  readonly context: ReleaseContext;
  readonly assessment: AssessmentService;
  /** Classifies a delivery failure without turning it into a scientific outcome. */
  readonly classifyAvailability?: (
    error: TechnicalError,
  ) => DeliveryAvailability | null;
}

type Listener = () => void;
type ActiveEvaluation = Readonly<{
  controller: AbortController;
  guard: OperationGuard;
}>;

function activeOperation(state: ProjectionState): ProjectionOperation | null {
  return state.phase === "evaluating" || state.phase === "updating"
    ? state.operation
    : null;
}

/**
 * Framework-neutral, release-scoped orchestration for the browser application.
 * Its stable getSnapshot/subscribe methods can be passed directly to
 * useSyncExternalStore without a global state dependency.
 */
export class AssessmentController {
  readonly #assessment: AssessmentService;
  readonly #classifyAvailability: (
    error: TechnicalError,
  ) => DeliveryAvailability | null;
  readonly #listeners = new Set<Listener>();
  #context: ReleaseContext;
  #state: ProjectionState;
  #nextOperationToken = 0;
  #active: ActiveEvaluation | null = null;
  #disposed = false;

  constructor(options: AssessmentControllerOptions) {
    this.#assessment = options.assessment;
    this.#context = options.context;
    this.#classifyAvailability = options.classifyAvailability ?? (() => null);
    this.#state = createBootingProjectionState(options.context.dataReleaseId);
    this.#state = projectionReducer(this.#state, {
      type: "release-ready",
      operationToken: 0,
      release: projectionReleaseIdentity(options.context),
    });
  }

  readonly getSnapshot = (): ProjectionState => this.#state;

  readonly subscribe = (listener: Listener): (() => void) => {
    if (this.#disposed) return () => undefined;
    this.#listeners.add(listener);
    return () => this.#listeners.delete(listener);
  };

  /** The single atomic selection command for search, map, and controls. */
  readonly select = async (selection: Selection): Promise<void> => {
    this.#assertUsable();
    if (selection.dataReleaseId !== this.#context.dataReleaseId) {
      throw new TechnicalFailure({
        kind: "technical-error",
        code: "ReleaseIdentityMismatch",
        message: "The selection belongs to a different immutable release.",
        recoverable: false,
      });
    }

    this.#cancelActive("superseded");
    const operationToken = this.#token();
    const type = visibleAcceptedProjection(this.#state)
      ? "update-started"
      : "evaluation-started";
    this.#dispatch({ type, operationToken, selection });
    await this.#runOperation(operationToken);
  };

  /** Replays only the selection retained by the current failure state. */
  readonly retry = async (): Promise<boolean> => {
    this.#assertUsable();
    const failure = this.#state;
    if (
      failure.phase !== "offline" &&
      failure.phase !== "connection-required" &&
      failure.phase !== "unsupported-browser" &&
      failure.phase !== "integrity-error" &&
      failure.phase !== "technical-error"
    ) {
      return false;
    }
    if (!failure.operation) return false;

    this.#cancelActive("retry");
    const operationToken = this.#token();
    this.#dispatch({
      type: "retry-started",
      operationToken,
      dataReleaseId: failure.expectedDataReleaseId,
      selectionKey: failure.operation.selectionKey,
    });
    await this.#runOperation(operationToken);
    return true;
  };

  readonly reset = (): void => {
    this.#assertUsable();
    this.#cancelActive("reset");
    this.#dispatch({
      type: "reset",
      operationToken: this.#token(),
      dataReleaseId: this.#context.dataReleaseId,
    });
  };

  /** Atomically invalidates work from the prior immutable release. */
  readonly replaceRelease = (context: ReleaseContext): void => {
    this.#assertUsable();
    this.#cancelActive("release-update");
    const operationToken = this.#token();
    this.#dispatch({
      type: "release-update-started",
      operationToken,
      expectedDataReleaseId: context.dataReleaseId,
    });
    this.#context = context;
    this.#dispatch({
      type: "release-ready",
      operationToken,
      release: projectionReleaseIdentity(context),
    });
  };

  readonly dispose = (): void => {
    if (this.#disposed) return;
    this.#disposed = true;
    this.#cancelActive("disposed");
    this.#listeners.clear();
  };

  #token(): number {
    this.#nextOperationToken += 1;
    return this.#nextOperationToken;
  }

  #dispatch(event: ProjectionEvent): void {
    const next = projectionReducer(this.#state, event);
    if (next === this.#state) return;
    this.#state = next;
    for (const listener of [...this.#listeners]) listener();
  }

  #cancelActive(reason: string): void {
    const active = this.#active;
    if (!active) return;
    this.#active = null;
    active.controller.abort(reason);
    this.#assessment.cancel();
  }

  async #runOperation(expectedToken: number): Promise<void> {
    const operation = activeOperation(this.#state);
    if (!operation || operation.operationToken !== expectedToken) return;
    const controller = new AbortController();
    const active = Object.freeze({
      controller,
      guard: Object.freeze({
        operationToken: operation.operationToken,
        selectionKey: operation.selectionKey,
        dataReleaseId: operation.dataReleaseId,
      }),
    });
    this.#active = active;

    try {
      const evaluation = await this.#assessment.evaluate(
        this.#context,
        operation.selection,
        controller.signal,
      );
      if (!this.#isActive(active)) return;
      this.#dispatch({
        type: "assessment-completed",
        ...active.guard,
        result: evaluation.result,
      });
    } catch (error: unknown) {
      if (!this.#isActive(active)) return;
      const technical = technicalErrorFrom(error);
      const availability = technical.code === "FetchFailed"
        ? this.#classifyAvailability(technical)
        : null;
      this.#dispatch(availability
        ? { type: "operation-unavailable", ...active.guard, availability, error: technical }
        : { type: "operation-failed", ...active.guard, error: technical });
    } finally {
      if (this.#active === active) this.#active = null;
    }
  }

  #isActive(active: ActiveEvaluation): boolean {
    if (this.#disposed || active.controller.signal.aborted || this.#active !== active) {
      return false;
    }
    const operation = activeOperation(this.#state);
    return operation !== null
      && operation.operationToken === active.guard.operationToken
      && operation.selectionKey === active.guard.selectionKey
      && operation.dataReleaseId === active.guard.dataReleaseId
      && selectionKey(operation.selection) === active.guard.selectionKey;
  }

  #assertUsable(): void {
    if (this.#disposed) throw new Error("AssessmentController has been disposed.");
  }
}
