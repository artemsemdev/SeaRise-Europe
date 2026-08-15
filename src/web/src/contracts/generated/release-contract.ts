/**
 * Generated from contracts/release/v1/{defs,manifest,artifact}.schema.json.
 * Run `npm run generate:contracts --workspace @searise/web`; do not edit.
 */

export const RELEASE_CONTRACT_SOURCE_SHA256 = "93a7d5e4b398958622e3b1bc4ef6ff7e9881f52d9d5fb08bdc84dffe7b86deff";
export type SchemaVersion = "1.0.0";
export const SCENARIO_IDS = ["ssp1-26", "ssp2-45", "ssp5-85"] as const;
export type ScenarioId = "ssp1-26" | "ssp2-45" | "ssp5-85";
export const HORIZON_YEARS = [2030, 2050, 2100] as const;
export type HorizonYear = 2030 | 2050 | 2100;
export const RESULT_STATES = ["ProjectionAvailable", "DataUnavailable", "OutOfScope", "UnsupportedGeography"] as const;
export type ResultState = "ProjectionAvailable" | "DataUnavailable" | "OutOfScope" | "UnsupportedGeography";
export type DataProvenanceClass = "real-source" | "synthetic-fixture";
export type ArtifactRole = "release-manifest" | "contract-schema" | "scenario-config" | "methodology" | "source-attribution" | "source-receipt" | "build-receipt" | "support-boundary" | "coastal-boundary" | "settlement-search-index" | "settlement-geoparquet" | "projection-analysis-cog" | "projection-visual-pmtiles" | "projection-geoparquet" | "quality-summary" | "release-gate-report" | "architecture-evidence" | "stac-catalog" | "stac-collection" | "stac-item" | "checksums" | "provenance" | "signature";
export type MediaType = "application/json" | "application/geo+json" | "application/vnd.apache.parquet" | "application/vnd.in-toto+json" | "application/vnd.pmtiles" | "application/vnd.searise.search-index+json" | "application/vnd.dev.sigstore.bundle+json;version=0.3" | "application/x-ndjson" | "image/tiff; application=geotiff; profile=cloud-optimized" | "text/markdown" | "text/plain";
export type DataReleaseId = string;
export type Sha256 = string;
export type BoundingBox = readonly [number, number, number, number];

export interface ReleaseAuthorityV1 {
  readonly automatedValidation: "pending" | "passed" | "failed";
  readonly releaseDisposition: "pending-owner" | "approved" | "rejected" | "blocked";
  readonly dataProvenanceClass: DataProvenanceClass;
  readonly statusDisclosureRequired: boolean;
}

export interface FileIdentityV1 {
  readonly path: string;
  readonly sha256: Sha256;
}

export interface ProjectionContextV1 {
  readonly scenario: ScenarioId;
  readonly horizon: HorizonYear;
  readonly source: {
    readonly sourceRelease: "20210809";
    readonly archiveSha256: Sha256;
    readonly memberSha256: Sha256;
    readonly methodologyVersion: "ar6-regional-projection-v1";
  };
  readonly grid: {
    readonly crs: "EPSG:4326";
    readonly bounds: readonly [-30.5, 29.5, 45.5, 75.5];
    readonly transform: readonly [1, 0, -30.5, 0, -1, 75.5];
    readonly width: 76;
    readonly height: 46;
    readonly nativeResolutionDegrees: 1;
    readonly nodata: -32768;
  };
  readonly values: {
    readonly storedUnits: "mm";
    readonly scaleToMetres: 0.001;
    readonly baseline: "1995-2014 mean";
    readonly quantiles: readonly [0.167, 0.5, 0.833];
  };
}

interface CommonReleaseArtifactV1 {
  readonly $schema: "https://artemsemdev.github.io/SeaRise-Europe/contracts/release/v1/artifact.schema.json";
  readonly schemaVersion: SchemaVersion;
  readonly dataReleaseId: DataReleaseId;
  readonly dataProvenanceClass: DataProvenanceClass;
  readonly artifactId: string;
  readonly path: string;
  readonly role: ArtifactRole;
  readonly mediaType: MediaType;
  readonly byteSize: number;
  readonly sha256: Sha256;
  readonly immutable: true;
  readonly scientificUse: "exact-lookup" | "exact-analytics" | "visual-only" | "not-applicable";
  readonly lineage: readonly FileIdentityV1[];
  readonly rights: {
    readonly attributionIds: readonly string[];
    readonly redistribution: "allowed" | "conditional";
  };
  readonly spatialBounds?: BoundingBox | null;
}

