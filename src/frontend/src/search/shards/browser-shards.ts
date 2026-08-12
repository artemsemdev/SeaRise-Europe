import { createHash } from "node:crypto";
import { spawnSync } from "node:child_process";
import {
  closeSync,
  constants as fsConstants,
  fstatSync,
  lstatSync,
  openSync,
  readSync,
} from "node:fs";
import type { BigIntStats } from "node:fs";
import { platform } from "node:os";
import { join } from "node:path";
import {
  brotliCompressSync,
  brotliDecompressSync,
  constants as zlibConstants,
} from "node:zlib";
import {
  BOUNDED_SEARCH_WORK_LIMIT,
  MAX_NORMALIZED_SEARCH_CODE_POINTS,
  boundedTrieAdapter,
} from "../evaluation/adapters";
import {
  normalizeSearchText,
  prepareCandidateDocuments,
  rankDocuments,
} from "../evaluation/search";
import type { CandidateDocument, SearchDocument } from "../evaluation/types";

export const SHARD_FORMAT_VERSION = "settlement-browser-search-shard-v1";
export const SHARD_FILENAMES = {
  "europe-core": "europe-core.codepoint-trie.json.br",
  "europe-coastal": "europe-coastal.codepoint-trie.json.br",
} as const;
export const SHARD_RECEIPT_FILENAME = "settlement-browser-search-shards.receipt.json";

const PROJECTION_SCHEMA_VERSION = "settlement-search-projection-v1";
const PROJECTION_HEADER = "settlement-search-projection-header";
const PROJECTION_DOCUMENT = "settlement-search-projection-document";
const PROJECTION_FOOTER = "settlement-search-projection-footer";
const SHARD_SET_FORMAT_VERSION = "settlement-browser-search-shard-set-v1";
const SHARD_ORDER = ["europe-core", "europe-coastal"] as const;
const FS_HELPER = join(process.cwd(), "scripts", "browser-shard-fs.py");
const MAX_QUERY_CODE_POINTS = 256;
const MAX_SEARCH_CANDIDATES = 128;
const MAX_SEARCH_RESULTS = 100;
const MAX_NAME_CODE_POINTS = 256;
const MAX_ALTERNATE_NAMES = 1_024;
const MAX_RECORD_NAME_CODE_POINTS = 16_384;
const RUNTIME = {
  brotli: "1.2.0", icu: "78.2", node: "20.20.1", unicode: "17.0", zlib: "1.2.12",
} as const;
const FALSE_CLAIMS = [
  "canonicalGeometryClaim",
  "hazardExtentClaim",
  "ownerApprovalClaim",
  "productionClaim",
  "publicationClaim",
  "scientificApprovalClaim",
  "signingClaim",
] as const;
const ADMIN_FEATURE_CODES = new Set(["PPLC", "PPLA", "PPLA2", "PPLA3", "PPLA4", "PPLA5"]);
const INCLUDED_FEATURE_CODES = new Set([
  "PPL", "PPLA", "PPLA2", "PPLA3", "PPLA4", "PPLA5", "PPLC", "PPLF", "PPLG", "PPLL", "PPLR",
]);
const DATA_PROVENANCE_CLASSES = new Set(["real-source", "synthetic-fixture"]);
const SCRIPT_CODES = new Set([
  "Arab", "Armn", "Beng", "Cyrl", "Deva", "Geor", "Grek", "Gujr", "Guru", "Hang", "Hani",
  "Hebr", "Hira", "Jpan", "Kana", "Knda", "Kore", "Laoo", "Latn", "Mlym", "Mymr", "Sinh",
  "Taml", "Telu", "Thai", "Tibt",
]);
const ALL_COUNTRIES_LINEAGE = {
  asset_id: "all-countries", source_file: "allCountries.txt", source_release: "2026-08-10",
  source_sha256: "4217bcadfce0d86d7f39244259dbbb96e5d1a610faedc3b4761bb96dcc492bf8",
} as const;
const ADMIN1_LINEAGE = {
  asset_id: "admin1-codes-ascii", source_file: "admin1CodesASCII.txt", source_release: "2026-08-10",
  source_sha256: "34784457b76b988a669dff7c3e4b104e4902c0875643cff019281ac79dfa2992",
} as const;
const ALTERNATE_LINEAGE = {
  asset_id: "alternate-names-v2", source_file: "alternateNamesV2.txt", source_release: "2026-08-10",
  source_sha256: "63453d348543a363bbd33a461c41e769de59d293c3fd62ca408eb3e2b0b47612",
} as const;
const UTF8 = new TextDecoder("utf-8", { fatal: true });

export interface ShardLimits {
  maxProjectionBytes: number;
  maxLineBytes: number;
  maxRecords: number;
  maxRawShardBytes: number;
  maxCompressedShardBytes: number;
}

export const DEFAULT_SHARD_LIMITS: Readonly<ShardLimits> = {
  maxProjectionBytes: 1024 * 1024 * 1024,
  maxLineBytes: 1024 * 1024,
  maxRecords: 5_000_000,
  maxRawShardBytes: 768 * 1024 * 1024,
  maxCompressedShardBytes: 256 * 1024 * 1024,
};

type ShardId = keyof typeof SHARD_FILENAMES;
type ProjectionHeader = Record<string, unknown> & {
  source: Record<string, string>;
  dataProvenanceClass: string;
  geometryStatus: string;
};
type ProjectionFooter = Record<string, unknown> & {
  deterministicIdentity: string;
  documentsSha256: string;
  recordCount: number;
};
export type BrowserSearchRecord = SearchDocument & { latitude: number; longitude: number };
type ParsedProjection = {
  header: ProjectionHeader;
  footer: ProjectionFooter;
  projectionSha256: string;
  shards: Record<ShardId, BrowserSearchRecord[]>;
};

