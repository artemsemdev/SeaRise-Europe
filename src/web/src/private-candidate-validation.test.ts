import { afterEach, describe, expect, it, vi } from "vitest";

const fixtureIdentity = Object.freeze({
  schemaVersion: "1.0.0",
  appBuildId: "local-fixture",
  dataReleaseId: "searise-europe-v1.0.0-20260810-c096aeab4e09",
  releaseDisposition: "synthetic-fixture",
  manifestPath: "/releases/searise-europe-v1.0.0-20260810-c096aeab4e09/manifest.json",
});

function installIdentity(identity: Readonly<{
  schemaVersion: string;
  appBuildId: string;
  dataReleaseId: string;
  releaseDisposition: string;
  manifestPath: string;
}>): void {
  Object.defineProperty(globalThis, "__SEARISE_RUNTIME_BUILD_IDENTITY__", {
    configurable: true,
    value: identity,
  });
}

afterEach(() => {
  vi.resetModules();
  vi.restoreAllMocks();
  installIdentity(fixtureIdentity);
});

describe("private Candidate production composition", () => {
  it("routes all explicit validation through one memory-only production router with no default-reader bypass", async () => {
    vi.resetModules();
    const candidateIdentity = Object.freeze({
      ...fixtureIdentity,
      appBuildId: "candidate-build",
      dataReleaseId: "candidate-release",
      releaseDisposition: "private-engineering" as const,
      manifestPath: "/releases/candidate-release/manifest.json",
    });
    installIdentity(candidateIdentity);

    const context = Object.freeze({ dataReleaseId: "candidate-release" });
    const artifactTransport = vi.fn();
    const baseCogRangeTransport = Object.freeze({
      validateDelivery: vi.fn(async () => undefined),
      readExpandedRange: vi.fn(async () => new ArrayBuffer(0)),
    });
    const close = vi.fn();
    const createResourceRouter = vi.fn(async () => Object.freeze({
      artifactTransport,
      cogRangeTransport: baseCogRangeTransport,
      close,
    }));
    const geographyOptions: unknown[] = [];
    class GeographyClassifier {
      constructor(options?: unknown) { geographyOptions.push(options); }
    }
    const readers: Array<{ readonly options: Record<string, unknown> }> = [];
    class AnalysisReader {
      readonly options: Record<string, unknown>;
      constructor(options: Record<string, unknown> = {}) {
        this.options = options;
        readers.push(this);
      }
    }
    class Engine {
      readonly dependencies: Record<string, unknown>;
      constructor(dependencies: Record<string, unknown>) { this.dependencies = dependencies; }
      async evaluate(_context: unknown, selection: Record<string, unknown>, signal: AbortSignal) {
        const analysis = this.dependencies.analysis;
        if (analysis instanceof AnalysisReader) {
          if (analysis === readers[0]) {
            return { result: {
              resultState: "ProjectionAvailable",
              scenario: selection.scenario,
              horizon: selection.horizon,
            } };
          }
          const transport = analysis.options.cogRangeTransport as {
            validateDelivery: (artifact: unknown, identity: unknown, signal: AbortSignal) => Promise<void>;
          };
          await transport.validateDelivery({}, {}, signal);
          throw new Error("The technical failure probe did not fail.");
        }
        const geography = this.dependencies.geography as {
          classify: () => Promise<string>;
        };
        const classification = await geography.classify();
        const resultState = classification === "InEuropeAndCoastalZone"
          ? "DataUnavailable"
          : classification === "InEuropeOutsideCoastalZone"
            ? "OutOfScope"
            : "UnsupportedGeography";
        return { result: { resultState } };
      }
    }

    vi.doMock("./config", () => ({ runtimeConfig: candidateIdentity }));
    vi.doMock("./data/manifest-repository", () => ({
      ManifestRepository: class {
        load = vi.fn(async () => context);
      },
    }));
    vi.doMock("./offline/create-production-resource-router", () => ({
      createProductionResourceRouter: createResourceRouter,
    }));
    vi.doMock("./data/geography-classifier", () => ({
      StaticGeographyClassifier: GeographyClassifier,
    }));
    vi.doMock("./data/cog-analysis-reader", () => ({
      CogAnalysisArtifactReader: AnalysisReader,
    }));
    vi.doMock("./domain/scientific-lookup", () => ({ AssessmentEngine: Engine }));

    const { runPrivateCandidateScientificValidation } =
      await import("./private-candidate-validation");
    const result = await runPrivateCandidateScientificValidation();

    expect(result.lookups).toHaveLength(9);
    expect(result.technicalFailure).toEqual({ kind: "technical-error", code: "FetchFailed" });
    expect(createResourceRouter).toHaveBeenCalledOnce();
    expect(createResourceRouter).toHaveBeenCalledWith(context, expect.any(AbortSignal));
    expect(geographyOptions).toEqual([{ transport: artifactTransport }]);
    expect(readers).toHaveLength(2);
    expect(readers[0].options).toEqual({
      artifactTransport,
      cogRangeTransport: baseCogRangeTransport,
    });
    expect(readers[1].options.artifactTransport).toBe(artifactTransport);
    expect(readers[1].options.cogRangeTransport).not.toBe(baseCogRangeTransport);
    expect(baseCogRangeTransport.validateDelivery).toHaveBeenCalledOnce();
    expect(baseCogRangeTransport.readExpandedRange).not.toHaveBeenCalled();
    expect(close).toHaveBeenCalledOnce();
  });
});
