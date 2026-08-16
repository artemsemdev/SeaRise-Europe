import { readFileSync, writeFileSync } from "node:fs";
import { createHash } from "node:crypto";
import { resolve } from "node:path";
import Ajv2020 from "ajv/dist/2020.js";
import { _ } from "ajv/dist/compile/codegen/index.js";
import standaloneCode from "ajv/dist/standalone/index.js";
import addFormats from "ajv-formats";

const root = resolve(import.meta.dirname, "../../..");
const contractRoot = resolve(root, "contracts/release/v2");
const output = resolve(import.meta.dirname, "../src/contracts/generated/release-contract.ts");
const validatorOutput = resolve(import.meta.dirname, "../src/contracts/generated/manifest-validator.mjs");
const validatorTypesOutput = resolve(import.meta.dirname, "../src/contracts/generated/manifest-validator.d.mts");
const schemaFiles = [
  "artifact.schema.json",
  "browser-derivation-provenance.schema.json",
  "browser-derivation-receipt.schema.json",
  "defs.schema.json",
  "manifest.schema.json",
];
const schemaSources = Object.fromEntries(
  schemaFiles.map((name) => [name, readFileSync(resolve(contractRoot, name), "utf8")]),
);
const artifact = JSON.parse(schemaSources["artifact.schema.json"]);
const defs = JSON.parse(schemaSources["defs.schema.json"]);
const manifest = JSON.parse(schemaSources["manifest.schema.json"]);

const literal = (value) => (typeof value === "string" ? JSON.stringify(value) : String(value));
const union = (values) => values.map(literal).join(" | ");
const tuple = (values) => `readonly [${values.map(literal).join(", ")}]`;
const constTuple = (values) => `[${values.map(literal).join(", ")}] as const`;
const definition = (name) => defs.$defs[name];
const enumValues = (name) => definition(name).enum;
const assertRequired = (schema, expected, name) => {
  if (JSON.stringify(schema.required) !== JSON.stringify(expected)) {
    throw new Error(`${name} structure changed; update the contract generator explicitly`);
  }
};
assertRequired(manifest, [
  "$schema", "schemaVersion", "dataReleaseId", "dataProvenanceClass", "releaseAuthority",
  "baseReleaseIdentity", "browserDerivationIdentity", "previousReleaseId", "methodologyVersion", "defaults",
  "publication", "sources", "contractArtifacts", "artifacts", "datasets",
], "manifest.schema.json");
assertRequired(artifact.$defs.common, [
  "$schema", "schemaVersion", "dataReleaseId", "dataProvenanceClass", "artifactId", "path",
  "role", "mediaType", "byteSize", "sha256", "immutable", "scientificUse", "lineage", "rights",
], "artifact.schema.json common artifact");
const artifactSchemaId = artifact.$defs.common.properties.$schema.const;
if (artifactSchemaId !== artifact.$id) {
  throw new Error("artifact.schema.json must require its own canonical $id");
}
const contractDigest = createHash("sha256")
  .update(schemaFiles.map((name) => schemaSources[name]).join("\n"))
  .digest("hex");

