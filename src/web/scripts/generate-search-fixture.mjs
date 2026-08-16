import { createHash } from "node:crypto";
import { Buffer } from "node:buffer";
import { readFileSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { brotliCompressSync, constants as zlibConstants } from "node:zlib";

const releaseId = "searise-europe-v1.0.0-20260810-c096aeab4e09";
const schemaId = "https://artemsemdev.github.io/SeaRise-Europe/contracts/settlements/v4/search-artifact.schema.json";
const releaseRoot = resolve(import.meta.dirname, "../../../contracts/release/v1/fixtures/release", releaseId);
const check = process.argv.includes("--check");
const manifestPath = resolve(releaseRoot, "manifest.json");
const checksumsPath = resolve(releaseRoot, "checksums.txt");

function compareCodePoints(left, right) {
  const leftPoints = Array.from(left, (point) => point.codePointAt(0));
  const rightPoints = Array.from(right, (point) => point.codePointAt(0));
  for (let index = 0; index < Math.min(leftPoints.length, rightPoints.length); index += 1) {
    if (leftPoints[index] !== rightPoints[index]) return leftPoints[index] - rightPoints[index];
  }
  return leftPoints.length - rightPoints.length;
}

function canonical(value) {
  if (value === null || typeof value === "boolean" || typeof value === "string") return JSON.stringify(value);
  if (typeof value === "number" && Number.isFinite(value)) return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  if (value && typeof value === "object") {
    const entries = Object.entries(value).sort(([left], [right]) => compareCodePoints(left, right));
    return `{${entries.map(([key, item]) => `${JSON.stringify(key)}:${canonical(item)}`).join(",")}}`;
  }
  throw new Error("synthetic search fixture contains a non-JSON value");
}

function digest(value) {
  return createHash("sha256").update(value).digest("hex");
}

const records = Object.freeze([
  { placeId: "geonames:900000001", displayName: "Málaga", searchNames: ["Malaga City"], countryCode: "ES", admin1Name: "Andalucía", population: 578460, featureCode: "PPLA", distanceToCoastMeters: 50, isCoastal: true, latitude: 36.7213, longitude: -4.4214, memberships: ["europe-core", "europe-coastal"] },
  { placeId: "geonames:900000002", displayName: "Αθήνα", searchNames: ["Athens", "Athina"], countryCode: "GR", admin1Name: "Attica", population: 637798, featureCode: "PPLC", distanceToCoastMeters: 7000, isCoastal: true, latitude: 37.9838, longitude: 23.7275, memberships: ["europe-core"] },
  { placeId: "geonames:900000003", displayName: "Springfield", searchNames: [], countryCode: "AA", admin1Name: "North", population: 1000, featureCode: "PPL", distanceToCoastMeters: 50000, isCoastal: false, latitude: 50, longitude: 10, memberships: ["europe-core"] },
  { placeId: "geonames:900000004", displayName: "Springfield", searchNames: [], countryCode: "BB", admin1Name: "South", population: 500, featureCode: "PPL", distanceToCoastMeters: 100, isCoastal: true, latitude: 50.1, longitude: 10.1, memberships: ["europe-coastal"] },
  { placeId: "geonames:900000005", displayName: "Islet Village", searchNames: [], countryCode: "CC", admin1Name: "Island", population: 0, featureCode: "PPL", distanceToCoastMeters: 0, isCoastal: true, latitude: 54, longitude: -10, memberships: ["europe-coastal"] },
  { placeId: "geonames:900000006", displayName: "Border City", searchNames: [], countryCode: "TR", admin1Name: "Boundary", population: 2000, featureCode: "PPL", distanceToCoastMeters: 10000, isCoastal: false, latitude: 41, longitude: 29, memberships: ["europe-core"] },
]);

const spatialIdentity = Object.freeze({
  supportGeometry: { artifactId: "europe-support", version: "natural-earth-5.1.1-explicit-scope-v2", sha256: "dd98b938df00fc582bbd220b913d96b1fd19bab812e2e9d95ecc4b409330a385" },
  coastalGeometry: { artifactId: "coastal-analysis-zone", version: "natural-earth-5.1.1-25km-scope-v2", sha256: "aa08f31460c80cbe35eefb44c6f8feb22b90727840eda3734241d707d7a910d9" },
  shorelineGeometry: { artifactId: "europe-settlement-shoreline-v1", version: "natural-earth-direct-linework-europe-selection-v1", sha256: "53972730f9af3f541b67ee67a4653fb5a21ac52011d33c4372eb9fa84bc331ac" },
  predicate: "covers",
  distanceMethodVersion: "epsg3035-planar-whole-meter-half-even-v1",
});
const source = Object.freeze({
  projectionDeterministicIdentity: digest("synthetic search projection deterministic identity"),
  projectionDocumentsSha256: digest("synthetic search projection documents"),
  projectionSchemaVersion: "settlement-search-projection-v1",
  projectionSha256: digest("synthetic search projection bytes"),
  spatialCandidateIdentity: "d225c8ecc8309ae8e685506780cf88147edaa521212050140a25c47666463091",
  spatialDatabaseSha256: "cf54f68e915d7f61b10b4f6c624522d2e9060881d5848da884f7b5de8596f608",
  spatialReceiptSha256: "1d47264bcdff3bf5365b000d75a08b3f2a8b22546eb4dce3a2cb3c2320a63125",
  spatialStageSchemaVersion: "spatial-classification-stage-v1",
});
const engine = Object.freeze({ engineId: "searise-codepoint-trie", packageVersion: "1.0.0", serializationVersion: "codepoint-trie-json-v1" });
const compression = Object.freeze({ algorithm: "brotli", mode: "text", quality: 11 });
const runtime = Object.freeze({ brotli: "1.1.0", icu: "78.2", node: "20.20.1", unicode: "17.0", zlib: "1.3.1-e00f703" });
const ranking = Object.freeze({ candidateLimit: 128, fuzzyDistance: "unicode-codepoint-levenshtein-max-2-v1", normalizationVersion: "unicode-nfkd-lowercase-v1", orderingVersion: "canonical-alternate-prefix-fuzzy-population-admin-coast-id-v1", queryWorkLimit: 250000, resultLimit: 100 });
const merge = Object.freeze({ order: ["europe-core", "europe-coastal"], deduplicateBy: "placeId", resultOrder: "core-results-then-unseen-coastal-results" });

function normalize(value) {
  return value.normalize("NFKD").replace(/\p{M}+/gu, "").toLowerCase().trim().replace(/\s+/g, " ");
}

function terms(record) {
  const tokens = [record.displayName, ...record.searchNames, record.countryCode, record.admin1Name ?? ""]
    .flatMap((value) => normalize(value).match(/[\p{L}\p{N}]+/gu) ?? []);
  return [...new Set(tokens)].join(" ");
}

function shard(shardId) {
  const selected = records.filter(({ memberships }) => memberships.includes(shardId));
  const prepared = selected.map((record, index) => ({
    ordinal: index + 1,
    placeId: record.placeId,
    displayName: record.displayName,
    searchNames: record.searchNames,
    countryCode: record.countryCode,
    admin1Name: record.admin1Name,
    population: record.population,
    featureCode: record.featureCode,
    distanceToCoastMeters: record.distanceToCoastMeters,
    isCoastal: record.isCoastal,
    latitude: record.latitude,
    longitude: record.longitude,
  }));
  const postings = new Map();
  prepared.forEach((record) => {
    for (const name of new Set([record.displayName, ...record.searchNames].map(normalize))) {
      postings.set(name, [...(postings.get(name) ?? []), record.ordinal]);
    }
  });
  const envelope = {
    formatVersion: "search-evaluation-index-v1",
    engine,
    binding: {
      evaluationId: "browser-search-shard-v2",
      shardId,
      documentCount: prepared.length,
      documentsSha256: digest(JSON.stringify(prepared.map((record) => [
        record.ordinal,
        terms(record),
        record.placeId,
        record.displayName,
        record.searchNames,
        record.countryCode,
        record.admin1Name,
        record.population,
        record.featureCode,
        record.distanceToCoastMeters,
        record.isCoastal,
      ]))),
      optionsSha256: digest("searise-codepoint-trie-1.0.0|full-name-codepoints|qualified-context|prefix|levenshtein-max-2|global-rank-cap|work=250000"),
    },
    payload: { serializationVersion: 1, entries: [...postings].sort(([left], [right]) => compareCodePoints(left, right)) },
  };
  const value = {
    $schema: schemaId,
    schemaVersion: "4.0.0",
    dataReleaseId: releaseId,
    dataProvenanceClass: "synthetic-fixture",
    artifactType: "settlement-browser-search-shard",
    mediaType: "application/vnd.searise.search-index+json",
    contentEncoding: "br",
    formatVersion: "settlement-browser-search-shard-v2",
    placeSchema: "https://artemsemdev.github.io/SeaRise-Europe/contracts/settlements/v3/place.schema.json",
    shardId,
    catalogMembership: shardId,
    normalizationVersion: "settlement-normalization-v2",
    spatialIdentity,
    geometryStatus: "selected-scope-approximation",
    canonicalGeometryClaim: false,
    hazardExtentClaim: false,
    scientificApprovalClaim: false,
    ownerApprovalClaim: false,
    productionClaim: false,
    publicationClaim: false,
    publicationEligible: false,
    signingClaim: false,
    recordCount: prepared.length,
    recordsSha256: digest(canonical(prepared)),
    records: prepared,
    indexBase64: Buffer.from(JSON.stringify(envelope)).toString("base64"),
    source,
    engine,
    compression,
    runtime,
    ranking,
    merge,
  };
  const raw = Buffer.from(canonical(value));
  return brotliCompressSync(raw, {
    params: {
      [zlibConstants.BROTLI_PARAM_MODE]: zlibConstants.BROTLI_MODE_TEXT,
      [zlibConstants.BROTLI_PARAM_QUALITY]: 11,
      [zlibConstants.BROTLI_PARAM_SIZE_HINT]: raw.length,
    },
  });
}

const generated = [];
for (const shardId of ["europe-core", "europe-coastal"]) {
  const relativePath = `search/${shardId}.codepoint-trie.json.br`;
  const path = resolve(releaseRoot, relativePath);
  const bytes = shard(shardId);
  if (check) {
    if (!readFileSync(path).equals(bytes)) throw new Error(`${shardId} synthetic search fixture is stale`);
  } else {
    writeFileSync(path, bytes);
  }
  const sha256 = digest(bytes);
  generated.push({ shardId, bytes: bytes.length, sha256, path: relativePath });
  console.log(`${shardId} ${bytes.length} ${sha256}`);
}

const checksumLines = readFileSync(checksumsPath, "utf8").trimEnd().split("\n");
const checksumHeader = checksumLines.shift();
const retainedChecksums = checksumLines.filter((line) =>
  !line.includes("search/europe-core.fixture.json") &&
  !line.includes("search/europe-coastal.fixture.json") &&
  !generated.some(({ path }) => line.endsWith(`  ${path}`))
);
const nextChecksums = `${checksumHeader}\n${[
  ...retainedChecksums,
  ...generated.map(({ path, sha256 }) => `${sha256}  ${path}`),
].sort((left, right) => compareCodePoints(left.slice(66), right.slice(66))).join("\n")}\n`;
if (check) {
  if (readFileSync(checksumsPath, "utf8") !== nextChecksums) throw new Error("synthetic release checksums are stale");
} else {
  writeFileSync(checksumsPath, nextChecksums);
}

const manifest = JSON.parse(readFileSync(manifestPath, "utf8"));
const newArtifacts = generated.map(({ shardId, bytes, sha256, path }) => ({
  $schema: "https://artemsemdev.github.io/SeaRise-Europe/contracts/release/v1/artifact.schema.json",
  artifactId: `settlements-${shardId}`,
  byteSize: bytes,
  dataProvenanceClass: "synthetic-fixture",
  dataReleaseId: releaseId,
  immutable: true,
  lineage: [{ path: "search/settlements.parquet", sha256: "cdb76a7956b5e627bbb2cfb18a4369ed955b703817ba87b58afa11240357ccee" }],
  mediaType: "application/vnd.searise.search-index+json",
  path,
  rights: { attributionIds: ["geonames-fixture"], redistribution: "allowed" },
  role: "settlement-search-index",
  schemaVersion: "1.0.0",
  scientificUse: "not-applicable",
  sha256,
  spatialBounds: null,
}));
const generatedIds = new Set(newArtifacts.map(({ artifactId }) => artifactId));
const artifacts = manifest.artifacts.filter(({ artifactId }) => !generatedIds.has(artifactId));
const searchRecordIndex = artifacts.findIndex(({ artifactId }) => artifactId === "search-records");
artifacts.splice(searchRecordIndex + 1, 0, ...newArtifacts);
manifest.artifacts = artifacts;
const checksumArtifact = manifest.artifacts.find(({ artifactId }) => artifactId === "checksums");
checksumArtifact.byteSize = Buffer.byteLength(nextChecksums);
checksumArtifact.sha256 = digest(nextChecksums);
const nextManifest = `${JSON.stringify(manifest)}\n`;
if (check) {
  if (readFileSync(manifestPath, "utf8") !== nextManifest) throw new Error("synthetic release manifest search bindings are stale");
} else {
  writeFileSync(manifestPath, nextManifest);
}
