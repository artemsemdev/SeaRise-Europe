import type { HorizonYear, ScenarioId } from "../contracts/generated/release-contract";
import {
  ReleaseContext,
  TechnicalFailure,
  validateCoordinates,
  type Coordinates,
  type GeographyClassification,
  type Selection,
} from "./release";

export const EARTH_MEAN_RADIUS_KILOMETRES = 6371.0088;
export const MAXIMUM_SOURCE_DISTANCE_KILOMETRES = 100;
export const REQUIRED_QUANTILES = [0.167, 0.5, 0.833] as const;

export interface SourceGridLocation {
  readonly locationId: number;
  readonly latitude: number;
  readonly longitude: number;
  readonly distanceKilometres: number;
}

export interface NativeGridCandidate {
  readonly locationId: number;
  readonly latitude: number;
  readonly longitude: number;
}

export interface NearestSourceSelection<T extends NativeGridCandidate> {
  readonly candidate: T;
  readonly source: SourceGridLocation;
  readonly unroundedDistanceKilometres: number;
}

export type AnalysisReadResult =
  | {
      readonly kind: "projection";
      readonly source: SourceGridLocation;
      readonly lowerMillimetres: number;
      readonly medianMillimetres: number;
      readonly upperMillimetres: number;
      readonly baseline: "1995-2014 mean";
      readonly sourceRelease: "20210809";
      readonly sourceMemberSha256: string;
      readonly nativeResolutionDegrees: 1;
    }
  | {
      readonly kind: "unavailable";
      readonly reason: "source-location-too-distant" | "source-value-nodata";
      readonly source: SourceGridLocation;
    };

export interface GeographyClassifier {
  classify(
    context: ReleaseContext,
    coordinates: Coordinates,
    signal: AbortSignal,
  ): Promise<GeographyClassification>;
}

export interface AnalysisArtifactReader {
  lookup(
    context: ReleaseContext,
    scenario: ScenarioId,
    horizon: HorizonYear,
    coordinates: Coordinates,
    signal: AbortSignal,
  ): Promise<AnalysisReadResult>;
}

interface ResultIdentity {
  readonly dataReleaseId: string;
  readonly methodologyVersion: "ar6-regional-projection-v1";
  readonly scenario: ScenarioId;
  readonly horizon: HorizonYear;
  readonly analysisArtifactId: string;
  readonly analysisArtifactSha256: string;
  readonly visualArtifactId: string;
  readonly visualArtifactSha256: string;
  readonly visualArtifactUrl: string;
}

export type AssessmentResult =
  | (ResultIdentity & {
      readonly resultState: "ProjectionAvailable";
      readonly reason: "projection-available";
      readonly source: SourceGridLocation;
      readonly lowerMillimetres: number;
      readonly medianMillimetres: number;
      readonly upperMillimetres: number;
      readonly lowerMetres: number;
      readonly medianMetres: number;
      readonly upperMetres: number;
      readonly units: "m";
      readonly baseline: "1995-2014 mean";
      readonly confidence: "medium";
      readonly sourceRelease: "20210809";
      readonly sourceMemberSha256: string;
      readonly nativeResolutionDegrees: 1;
    })
  | (ResultIdentity & {
      readonly resultState: "DataUnavailable";
      readonly reason: "source-location-too-distant" | "source-value-nodata";
      readonly source: SourceGridLocation;
    })
  | (ResultIdentity & {
      readonly resultState: "OutOfScope";
      readonly reason: "outside-coastal-scope";
    })
  | (ResultIdentity & {
      readonly resultState: "UnsupportedGeography";
      readonly reason: "outside-europe-support";
    });

export interface AssessmentEvaluation {
  readonly evaluationToken: number;
  readonly result: AssessmentResult;
}

function aborted(message = "The projection evaluation was superseded or cancelled."): TechnicalFailure {
  return new TechnicalFailure({
    kind: "technical-error",
    code: "Aborted",
    message,
    recoverable: true,
  });
}

