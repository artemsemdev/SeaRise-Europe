/* eslint-disable */
/** Generated from contracts/release/v1. Do not edit; run `npm run contracts:generate`. */

export type ReleaseAuthority = {
  [k: string]: unknown;
} & {
  automatedValidation: "pending" | "passed" | "failed";
  releaseDisposition: "pending-owner" | "approved" | "rejected" | "blocked";
  dataProvenanceClass: "real-source" | "synthetic-fixture";
  statusDisclosureRequired: boolean;
};
export type ArtifactId = string;
export type SeaRiseEuropeImmutableReleaseArtifactV1 =
  | (Common & {
      path?: {
        [k: string]: unknown;
      };
      role?: "projection-analysis-cog";
      mediaType?: "image/tiff; application=geotiff; profile=cloud-optimized";
      scientificUse?: "exact-lookup";
      spatialBounds: BoundingBox;
      [k: string]: unknown;
    })
  | (Common & {
      path?: {
        [k: string]: unknown;
      };
      role?: "projection-visual-pmtiles";
      mediaType?: "application/vnd.pmtiles";
      scientificUse?: "visual-only";
      spatialBounds: BoundingBox;
      [k: string]: unknown;
    })
  | (Common & {
      path?: "analysis/projections.parquet";
      role?: "projection-geoparquet";
      mediaType?: "application/vnd.apache.parquet";
      scientificUse?: "exact-analytics";
      spatialBounds: BoundingBox;
      [k: string]: unknown;
    })
  | (Common & {
      role?: {
        [k: string]: unknown;
      };
      scientificUse?: "not-applicable";
      [k: string]: unknown;
    } & {
      [k: string]: unknown;
    } & {
      [k: string]: unknown;
    } & {
      [k: string]: unknown;
    } & {
      [k: string]: unknown;
    } & {
      [k: string]: unknown;
    } & {
      [k: string]: unknown;
    } & {
      [k: string]: unknown;
    } & {
      [k: string]: unknown;
    } & {
      [k: string]: unknown;
    });
/**
 * @minItems 4
 * @maxItems 4
 */
export type BoundingBox = [number, number, number, number];