export type BrowserShard = {
  formatVersion: typeof SHARD_FORMAT_VERSION;
  shardId: ShardId;
  recordCount: number;
  recordsSha256: string;
  records: Array<BrowserSearchRecord & { ordinal: number }>;
  indexBase64: string;
  source: Record<string, string>;
  dataProvenanceClass: string;
  geometryStatus: string;
  publicationEligible: false;
  canonicalGeometryClaim: false;
  hazardExtentClaim: false;
  ownerApprovalClaim: false;
  productionClaim: false;
  publicationClaim: false;
  scientificApprovalClaim: false;
  signingClaim: false;
  engine: typeof boundedTrieAdapter.descriptor;
  compression: { algorithm: "brotli"; mode: "text"; quality: 11 };
  runtime: typeof RUNTIME;
  ranking: {
    candidateLimit: 128;
    fuzzyDistance: "unicode-codepoint-levenshtein-max-2-v1";
    normalizationVersion: "unicode-nfkd-lowercase-v1";
    orderingVersion: "canonical-alternate-prefix-fuzzy-population-admin-coast-id-v1";
    queryWorkLimit: 250000;
    resultLimit: 100;
  };
  merge: {
    order: readonly ["europe-core", "europe-coastal"];
    deduplicateBy: "placeId";
    resultOrder: "core-results-then-unseen-coastal-results";
  };
};

type BrowserShardRuntime = {
  byOrdinal: Map<number, CandidateDocument>;
  index: unknown;
  records: Map<string, BrowserSearchRecord>;
};
const VALIDATED_RUNTIMES = new WeakMap<BrowserShard, BrowserShardRuntime>();

export class BrowserShardError extends Error {}

function fail(message: string): never {
  throw new BrowserShardError(message);
}

function sha256(bytes: Uint8Array | string): string {
  return createHash("sha256").update(bytes).digest("hex");
}

function canonical(value: unknown): string {
  if (value === null || typeof value === "boolean" || typeof value === "string") {
    return JSON.stringify(value);
  }
  if (typeof value === "number") {
    if (!Number.isFinite(value)) fail("search shard contains a non-finite number");
    return JSON.stringify(value);
  }
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  if (typeof value === "object") {
    const entries = Object.entries(value as Record<string, unknown>).sort(([left], [right]) =>
      left < right ? -1 : left > right ? 1 : 0
    );
    return `{${entries.map(([key, item]) => `${JSON.stringify(key)}:${canonical(item)}`).join(",")}}`;
  }
  return fail("search shard contains a non-JSON value");
}

function pythonFloat(value: number): string {
  if (!Number.isFinite(value) || Object.is(value, -0)) fail("search projection has an invalid float");
  if (value !== 0 && Math.abs(value) < 0.0001) {
    const [coefficient, exponent] = value.toExponential().split("e");
    const numericExponent = Number(exponent);
    return `${coefficient}e${numericExponent < 0 ? "-" : "+"}${String(Math.abs(numericExponent)).padStart(2, "0")}`;
  }
  return Number.isInteger(value) ? `${value}.0` : String(value);
}

function projectionCanonical(value: unknown, path: readonly string[] = []): string {
  if (typeof value === "number" && path.at(-2) === "location"
      && ["latitude", "longitude"].includes(path.at(-1)!)) return pythonFloat(value);
  if (value === null || typeof value === "boolean" || typeof value === "string"
      || typeof value === "number") return canonical(value);
  if (Array.isArray(value)) return `[${value.map((item) => projectionCanonical(item, path)).join(",")}]`;
  if (typeof value === "object") {
    const entries = Object.entries(value as Record<string, unknown>).sort(([left], [right]) =>
      left < right ? -1 : left > right ? 1 : 0
    );
    return `{${entries.map(([key, item]) =>
      `${JSON.stringify(key)}:${projectionCanonical(item, [...path, key])}`).join(",")}}`;
  }
  return fail("search projection contains a non-JSON value");
}

function exactKeys(value: unknown, keys: readonly string[]): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    && Object.keys(value).sort().join("\0") === [...keys].sort().join("\0");
}

function positiveLimit(value: number, label: string): void {
  if (!Number.isSafeInteger(value) || value < 1) fail(`${label} must be a positive safe integer`);
}

function checkedLimits(limits: Readonly<ShardLimits>): void {
  const names = Object.keys(DEFAULT_SHARD_LIMITS) as Array<keyof ShardLimits>;
  if (!exactKeys(limits, names)) fail("search shard limit fields differ");
  for (const name of names) {
    const value = limits[name];
    positiveLimit(value, name);
    if (value > DEFAULT_SHARD_LIMITS[name]) fail(`${name} exceeds its hard cap`);
  }
  if (limits.maxLineBytes > limits.maxProjectionBytes
      || limits.maxCompressedShardBytes > limits.maxRawShardBytes) {
    fail("search shard limits are not relationally bounded");
  }
  if (!(["darwin", "linux"] as const).includes(platform() as "darwin" | "linux")) {
    fail("browser shard tooling requires macOS or Linux");
  }
  for (const [name, version] of Object.entries(RUNTIME)) {
    if (process.versions[name as keyof NodeJS.ProcessVersions] !== version) {
      fail(`browser shard runtime ${name} differs from its exact binding`);
    }
  }
}

function sameFile(left: BigIntStats, right: BigIntStats): boolean {
  return left.dev === right.dev && left.ino === right.ino && left.mode === right.mode
    && left.nlink === right.nlink && left.size === right.size
    && left.mtimeNs === right.mtimeNs && left.ctimeNs === right.ctimeNs;
}