const generated = `/**
 * Generated from the versioned contracts in contracts/release/v2.
 * Run \`npm run generate:contracts --workspace @searise/web\`; do not edit.
 */

export const RELEASE_CONTRACT_SOURCE_SHA256 = ${literal(contractDigest)};
export type SchemaVersion = ${literal(definition("schemaVersion").const)};
export const SCENARIO_IDS = ${constTuple(enumValues("scenarioId"))};
export type ScenarioId = ${union(enumValues("scenarioId"))};
export const HORIZON_YEARS = ${constTuple(enumValues("horizonYear"))};
export type HorizonYear = ${union(enumValues("horizonYear"))};
export const RESULT_STATES = ${constTuple(enumValues("resultState"))};
export type ResultState = ${union(enumValues("resultState"))};
export type DataProvenanceClass = ${union(enumValues("dataProvenanceClass"))};
export type ArtifactRole = ${union(enumValues("artifactRole"))};
export type MediaType = ${union(enumValues("mediaType"))};
export type DataReleaseId = string;
export type Sha256 = string;
export type BoundingBox = readonly [number, number, number, number];

export interface ReleaseAuthorityV2 {
  readonly automatedValidation: "pending" | "passed" | "failed";
  readonly releaseDisposition: "pending-owner" | "approved" | "rejected" | "blocked";
  readonly dataProvenanceClass: DataProvenanceClass;
  readonly statusDisclosureRequired: boolean;
}

export interface FileIdentityV2 {
  readonly path: string;
  readonly sha256: Sha256;
}

export interface ProjectionContextV2 {
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

interface CommonReleaseArtifactV2 {
  readonly $schema: ${literal(artifactSchemaId)};
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
  readonly scientificUse: "exact-lookup" | "exact-lookup-support" | "exact-analytics" | "visual-only" | "not-applicable";
  readonly lineage: readonly FileIdentityV2[];
  readonly rights: {
    readonly attributionIds: readonly string[];
    readonly redistribution: "allowed" | "conditional";
  };
  readonly spatialBounds?: BoundingBox | null;
}

export type ReleaseArtifactV2 =
  | (CommonReleaseArtifactV2 & {
      readonly role: "source-grid-identity";
      readonly mediaType: "application/gzip";
      readonly scientificUse: "exact-lookup-support";
      readonly projectionContext?: never;
      readonly projectionMatrixContext?: never;
    })
  | (CommonReleaseArtifactV2 & {
      readonly role: "range-integrity-index";
      readonly mediaType: "application/json";
      readonly scientificUse: "exact-lookup-support";
      readonly projectionContext?: never;
      readonly projectionMatrixContext?: never;
    })
  | (CommonReleaseArtifactV2 & {
      readonly role: "projection-analysis-cog";
      readonly mediaType: "image/tiff; application=geotiff; profile=cloud-optimized";
      readonly scientificUse: "exact-lookup";
      readonly spatialBounds: BoundingBox;
      readonly projectionContext: ProjectionContextV2;
      readonly projectionMatrixContext?: never;
    })
  | (CommonReleaseArtifactV2 & {
      readonly role: "projection-visual-pmtiles";
      readonly mediaType: "application/vnd.pmtiles";
      readonly scientificUse: "visual-only";
      readonly spatialBounds: BoundingBox;
      readonly projectionContext: ProjectionContextV2;
      readonly projectionMatrixContext?: never;
    })
  | (CommonReleaseArtifactV2 & {
      readonly role: "projection-geoparquet";
      readonly mediaType: "application/vnd.apache.parquet";
      readonly scientificUse: "exact-analytics";
      readonly spatialBounds: BoundingBox;
      readonly projectionContext?: never;
      readonly projectionMatrixContext: ProjectionMatrixContextV2;
    })
  | (CommonReleaseArtifactV2 & {
      readonly role: Exclude<ArtifactRole, "projection-analysis-cog" | "source-grid-identity" | "range-integrity-index" | "projection-visual-pmtiles" | "projection-geoparquet">;
      readonly scientificUse: "not-applicable";
      readonly projectionContext?: never;
      readonly projectionMatrixContext?: never;
    });

export interface ProjectionMatrixContextV2 {
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
  readonly grid: ProjectionContextV2["grid"];
  readonly values: ProjectionContextV2["values"];
}

export interface ReleaseDatasetV2 {
  readonly scenario: ScenarioId;
  readonly horizon: HorizonYear;
  readonly analysisArtifactId: string;
  readonly visualArtifactId: string;
  readonly analyticalArtifactId: "projection-matrix-geoparquet";
  readonly stacItemArtifactId: string;
}

export interface ReleaseManifestV2 {
  readonly $schema: ${literal(manifest.properties.$schema.const)};
  readonly schemaVersion: SchemaVersion;
  readonly dataReleaseId: DataReleaseId;
  readonly dataProvenanceClass: DataProvenanceClass;
  readonly releaseAuthority: ReleaseAuthorityV2;
  readonly baseReleaseIdentity: Readonly<{
    identityScope: "sealed-release-v1";
    schemaVersion: "1.0.0";
    manifestSha256: Sha256;
    createdAt: string;
    codeRevision: string;
  }>;
  readonly browserDerivationIdentity: Readonly<{
    identityScope: "browser-overlay-derivation";
    executionIdentity: "not-recorded";
    receiptArtifactId: string;
    provenanceArtifactId: string;
  }>;
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
    baseReleaseBuildReceipt: string;
    browserDerivationReceipt: string;
    sourceGridIdentity: string;
    rangeIntegrityIndex: string;
    sbom: string;
    searchRecords: string;
    qualitySummary: string;
    architectureEvidence: string;
    stacCatalog: string;
    stacCollection: string;
    stacItems: readonly string[];
    checksums: string;
    baseReleaseProvenance: string;
    browserDerivationProvenance: string;
    baseReleaseSignature: string;
  }>;
  readonly artifacts: readonly ReleaseArtifactV2[];
  readonly datasets: ${tuple(manifest.$defs.contractArtifacts.properties.stacItems.prefixItems.map((item) => item.const)).replace(/"stac-[^"]+"/g, "ReleaseDatasetV2")};
}
`;

