/// <reference types="vite/client" />

declare const __SEARISE_BUILD_IDENTITY_JSON__: string;
declare const __SEARISE_PRECACHE_JSON__: string;

interface Window {
  readonly __SEARISE_PRIVATE_CANDIDATE_VALIDATION__?: Readonly<{
    run(): Promise<Readonly<{
      lookups: readonly import("./domain/scientific-lookup").AssessmentResult[];
      outcomes: readonly import("./domain/scientific-lookup").AssessmentResult["resultState"][];
      technicalFailure: Readonly<{ kind: "technical-error"; code: string }>;
    }>>;
  }>;
}
