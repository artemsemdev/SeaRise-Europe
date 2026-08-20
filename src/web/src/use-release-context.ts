import { useEffect, useMemo, useState } from "react";
import { runtimeConfig } from "./config";
import { technicalErrorFrom } from "./data/technical-error";
import type { ReleaseContext, TechnicalError } from "./domain/release";

const MAX_ATTEMPTS = 3;

export type ReleaseBootstrapState =
  | { readonly phase: "loading"; readonly attempt: number }
  | { readonly phase: "ready"; readonly context: ReleaseContext }
  | { readonly phase: "error"; readonly attempt: number; readonly error: TechnicalError };

export function useReleaseContext(): readonly [ReleaseBootstrapState, () => void] {
  const [attempt, setAttempt] = useState(1);
  const [state, setState] = useState<ReleaseBootstrapState>({ phase: "loading", attempt });
  const repositoryOptions = useMemo(() => {
    const manifestUrl = new URL(runtimeConfig.manifestPath, window.location.href);
    return {
      manifestUrl: manifestUrl.href,
      allowedOrigins: [manifestUrl.origin],
      expectedDisposition: runtimeConfig.releaseDisposition,
    } as const;
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    const load = () => {
      void import("./data/manifest-repository").then(
        ({ ManifestRepository }) => new ManifestRepository(repositoryOptions).load(
          runtimeConfig.dataReleaseId,
          controller.signal,
        ),
      ).then(
        (context) => setState({ phase: "ready", context }),
        (error: unknown) => {
          if (controller.signal.aborted) return;
          setState({ phase: "error", attempt, error: technicalErrorFrom(error) });
        },
      );
    };
    const idle = window.requestIdleCallback?.(load, { timeout: 1_000 });
    const timer = idle === undefined ? window.setTimeout(load, 0) : undefined;
    return () => {
      if (idle !== undefined) window.cancelIdleCallback(idle);
      if (timer !== undefined) window.clearTimeout(timer);
      controller.abort();
    };
  }, [attempt, repositoryOptions]);

  const retry = () => {
    if (attempt >= MAX_ATTEMPTS) return;
    const nextAttempt = attempt + 1;
    setState({ phase: "loading", attempt: nextAttempt });
    setAttempt(nextAttempt);
  };
  return [state, retry] as const;
}

export function canRetryRelease(state: ReleaseBootstrapState): boolean {
  return state.phase === "error" && state.error.recoverable && state.attempt < MAX_ATTEMPTS;
}