export interface SeaRiseEuropeImmutableReleaseManifestV1 {
  $schema: "https://artemsemdev.github.io/SeaRise-Europe/contracts/release/v1/manifest.schema.json";
  schemaVersion: "1.0.0";
  dataReleaseId: string;
  dataProvenanceClass: "real-source" | "synthetic-fixture";
  releaseAuthority: ReleaseAuthority;
  createdAt: string;
  codeRevision: string;
  previousReleaseId: string | null;
  methodologyVersion: "ar6-regional-projection-v1";
  defaults: {
    scenario: "ssp2-45";
    horizon: 2050;
  };
  publication: {
    releasePath: string;
    cacheControl: "public, max-age=31536000, immutable";
    appendOnly: true;
  };
  /**
   * @minItems 1
   */
  sources: [Source, ...Source[]];
  contractArtifacts: ContractArtifacts;
  /**
   * @minItems 41
   */
  artifacts: [
    SeaRiseEuropeImmutableReleaseArtifactV1,
    SeaRiseEuropeImmutableReleaseArtifactV1,
    SeaRiseEuropeImmutableReleaseArtifactV1,
    SeaRiseEuropeImmutableReleaseArtifactV1,
    SeaRiseEuropeImmutableReleaseArtifactV1,
    SeaRiseEuropeImmutableReleaseArtifactV1,
    SeaRiseEuropeImmutableReleaseArtifactV1,
    SeaRiseEuropeImmutableReleaseArtifactV1,
    SeaRiseEuropeImmutableReleaseArtifactV1,
    SeaRiseEuropeImmutableReleaseArtifactV1,
    SeaRiseEuropeImmutableReleaseArtifactV1,
    SeaRiseEuropeImmutableReleaseArtifactV1,
    SeaRiseEuropeImmutableReleaseArtifactV1,
    SeaRiseEuropeImmutableReleaseArtifactV1,
    SeaRiseEuropeImmutableReleaseArtifactV1,
    SeaRiseEuropeImmutableReleaseArtifactV1,
    SeaRiseEuropeImmutableReleaseArtifactV1,
    SeaRiseEuropeImmutableReleaseArtifactV1,
    SeaRiseEuropeImmutableReleaseArtifactV1,
    SeaRiseEuropeImmutableReleaseArtifactV1,
    SeaRiseEuropeImmutableReleaseArtifactV1,
    SeaRiseEuropeImmutableReleaseArtifactV1,
    SeaRiseEuropeImmutableReleaseArtifactV1,
    SeaRiseEuropeImmutableReleaseArtifactV1,
    SeaRiseEuropeImmutableReleaseArtifactV1,
    SeaRiseEuropeImmutableReleaseArtifactV1,
    SeaRiseEuropeImmutableReleaseArtifactV1,
    SeaRiseEuropeImmutableReleaseArtifactV1,
    SeaRiseEuropeImmutableReleaseArtifactV1,
    SeaRiseEuropeImmutableReleaseArtifactV1,
    SeaRiseEuropeImmutableReleaseArtifactV1,
    SeaRiseEuropeImmutableReleaseArtifactV1,
    SeaRiseEuropeImmutableReleaseArtifactV1,
    SeaRiseEuropeImmutableReleaseArtifactV1,
    SeaRiseEuropeImmutableReleaseArtifactV1,
    SeaRiseEuropeImmutableReleaseArtifactV1,
    SeaRiseEuropeImmutableReleaseArtifactV1,
    SeaRiseEuropeImmutableReleaseArtifactV1,
    SeaRiseEuropeImmutableReleaseArtifactV1,
    SeaRiseEuropeImmutableReleaseArtifactV1,
    SeaRiseEuropeImmutableReleaseArtifactV1,
    ...SeaRiseEuropeImmutableReleaseArtifactV1[]
  ];
  /**
   * @minItems 9
   * @maxItems 9
   */
  datasets: [
    Ssp1262030,
    Ssp1262050,
    Ssp1262100,
    Ssp2452030,
    Ssp2452050,
    Ssp2452100,
    Ssp5852030,
    Ssp5852050,
    Ssp5852100
  ];
}
export interface Source {
  sourceId: string;
  sourceRelease: string;
  archiveSha256: string;
  attributionId: string;
  receiptArtifactId: ArtifactId;
}
export interface ContractArtifacts {
  scenarioConfig: ArtifactId;
  methodology: ArtifactId;
  attribution: ArtifactId;
  /**
   * @minItems 1
   */
  sourceReceipts: [ArtifactId, ...ArtifactId[]];
  buildReceipt: ArtifactId;
  searchRecords: ArtifactId;
  qualitySummary: ArtifactId;
  architectureEvidence: ArtifactId;
  stacCatalog: ArtifactId;
  stacCollection: ArtifactId;
  /**
   * @minItems 9
   * @maxItems 9
   */
  stacItems: [
    "stac-ssp1-26-2030",
    "stac-ssp1-26-2050",
    "stac-ssp1-26-2100",
    "stac-ssp2-45-2030",
    "stac-ssp2-45-2050",
    "stac-ssp2-45-2100",
    "stac-ssp5-85-2030",
    "stac-ssp5-85-2050",
    "stac-ssp5-85-2100"
  ];
  checksums: ArtifactId;
  provenance: ArtifactId;
  signature: ArtifactId;
}
export interface Common {
  $schema: "https://artemsemdev.github.io/SeaRise-Europe/contracts/release/v1/artifact.schema.json";
  schemaVersion: "1.0.0";
  dataReleaseId: string;
  dataProvenanceClass: "real-source" | "synthetic-fixture";
  artifactId: string;
  path: string;
  role:
    | "release-manifest"
    | "contract-schema"
    | "scenario-config"
    | "methodology"
    | "source-attribution"
    | "source-receipt"
    | "build-receipt"
    | "support-boundary"
    | "coastal-boundary"
    | "settlement-search-index"
    | "settlement-search-receipt"
    | "settlement-geoparquet"
    | "projection-analysis-cog"
    | "projection-visual-pmtiles"
    | "projection-geoparquet"
    | "quality-summary"
    | "release-gate-report"
    | "architecture-evidence"
    | "stac-catalog"
    | "stac-collection"
    | "stac-item"
    | "checksums"
    | "provenance"
    | "signature";
  mediaType:
    | "application/json"
    | "application/geo+json"
    | "application/vnd.apache.parquet"
    | "application/vnd.in-toto+json"
    | "application/vnd.pmtiles"
    | "application/vnd.searise.search-index+json"
    | "application/vnd.dev.sigstore.bundle+json;version=0.3"
    | "application/x-ndjson"
    | "image/tiff; application=geotiff; profile=cloud-optimized"
    | "text/markdown"
    | "text/plain";
  byteSize: number;
  sha256: string;
  immutable: true;
  scientificUse: "exact-lookup" | "exact-analytics" | "visual-only" | "not-applicable";
  /**
   * @minItems 1
   */
  lineage: [FileIdentity, ...FileIdentity[]];
  rights: {
    /**
     * @minItems 1
     */
    attributionIds: [string, ...string[]];
    redistribution: "allowed" | "conditional";
  };
  spatialBounds?: BoundingBox | null;
  projectionContext?: ProjectionContext;
  projectionMatrixContext?: ProjectionMatrixContext;
}
export interface FileIdentity {
  path: string;
  sha256: string;
}
export interface ProjectionContext {
  scenario: "ssp1-26" | "ssp2-45" | "ssp5-85";
  horizon: 2030 | 2050 | 2100;
  source: SourceBinding;
  grid: Grid;
  values: ValueSemantics;
}
export interface SourceBinding {
  sourceRelease: "20210809";
  archiveSha256: string;
  memberSha256: string;
  methodologyVersion: "ar6-regional-projection-v1";
}
export interface Grid {
  crs: "EPSG:4326";
  /**
   * @minItems 4
   * @maxItems 4
   */
  bounds: [-30.5, 29.5, 45.5, 75.5];
  /**
   * @minItems 6
   * @maxItems 6
   */
  transform: [1, 0, -30.5, 0, -1, 75.5];
  width: 76;
  height: 46;
  nativeResolutionDegrees: 1;
  nodata: -32768;
}
export interface ValueSemantics {
  storedUnits: "mm";
  scaleToMetres: 0.001;
  baseline: "1995-2014 mean";
  /**
   * @minItems 3
   * @maxItems 3
   */
  quantiles: [0.167, 0.5, 0.833];
}
export interface ProjectionMatrixContext {
  /**
   * @minItems 3
   * @maxItems 3
   */
  scenarios: ["ssp1-26", "ssp2-45", "ssp5-85"];
  /**
   * @minItems 3
   * @maxItems 3
   */
  horizons: [2030, 2050, 2100];
  source: MatrixSourceBinding;
  grid: Grid;
  values: ValueSemantics;
}
export interface MatrixSourceBinding {
  sourceRelease: "20210809";
  archiveSha256: string;
  /**
   * @minItems 3
   * @maxItems 3
   */
  members: [Ssp126Member, Ssp245Member, Ssp585Member];
  methodologyVersion: "ar6-regional-projection-v1";
}
export interface Ssp126Member {
  scenario: "ssp1-26";
}
export interface Ssp245Member {
  scenario: "ssp2-45";
}
export interface Ssp585Member {
  scenario: "ssp5-85";
}
export interface Ssp1262030 {
  scenario: "ssp1-26";
  horizon: 2030;
  analysisArtifactId: "projection-ssp1-26-2030-cog";
  visualArtifactId: "projection-ssp1-26-2030-pmtiles";
  stacItemArtifactId: "stac-ssp1-26-2030";
}
export interface Ssp1262050 {
  scenario: "ssp1-26";
  horizon: 2050;
  analysisArtifactId: "projection-ssp1-26-2050-cog";
  visualArtifactId: "projection-ssp1-26-2050-pmtiles";
  stacItemArtifactId: "stac-ssp1-26-2050";
}
export interface Ssp1262100 {
  scenario: "ssp1-26";
  horizon: 2100;
  analysisArtifactId: "projection-ssp1-26-2100-cog";
  visualArtifactId: "projection-ssp1-26-2100-pmtiles";
  stacItemArtifactId: "stac-ssp1-26-2100";
}
export interface Ssp2452030 {
  scenario: "ssp2-45";
  horizon: 2030;
  analysisArtifactId: "projection-ssp2-45-2030-cog";
  visualArtifactId: "projection-ssp2-45-2030-pmtiles";
  stacItemArtifactId: "stac-ssp2-45-2030";
}
export interface Ssp2452050 {
  scenario: "ssp2-45";
  horizon: 2050;
  analysisArtifactId: "projection-ssp2-45-2050-cog";
  visualArtifactId: "projection-ssp2-45-2050-pmtiles";
  stacItemArtifactId: "stac-ssp2-45-2050";
}
export interface Ssp2452100 {
  scenario: "ssp2-45";
  horizon: 2100;
  analysisArtifactId: "projection-ssp2-45-2100-cog";
  visualArtifactId: "projection-ssp2-45-2100-pmtiles";
  stacItemArtifactId: "stac-ssp2-45-2100";
}
export interface Ssp5852030 {
  scenario: "ssp5-85";
  horizon: 2030;
  analysisArtifactId: "projection-ssp5-85-2030-cog";
  visualArtifactId: "projection-ssp5-85-2030-pmtiles";
  stacItemArtifactId: "stac-ssp5-85-2030";
}
export interface Ssp5852050 {
  scenario: "ssp5-85";
  horizon: 2050;
  analysisArtifactId: "projection-ssp5-85-2050-cog";
  visualArtifactId: "projection-ssp5-85-2050-pmtiles";
  stacItemArtifactId: "stac-ssp5-85-2050";
}
export interface Ssp5852100 {
  scenario: "ssp5-85";
  horizon: 2100;
  analysisArtifactId: "projection-ssp5-85-2100-cog";
  visualArtifactId: "projection-ssp5-85-2100-pmtiles";
  stacItemArtifactId: "stac-ssp5-85-2100";
}