function openBounded(
  path: string, maximum: number, label: string,
): { descriptor: number; size: number; before: BigIntStats } {
  const before = lstatSync(path, { bigint: true });
  if (!before.isFile() || before.isSymbolicLink()) fail(`${label} must be a regular non-symlink file`);
  if (before.size > BigInt(maximum)) fail(`${label} exceeds its ${maximum}-byte limit`);
  let descriptor = -1;
  try {
    descriptor = openSync(path, fsConstants.O_RDONLY | fsConstants.O_NOFOLLOW);
    const opened = fstatSync(descriptor, { bigint: true });
    if (!opened.isFile() || !sameFile(before, opened)) fail(`${label} changed while opened`);
    return { descriptor, size: Number(opened.size), before };
  } catch (error) {
    if (descriptor >= 0) closeSync(descriptor);
    if (error instanceof BrowserShardError) throw error;
    return fail(`${label} could not be opened safely`);
  }
}

function verifyAndClose(path: string, descriptor: number, before: BigIntStats, label: string): void {
  try {
    if (readSync(descriptor, Buffer.alloc(1), 0, 1, Number(before.size))) fail(`${label} grew while read`);
    const after = fstatSync(descriptor, { bigint: true });
    const linked = lstatSync(path, { bigint: true });
    if (!sameFile(before, after) || !sameFile(after, linked)) fail(`${label} changed while read`);
  } finally {
    closeSync(descriptor);
  }
}

function parseJsonLine(raw: Buffer, label: string): Record<string, unknown> {
  if (!raw.length || raw.includes(0x0d)) fail(`${label} is not canonical NDJSON`);
  try {
    const text = UTF8.decode(raw);
    const value: unknown = JSON.parse(text);
    if (typeof value !== "object" || value === null || Array.isArray(value)) fail(`${label} is not an object`);
    if (projectionCanonical(value) !== text) fail(`${label} is not canonical duplicate-free JSON`);
    return value as Record<string, unknown>;
  } catch (error) {
    if (error instanceof BrowserShardError) throw error;
    return fail(`${label} is not strict UTF-8 JSON`);
  }
}

function assertSha(value: unknown, label: string): asserts value is string {
  if (typeof value !== "string" || !/^[0-9a-f]{64}$/.test(value)) fail(`${label} is not a SHA-256`);
}

function nullableText(value: unknown): value is string | null {
  return value === null || typeof value === "string";
}

function boundedText(value: unknown, label: string, nullable = false): value is string | null {
  if (nullable && value === null) return true;
  if (typeof value !== "string" || !value || Array.from(value).length > MAX_NAME_CODE_POINTS
      || value !== value.normalize("NFC")) fail(`${label} is not bounded canonical text`);
  if (Array.from(normalizeSearchText(value)).length > MAX_NORMALIZED_SEARCH_CODE_POINTS) {
    fail(`${label} exceeds its normalized search bound`);
  }
  return true;
}

function boundedSourceText(value: unknown, label: string): value is string;
function boundedSourceText(value: unknown, label: string, nullable: true): value is string | null;
function boundedSourceText(value: unknown, label: string, nullable = false): value is string | null {
  if (nullable && value === null) return true;
  if (typeof value !== "string" || !value || Array.from(value).length > MAX_NAME_CODE_POINTS) {
    fail(`${label} is not bounded source text`);
  }
  if (Array.from(normalizeSearchText(value)).length > MAX_NORMALIZED_SEARCH_CODE_POINTS) {
    fail(`${label} exceeds its normalized search bound`);
  }
  return true;
}

