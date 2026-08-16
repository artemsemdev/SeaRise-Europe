import { CogAnalysisArtifactReader } from "../data/cog-analysis-reader";
import type { ArtifactTransport } from "../data/artifact-integrity";
import { StaticGeographyClassifier } from "../data/geography-classifier";
import {
  MethodologyRepository,
  type ReleaseMethodology,
} from "../data/methodology-repository";
import { AssessmentEngine } from "../domain/scientific-lookup";
import type { ProjectionState } from "../domain/projection-state";
import type { ReleaseContext, Selection } from "../domain/release";
import { AssessmentController } from "./assessment-controller";

export interface AssessmentControllerPort {
  readonly getSnapshot: () => ProjectionState;
  readonly subscribe: (listener: () => void) => () => void;
  readonly select: (selection: Selection) => Promise<void>;
  readonly retry: () => Promise<boolean>;
  readonly reset: () => void;
  readonly dispose: () => void;
}

export interface MethodologyLoader {
  load(context: ReleaseContext, signal: AbortSignal): Promise<ReleaseMethodology>;
}

export interface BrowserRuntimeScope {
  readonly context: ReleaseContext;
  readonly controller: AssessmentControllerPort;
  readonly methodology: MethodologyLoader;
}

export interface ProductionBrowserRuntime extends BrowserRuntimeScope {
  readonly geography: StaticGeographyClassifier;
  readonly analysis: CogAnalysisArtifactReader;
  readonly assessment: AssessmentEngine;
  readonly controller: AssessmentController;
  readonly methodology: MethodologyRepository;
}

export type BrowserRuntimeFactory = (context: ReleaseContext) => BrowserRuntimeScope;

export interface BrowserRuntimeOptions {
  readonly fetch?: typeof fetch;
  readonly artifactTransport?: ArtifactTransport;
}

/**
 * Creates one immutable-release browser runtime from the real static adapters.
 * Delivery failures remain technical here; service-worker/cache availability
 * classification and policy belong to Phase 2 #60.
 */
export function createBrowserRuntime(
  context: ReleaseContext,
  options: BrowserRuntimeOptions = {},
): ProductionBrowserRuntime {
  const geography = new StaticGeographyClassifier({
    transport: options.artifactTransport,
  });
  const analysis = new CogAnalysisArtifactReader({
    fetch: options.fetch,
    artifactTransport: options.artifactTransport,
  });
  const assessment = new AssessmentEngine({ geography, analysis });
  const controller = new AssessmentController({
    context,
    assessment,
  });
  const methodology = new MethodologyRepository({
    transport: options.artifactTransport,
  });

  return Object.freeze({
    context,
    geography,
    analysis,
    assessment,
    controller,
    methodology,
  });
}
