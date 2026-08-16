/// <reference types="vite/client" />

declare const __APP_BUILD_ID__: string;
declare const __DATA_RELEASE_ID__: string;
declare const __RELEASE_DISPOSITION__: "synthetic-fixture" | "private-engineering" | "public-promoted";
declare const __MANIFEST_URL__: string;
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