const ajv = new Ajv2020({
  allErrors: true,
  strict: true,
  strictRequired: false,
  strictTypes: false,
  code: {
    source: true,
    esm: true,
    formats: _`require("ajv-formats/dist/formats").fullFormats`,
  },
});
addFormats(ajv);
ajv.addSchema(defs);
ajv.addSchema(artifact);
const validateManifest = ajv.compile(manifest);
const generatedValidator = `/* eslint-disable */
${standaloneCode(ajv, validateManifest)
  .replace(
    /const (func\d+) = require\("ajv\/dist\/runtime\/equal"\)\.default;/,
    'import equalRuntime from "ajv/dist/runtime/equal.js";const $1 = typeof equalRuntime === "function" ? equalRuntime : equalRuntime.default;',
  )
  .replace(
    /const (func\d+) = require\("ajv\/dist\/runtime\/ucs2length"\)\.default;/,
    'import ucs2LengthRuntime from "ajv/dist/runtime/ucs2length.js";const $1 = typeof ucs2LengthRuntime === "function" ? ucs2LengthRuntime : ucs2LengthRuntime.default;',
  )
  .replace(
    /const (formats\d+) = require\("ajv-formats\/dist\/formats"\)\.fullFormats\["date-time"\];/,
    'import formatsRuntime from "ajv-formats/dist/formats.js";const fullFormatsRuntime = formatsRuntime.fullFormats ?? formatsRuntime.default?.fullFormats;const $1 = fullFormatsRuntime["date-time"];',
  )}\n`;
if (/\brequire\s*\(|\b(?:new\s+)?Function\s*\(/.test(generatedValidator)) {
  throw new Error("Standalone manifest validator is not browser CSP-safe");
}
const generatedValidatorTypes = `/** Generated with the release contract; do not edit. */
import type { ErrorObject } from "ajv";
import type { ReleaseManifestV2 } from "./release-contract";

declare const validateManifest: {
  (value: unknown): value is ReleaseManifestV2;
  errors?: ErrorObject[] | null;
};

export default validateManifest;
`;

if (process.argv.includes("--check")) {
  const current = readFileSync(output, "utf8");
  if (current !== generated) throw new Error("Generated release contracts are stale");
  if (readFileSync(validatorOutput, "utf8") !== generatedValidator) {
    throw new Error("Generated standalone manifest validator is stale");
  }
  if (readFileSync(validatorTypesOutput, "utf8") !== generatedValidatorTypes) {
    throw new Error("Generated standalone manifest validator types are stale");
  }
} else {
  writeFileSync(output, generated);
  writeFileSync(validatorOutput, generatedValidator);
  writeFileSync(validatorTypesOutput, generatedValidatorTypes);
}
