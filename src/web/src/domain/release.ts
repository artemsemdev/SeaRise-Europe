import type {
  DataReleaseId,
  HorizonYear,
  ReleaseArtifactV2,
  ReleaseDatasetV2,
  ReleaseManifestV2,
  ResultState,
  ScenarioId,
} from "../contracts/generated/release-contract";

export type ReleaseDisposition =
  | "synthetic-fixture"
  | "private-engineering"
  | "public-promoted";

export const TECHNICAL_ERROR_CODES = [
  "SchemaInvalid",
  "ReleaseIdentityMismatch",
  "FetchFailed",
  "RangeUnsupported",
  "DecodeFailed",
  "IntegrityFailed",
  "UnsupportedBrowser",
  "Aborted",
] as const;
export type TechnicalErrorCode = (typeof TECHNICAL_ERROR_CODES)[number];

export type GeographyClassification =
  | "OutsideEurope"
  | "InEuropeOutsideCoastalZone"
  | "InEuropeAndCoastalZone";

export interface TechnicalError {
  readonly kind: "technical-error";
  readonly code: TechnicalErrorCode;
  readonly message: string;
  readonly recoverable: boolean;
}

const TECHNICAL_ERROR_PRESENTATION: Readonly<
  Record<TechnicalErrorCode, Readonly<{ title: string; guidance: string }>>
> = Object.freeze({
  SchemaInvalid: { title: "Release contract invalid", guidance: "Use a complete reviewed release." },
  ReleaseIdentityMismatch: { title: "Release identity mismatch", guidance: "Use the release pinned by this application build." },
  FetchFailed: { title: "Release delivery unavailable", guidance: "Check the connection and retry the same release." },
  RangeUnsupported: { title: "Byte ranges unavailable", guidance: "Use a host that preserves range requests." },
  DecodeFailed: { title: "Release data unreadable", guidance: "Retry only if delivery may have been interrupted." },
  IntegrityFailed: { title: "Release integrity check failed", guidance: "Do not use or substitute these artifacts." },
  UnsupportedBrowser: { title: "Browser capability unavailable", guidance: "Use a current supported browser." },
  Aborted: { title: "Operation cancelled", guidance: "No scientific outcome was produced." },
});

export function technicalErrorPresentation(error: TechnicalError): Readonly<{
  title: string;
  guidance: string;
}> {
  return TECHNICAL_ERROR_PRESENTATION[error.code];
}

export class TechnicalFailure extends Error {
  readonly detail: TechnicalError;

  constructor(detail: TechnicalError) {
    super(detail.message);
    this.name = "TechnicalFailure";
    this.detail = Object.freeze(detail);
  }
}

export interface Coordinates {
  readonly latitude: number;
  readonly longitude: number;
}

export type SelectedLocation =
  | { readonly kind: "coordinate"; readonly coordinates: Coordinates }
  | {
      readonly kind: "settlement";
      readonly placeId: string;
      readonly coordinates: Coordinates;
    };

export interface Selection {
  readonly location: SelectedLocation;
  readonly scenario: ScenarioId;
  readonly horizon: HorizonYear;
  readonly dataReleaseId: DataReleaseId;
}

export type ProjectionOutcome =
  | { readonly resultState: "ProjectionAvailable" }
  | {
      readonly resultState: "DataUnavailable";
      readonly reason: "source-location-too-distant" | "source-value-nodata";
    }
  | { readonly resultState: "OutOfScope" }
  | { readonly resultState: "UnsupportedGeography" };

const outcomeExhaustiveness: Readonly<Record<ResultState, true>> = Object.freeze({
  ProjectionAvailable: true,
  DataUnavailable: true,
  OutOfScope: true,
  UnsupportedGeography: true,
});
void outcomeExhaustiveness;

export type ResolvedArtifact = ReleaseArtifactV2 & { readonly url: string };

function datasetKey(scenario: ScenarioId, horizon: HorizonYear): string {
  return `${scenario}:${horizon}`;
}

export class ReleaseContext {
  readonly dataReleaseId: DataReleaseId;
  readonly disposition: ReleaseDisposition;
  readonly methodologyVersion: "ar6-regional-projection-v1";
  readonly defaults: Readonly<{ scenario: "ssp2-45"; horizon: 2050 }>;
  readonly manifest: ReleaseManifestV2;
  readonly manifestUrl: string;
  readonly artifacts: Readonly<Record<string, ResolvedArtifact>>;
  readonly datasets: Readonly<Record<string, ReleaseDatasetV2>>;

  constructor(input: {
    manifest: ReleaseManifestV2;
    manifestUrl: string;
    disposition: ReleaseDisposition;
    artifacts: Record<string, ResolvedArtifact>;
    datasets: Record<string, ReleaseDatasetV2>;
  }) {
    this.manifest = input.manifest;
    this.manifestUrl = input.manifestUrl;
    this.dataReleaseId = input.manifest.dataReleaseId;
    this.disposition = input.disposition;
    this.methodologyVersion = input.manifest.methodologyVersion;
    this.defaults = input.manifest.defaults;
    this.artifacts = Object.freeze(input.artifacts);
    this.datasets = Object.freeze(input.datasets);
    Object.freeze(this);
  }

  artifact(artifactId: string): ResolvedArtifact {
    const artifact = this.artifacts[artifactId];
    if (!artifact) {
      throw new TechnicalFailure({
        kind: "technical-error",
        code: "SchemaInvalid",
        message: `The pinned release does not declare artifact ${artifactId}.`,
        recoverable: false,
      });
    }
    return artifact;
  }

  dataset(scenario: ScenarioId, horizon: HorizonYear): ReleaseDatasetV2 {
    const dataset = this.datasets[datasetKey(scenario, horizon)];
    if (!dataset) {
      throw new TechnicalFailure({
        kind: "technical-error",
        code: "SchemaInvalid",
        message: `The pinned release does not declare ${scenario}/${horizon}.`,
        recoverable: false,
      });
    }
    return dataset;
  }
}

export function validateCoordinates(value: Coordinates): Coordinates {
  if (
    !Number.isFinite(value.latitude) ||
    !Number.isFinite(value.longitude) ||
    value.latitude < -90 ||
    value.latitude > 90 ||
    value.longitude < -180 ||
    value.longitude > 180
  ) {
    throw new TechnicalFailure({
      kind: "technical-error",
      code: "SchemaInvalid",
      message: "Coordinates must be finite WGS84 latitude/longitude values.",
      recoverable: false,
    });
  }
  return Object.freeze({ ...value });
}

export function datasetIdentity(scenario: ScenarioId, horizon: HorizonYear): string {
  return datasetKey(scenario, horizon);
}
