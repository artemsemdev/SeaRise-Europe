import type {
  DataReleaseId,
  HorizonYear,
  ReleaseArtifactV1,
  ReleaseDatasetV1,
  ReleaseManifestV1,
  ResultState,
  ScenarioId,
} from "../contracts/generated/release-contract";

export type ReleaseDisposition =
  | "synthetic-fixture"
  | "private-engineering"
  | "public-promoted";

export type TechnicalErrorCode =
  | "SchemaInvalid"
  | "ReleaseIdentityMismatch"
  | "FetchFailed"
  | "RangeUnsupported"
  | "DecodeFailed"
  | "IntegrityFailed"
  | "UnsupportedBrowser"
  | "Aborted";

export interface TechnicalError {
  readonly kind: "technical-error";
  readonly code: TechnicalErrorCode;
  readonly message: string;
  readonly recoverable: boolean;
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

export type ResolvedArtifact = ReleaseArtifactV1 & { readonly url: string };

function datasetKey(scenario: ScenarioId, horizon: HorizonYear): string {
  return `${scenario}:${horizon}`;
}

export class ReleaseContext {
  readonly dataReleaseId: DataReleaseId;
  readonly disposition: ReleaseDisposition;
  readonly methodologyVersion: "ar6-regional-projection-v1";
  readonly defaults: Readonly<{ scenario: "ssp2-45"; horizon: 2050 }>;
  readonly manifest: ReleaseManifestV1;
  readonly manifestUrl: string;
  readonly artifacts: Readonly<Record<string, ResolvedArtifact>>;
  readonly datasets: Readonly<Record<string, ReleaseDatasetV1>>;

  constructor(input: {
    manifest: ReleaseManifestV1;
    manifestUrl: string;
    disposition: ReleaseDisposition;
    artifacts: Record<string, ResolvedArtifact>;
    datasets: Record<string, ReleaseDatasetV1>;
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

  dataset(scenario: ScenarioId, horizon: HorizonYear): ReleaseDatasetV1 {
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