export type ReleaseArtifactV1 =
  | (CommonReleaseArtifactV1 & {
      readonly role: "projection-analysis-cog";
      readonly mediaType: "image/tiff; application=geotiff; profile=cloud-optimized";
      readonly scientificUse: "exact-lookup";
      readonly spatialBounds: BoundingBox;
      readonly projectionContext: ProjectionContextV1;
      readonly projectionMatrixContext?: never;
    })
  | (CommonReleaseArtifactV1 & {
      readonly role: "projection-visual-pmtiles";
      readonly mediaType: "application/vnd.pmtiles";
      readonly scientificUse: "visual-only";
      readonly spatialBounds: BoundingBox;
      readonly projectionContext: ProjectionContextV1;
      readonly projectionMatrixContext?: never;
    })
  | (CommonReleaseArtifactV1 & {
      readonly role: "projection-geoparquet";
      readonly mediaType: "application/vnd.apache.parquet";
      readonly scientificUse: "exact-analytics";
      readonly spatialBounds: BoundingBox;
      readonly projectionContext?: never;
      readonly projectionMatrixContext: ProjectionMatrixContextV1;
    })
  | (CommonReleaseArtifactV1 & {
      readonly role: Exclude<ArtifactRole, "projection-analysis-cog" | "projection-visual-pmtiles" | "projection-geoparquet">;
      readonly scientificUse: "not-applicable";
      readonly projectionContext?: never;
      readonly projectionMatrixContext?: never;
    });

export interface ProjectionMatrixContextV1 {
  readonly scenarios: readonly ["ssp1-26", "ssp2-45", "ssp5-85"];
  readonly horizons: readonly [2030, 2050, 2100];
  readonly source: {
    readonly sourceRelease: "20210809";
    readonly archiveSha256: Sha256;
    readonly members: readonly [
      Readonly<{ scenario: "ssp1-26"; sha256: Sha256 }>,
      Readonly<{ scenario: "ssp2-45"; sha256: Sha256 }>,
      Readonly<{ scenario: "ssp5-85"; sha256: Sha256 }>,
    ];
    readonly methodologyVersion: "ar6-regional-projection-v1";
  };
  readonly grid: ProjectionContextV1["grid"];
  readonly values: ProjectionContextV1["values"];
}

export interface ReleaseDatasetV1 {
  readonly scenario: ScenarioId;
  readonly horizon: HorizonYear;
  readonly analysisArtifactId: string;
  readonly visualArtifactId: string;
  readonly analyticalArtifactId: "projection-matrix-geoparquet";
  readonly stacItemArtifactId: string;
}

export interface ReleaseManifestV1 {
  readonly $schema: "https://artemsemdev.github.io/SeaRise-Europe/contracts/release/v1/manifest.schema.json";
  readonly schemaVersion: SchemaVersion;
  readonly dataReleaseId: DataReleaseId;
  readonly dataProvenanceClass: DataProvenanceClass;
  readonly releaseAuthority: ReleaseAuthorityV1;
  readonly createdAt: string;
  readonly codeRevision: string;
  readonly previousReleaseId: DataReleaseId | null;
  readonly methodologyVersion: "ar6-regional-projection-v1";
  readonly defaults: { readonly scenario: "ssp2-45"; readonly horizon: 2050 };
  readonly publication: {
    readonly releasePath: string;
    readonly cacheControl: "public, max-age=31536000, immutable";
    readonly appendOnly: true;
  };
  readonly sources: readonly Readonly<{
    sourceId: string;
    sourceRelease: string;
    archiveSha256: Sha256;
    attributionId: string;
    receiptArtifactId: string;
  }>[];
  readonly contractArtifacts: Readonly<{
    scenarioConfig: string;
    methodology: string;
    attribution: string;
    sourceReceipts: readonly string[];
    buildReceipt: string;
    searchRecords: string;
    qualitySummary: string;
    architectureEvidence: string;
    stacCatalog: string;
    stacCollection: string;
    stacItems: readonly string[];
    checksums: string;
    provenance: string;
    signature: string;
  }>;
  readonly artifacts: readonly ReleaseArtifactV1[];
  readonly datasets: readonly [ReleaseDatasetV1, ReleaseDatasetV1, ReleaseDatasetV1, ReleaseDatasetV1, ReleaseDatasetV1, ReleaseDatasetV1, ReleaseDatasetV1, ReleaseDatasetV1, ReleaseDatasetV1];
}
