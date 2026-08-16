import { runtimeConfig } from "./config";
import { CogAnalysisArtifactReader } from "./data/cog-analysis-reader";
import { StaticGeographyClassifier } from "./data/geography-classifier";
import { ManifestRepository } from "./data/manifest-repository";
import {
  TechnicalFailure,
  type GeographyClassification,
  type Selection,
} from "./domain/release";
import {
  AssessmentEngine,
  type AnalysisArtifactReader,
  type AssessmentResult,
  type GeographyClassifier,
} from "./domain/scientific-lookup";

const coordinates = Object.freeze({ latitude: 51.9244, longitude: 4.4777 });
const scenarios = ["ssp1-26", "ssp2-45", "ssp5-85"] as const;
const horizons = [2030, 2050, 2100] as const;

function fixedGeography(classification: GeographyClassification): GeographyClassifier {
  return { classify: async () => classification };
}

function unavailableAnalysis(): AnalysisArtifactReader {
  return {
    lookup: async () => ({
      kind: "unavailable",
      reason: "source-value-nodata",
      source: {
        locationId: 1_003_800_040,
        latitude: 52,
        longitude: 4,
        distanceKilometres: 33.792469,
      },
    }),
  };
}

function selection(dataReleaseId: string, scenario: (typeof scenarios)[number], horizon: (typeof horizons)[number]): Selection {
  return {
    dataReleaseId,
    scenario,
    horizon,
    location: { kind: "coordinate", coordinates },
  };
}

export async function runPrivateCandidateScientificValidation(): Promise<Readonly<{
  lookups: readonly AssessmentResult[];
  outcomes: readonly AssessmentResult["resultState"][];
  technicalFailure: Readonly<{ kind: "technical-error"; code: string }>;
}>> {
  if (runtimeConfig.releaseDisposition !== "private-engineering") {
    throw new Error("Private Candidate validation is unavailable outside private-engineering mode");
  }
  const origin = window.location.origin;
  const context = await new ManifestRepository({
    manifestUrl: runtimeConfig.manifestUrl,
    allowedOrigins: [origin],
    expectedDisposition: "private-engineering",
  }).load(runtimeConfig.dataReleaseId, new AbortController().signal);

  const engine = new AssessmentEngine({
    geography: new StaticGeographyClassifier(),
    analysis: new CogAnalysisArtifactReader(),
  });
  const lookups: AssessmentResult[] = [];
  for (const scenario of scenarios) {
    for (const horizon of horizons) {
      lookups.push(
        (
          await engine.evaluate(
            context,
            selection(context.dataReleaseId, scenario, horizon),
            new AbortController().signal,
          )
        ).result,
      );
    }
  }

  const outcomeResults = await Promise.all([
    new AssessmentEngine({
      geography: fixedGeography("InEuropeAndCoastalZone"),
      analysis: unavailableAnalysis(),
    }).evaluate(
      context,
      selection(context.dataReleaseId, "ssp2-45", 2050),
      new AbortController().signal,
    ),
    new AssessmentEngine({
      geography: fixedGeography("InEuropeOutsideCoastalZone"),
      analysis: unavailableAnalysis(),
    }).evaluate(
      context,
      selection(context.dataReleaseId, "ssp2-45", 2050),
      new AbortController().signal,
    ),
    new AssessmentEngine({
      geography: fixedGeography("OutsideEurope"),
      analysis: unavailableAnalysis(),
    }).evaluate(
      context,
      selection(context.dataReleaseId, "ssp2-45", 2050),
      new AbortController().signal,
    ),
  ]);

  const failingFetch: typeof fetch = async (input, init) => {
    const url = new URL(input instanceof Request ? input.url : input.toString());
    if (init?.method === "HEAD" && url.pathname.endsWith("/analysis/ssp2-45/2050.tif")) {
      return new Response(null, { status: 503 });
    }
    return fetch(input, init);
  };
  let technicalFailure: Readonly<{ kind: "technical-error"; code: string }> | undefined;
  try {
    await new AssessmentEngine({
      geography: fixedGeography("InEuropeAndCoastalZone"),
      analysis: new CogAnalysisArtifactReader({ fetch: failingFetch }),
    }).evaluate(
      context,
      selection(context.dataReleaseId, "ssp2-45", 2050),
      new AbortController().signal,
    );
  } catch (error) {
    if (!(error instanceof TechnicalFailure)) throw error;
    technicalFailure = Object.freeze({ kind: error.detail.kind, code: error.detail.code });
  }
  if (!technicalFailure) throw new Error("Technical delivery failure produced a scientific outcome");

  return Object.freeze({
    lookups: Object.freeze(lookups),
    outcomes: Object.freeze([
      lookups[4].resultState,
      ...outcomeResults.map((evaluation) => evaluation.result.resultState),
    ]),
    technicalFailure,
  });
}

export function installPrivateCandidateValidation(): void {
  Object.defineProperty(window, "__SEARISE_PRIVATE_CANDIDATE_VALIDATION__", {
    configurable: false,
    enumerable: false,
    writable: false,
    value: Object.freeze({ run: runPrivateCandidateScientificValidation }),
  });
}
