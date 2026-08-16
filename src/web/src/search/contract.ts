import searchArtifactSchema from "../../../../contracts/settlements/v4/search-artifact.schema.json";
import { normalizeSearchText } from "./ranking";
import type { SearchShardAuthority, SearchShardId, SettlementSearchRecord } from "./types";

const SCHEMA = searchArtifactSchema as unknown as {
  readonly $id: string;
  readonly $defs: {
    readonly shard: { readonly required: readonly string[] };
    readonly source: { readonly required: readonly string[] };
    readonly spatialIdentity: { readonly required: readonly string[] };
    readonly geometryArtifact: { readonly required: readonly string[] };
    readonly engine: { readonly required: readonly string[] };
    readonly compression: { readonly required: readonly string[] };
    readonly runtime: { readonly required: readonly string[] };
    readonly ranking: { readonly required: readonly string[] };
    readonly merge: { readonly required: readonly string[] };
    readonly record: { readonly required: readonly string[] };
  };
};

const SHA256 = /^[a-f0-9]{64}$/;
const RELEASE_ID = /^searise-europe-v[0-9]+\.[0-9]+\.[0-9]+-[0-9]{8}-[a-f0-9]{12}$/;
const FEATURE_CODES = new Set(["PPL", "PPLA", "PPLA2", "PPLA3", "PPLA4", "PPLA5", "PPLC", "PPLF", "PPLG", "PPLL", "PPLR"]);
const ADMIN_CODES = new Set(["PPLC", "PPLA", "PPLA2", "PPLA3", "PPLA4", "PPLA5"]);
const FALSE_CLAIMS = ["canonicalGeometryClaim", "hazardExtentClaim", "scientificApprovalClaim", "ownerApprovalClaim", "productionClaim", "publicationClaim", "signingClaim"] as const;
const ENGINE = { engineId: "searise-codepoint-trie", packageVersion: "1.0.0", serializationVersion: "codepoint-trie-json-v1" } as const;
const COMPRESSION = { algorithm: "brotli", mode: "text", quality: 11 } as const;
const RUNTIME = { brotli: "1.1.0", icu: "78.2", node: "20.20.1", unicode: "17.0", zlib: "1.3.1-e00f703" } as const;
const RANKING = { candidateLimit: 128, fuzzyDistance: "unicode-codepoint-levenshtein-max-2-v1", normalizationVersion: "unicode-nfkd-lowercase-v1", orderingVersion: "canonical-alternate-prefix-fuzzy-population-admin-coast-id-v1", queryWorkLimit: 250000, resultLimit: 100 } as const;
const MERGE = { order: ["europe-core", "europe-coastal"], deduplicateBy: "placeId", resultOrder: "core-results-then-unseen-coastal-results" } as const;
const OPTIONS_IDENTITY = "searise-codepoint-trie-1.0.0|full-name-codepoints|qualified-context|prefix|levenshtein-max-2|global-rank-cap|work=250000";

export interface IndexedRecord extends SettlementSearchRecord { readonly ordinal: number }
export interface IndexEnvelope {
  readonly formatVersion: "search-evaluation-index-v1";
  readonly engine: typeof ENGINE;
  readonly binding: {
    readonly evaluationId: "browser-search-shard-v2";
    readonly shardId: SearchShardId;
    readonly documentCount: number;
    readonly documentsSha256: string;
    readonly optionsSha256: string;
  };
  readonly payload: { readonly serializationVersion: 1; readonly entries: readonly (readonly [string, readonly number[]])[] };
}
export interface ValidatedSearchShard {
  readonly records: readonly IndexedRecord[];
  readonly envelope: IndexEnvelope;
  readonly commonIdentity: string;
}

function fail(message: string): never { throw new Error(message); }

export function compareCodePoints(left: string, right: string): number {
  let leftIndex = 0;
  let rightIndex = 0;
  while (leftIndex < left.length && rightIndex < right.length) {
    const leftPoint = left.codePointAt(leftIndex)!;
    const rightPoint = right.codePointAt(rightIndex)!;
    if (leftPoint !== rightPoint) return leftPoint - rightPoint;
    leftIndex += leftPoint > 0xffff ? 2 : 1;
    rightIndex += rightPoint > 0xffff ? 2 : 1;
  }
  return (left.length - leftIndex) - (right.length - rightIndex);
}