function resultIdentity(
  context: ReleaseContext,
  scenario: ScenarioId,
  horizon: HorizonYear,
): ResultIdentity {
  const dataset = context.dataset(scenario, horizon);
  const analysis = context.artifact(dataset.analysisArtifactId);
  const visual = context.artifact(dataset.visualArtifactId);
  if (
    analysis.role !== "projection-analysis-cog" ||
    visual.role !== "projection-visual-pmtiles" ||
    analysis.projectionContext.scenario !== scenario ||
    analysis.projectionContext.horizon !== horizon ||
    visual.projectionContext.scenario !== scenario ||
    visual.projectionContext.horizon !== horizon
  ) {
    throw new TechnicalFailure({
      kind: "technical-error",
      code: "ReleaseIdentityMismatch",
      message: "The result and visual artifacts do not share one release selection.",
      recoverable: false,
    });
  }
  return Object.freeze({
    dataReleaseId: context.dataReleaseId,
    methodologyVersion: context.methodologyVersion,
    scenario,
    horizon,
    analysisArtifactId: analysis.artifactId,
    analysisArtifactSha256: analysis.sha256,
    visualArtifactId: visual.artifactId,
    visualArtifactSha256: visual.sha256,
    visualArtifactUrl: visual.url,
  });
}

export function mapAssessmentResult(
  identity: ResultIdentity,
  geography: GeographyClassification,
  analysis?: AnalysisReadResult,
): AssessmentResult {
  if (geography === "OutsideEurope") {
    return Object.freeze({
      ...identity,
      resultState: "UnsupportedGeography",
      reason: "outside-europe-support",
    });
  }
  if (geography === "InEuropeOutsideCoastalZone") {
    return Object.freeze({
      ...identity,
      resultState: "OutOfScope",
      reason: "outside-coastal-scope",
    });
  }
  if (!analysis) {
    throw new TechnicalFailure({
      kind: "technical-error",
      code: "DecodeFailed",
      message: "An in-scope evaluation completed without an exact analysis read.",
      recoverable: false,
    });
  }
  if (analysis.kind === "unavailable") {
    return Object.freeze({
      ...identity,
      resultState: "DataUnavailable",
      reason: analysis.reason,
      source: analysis.source,
    });
  }
  return Object.freeze({
    ...identity,
    resultState: "ProjectionAvailable",
    reason: "projection-available",
    source: analysis.source,
    lowerMillimetres: analysis.lowerMillimetres,
    medianMillimetres: analysis.medianMillimetres,
    upperMillimetres: analysis.upperMillimetres,
    lowerMetres: analysis.lowerMillimetres * 0.001,
    medianMetres: analysis.medianMillimetres * 0.001,
    upperMetres: analysis.upperMillimetres * 0.001,
    units: "m",
    baseline: analysis.baseline,
    confidence: "medium",
    sourceRelease: analysis.sourceRelease,
    sourceMemberSha256: analysis.sourceMemberSha256,
    nativeResolutionDegrees: analysis.nativeResolutionDegrees,
  });
}

function linkedAbortController(externalSignal: AbortSignal): AbortController {
  const controller = new AbortController();
  if (externalSignal.aborted) controller.abort(externalSignal.reason);
  else {
    externalSignal.addEventListener(
      "abort",
      () => controller.abort(externalSignal.reason),
      { once: true, signal: controller.signal },
    );
  }
  return controller;
}

export class AssessmentEngine {
  readonly #geography: GeographyClassifier;
  readonly #analysis: AnalysisArtifactReader;
  #token = 0;
  #active: AbortController | undefined;

  constructor(dependencies: {
    readonly geography: GeographyClassifier;
    readonly analysis: AnalysisArtifactReader;
  }) {
    this.#geography = dependencies.geography;
    this.#analysis = dependencies.analysis;
  }

  get currentEvaluationToken(): number {
    return this.#token;
  }

