import {
  selectionKey,
  type AcceptedProjection,
} from "../domain/projection-state";
import {
  TechnicalFailure,
  type ReleaseContext,
  type TechnicalError,
} from "../domain/release";
import { parseUrlSelection, writeUrlSelection } from "../domain/url-state";

export const PROJECTION_URL_PARAMETERS = Object.freeze([
  "release",
  "scenario",
  "horizon",
  "lat",
  "lon",
  "place",
] as const);

export type ProjectionUrlReadSource = "initial" | "popstate";

export type ProjectionUrlEvent =
  | {
      readonly type: "selection";
      readonly source: ProjectionUrlReadSource;
      readonly selection: AcceptedProjection["selection"];
    }
  | { readonly type: "clear"; readonly source: ProjectionUrlReadSource | "reset" }
  | {
      readonly type: "technical-error";
      readonly source: ProjectionUrlReadSource | "share";
      readonly error: TechnicalError;
    };

export interface ProjectionUrlEnvironment {
  readonly currentUrl: () => URL;
  readonly replaceUrl: (url: URL) => void;
  readonly subscribePopState: (listener: () => void) => () => void;
}

export interface ProjectionUrlCommands {
  /** Publish only the immutable selection from one accepted projection. */
  readonly share: (accepted: AcceptedProjection) => boolean;
  /** Remove only SeaRise projection parameters and preserve the surrounding URL. */
  readonly reset: () => void;
}

export type ProjectionUrlObserver = (event: ProjectionUrlEvent) => void;

function genericTechnicalError(): TechnicalError {
  return Object.freeze({
    kind: "technical-error",
    code: "SchemaInvalid",
    message: "The projection URL could not be validated.",
    recoverable: false,
  });
}

function technicalError(error: unknown): TechnicalError {
  return error instanceof TechnicalFailure ? error.detail : genericTechnicalError();
}

function identityMismatch(message: string): TechnicalFailure {
  return new TechnicalFailure({
    kind: "technical-error",
    code: "ReleaseIdentityMismatch",
    message,
    recoverable: false,
  });
}

/**
 * One release-scoped URL session. It never owns scientific state: it only
 * validates navigation input and publishes an already accepted selection.
 */
export class ProjectionUrlController implements ProjectionUrlCommands {
  readonly #context: ReleaseContext;
  readonly #environment: ProjectionUrlEnvironment;
  #observer: ProjectionUrlObserver;
  #active = false;
  #unsubscribe: (() => void) | null = null;

  constructor(
    context: ReleaseContext,
    environment: ProjectionUrlEnvironment,
    observer: ProjectionUrlObserver,
  ) {
    this.#context = context;
    this.#environment = environment;
    this.#observer = observer;
  }

  replaceObserver(observer: ProjectionUrlObserver): void {
    this.#observer = observer;
  }

  start(): void {
    if (this.#active) return;
    this.#active = true;
    this.#unsubscribe = this.#environment.subscribePopState(() => {
      if (this.#active) this.#read("popstate");
    });
    this.#read("initial");
  }

  readonly share = (accepted: AcceptedProjection): boolean => {
    if (!this.#active) return false;
    try {
      this.#validateAccepted(accepted);
      const next = writeUrlSelection(this.#environment.currentUrl(), accepted.selection);
      const verified = parseUrlSelection(
        next,
        this.#context.dataReleaseId,
        this.#context.defaults,
      );
      if (!verified || selectionKey(verified) !== accepted.selectionKey) {
        throw identityMismatch("The shared URL did not preserve the accepted selection identity.");
      }
      if (!this.#active) return false;
      this.#environment.replaceUrl(next);
      return true;
    } catch (error: unknown) {
      this.#emit({ type: "technical-error", source: "share", error: technicalError(error) });
      return false;
    }
  };

  readonly reset = (): void => {
    if (!this.#active) return;
    const next = new URL(this.#environment.currentUrl());
    for (const parameter of PROJECTION_URL_PARAMETERS) next.searchParams.delete(parameter);
    if (!this.#active) return;
    this.#environment.replaceUrl(next);
    this.#emit({ type: "clear", source: "reset" });
  };

  dispose(): void {
    if (!this.#active) return;
    this.#active = false;
    const unsubscribe = this.#unsubscribe;
    this.#unsubscribe = null;
    unsubscribe?.();
  }

  #read(source: ProjectionUrlReadSource): void {
    try {
      const selection = parseUrlSelection(
        this.#environment.currentUrl(),
        this.#context.dataReleaseId,
        this.#context.defaults,
      );
      if (!this.#active) return;
      if (!selection) {
        this.#emit({ type: "clear", source });
        return;
      }
      this.#context.dataset(selection.scenario, selection.horizon);
      this.#emit({ type: "selection", source, selection });
    } catch (error: unknown) {
      this.#emit({ type: "technical-error", source, error: technicalError(error) });
    }
  }

  #validateAccepted(accepted: AcceptedProjection): void {
    if (
      accepted.release.dataReleaseId !== this.#context.dataReleaseId ||
      accepted.release.methodologyVersion !== this.#context.methodologyVersion ||
      accepted.selection.dataReleaseId !== this.#context.dataReleaseId ||
      accepted.result.dataReleaseId !== this.#context.dataReleaseId ||
      accepted.result.methodologyVersion !== this.#context.methodologyVersion ||
      accepted.result.scenario !== accepted.selection.scenario ||
      accepted.result.horizon !== accepted.selection.horizon
    ) {
      throw identityMismatch("The accepted projection tuple does not match the immutable release selection.");
    }
    if (
      !Object.isFrozen(accepted) ||
      !Object.isFrozen(accepted.selection) ||
      !Object.isFrozen(accepted.selection.location) ||
      !Object.isFrozen(accepted.selection.location.coordinates)
    ) {
      throw new TechnicalFailure({
        kind: "technical-error",
        code: "SchemaInvalid",
        message: "Share requires an immutable accepted projection selection.",
        recoverable: false,
      });
    }
    this.#context.dataset(accepted.selection.scenario, accepted.selection.horizon);
    if (selectionKey(accepted.selection) !== accepted.selectionKey) {
      throw identityMismatch("The accepted projection selection identity is inconsistent.");
    }
  }

  #emit(event: ProjectionUrlEvent): void {
    if (this.#active) this.#observer(event);
  }
}

export function createWindowProjectionUrlEnvironment(
  target: Window = window,
): ProjectionUrlEnvironment {
  return Object.freeze({
    currentUrl: () => new URL(target.location.href),
    replaceUrl: (url: URL) => {
      target.history.replaceState(
        target.history.state,
        "",
        `${url.pathname}${url.search}${url.hash}`,
      );
    },
    subscribePopState: (listener: () => void) => {
      target.addEventListener("popstate", listener);
      return () => target.removeEventListener("popstate", listener);
    },
  });
}
