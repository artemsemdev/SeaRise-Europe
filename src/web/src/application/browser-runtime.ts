import { CogAnalysisArtifactReader } from "../data/cog-analysis-reader";
import type { ArtifactTransport } from "../data/artifact-integrity";
import { StaticGeographyClassifier } from "../data/geography-classifier";
import {
  MethodologyRepository,
  type ReleaseMethodology,
} from "../data/methodology-repository";
import { AssessmentEngine } from "../domain/scientific-lookup";
import type { SearchLifecycleEvent } from "../domain/projection-search";
import type { ProjectionState } from "../domain/projection-state";
import type { ReleaseContext, Selection } from "../domain/release";
import { AssessmentController } from "./assessment-controller";
import { createProductionResourceRouter } from "../offline/create-production-resource-router";
import type { CogRangeTransport } from "../data/cog-analysis-reader";
import type {
  InteractionSubjectV1,
  RuntimeCapabilityV2,
} from "../offline/contracts/policy";
import type { RuntimeCapabilityInspectionV1 } from "../offline/verified-resource-router";
import {
  RuntimeCapabilityController,
  type RuntimeCapabilityPort,
} from "./runtime-capability";

export interface AssessmentControllerPort {
  readonly getSnapshot: () => ProjectionState;
  readonly subscribe: (listener: () => void) => () => void;
  readonly select: (selection: Selection) => Promise<void>;
  readonly retry: () => Promise<boolean>;
  readonly reset: () => void;
  readonly handleSearchLifecycle: (event: SearchLifecycleEvent) => void;
  readonly cancelSearch: () => void;
  readonly dispose: () => void;
}

export interface MethodologyLoader {
  load(context: ReleaseContext, signal: AbortSignal): Promise<ReleaseMethodology>;
}

export interface BrowserRuntimeScope {
  readonly context: ReleaseContext;
  readonly controller: AssessmentControllerPort;
  readonly methodology: MethodologyLoader;
  readonly searchArtifactTransport?: ArtifactTransport;
  readonly capability?: RuntimeCapabilityPort;
  readonly dispose?: () => void;
}

export interface ProductionBrowserRuntime extends BrowserRuntimeScope {
  readonly geography: StaticGeographyClassifier;
  readonly analysis: CogAnalysisArtifactReader;
  readonly assessment: AssessmentEngine;
  readonly controller: AssessmentController;
  readonly methodology: MethodologyRepository;
  readonly resources: BrowserResourceRouter;
  readonly searchArtifactTransport: ArtifactTransport;
  readonly dispose: () => void;
}

export interface BrowserResourceRouter {
  readonly artifactTransport: ArtifactTransport;
  readonly cogRangeTransport: CogRangeTransport;
  readonly inspectCapability?: (
    subject: InteractionSubjectV1,
    options?: RuntimeCapabilityInspectionV1,
  ) => Promise<RuntimeCapabilityV2>;
  close(): void;
}

export type BrowserRuntimeFactory = (
  context: ReleaseContext,
  signal: AbortSignal,
) => BrowserRuntimeScope | Promise<BrowserRuntimeScope>;

export interface BrowserRuntimeOptions {
  readonly resourceRouter?: BrowserResourceRouter;
  readonly createResourceRouter?: (
    context: ReleaseContext,
    signal: AbortSignal,
  ) => Promise<BrowserResourceRouter>;
}

function requiresConnection(error: Readonly<{ message: string }>): boolean {
  return /^COG (?:delivery metadata|range|range body) for .+ is unavailable\.$/u.test(error.message);
}

/**
 * Creates one immutable-release browser runtime from the real static adapters.
 * Delivery failures remain technical here; service-worker/cache availability
 * classification and policy belong to Phase 2 #60.
 */
export async function createBrowserRuntime(
  context: ReleaseContext,
  signal: AbortSignal = new AbortController().signal,
  options: BrowserRuntimeOptions = {},
): Promise<ProductionBrowserRuntime> {
  const resources = options.resourceRouter ?? await (
    options.createResourceRouter ?? createProductionResourceRouter
  )(context, signal);
  const geography = new StaticGeographyClassifier({
    transport: resources.artifactTransport,
  });
  const analysis = new CogAnalysisArtifactReader({
    artifactTransport: resources.artifactTransport,
    cogRangeTransport: resources.cogRangeTransport,
  });
  const assessment = new AssessmentEngine({ geography, analysis });
  const controller = new AssessmentController({
    context,
    assessment,
    // The controller asks only for recoverable FetchFailed operations. A
    // failed request for absent COG bytes needs a connection; an HTTP failure
    // remains a distinct technical delivery error.
    classifyAvailability: (error) => requiresConnection(error) ? "connection-required" : null,
  });
  const methodology = new MethodologyRepository({
    transport: resources.artifactTransport,
  });
  const capability = resources.inspectCapability
    ? new RuntimeCapabilityController({
        inspect: (subject, inspection) => resources.inspectCapability!(subject, inspection),
      })
    : undefined;

  return Object.freeze({
    context,
    geography,
    analysis,
    assessment,
    controller,
    methodology,
    ...(capability ? { capability } : {}),
    resources,
    searchArtifactTransport: resources.artifactTransport,
    dispose: () => {
      controller.dispose();
      capability?.dispose();
      resources.close();
    },
  });
}
