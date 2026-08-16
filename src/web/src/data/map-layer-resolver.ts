import type { HorizonYear, ScenarioId } from "../contracts/generated/release-contract";
import { TechnicalFailure, type ReleaseContext, type ResolvedArtifact } from "../domain/release";

export const VISUAL_BANDS = ["lower", "central", "upper"] as const;
export type VisualBand = (typeof VISUAL_BANDS)[number];

export interface ProjectionVisualLayer {
  readonly kind: "projection";
  readonly dataReleaseId: string;
  readonly scenario: ScenarioId;
  readonly horizon: HorizonYear;
  readonly artifactId: string;
  readonly url: string;
  readonly sourceLayer: "projection";
  readonly bounds: readonly [number, number, number, number];
  readonly visualOnly: true;
  readonly valueProperties: Readonly<Record<VisualBand, "lower_mm" | "median_mm" | "upper_mm">>;
}

export interface BoundaryVisualLayer {
  readonly kind: "support-boundary" | "coastal-boundary";
  readonly artifactId: string;
  readonly url: string;
  readonly mediaType: "application/vnd.pmtiles" | "application/geo+json";
  readonly sourceLayer: "support_boundary" | "coastal_boundary";
  readonly visualOnly: true;
}

export interface ResolvedMapLayers {
  readonly projection: ProjectionVisualLayer;
  readonly boundaries: readonly BoundaryVisualLayer[];
  readonly attributionArtifactUrl: string;
}

const VALUE_PROPERTIES = Object.freeze({
  lower: "lower_mm",
  central: "median_mm",
  upper: "upper_mm",
} as const);

function fail(message: string): never {
  throw new TechnicalFailure({
    kind: "technical-error",
    code: "SchemaInvalid",
    message,
    recoverable: false,
  });
}

function exactBounds(artifact: ResolvedArtifact): readonly [number, number, number, number] {
  const bounds = artifact.spatialBounds;
  if (!bounds || bounds.length !== 4) fail(`Visual artifact ${artifact.artifactId} has no bounds.`);
  return Object.freeze([bounds[0], bounds[1], bounds[2], bounds[3]]);
}

function optionalBoundaries(context: ReleaseContext): readonly BoundaryVisualLayer[] {
  const boundaries: BoundaryVisualLayer[] = [];
  for (const artifact of Object.values(context.artifacts)) {
    if (artifact.role !== "support-boundary" && artifact.role !== "coastal-boundary") continue;
    if (artifact.mediaType !== "application/vnd.pmtiles" && artifact.mediaType !== "application/geo+json") {
      continue;
    }
    boundaries.push(Object.freeze({
      kind: artifact.role,
      artifactId: artifact.artifactId,
      url: artifact.url,
      mediaType: artifact.mediaType,
      sourceLayer: artifact.role === "support-boundary" ? "support_boundary" : "coastal_boundary",
      visualOnly: true,
    }));
  }
  return Object.freeze(boundaries.sort((left, right) => left.kind.localeCompare(right.kind)));
}

/** Resolve map-only artifacts from the already validated immutable release aggregate. */
export function resolveMapLayers(
  context: ReleaseContext,
  scenario: ScenarioId,
  horizon: HorizonYear,
): ResolvedMapLayers {
  const dataset = context.dataset(scenario, horizon);
  const artifact = context.artifact(dataset.visualArtifactId);
  if (
    artifact.role !== "projection-visual-pmtiles" ||
    artifact.mediaType !== "application/vnd.pmtiles" ||
    artifact.scientificUse !== "visual-only" ||
    artifact.projectionContext?.scenario !== scenario ||
    artifact.projectionContext.horizon !== horizon
  ) {
    fail(`Dataset ${scenario}/${horizon} does not resolve to its visual-only PMTiles artifact.`);
  }
  const projection = Object.freeze({
    kind: "projection" as const,
    dataReleaseId: context.dataReleaseId,
    scenario,
    horizon,
    artifactId: artifact.artifactId,
    url: artifact.url,
    sourceLayer: "projection" as const,
    bounds: exactBounds(artifact),
    visualOnly: true as const,
    valueProperties: VALUE_PROPERTIES,
  });
  return Object.freeze({
    projection,
    boundaries: optionalBoundaries(context),
    attributionArtifactUrl: context.artifact(context.manifest.contractArtifacts.attribution).url,
  });
}
