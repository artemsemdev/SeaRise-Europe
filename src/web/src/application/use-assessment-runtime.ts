/* eslint-disable react-hooks/set-state-in-effect -- external runtime scopes are created and published only after React commits them */
import {
  useCallback,
  useEffect,
  useState,
  useSyncExternalStore,
} from "react";
import { technicalErrorFrom } from "../data/manifest-repository";
import type { ReleaseMethodology } from "../data/methodology-repository";
import type { ProjectionState } from "../domain/projection-state";
import type { ReleaseContext, Selection, TechnicalError } from "../domain/release";
import {
  createBrowserRuntime,
  type BrowserRuntimeFactory,
  type BrowserRuntimeScope,
} from "./browser-runtime";

export type MethodologyState =
  | { readonly phase: "idle" }
  | { readonly phase: "loading"; readonly dataReleaseId: string }
  | {
      readonly phase: "ready";
      readonly dataReleaseId: string;
      readonly methodology: ReleaseMethodology;
    }
  | {
      readonly phase: "technical-error";
      readonly dataReleaseId: string;
      readonly error: TechnicalError;
    };

export interface AssessmentRuntimeView {
  readonly projection: ProjectionState | null;
  readonly methodology: MethodologyState;
  readonly select: (selection: Selection) => Promise<void>;
  readonly retry: () => Promise<boolean>;
  readonly reset: () => void;
}

interface MethodologyRecord {
  readonly context: ReleaseContext;
  readonly state: MethodologyState;
}

const EMPTY_SUBSCRIBE = (): (() => void) => () => undefined;
const NULL_SNAPSHOT = (): null => null;

function unavailable(): Error {
  return new Error("The immutable release browser runtime is not ready.");
}

function methodologyIdentityError(
  context: ReleaseContext,
  methodology: ReleaseMethodology,
): TechnicalError | null {
  return methodology.dataReleaseId === context.dataReleaseId &&
      methodology.methodologyVersion === context.methodologyVersion &&
      methodology.disposition === context.disposition
    ? null
    : Object.freeze({
        kind: "technical-error",
        code: "ReleaseIdentityMismatch",
        message: "Methodology and application release identities disagree.",
        recoverable: false,
      });
}

/**
 * Owns the controller and verified methodology for exactly one ReleaseContext.
 * Context replacement exposes no prior-release snapshot while React disposes
 * the old scope and installs the new one after commit.
 */
export function useAssessmentRuntime(
  context: ReleaseContext | null,
  factory: BrowserRuntimeFactory = createBrowserRuntime,
): AssessmentRuntimeView {
  const [runtime, setRuntime] = useState<BrowserRuntimeScope | null>(null);
  const [methodologyRecord, setMethodologyRecord] = useState<MethodologyRecord | null>(null);
  const active = runtime?.context === context ? runtime : null;

  useEffect(() => {
    if (!context) {
      setRuntime(null);
      setMethodologyRecord(null);
      return;
    }

    const next = factory(context);
    if (next.context !== context) {
      next.controller.dispose();
      throw new Error("The runtime factory returned a different ReleaseContext.");
    }
    const controller = new AbortController();
    let current = true;
    // Runtime construction and publication deliberately happen after commit.
    setRuntime(next);
    void next.methodology.load(context, controller.signal).then(
      (methodology) => {
        if (!current || controller.signal.aborted) return;
        const identityError = methodologyIdentityError(context, methodology);
        setMethodologyRecord({
          context,
          state: identityError
            ? {
                phase: "technical-error",
                dataReleaseId: context.dataReleaseId,
                error: identityError,
              }
            : {
                phase: "ready",
                dataReleaseId: context.dataReleaseId,
                methodology,
              },
        });
      },
      (error: unknown) => {
        if (!current || controller.signal.aborted) return;
        setMethodologyRecord({
          context,
          state: {
            phase: "technical-error",
            dataReleaseId: context.dataReleaseId,
            error: technicalErrorFrom(error),
          },
        });
      },
    );

    return () => {
      current = false;
      controller.abort("release context replaced or component unmounted");
      next.controller.dispose();
    };
  }, [context, factory]);

  const projection = useSyncExternalStore(
    active?.controller.subscribe ?? EMPTY_SUBSCRIBE,
    active?.controller.getSnapshot ?? NULL_SNAPSHOT,
    active?.controller.getSnapshot ?? NULL_SNAPSHOT,
  );

  const methodology = context === null
    ? ({ phase: "idle" } as const)
    : active && methodologyRecord?.context === context
      ? methodologyRecord.state
      : ({ phase: "loading", dataReleaseId: context.dataReleaseId } as const);

  const select = useCallback((selection: Selection): Promise<void> => {
    if (!active) return Promise.reject(unavailable());
    return active.controller.select(selection);
  }, [active]);
  const retry = useCallback((): Promise<boolean> => {
    if (!active) return Promise.reject(unavailable());
    return active.controller.retry();
  }, [active]);
  const reset = useCallback((): void => {
    if (!active) throw unavailable();
    active.controller.reset();
  }, [active]);

  return { projection, methodology, select, retry, reset };
}
