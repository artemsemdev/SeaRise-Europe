import { useEffect, useMemo, useState } from "react";
import { runtimeConfig } from "./config";
import { ManifestRepository, technicalErrorFrom } from "./data/manifest-repository";
import type { ReleaseContext, TechnicalError } from "./domain/release";

const MAX_ATTEMPTS = 3;

export type ReleaseBootstrapState =
  | { readonly phase: "loading"; readonly attempt: number }
  | { readonly phase: "ready"; readonly context: ReleaseContext }
  | { readonly phase: "error"; readonly attempt: number; readonly error: TechnicalError };

export function useReleaseContext(): readonly [ReleaseBootstrapState, () => void] {
  const [attempt, setAttempt] = useState(1);
  const [state, setState] = useState<ReleaseBootstrapState>({ phase: "loading", attempt });
  const repository = useMemo(() => {
    const manifestUrl = new URL(runtimeConfig.manifestUrl, window.location.href);
    return new ManifestRepository({
      manifestUrl: manifestUrl.href,
      allowedOrigins: [manifestUrl.origin],
      expectedDisposition: runtimeConfig.releaseDisposition,
    });
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    repository.load(runtimeConfig.dataReleaseId, controller.signal).then(
      (context) => setState({ phase: "ready", context }),
      (error: unknown) => {
        if (controller.signal.aborted) return;
        setState({ phase: "error", attempt, error: technicalErrorFrom(error) });
      },
    );
    return () => controller.abort();
  }, [attempt, repository]);

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