function calendarDate(value: unknown): value is string {
  if (typeof value !== "string" || !/^(?!0000)\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  const parsed = new Date(`${value}T00:00:00Z`);
  return !Number.isNaN(parsed.valueOf()) && parsed.toISOString().slice(0, 10) === value;
}

function nameMetadata(value: unknown, canonicalName: boolean): value is Record<string, unknown> {
  if (!exactKeys(value, ["language", "script", "value"])) return false;
  boundedText(value.value, "search projection name");
  if (canonicalName ? value.language !== null
    : !(value.language === null || (typeof value.language === "string" && /^[a-z]{2,3}$/.test(value.language)))) {
    return false;
  }
  return value.script === null || (typeof value.script === "string" && SCRIPT_CODES.has(value.script));
}

function exactLineage(item: Record<string, unknown>, expected: Record<string, string>): boolean {
  return Object.entries(expected).every(([name, value]) => item[name] === value);
}

function headerFrom(raw: Buffer): ProjectionHeader {
  const value = parseJsonLine(raw, "search projection header");
  const keys = [
    "canonicalGeometryClaim", "dataProvenanceClass", "geometryStatus", "hazardExtentClaim",
    "kind", "normalizationVersion", "ownerApprovalClaim", "productionClaim",
    "publicationClaim", "publicationEligible", "schemaVersion", "scientificApprovalClaim",
    "signingClaim", "source",
  ];
  if (!exactKeys(value, keys) || value.kind !== PROJECTION_HEADER
      || value.schemaVersion !== PROJECTION_SCHEMA_VERSION
      || value.normalizationVersion !== "settlement-normalization-v2"
      || value.publicationEligible !== false
      || typeof value.dataProvenanceClass !== "string"
      || !DATA_PROVENANCE_CLASSES.has(value.dataProvenanceClass)
      || value.geometryStatus !== "selected-scope-approximation"
      || FALSE_CLAIMS.some((claim) => value[claim] !== false)
      || !exactKeys(value.source, [
        "spatialCandidateIdentity", "spatialDatabaseSha256", "spatialReceiptSha256",
        "spatialStageSchemaVersion",
      ])) fail("search projection header contract differs");
  assertSha(value.source.spatialCandidateIdentity, "spatial candidate identity");
  assertSha(value.source.spatialDatabaseSha256, "spatial database identity");
  assertSha(value.source.spatialReceiptSha256, "spatial receipt identity");
  if (value.source.spatialStageSchemaVersion !== "spatial-classification-stage-v1") {
    fail("spatial stage version differs");
  }
  return value as ProjectionHeader;
}

function numericPlaceId(value: unknown): bigint {
  if (typeof value !== "string" || !/^geonames:[1-9][0-9]*$/.test(value)) {
    return fail("search projection placeId is invalid");
  }
  return BigInt(value.slice("geonames:".length));
}

function projectionDocument(raw: Buffer, previous: bigint): { id: bigint; memberships: ShardId[]; record: BrowserSearchRecord } {
  const value = parseJsonLine(raw, "search projection document");
  const keys = [
    "admin1Code", "admin1Name", "alternateNames", "asciiName", "canonicalName", "countryCode",
    "featureCode", "kind", "lineage", "location", "placeId", "population", "sourceSpelling",
    "sourceUpdatedAt", "spatialClassification",
  ];
  if (!exactKeys(value, keys) || value.kind !== PROJECTION_DOCUMENT
      || !nameMetadata(value.canonicalName, true)
      || !exactKeys(value.location, ["latitude", "longitude"])
      || !exactKeys(value.spatialClassification, [
        "catalogMembership", "distanceToShorelineMeters", "isCoastal",
      ])) fail("search projection document fields differ");
  const id = numericPlaceId(value.placeId);
  if (id <= previous) fail("search projection placeIds are not strictly ordered");
  const names = value.alternateNames;
  if (!Array.isArray(names) || names.length > MAX_ALTERNATE_NAMES
      || names.some((item) => !nameMetadata(item, false))) {
    fail("search projection alternate names differ");
  }
  const alternateValues = names.map((item) => item.value as string);
  if (new Set(alternateValues).size !== alternateValues.length) {
    fail("search projection alternate names are not unique");
  }
  const memberships = value.spatialClassification.catalogMembership;
  if (!Array.isArray(memberships)
      || ![[], ["europe-core"], ["europe-coastal"], [...SHARD_ORDER]].some(
        (allowed) => JSON.stringify(allowed) === JSON.stringify(memberships)
      )) fail("search projection memberships differ");
  const population = value.population;
  const featureCode = value.featureCode;
  const expectedCore = (Number.isSafeInteger(population) && (population as number) >= 500)
    || (typeof featureCode === "string" && ADMIN_FEATURE_CODES.has(featureCode));
  if (memberships.includes("europe-core") !== expectedCore
      || memberships.includes("europe-coastal") !== value.spatialClassification.isCoastal) {
    fail("search projection membership policy differs");
  }
  const latitude = value.location.latitude;
  const longitude = value.location.longitude;
  const distance = value.spatialClassification.distanceToShorelineMeters;
  const lineageKeys = [
    "asset_id", "source_file", "source_line", "source_record_id", "source_release", "source_sha256",
  ];
  const lineage = value.lineage;
  const firstLineage = Array.isArray(lineage) ? lineage[0] : undefined;
  const hasAdminLineage = Array.isArray(lineage) && lineage.length > 1
    && exactKeys(lineage[1], lineageKeys) && exactLineage(lineage[1], ADMIN1_LINEAGE);
  const alternateLineage = Array.isArray(lineage) ? lineage.slice(hasAdminLineage ? 2 : 1) : [];
  const lineageIdentities = Array.isArray(lineage)
    ? lineage.map((item) => canonical(item)) : [];
  if (!boundedSourceText(value.sourceSpelling, "search projection source spelling")
      || value.canonicalName.value !== value.sourceSpelling.normalize("NFC")
      || !boundedSourceText(value.asciiName, "search projection ASCII name")
      || typeof value.countryCode !== "string" || !/^[A-Z]{2}$/.test(value.countryCode)
      || !nullableText(value.admin1Code)
      || (typeof value.admin1Code === "string"
        && (!value.admin1Code || !/^[A-Za-z0-9][A-Za-z0-9._-]*$/.test(value.admin1Code)))
      || !boundedSourceText(value.admin1Name, "search projection admin1 name", true)
      || (value.admin1Name !== null && (value.admin1Code === null || !hasAdminLineage))
      || typeof featureCode !== "string" || !INCLUDED_FEATURE_CODES.has(featureCode)
      || !calendarDate(value.sourceUpdatedAt)
      || !Array.isArray(lineage) || !lineage.length
      || lineage.some((item) => !exactKeys(item, lineageKeys)
        || typeof item.asset_id !== "string" || typeof item.source_file !== "string"
        || typeof item.source_release !== "string" || typeof item.source_sha256 !== "string"
        || !/^[0-9a-f]{64}$/.test(item.source_sha256)
        || !Number.isSafeInteger(item.source_line) || (item.source_line as number) < 1
        || !Number.isSafeInteger(item.source_record_id) || (item.source_record_id as number) < 1)
      || !exactKeys(firstLineage, lineageKeys) || !exactLineage(firstLineage, ALL_COUNTRIES_LINEAGE)
      || BigInt(firstLineage.source_record_id as number) !== id
      || (value.admin1Name === null && hasAdminLineage)
      || alternateLineage.length !== names.length
      || alternateLineage.some((item) => !exactKeys(item, lineageKeys)
        || !exactLineage(item, ALTERNATE_LINEAGE))
      || new Set(lineageIdentities).size !== lineageIdentities.length
      || !(population === null || (Number.isSafeInteger(population) && (population as number) >= 0))
      || typeof latitude !== "number" || latitude < -90 || latitude > 90
      || typeof longitude !== "number" || longitude < -180 || longitude > 180
      || !Number.isSafeInteger(distance) || (distance as number) < 0) {
    fail("search projection document values differ");
  }
  const namePoints = ([(value.canonicalName.value as string), value.sourceSpelling as string,
    value.asciiName as string, ...alternateValues, (value.admin1Name ?? "") as string])
    .reduce<number>((total, item) => total + Array.from(item).length, 0);
  if (namePoints > MAX_RECORD_NAME_CODE_POINTS) fail("search projection names exceed their record limit");
  const searchNames = Array.from(new Set([
    value.sourceSpelling.normalize("NFC"),
    value.asciiName.normalize("NFC"),
    ...names.map((item) => item.value),
  ] as string[]));
  [value.canonicalName.value, ...searchNames, value.countryCode, value.admin1Name ?? ""]
    .forEach((item) => normalizeSearchText(String(item)));
  return {
    id,
    memberships: memberships as ShardId[],
    record: {
      placeId: value.placeId as string,
      displayName: value.canonicalName.value as string,
      searchNames,
      countryCode: value.countryCode,
      admin1Name: value.admin1Name === null ? null : value.admin1Name.normalize("NFC"),
      population: population as number | null,
      featureCode,
      distanceToCoastMeters: distance as number,
      isCoastal: value.spatialClassification.isCoastal as boolean,
      latitude,
      longitude,
    },
  };
}

function footerFrom(raw: Buffer, header: ProjectionHeader, count: number, documentsSha256: string): ProjectionFooter {
  const value = parseJsonLine(raw, "search projection footer");
  if (!exactKeys(value, ["deterministicIdentity", "documentsSha256", "kind", "recordCount"])
      || value.kind !== PROJECTION_FOOTER || value.recordCount !== count
      || value.documentsSha256 !== documentsSha256) fail("search projection footer differs");
  assertSha(value.deterministicIdentity, "search projection identity");
  const identity = sha256(`${canonical({ header, recordCount: count, documentsSha256 })}\n`);
  if (value.deterministicIdentity !== identity) fail("search projection footer identity differs");
  return value as ProjectionFooter;
}

function parseProjection(path: string, limits: Readonly<ShardLimits>): ParsedProjection {
  checkedLimits(limits);
  const { descriptor, size, before } = openBounded(
    path, limits.maxProjectionBytes, "search projection"
  );
  const projectionDigest = createHash("sha256");
  const documentDigest = createHash("sha256");
  const shards: Record<ShardId, BrowserSearchRecord[]> = { "europe-core": [], "europe-coastal": [] };
  let buffer = Buffer.alloc(0);
  let header: ProjectionHeader | undefined;
  let pending: Buffer | undefined;
  let previous = BigInt(0);
  let count = 0;
  const consume = (line: Buffer): void => {
    if (!header) {
      header = headerFrom(line);
      return;
    }
    if (pending) {
      const parsed = projectionDocument(pending, previous);
      previous = parsed.id;
      parsed.memberships.forEach((shard) => shards[shard].push(parsed.record));
      documentDigest.update(pending).update("\n");
      count += 1;
      if (count > limits.maxRecords) fail("search projection exceeds its record limit");
    }
    pending = line;
  };
  try {
    const chunk = Buffer.allocUnsafe(64 * 1024);
    let offset = 0;
    while (offset < size) {
      const length = readSync(descriptor, chunk, 0, Math.min(chunk.length, size - offset), offset);
      if (!length) fail("search projection ended before its declared size");
      const bytes = chunk.subarray(0, length);
      projectionDigest.update(bytes);
      offset += length;
      buffer = Buffer.concat([buffer, bytes]);
      if (buffer.length > limits.maxLineBytes && buffer.indexOf(0x0a) < 0) {
        fail("search projection contains an oversized line");
      }
      let newline = buffer.indexOf(0x0a);
      while (newline >= 0) {
        if (newline > limits.maxLineBytes) fail("search projection contains an oversized line");
        consume(Buffer.from(buffer.subarray(0, newline)));
        buffer = buffer.subarray(newline + 1);
        newline = buffer.indexOf(0x0a);
      }
    }
    if (buffer.length) fail("search projection must end with a newline");
    if (!header || !pending) fail("search projection is incomplete");
    const footer = footerFrom(pending, header, count, documentDigest.digest("hex"));
    return { header, footer, projectionSha256: projectionDigest.digest("hex"), shards };
  } finally {
    verifyAndClose(path, descriptor, before, "search projection");
  }
}

function sourceBinding(projection: ParsedProjection): Record<string, string> {
  return {
    projectionDeterministicIdentity: projection.footer.deterministicIdentity,
    projectionDocumentsSha256: projection.footer.documentsSha256,
    projectionSchemaVersion: PROJECTION_SCHEMA_VERSION,
    projectionSha256: projection.projectionSha256,
    spatialCandidateIdentity: projection.header.source.spatialCandidateIdentity,
    spatialDatabaseSha256: projection.header.source.spatialDatabaseSha256,
    spatialReceiptSha256: projection.header.source.spatialReceiptSha256,
    spatialStageSchemaVersion: projection.header.source.spatialStageSchemaVersion,
  };
}

function shardRaw(projection: ParsedProjection, shardId: ShardId, limits: Readonly<ShardLimits>): Buffer {
  const prepared = prepareCandidateDocuments(projection.shards[shardId]);
  const sourceRecords = new Map(
    projection.shards[shardId].map((record) => [record.placeId, record])
  );
  const records = prepared.map(({ ordinal, record }) => ({
    ordinal,
    ...sourceRecords.get(record.placeId)!,
  }));
  const identity = { evaluationId: "browser-search-shard-v1", shardId };
  const index = boundedTrieAdapter.serialize(boundedTrieAdapter.build(prepared, identity));
  const value: BrowserShard = {
    formatVersion: SHARD_FORMAT_VERSION,
    shardId,
    recordCount: records.length,
    recordsSha256: sha256(canonical(records)),
    records,
    indexBase64: Buffer.from(index).toString("base64"),
    source: sourceBinding(projection),
    dataProvenanceClass: projection.header.dataProvenanceClass,
    geometryStatus: projection.header.geometryStatus,
    publicationEligible: false,
    canonicalGeometryClaim: false,
    hazardExtentClaim: false,
    ownerApprovalClaim: false,
    productionClaim: false,
    publicationClaim: false,
    scientificApprovalClaim: false,
    signingClaim: false,
    engine: boundedTrieAdapter.descriptor,
    compression: { algorithm: "brotli", mode: "text", quality: 11 },
    runtime: RUNTIME,
    ranking: {
      candidateLimit: MAX_SEARCH_CANDIDATES,
      fuzzyDistance: "unicode-codepoint-levenshtein-max-2-v1",
      normalizationVersion: "unicode-nfkd-lowercase-v1",
      orderingVersion: "canonical-alternate-prefix-fuzzy-population-admin-coast-id-v1",
      queryWorkLimit: BOUNDED_SEARCH_WORK_LIMIT,
      resultLimit: MAX_SEARCH_RESULTS,
    },
    merge: {
      order: SHARD_ORDER,
      deduplicateBy: "placeId",
      resultOrder: "core-results-then-unseen-coastal-results",
    },
  };
  const raw = Buffer.from(canonical(value));
  if (raw.length > limits.maxRawShardBytes) fail(`${shardId} raw shard exceeds its byte limit`);
  return raw;
}

function compress(raw: Buffer, shardId: ShardId, limits: Readonly<ShardLimits>): Buffer {
  const compressed = brotliCompressSync(raw, {
    params: {
      [zlibConstants.BROTLI_PARAM_MODE]: zlibConstants.BROTLI_MODE_TEXT,
      [zlibConstants.BROTLI_PARAM_QUALITY]: 11,
      [zlibConstants.BROTLI_PARAM_SIZE_HINT]: raw.length,
    },
  });
  if (compressed.length > limits.maxCompressedShardBytes) {
    fail(`${shardId} compressed shard exceeds its byte limit`);
  }
  return compressed;
}

function buildBytes(projectionPath: string, limits: Readonly<ShardLimits>): Record<ShardId, Buffer> {
  const projection = parseProjection(projectionPath, limits);
  return {
    "europe-core": compress(shardRaw(projection, "europe-core", limits), "europe-core", limits),
    "europe-coastal": compress(
      shardRaw(projection, "europe-coastal", limits), "europe-coastal", limits
    ),
  };
}

function outputPath(outputDirectory: string, shardId: ShardId): string {
  return join(outputDirectory, SHARD_FILENAMES[shardId]);
}

function receiptBytes(bytes: Record<ShardId, Buffer>): Buffer {
  return Buffer.from(canonical({
    complete: true,
    formatVersion: SHARD_SET_FORMAT_VERSION,
    shards: SHARD_ORDER.map((shardId) => ({
      byteSize: bytes[shardId].length,
      path: SHARD_FILENAMES[shardId],
      sha256: sha256(bytes[shardId]),
      shardId,
    })),
  }));
}

type FsArtifact = { name: string; bytes: Buffer; size: number; sha256: string };

function artifactSet(bytes: Record<ShardId, Buffer>): FsArtifact[] {
  return [
    ...SHARD_ORDER.map((shard) => ({ name: SHARD_FILENAMES[shard], bytes: bytes[shard] })),
    { name: SHARD_RECEIPT_FILENAME, bytes: receiptBytes(bytes) },
  ].map((item) => ({ ...item, size: item.bytes.length, sha256: sha256(item.bytes) }));
}

function filesystemHelper(
  command: "publish" | "read", outputDirectory: string, artifacts: readonly FsArtifact[],
): Buffer {
  const metadata = artifacts.map(({ name, size, sha256: digest }) => ({ name, sha256: digest, size }));
  const header = Buffer.from(`${JSON.stringify({ artifacts: metadata, command })}\n`);
  const input = command === "publish"
    ? Buffer.concat([header, ...artifacts.map(({ bytes }) => bytes)]) : header;
  const expectedOutput = command === "read" ? artifacts[0].size + artifacts[1].size : 0;
  const result = spawnSync("python3", [FS_HELPER, outputDirectory], {
    input, maxBuffer: Math.max(1024 * 1024, expectedOutput + 64 * 1024),
  });
  if (result.error || result.status !== 0) {
    fail(`browser shard filesystem helper failed: ${result.stderr.toString().trim()}`);
  }
  if (result.stdout.length !== expectedOutput) fail("browser shard filesystem handoff length differs");
  return result.stdout;
}

function publishSet(outputDirectory: string, bytes: Record<ShardId, Buffer>): void {
  filesystemHelper("publish", outputDirectory, artifactSet(bytes));
}

function candidateDocuments(shard: BrowserShard): CandidateDocument[] {
  const documents = prepareCandidateDocuments(shard.records.map(({ ordinal: _, ...record }) => record));
  if (documents.some((document, index) => document.ordinal !== shard.records[index].ordinal)) {
    fail("search shard ordinals differ");
  }
  return documents;
}

export function decodeBrowserShard(
  compressed: Buffer,
  expectedShardId: ShardId,
  limits: Readonly<ShardLimits> = DEFAULT_SHARD_LIMITS,
): BrowserShard {
  checkedLimits(limits);
  if (compressed.length > limits.maxCompressedShardBytes) fail("compressed shard exceeds its byte limit");
  let raw: Buffer;
  try {
    raw = brotliDecompressSync(compressed, { maxOutputLength: limits.maxRawShardBytes });
  } catch {
    return fail("search shard is not bounded Brotli data");
  }
  if (!compress(raw, expectedShardId, limits).equals(compressed)) {
    fail("search shard is not canonical quality-11 Brotli data");
  }
  let value: unknown;
  try {
    const text = UTF8.decode(raw);
    value = JSON.parse(text);
    if (canonical(value) !== text) fail("search shard JSON is not canonical");
  } catch (error) {
    if (error instanceof BrowserShardError) throw error;
    return fail("search shard is not strict UTF-8 JSON");
  }
  const keys = [
    ...FALSE_CLAIMS, "compression", "dataProvenanceClass", "engine", "formatVersion",
    "geometryStatus", "indexBase64", "merge", "publicationEligible", "ranking", "recordCount",
    "records", "recordsSha256", "runtime", "shardId", "source",
  ];
  if (!exactKeys(value, keys) || value.formatVersion !== SHARD_FORMAT_VERSION
      || value.shardId !== expectedShardId || value.publicationEligible !== false
      || FALSE_CLAIMS.some((claim) => value[claim] !== false)
      || canonical(value.engine) !== canonical(boundedTrieAdapter.descriptor)
      || canonical(value.compression) !== canonical({ algorithm: "brotli", mode: "text", quality: 11 })
      || canonical(value.runtime) !== canonical(RUNTIME)
      || canonical(value.ranking) !== canonical({
        candidateLimit: MAX_SEARCH_CANDIDATES,
        fuzzyDistance: "unicode-codepoint-levenshtein-max-2-v1",
        normalizationVersion: "unicode-nfkd-lowercase-v1",
        orderingVersion: "canonical-alternate-prefix-fuzzy-population-admin-coast-id-v1",
        queryWorkLimit: BOUNDED_SEARCH_WORK_LIMIT,
        resultLimit: MAX_SEARCH_RESULTS,
      })
      || canonical(value.merge) !== canonical({
        order: SHARD_ORDER, deduplicateBy: "placeId",
        resultOrder: "core-results-then-unseen-coastal-results",
      }) || !exactKeys(value.source, [
        "projectionDeterministicIdentity", "projectionDocumentsSha256", "projectionSchemaVersion",
        "projectionSha256", "spatialCandidateIdentity", "spatialDatabaseSha256",
        "spatialReceiptSha256", "spatialStageSchemaVersion",
      ]) || value.source.projectionSchemaVersion !== PROJECTION_SCHEMA_VERSION
      || value.source.spatialStageSchemaVersion !== "spatial-classification-stage-v1"
      || Object.entries(value.source).some(([name, item]) =>
        name !== "projectionSchemaVersion" && name !== "spatialStageSchemaVersion"
          && (typeof item !== "string" || !/^[0-9a-f]{64}$/.test(item))
      ) || typeof value.dataProvenanceClass !== "string"
      || !DATA_PROVENANCE_CLASSES.has(value.dataProvenanceClass)
      || value.geometryStatus !== "selected-scope-approximation"
      || !Array.isArray(value.records) || value.recordCount !== value.records.length
      || !Number.isSafeInteger(value.recordCount) || (value.recordCount as number) > limits.maxRecords) {
    fail("search shard format, engine, claims, or merge contract differs");
  }
  const shard = value as BrowserShard;
  assertSha(shard.recordsSha256, "search shard record identity");
  const recordKeys = [
    "admin1Name", "countryCode", "displayName", "distanceToCoastMeters", "featureCode",
    "isCoastal", "latitude", "longitude", "ordinal", "placeId", "population", "searchNames",
  ];
  if (shard.records.some((record) => !exactKeys(record, recordKeys))) {
    fail("search shard record fields differ");
  }
  let previous = BigInt(0);
  shard.records.forEach((record, index) => {
    const numericId = numericPlaceId(record.placeId);
    if (record.ordinal !== index + 1
        || !boundedText(record.displayName, "search shard display name")
        || !Array.isArray(record.searchNames)
        || record.searchNames.length > MAX_ALTERNATE_NAMES + 2
        || record.searchNames.some((name) => !boundedText(name, "search shard search name"))
        || new Set(record.searchNames).size !== record.searchNames.length
        || typeof record.countryCode !== "string" || !/^[A-Z]{2}$/.test(record.countryCode)
        || !boundedText(record.admin1Name, "search shard admin1 name", true)
        || !(record.population === null
          || (Number.isSafeInteger(record.population) && record.population >= 0))
        || typeof record.featureCode !== "string" || !INCLUDED_FEATURE_CODES.has(record.featureCode)
        || !Number.isSafeInteger(record.distanceToCoastMeters)
        || record.distanceToCoastMeters < 0 || typeof record.isCoastal !== "boolean"
        || typeof record.latitude !== "number" || record.latitude < -90 || record.latitude > 90
        || numericId <= previous || typeof record.longitude !== "number" || record.longitude < -180
        || record.longitude > 180) fail("search shard record values differ");
    const namePoints = [record.displayName, ...record.searchNames, record.admin1Name ?? ""]
      .reduce((total, item) => total + Array.from(item).length, 0);
    if (namePoints > MAX_RECORD_NAME_CODE_POINTS) fail("search shard names exceed their record limit");
    previous = numericId;
  });
  if (sha256(canonical(shard.records)) !== shard.recordsSha256) fail("search shard record hash differs");
  const documents = candidateDocuments(shard);
  if (documents.some(({ record }) => expectedShardId === "europe-core"
    ? !((record.population !== null && record.population >= 500) || ADMIN_FEATURE_CODES.has(record.featureCode))
    : !record.isCoastal)) fail("search shard contains a record outside its membership");
  if (typeof shard.indexBase64 !== "string"
      || Buffer.from(shard.indexBase64, "base64").toString("base64") !== shard.indexBase64) {
    fail("search shard index encoding differs");
  }
  const identity = { evaluationId: "browser-search-shard-v1", shardId: expectedShardId };
  const actualIndex = Buffer.from(shard.indexBase64, "base64");
  const expectedIndex = Buffer.from(
    boundedTrieAdapter.serialize(boundedTrieAdapter.build(documents, identity))
  );
  if (!actualIndex.equals(expectedIndex)) fail("search shard index differs from its exact records");
  const index = boundedTrieAdapter.deserialize(
    actualIndex, documents, identity,
  );
  VALIDATED_RUNTIMES.set(shard, {
    byOrdinal: new Map(documents.map((document) => [document.ordinal, document])),
    index,
    records: new Map(shard.records.map(({ ordinal: _, ...record }) => [record.placeId, record])),
  });
  return shard;
}

export function buildBrowserSearchShards(
  projectionPath: string,
  outputDirectory: string,
  limits: Readonly<ShardLimits> = DEFAULT_SHARD_LIMITS,
): Record<ShardId, { path: string; byteSize: number; sha256: string }> {
  const bytes = buildBytes(projectionPath, limits);
  publishSet(outputDirectory, bytes);
  return Object.fromEntries(SHARD_ORDER.map((shard) => [shard, {
    path: outputPath(outputDirectory, shard),
    byteSize: bytes[shard].length,
    sha256: sha256(bytes[shard]),
  }])) as Record<ShardId, { path: string; byteSize: number; sha256: string }>;
}

export function validateBrowserSearchShards(
  projectionPath: string,
  outputDirectory: string,
  limits: Readonly<ShardLimits> = DEFAULT_SHARD_LIMITS,
): Record<ShardId, { byteSize: number; sha256: string; recordCount: number }> {
  const loaded = loadBrowserSearchShards(projectionPath, outputDirectory, limits);
  return Object.fromEntries(SHARD_ORDER.map((shard) => [shard, {
    byteSize: loaded.shards[shard].bytes.length,
    sha256: sha256(loaded.shards[shard].bytes),
    recordCount: loaded.shards[shard].shard.recordCount,
  }])) as Record<ShardId, { byteSize: number; sha256: string; recordCount: number }>;
}

export type LoadedBrowserShardSet = {
  receipt: Buffer;
  shards: Record<ShardId, { bytes: Buffer; shard: BrowserShard }>;
};

export function loadBrowserSearchShards(
  projectionPath: string,
  outputDirectory: string,
  limits: Readonly<ShardLimits> = DEFAULT_SHARD_LIMITS,
): LoadedBrowserShardSet {
  const expected = buildBytes(projectionPath, limits);
  const artifacts = artifactSet(expected);
  const raw = filesystemHelper("read", outputDirectory, artifacts);
  let offset = 0;
  const shards = Object.fromEntries(SHARD_ORDER.map((shard, index) => {
    const bytes = Buffer.from(raw.subarray(offset, offset + artifacts[index].size));
    offset += bytes.length;
    if (!bytes.equals(expected[shard])) fail(`${shard} search shard differs from its exact projection`);
    return [shard, { bytes, shard: decodeBrowserShard(bytes, shard, limits) }];
  })) as LoadedBrowserShardSet["shards"];
  return { receipt: artifacts[2].bytes, shards };
}

export function searchBrowserShard(shard: BrowserShard, query: string): BrowserSearchRecord[] {
  if (Array.from(query).length > MAX_QUERY_CODE_POINTS) fail("browser search query exceeds its limit");
  const runtime = VALIDATED_RUNTIMES.get(shard);
  if (!runtime) fail("browser search shard was not validated by its decoder");
  const matches = boundedTrieAdapter.search(runtime.index, query, MAX_SEARCH_CANDIDATES)
    .map((ordinal) => runtime.byOrdinal.get(ordinal))
    .filter((item): item is CandidateDocument => item !== undefined);
  return rankDocuments(query, matches).slice(0, MAX_SEARCH_RESULTS)
    .map(({ record }) => runtime.records.get(record.placeId)!);
}

export function mergeCoreFirst<T extends { placeId: string }>(
  core: readonly T[], coastal: readonly T[], limit: number
): T[] {
  positiveLimit(limit, "merge result limit");
  if (limit > MAX_SEARCH_RESULTS || core.length > MAX_SEARCH_RESULTS
      || coastal.length > MAX_SEARCH_RESULTS) fail("browser merge exceeds its result cap");
  const result: T[] = [];
  const seen = new Set<string>();
  for (const [label, values] of [["core", core], ["coastal", coastal]] as const) {
    const within = new Set<string>();
    for (const value of values) {
      numericPlaceId(value.placeId);
      if (within.has(value.placeId)) fail(`${label} results contain a duplicate placeId`);
      within.add(value.placeId);
      if (!seen.has(value.placeId) && result.length < limit) result.push(value);
      seen.add(value.placeId);
    }
  }
  return result;
}