export function canonicalJson(value: unknown): string {
  if (value === null || typeof value === "boolean" || typeof value === "string") return JSON.stringify(value);
  if (typeof value === "number" && Number.isFinite(value)) return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(",")}]`;
  if (typeof value === "object" && value !== null) {
    const entries = Object.entries(value as Record<string, unknown>).sort(([left], [right]) => compareCodePoints(left, right));
    return `{${entries.map(([key, item]) => `${JSON.stringify(key)}:${canonicalJson(item)}`).join(",")}}`;
  }
  return fail("search shard contains a non-JSON value");
}

function exactKeys(value: unknown, keys: readonly string[]): value is Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return false;
  const actual = Object.keys(value);
  if (actual.length !== keys.length) return false;
  const expected = new Set(keys);
  return actual.every((key) => expected.has(key));
}

function hex(bytes: ArrayBuffer): string {
  return Array.from(new Uint8Array(bytes), (value) => value.toString(16).padStart(2, "0")).join("");
}

async function digest(value: string): Promise<string> {
  return hex(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(value)));
}

function strictText(value: unknown, maximum: number, nullable = false): value is string | null {
  if (nullable && value === null) return true;
  if (typeof value !== "string" || !value || Array.from(value).length > maximum) return false;
  try { normalizeSearchText(value); } catch { return false; }
  return true;
}

function numericPlaceId(value: unknown): bigint {
  const match = typeof value === "string" ? /^geonames:([1-9][0-9]*)$/.exec(value) : null;
  return match ? BigInt(match[1]) : fail("search shard place ID is not a GeoNames stable ID");
}

function validateGeometry(value: unknown): void {
  if (!exactKeys(value, SCHEMA.$defs.geometryArtifact.required)
      || typeof value.artifactId !== "string" || !value.artifactId
      || typeof value.version !== "string" || !value.version
      || typeof value.sha256 !== "string" || !SHA256.test(value.sha256)) {
    fail("search shard geometry identity differs from the v4 contract");
  }
}

function validateSpatial(value: unknown): void {
  if (!exactKeys(value, SCHEMA.$defs.spatialIdentity.required)
      || value.predicate !== "covers"
      || value.distanceMethodVersion !== "epsg3035-planar-whole-meter-half-even-v1") {
    fail("search shard spatial identity differs from the v4 contract");
  }
  for (const name of ["supportGeometry", "coastalGeometry", "shorelineGeometry"] as const) validateGeometry(value[name]);
  const hashes = [value.supportGeometry, value.coastalGeometry, value.shorelineGeometry]
    .map((item) => (item as Record<string, unknown>).sha256);
  if (new Set(hashes).size !== 3) fail("search shard geometry identities are not distinct");
}

function validateSource(value: unknown): void {
  if (!exactKeys(value, SCHEMA.$defs.source.required)
      || value.projectionSchemaVersion !== "settlement-search-projection-v1"
      || value.spatialStageSchemaVersion !== "spatial-classification-stage-v1"
      || Object.entries(value).some(([name, item]) =>
        !["projectionSchemaVersion", "spatialStageSchemaVersion"].includes(name)
        && (typeof item !== "string" || !SHA256.test(item)))) {
    fail("search shard source identity differs from the v4 contract");
  }
}

function tokenize(value: string): readonly string[] {
  return normalizeSearchText(value).match(/[\p{L}\p{N}]+/gu) ?? [];
}

function terms(record: IndexedRecord): string {
  return [...new Set([record.displayName, ...record.searchNames, record.countryCode, record.admin1Name ?? ""]
    .flatMap(tokenize))].join(" ");
}

function validateRecords(value: unknown, shardId: SearchShardId, artifactVerified: boolean): readonly IndexedRecord[] {
  if (!Array.isArray(value)) fail("search shard records differ from the v4 contract");
  if (artifactVerified) {
    value.forEach((record, index) => {
      if (typeof record !== "object" || record === null || Array.isArray(record)
          || record.ordinal !== index + 1
          || typeof record.placeId !== "string" || !/^geonames:[1-9][0-9]*$/.test(record.placeId)
          || typeof record.displayName !== "string" || !record.displayName
          || !Array.isArray(record.searchNames) || record.searchNames.length > 1026
          || record.searchNames.some((name: unknown) => typeof name !== "string" || !name)
          || typeof record.countryCode !== "string" || !/^[A-Z]{2}$/.test(record.countryCode)
          || !(record.admin1Name === null || (typeof record.admin1Name === "string" && record.admin1Name.length > 0))
          || !(record.population === null || (Number.isSafeInteger(record.population) && record.population >= 0))
          || typeof record.featureCode !== "string" || !FEATURE_CODES.has(record.featureCode)
          || !Number.isSafeInteger(record.distanceToCoastMeters) || record.distanceToCoastMeters < 0
          || typeof record.isCoastal !== "boolean"
          || typeof record.latitude !== "number" || !Number.isFinite(record.latitude) || record.latitude < -90 || record.latitude > 90
          || typeof record.longitude !== "number" || !Number.isFinite(record.longitude) || record.longitude < -180 || record.longitude > 180
          || (shardId === "europe-coastal" && record.isCoastal !== true)) {
        fail("verified search shard record has an unsafe runtime shape");
      }
    });
    return value as IndexedRecord[];
  }
  let previous = 0n;
  let totalNamePoints = 0;
  value.forEach((record, index) => {
    if (!exactKeys(record, SCHEMA.$defs.record.required)) fail("search shard record fields differ from the v4 contract");
    const numericId = numericPlaceId(record.placeId);
    if (record.ordinal !== index + 1 || numericId <= previous
        || !strictText(record.displayName, 256)
        || !Array.isArray(record.searchNames) || record.searchNames.length > 1026
        || record.searchNames.some((name) => !strictText(name, 256))
        || new Set(record.searchNames).size !== record.searchNames.length
        || typeof record.countryCode !== "string" || !/^[A-Z]{2}$/.test(record.countryCode)
        || !strictText(record.admin1Name, 256, true)
        || !(record.population === null || (Number.isSafeInteger(record.population) && Number(record.population) >= 0))
        || typeof record.featureCode !== "string" || !FEATURE_CODES.has(record.featureCode)
        || !Number.isSafeInteger(record.distanceToCoastMeters) || Number(record.distanceToCoastMeters) < 0
        || typeof record.isCoastal !== "boolean"
        || typeof record.latitude !== "number" || !Number.isFinite(record.latitude) || record.latitude < -90 || record.latitude > 90
        || typeof record.longitude !== "number" || !Number.isFinite(record.longitude) || record.longitude < -180 || record.longitude > 180
        || (shardId === "europe-core" && !((record.population !== null && Number(record.population) >= 500) || ADMIN_CODES.has(record.featureCode)))
        || (shardId === "europe-coastal" && record.isCoastal !== true)) {
      fail("search shard record values or membership differ from the v4 contract");
    }
    totalNamePoints = [record.displayName, ...record.searchNames, record.admin1Name ?? ""]
      .reduce((total, item) => total + Array.from(item).length, 0);
    if (totalNamePoints > 16_384) fail("search shard record names exceed the v4 limit");
    previous = numericId;
  });
  return value as IndexedRecord[];
}

function decodeBase64(value: unknown): Uint8Array {
  if (typeof value !== "string" || !value || !/^[A-Za-z0-9+/]*={0,2}$/.test(value) || value.length % 4 !== 0) {
    return fail("search index is not canonical base64");
  }
  const binary = atob(value);
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) bytes[index] = binary.charCodeAt(index);
  return bytes;
}

async function validateEnvelope(
  value: unknown,
  records: readonly IndexedRecord[],
  shardId: SearchShardId,
  artifactVerified: boolean,
): Promise<IndexEnvelope> {
  let envelope: unknown;
  try { envelope = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(decodeBase64(value))); }
  catch { return fail("search index is not strict UTF-8 JSON"); }
  if (!exactKeys(envelope, ["formatVersion", "engine", "binding", "payload"])
      || canonicalJson(envelope.engine) !== canonicalJson(ENGINE)
      || !exactKeys(envelope.binding, ["evaluationId", "shardId", "documentCount", "documentsSha256", "optionsSha256"])
      || envelope.formatVersion !== "search-evaluation-index-v1"
      || envelope.binding.evaluationId !== "browser-search-shard-v2"
      || envelope.binding.shardId !== shardId || envelope.binding.documentCount !== records.length
      || envelope.binding.optionsSha256 !== await digest(OPTIONS_IDENTITY)
      || typeof envelope.binding.documentsSha256 !== "string" || !SHA256.test(envelope.binding.documentsSha256)
      || (!artifactVerified && envelope.binding.documentsSha256 !== await digest(JSON.stringify(records.map((record) => [
        record.ordinal, terms(record), record.placeId, record.displayName, record.searchNames,
        record.countryCode, record.admin1Name, record.population, record.featureCode,
        record.distanceToCoastMeters, record.isCoastal,
      ]))))
      || !exactKeys(envelope.payload, ["serializationVersion", "entries"])
      || envelope.payload.serializationVersion !== 1 || !Array.isArray(envelope.payload.entries)) {
    fail("search index identity or document binding differs from the v4 contract");
  }
  let previousName = "";
  for (const entry of envelope.payload.entries) {
    if (!Array.isArray(entry) || entry.length !== 2 || typeof entry[0] !== "string" || !entry[0]
        || (!artifactVerified && normalizeSearchText(entry[0]) !== entry[0])
        || (previousName && compareCodePoints(entry[0], previousName) <= 0)
        || !Array.isArray(entry[1]) || entry[1].length === 0) {
      fail("search index entries are not normalized, unique, and sorted");
    }
    let previousOrdinal = 0;
    for (const ordinal of entry[1]) {
      if (!Number.isSafeInteger(ordinal) || ordinal <= previousOrdinal || ordinal > records.length) {
        fail("search index posting differs from the record inventory");
      }
      previousOrdinal = ordinal;
    }
    previousName = entry[0];
  }
  if (!artifactVerified) {
    const postings = new Map<string, number[]>();
    for (const record of records) {
      for (const name of new Set([record.displayName, ...record.searchNames].map(normalizeSearchText))) {
        postings.set(name, [...(postings.get(name) ?? []), record.ordinal]);
      }
    }
    const expectedEntries = [...postings].sort(([left], [right]) => compareCodePoints(left, right));
    if (envelope.payload.entries.length !== expectedEntries.length) {
      fail("search index differs from its exact v4 records");
    }
    for (let index = 0; index < expectedEntries.length; index += 1) {
      const actual = envelope.payload.entries[index];
      const expected = expectedEntries[index];
      const actualOrdinals = actual[1] as readonly number[];
      if (actual[0] !== expected[0] || actualOrdinals.length !== expected[1].length
          || actualOrdinals.some((ordinal: number, ordinalIndex: number) => ordinal !== expected[1][ordinalIndex])) {
        fail("search index differs from its exact v4 records");
      }
    }
  }
  return envelope as unknown as IndexEnvelope;
}

export async function validateSearchShardDocument(
  raw: Uint8Array,
  authority: SearchShardAuthority,
  artifactVerified = false,
): Promise<ValidatedSearchShard> {
  let text: string;
  let value: unknown;
  try {
    text = new TextDecoder("utf-8", { fatal: true }).decode(raw);
    value = JSON.parse(text);
  } catch { return fail("search shard is not strict UTF-8 JSON"); }
  if (!artifactVerified && canonicalJson(value) !== text) fail("search shard JSON is not canonical");
  if (!exactKeys(value, SCHEMA.$defs.shard.required)
      || value.$schema !== SCHEMA.$id || value.schemaVersion !== "4.0.0"
      || typeof value.dataReleaseId !== "string" || !RELEASE_ID.test(value.dataReleaseId)
      || value.dataReleaseId !== authority.dataReleaseId
      || value.dataProvenanceClass !== authority.dataProvenanceClass
      || value.artifactType !== "settlement-browser-search-shard"
      || value.mediaType !== "application/vnd.searise.search-index+json"
      || value.contentEncoding !== "br" || value.formatVersion !== "settlement-browser-search-shard-v2"
      || value.placeSchema !== "https://artemsemdev.github.io/SeaRise-Europe/contracts/settlements/v3/place.schema.json"
      || value.shardId !== authority.shardId || value.catalogMembership !== authority.shardId
      || value.normalizationVersion !== "settlement-normalization-v2"
      || value.geometryStatus !== "selected-scope-approximation"
      || value.publicationEligible !== false || FALSE_CLAIMS.some((name) => value[name] !== false)
      || !exactKeys(value.engine, SCHEMA.$defs.engine.required) || canonicalJson(value.engine) !== canonicalJson(ENGINE)
      || !exactKeys(value.compression, SCHEMA.$defs.compression.required) || canonicalJson(value.compression) !== canonicalJson(COMPRESSION)
      || !exactKeys(value.runtime, SCHEMA.$defs.runtime.required) || canonicalJson(value.runtime) !== canonicalJson(RUNTIME)
      || !exactKeys(value.ranking, SCHEMA.$defs.ranking.required) || canonicalJson(value.ranking) !== canonicalJson(RANKING)
      || !exactKeys(value.merge, SCHEMA.$defs.merge.required) || canonicalJson(value.merge) !== canonicalJson(MERGE)) {
    fail("search shard format, claims, runtime, ranking, or merge differs from the authoritative v4 schema");
  }
  validateSpatial(value.spatialIdentity);
  validateSource(value.source);
  const records = validateRecords(value.records, authority.shardId, artifactVerified);
  if (!Number.isSafeInteger(value.recordCount) || Number(value.recordCount) < 0
      || Number(value.recordCount) > 5_000_000 || value.recordCount !== records.length
      || typeof value.recordsSha256 !== "string" || !SHA256.test(value.recordsSha256)
      || (!artifactVerified && value.recordsSha256 !== await digest(JSON.stringify(records)))) {
    fail("search shard record count or recordsSha256 differs from the v4 contract");
  }
  const envelope = await validateEnvelope(value.indexBase64, records, authority.shardId, artifactVerified);
  return Object.freeze({
    records,
    envelope,
    commonIdentity: canonicalJson({
      dataReleaseId: value.dataReleaseId,
      dataProvenanceClass: value.dataProvenanceClass,
      spatialIdentity: value.spatialIdentity,
      source: value.source,
      engine: value.engine,
      compression: value.compression,
      runtime: value.runtime,
      ranking: value.ranking,
      merge: value.merge,
    }),
  });
}