  cancel(): void {
    this.#active?.abort("cancelled");
    this.#active = undefined;
    this.#token += 1;
  }

  async evaluate(
    context: ReleaseContext,
    selection: Selection,
    externalSignal: AbortSignal,
  ): Promise<AssessmentEvaluation> {
    this.#active?.abort("superseded");
    const controller = linkedAbortController(externalSignal);
    this.#active = controller;
    const evaluationToken = ++this.#token;
    try {
      const coordinates = validateCoordinates(selection.location.coordinates);
      if (selection.dataReleaseId !== context.dataReleaseId) {
        throw new TechnicalFailure({
          kind: "technical-error",
          code: "ReleaseIdentityMismatch",
          message: "The selection belongs to a different immutable release.",
          recoverable: false,
        });
      }
      const identity = resultIdentity(context, selection.scenario, selection.horizon);
      const geography = await this.#geography.classify(context, coordinates, controller.signal);
      if (evaluationToken !== this.#token || controller.signal.aborted) throw aborted();
      const analysis =
        geography === "InEuropeAndCoastalZone"
          ? await this.#analysis.lookup(
              context,
              selection.scenario,
              selection.horizon,
              coordinates,
              controller.signal,
            )
          : undefined;
      if (evaluationToken !== this.#token || controller.signal.aborted) throw aborted();
      return Object.freeze({
        evaluationToken,
        result: mapAssessmentResult(identity, geography, analysis),
      });
    } catch (error) {
      if (controller.signal.aborted && !(error instanceof TechnicalFailure)) throw aborted();
      throw error;
    } finally {
      if (evaluationToken === this.#token) this.#active = undefined;
    }
  }
}

export function haversineKilometres(
  query: Coordinates,
  source: Readonly<{ latitude: number; longitude: number }>,
): number {
  const radians = Math.PI / 180;
  const queryLatitude = query.latitude * radians;
  const sourceLatitude = source.latitude * radians;
  const latitudeDelta = sourceLatitude - queryLatitude;
  const rawLongitudeDelta = (source.longitude - query.longitude) * radians;
  const longitudeDelta =
    ((((rawLongitudeDelta + Math.PI) % (2 * Math.PI)) + 2 * Math.PI) %
      (2 * Math.PI)) -
    Math.PI;
  const haversine =
    Math.sin(latitudeDelta / 2) ** 2 +
    Math.cos(queryLatitude) *
      Math.cos(sourceLatitude) *
      Math.sin(longitudeDelta / 2) ** 2;
  return (
    2 *
    EARTH_MEAN_RADIUS_KILOMETRES *
    Math.atan2(Math.sqrt(haversine), Math.sqrt(Math.max(0, 1 - haversine)))
  );
}

export function roundedSourceDistance(distanceKilometres: number): number {
  return Math.round(distanceKilometres * 1_000_000) / 1_000_000;
}

export function selectNearestSourceGridLocation<T extends NativeGridCandidate>(
  candidates: readonly T[],
  coordinates: Coordinates,
): NearestSourceSelection<T> {
  let selected: T | undefined;
  let selectedDistance = Number.POSITIVE_INFINITY;
  for (const candidate of candidates) {
    const distance = haversineKilometres(coordinates, candidate);
    if (
      distance < selectedDistance ||
      (distance === selectedDistance && (!selected || candidate.locationId < selected.locationId))
    ) {
      selected = candidate;
      selectedDistance = distance;
    }
  }
  if (!selected) {
    throw new TechnicalFailure({
      kind: "technical-error",
      code: "DecodeFailed",
      message: "The analysis COG declares no source-grid location.",
      recoverable: false,
    });
  }
  return Object.freeze({
    candidate: selected,
    unroundedDistanceKilometres: selectedDistance,
    source: Object.freeze({
      locationId: selected.locationId,
      latitude: selected.latitude,
      longitude: selected.longitude,
      distanceKilometres: roundedSourceDistance(selectedDistance),
    }),
  });
}
