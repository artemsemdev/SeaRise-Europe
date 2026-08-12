import { createHash, randomBytes } from "node:crypto";
import {
  closeSync,
  constants as fsConstants,
  fstatSync,
  fsyncSync,
  linkSync,
  lstatSync,
  openSync,
  readSync,
  unlinkSync,
  writeSync,
} from "node:fs";
import type { Stats } from "node:fs";
import { join } from "node:path";
import {
  brotliCompressSync,
  brotliDecompressSync,
  constants as zlibConstants,
} from "node:zlib";
import { miniSearchAdapter } from "../evaluation/adapters";
import {
  normalizeSearchText,
  prepareCandidateDocuments,
  rankDocuments,
} from "../evaluation/search";
import type { CandidateDocument, SearchDocument } from "../evaluation/types";

export const SHARD_FORMAT_VERSION = "settlement-browser-search-shard-v1";
export const SHARD_FILENAMES = {
  "europe-core": "europe-core.minisearch.json.br",
  "europe-coastal": "europe-coastal.minisearch.json.br",
} as const;
export const SHARD_RECEIPT_FILENAME = "settlement-browser-search-shards.receipt.json";

const PROJECTION_SCHEMA_VERSION = "settlement-search-projection-v1";
const PROJECTION_HEADER = "settlement-search-projection-header";
const PROJECTION_DOCUMENT = "settlement-search-projection-document";
const PROJECTION_FOOTER = "settlement-search-projection-footer";
const SHARD_SET_FORMAT_VERSION = "settlement-browser-search-shard-set-v1";
const SHARD_ORDER = ["europe-core", "europe-coastal"] as const;
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
  engine: typeof miniSearchAdapter.descriptor;
  compression: { algorithm: "brotli"; mode: "text"; quality: 11 };
  ranking: {
    normalizationVersion: "unicode-nfkd-lowercase-v1";
    orderingVersion: "canonical-alternate-prefix-fuzzy-population-admin-coast-id-v1";
  };
  merge: {
    order: readonly ["europe-core", "europe-coastal"];
    deduplicateBy: "placeId";
    resultOrder: "core-results-then-unseen-coastal-results";
  };
};

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

function exactKeys(value: unknown, keys: readonly string[]): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    && Object.keys(value).sort().join("\0") === [...keys].sort().join("\0");
}

function positiveLimit(value: number, label: string): void {
  if (!Number.isSafeInteger(value) || value < 1) fail(`${label} must be a positive safe integer`);
}

function checkedLimits(limits: Readonly<ShardLimits>): void {
  for (const [name, value] of Object.entries(limits)) positiveLimit(value, name);
}

function sameNode(left: Stats, right: Stats): boolean {
  return left.dev === right.dev && left.ino === right.ino && left.mode === right.mode;
}

function sameFile(left: Stats, right: Stats): boolean {
  return sameNode(left, right) && left.nlink === right.nlink && left.size === right.size
    && left.mtimeMs === right.mtimeMs && left.ctimeMs === right.ctimeMs;
}

function openBounded(path: string, maximum: number, label: string): { descriptor: number; size: number; before: Stats } {
  const before = lstatSync(path);
  if (!before.isFile() || before.isSymbolicLink()) fail(`${label} must be a regular non-symlink file`);
  if (before.size > maximum) fail(`${label} exceeds its ${maximum}-byte limit`);
  let descriptor = -1;
  try {
    descriptor = openSync(path, fsConstants.O_RDONLY | fsConstants.O_NOFOLLOW);
    const opened = fstatSync(descriptor);
    if (!opened.isFile() || !sameFile(before, opened)) fail(`${label} changed while opened`);
    return { descriptor, size: opened.size, before };
  } catch (error) {
    if (descriptor >= 0) closeSync(descriptor);
    if (error instanceof BrowserShardError) throw error;
    return fail(`${label} could not be opened safely`);
  }
}

function verifyAndClose(path: string, descriptor: number, before: Stats, label: string): void {
  try {
    if (readSync(descriptor, Buffer.alloc(1), 0, 1, before.size)) fail(`${label} grew while read`);
    const after = fstatSync(descriptor);
    const linked = lstatSync(path);
    if (!sameFile(before, after) || !sameFile(after, linked)) fail(`${label} changed while read`);
  } finally {
    closeSync(descriptor);
  }
}

function parseJsonLine(raw: Buffer, label: string): Record<string, unknown> {
  if (!raw.length || raw.includes(0x0d)) fail(`${label} is not canonical NDJSON`);
  try {
    const value: unknown = JSON.parse(UTF8.decode(raw));
    if (typeof value !== "object" || value === null || Array.isArray(value)) fail(`${label} is not an object`);
    return value as Record<string, unknown>;
  } catch (error) {
    if (error instanceof BrowserShardError) throw error;
    return fail(`${label} is not strict UTF-8 JSON`);
  }
}

function assertSha(value: unknown, label: string): asserts value is string {
  if (typeof value !== "string" || !/^[0-9a-f]{64}$/.test(value)) fail(`${label} is not a SHA-256`);
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
      || typeof value.geometryStatus !== "string"
      || FALSE_CLAIMS.some((claim) => value[claim] !== false)
      || !exactKeys(value.source, [
        "spatialCandidateIdentity", "spatialDatabaseSha256", "spatialReceiptSha256",
        "spatialStageSchemaVersion",
      ])) fail("search projection header contract differs");
  assertSha(value.source.spatialCandidateIdentity, "spatial candidate identity");
  assertSha(value.source.spatialDatabaseSha256, "spatial database identity");
  assertSha(value.source.spatialReceiptSha256, "spatial receipt identity");
  if (typeof value.source.spatialStageSchemaVersion !== "string") fail("spatial stage version differs");
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
      || !exactKeys(value.canonicalName, ["language", "script", "value"])
      || !exactKeys(value.location, ["latitude", "longitude"])
      || !exactKeys(value.spatialClassification, [
        "catalogMembership", "distanceToShorelineMeters", "isCoastal",
      ])) fail("search projection document fields differ");
  const id = numericPlaceId(value.placeId);
  if (id <= previous) fail("search projection placeIds are not strictly ordered");
  const names = value.alternateNames;
  if (!Array.isArray(names) || names.some((item) => !exactKeys(item, ["language", "script", "value"])
      || typeof item.value !== "string" || typeof item.language !== "string" || typeof item.script !== "string")) {
    fail("search projection alternate names differ");
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
  if (typeof value.canonicalName.value !== "string" || typeof value.sourceSpelling !== "string"
      || typeof value.asciiName !== "string" || typeof value.countryCode !== "string"
      || !(value.admin1Name === null || typeof value.admin1Name === "string")
      || typeof featureCode !== "string" || !Array.isArray(value.lineage) || !value.lineage.length
      || !(population === null || (Number.isSafeInteger(population) && (population as number) >= 0))
      || typeof latitude !== "number" || latitude < -90 || latitude > 90
      || typeof longitude !== "number" || longitude < -180 || longitude > 180
      || !Number.isSafeInteger(distance) || (distance as number) < 0) {
    fail("search projection document values differ");
  }
  const searchNames = Array.from(new Set([
    value.sourceSpelling,
    value.asciiName,
    ...names.map((item) => item.value),
  ] as string[]));
  [value.canonicalName.value, ...searchNames, value.countryCode, value.admin1Name ?? ""]
    .forEach((item) => normalizeSearchText(String(item)));
  return {
    id,
    memberships: memberships as ShardId[],
    record: {
      placeId: value.placeId as string,
      displayName: value.canonicalName.value,
      searchNames,
      countryCode: value.countryCode,
      admin1Name: value.admin1Name as string | null,
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
  const index = miniSearchAdapter.serialize(miniSearchAdapter.build(prepared, identity));
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
    engine: miniSearchAdapter.descriptor,
    compression: { algorithm: "brotli", mode: "text", quality: 11 },
    ranking: {
      normalizationVersion: "unicode-nfkd-lowercase-v1",
      orderingVersion: "canonical-alternate-prefix-fuzzy-population-admin-coast-id-v1",
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

function writeAll(descriptor: number, bytes: Buffer): void {
  let offset = 0;
  while (offset < bytes.length) {
    const written = writeSync(descriptor, bytes, offset, bytes.length - offset, offset);
    if (written < 1) fail("search shard write made no progress");
    offset += written;
  }
}

function removeOwned(path: string, identity: Stats): boolean {
  try {
    const current = lstatSync(path);
    if (!sameNode(current, identity)) return false;
    unlinkSync(path);
    return true;
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return true;
    throw error;
  }
}

function verifyOwned(path: string, identity: Stats, bytes: Buffer, label: string): void {
  if (!sameNode(lstatSync(path), identity)) fail(`${label} inode was replaced`);
  const actual = readBounded(path, bytes.length, label);
  if (!actual.equals(bytes) || !sameNode(lstatSync(path), identity)) {
    fail(`${label} bytes or inode changed`);
  }
}

function publishSet(outputDirectory: string, bytes: Record<ShardId, Buffer>): void {
  const directory = lstatSync(outputDirectory);
  if (!directory.isDirectory() || directory.isSymbolicLink()) fail("output directory is unsafe");
  const directoryDescriptor = openSync(
    outputDirectory, fsConstants.O_RDONLY | fsConstants.O_DIRECTORY | fsConstants.O_NOFOLLOW
  );
  const heldDirectory = fstatSync(directoryDescriptor);
  const verifyDirectory = (): void => {
    if (!sameNode(directory, heldDirectory) || !sameNode(heldDirectory, fstatSync(directoryDescriptor))
        || !sameNode(heldDirectory, lstatSync(outputDirectory))) {
      fail("output directory identity changed during publication");
    }
  };
  const artifacts = [
    ...SHARD_ORDER.map((shard) => ({ name: SHARD_FILENAMES[shard], bytes: bytes[shard] })),
    { name: SHARD_RECEIPT_FILENAME, bytes: receiptBytes(bytes) },
  ].map((artifact) => ({
    ...artifact,
    final: join(outputDirectory, artifact.name),
    identity: undefined as Stats | undefined,
    temporary: join(outputDirectory, `.search-shard-${randomBytes(16).toString("hex")}`),
  }));
  const promoted: typeof artifacts = [];
  try {
    verifyDirectory();
    for (const artifact of artifacts) {
      try {
        lstatSync(artifact.final);
        fail("search shard output exists; overwrite is refused");
      } catch (error) {
        if (error instanceof BrowserShardError) throw error;
        if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error;
      }
      const descriptor = openSync(
        artifact.temporary, fsConstants.O_WRONLY | fsConstants.O_CREAT | fsConstants.O_EXCL
          | fsConstants.O_NOFOLLOW, 0o600
      );
      try {
        artifact.identity = fstatSync(descriptor);
        writeAll(descriptor, artifact.bytes);
        fsyncSync(descriptor);
      } finally {
        closeSync(descriptor);
      }
      verifyOwned(artifact.temporary, artifact.identity, artifact.bytes, "staged search shard");
      verifyDirectory();
    }
    for (const artifact of artifacts) {
      verifyOwned(artifact.temporary, artifact.identity!, artifact.bytes, "staged search shard");
      verifyDirectory();
      linkSync(artifact.temporary, artifact.final);
      promoted.push(artifact);
      verifyOwned(artifact.temporary, artifact.identity!, artifact.bytes, "staged search shard");
      verifyOwned(artifact.final, artifact.identity!, artifact.bytes, "published search shard");
      verifyDirectory();
    }
    if (!artifacts.every((artifact) => removeOwned(artifact.temporary, artifact.identity!))) {
      fail("foreign staged search shard replacement was preserved");
    }
    fsyncSync(directoryDescriptor);
    artifacts.forEach((artifact) =>
      verifyOwned(artifact.final, artifact.identity!, artifact.bytes, "published search shard")
    );
    verifyDirectory();
  } catch (error) {
    [...promoted].reverse().forEach((artifact) => removeOwned(artifact.final, artifact.identity!));
    artifacts.forEach((artifact) => {
      if (artifact.identity) removeOwned(artifact.temporary, artifact.identity);
    });
    try { fsyncSync(directoryDescriptor); } catch { /* retain the primary failure */ }
    if (error instanceof BrowserShardError) throw error;
    fail(`search shard publication failed: ${(error as Error).message}`);
  } finally {
    closeSync(directoryDescriptor);
  }
}

function readBounded(path: string, maximum: number, label: string): Buffer {
  const { descriptor, size, before } = openBounded(path, maximum, label);
  const bytes = Buffer.allocUnsafe(size);
  try {
    let offset = 0;
    while (offset < size) {
      const length = readSync(descriptor, bytes, offset, size - offset, offset);
      if (!length) fail(`${label} ended before its declared size`);
      offset += length;
    }
    return bytes;
  } finally {
    verifyAndClose(path, descriptor, before, label);
  }
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
    "records", "recordsSha256", "shardId", "source",
  ];
  if (!exactKeys(value, keys) || value.formatVersion !== SHARD_FORMAT_VERSION
      || value.shardId !== expectedShardId || value.publicationEligible !== false
      || FALSE_CLAIMS.some((claim) => value[claim] !== false)
      || canonical(value.engine) !== canonical(miniSearchAdapter.descriptor)
      || canonical(value.compression) !== canonical({ algorithm: "brotli", mode: "text", quality: 11 })
      || canonical(value.ranking) !== canonical({
        normalizationVersion: "unicode-nfkd-lowercase-v1",
        orderingVersion: "canonical-alternate-prefix-fuzzy-population-admin-coast-id-v1",
      })
      || canonical(value.merge) !== canonical({
        order: SHARD_ORDER, deduplicateBy: "placeId",
        resultOrder: "core-results-then-unseen-coastal-results",
      }) || !exactKeys(value.source, [
        "projectionDeterministicIdentity", "projectionDocumentsSha256", "projectionSchemaVersion",
        "projectionSha256", "spatialCandidateIdentity", "spatialDatabaseSha256",
        "spatialReceiptSha256", "spatialStageSchemaVersion",
      ]) || value.source.projectionSchemaVersion !== PROJECTION_SCHEMA_VERSION
      || typeof value.source.spatialStageSchemaVersion !== "string"
      || Object.entries(value.source).some(([name, item]) =>
        name !== "projectionSchemaVersion" && name !== "spatialStageSchemaVersion"
          && (typeof item !== "string" || !/^[0-9a-f]{64}$/.test(item))
      ) || typeof value.dataProvenanceClass !== "string" || typeof value.geometryStatus !== "string"
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
    if (record.ordinal !== index + 1 || typeof record.displayName !== "string"
        || !Array.isArray(record.searchNames)
        || record.searchNames.some((name) => typeof name !== "string")
        || typeof record.countryCode !== "string"
        || !(record.admin1Name === null || typeof record.admin1Name === "string")
        || !(record.population === null
          || (Number.isSafeInteger(record.population) && record.population >= 0))
        || typeof record.featureCode !== "string"
        || !Number.isSafeInteger(record.distanceToCoastMeters)
        || record.distanceToCoastMeters < 0 || typeof record.isCoastal !== "boolean"
        || typeof record.latitude !== "number" || record.latitude < -90 || record.latitude > 90
        || numericId <= previous || typeof record.longitude !== "number" || record.longitude < -180
        || record.longitude > 180) fail("search shard record values differ");
    previous = numericId;
  });
  if (sha256(canonical(shard.records)) !== shard.recordsSha256) fail("search shard record hash differs");
  const documents = candidateDocuments(shard);
  if (documents.some(({ record }) => expectedShardId === "europe-core"
    ? !((record.population !== null && record.population >= 500) || ADMIN_FEATURE_CODES.has(record.featureCode))
    : !record.isCoastal)) fail("search shard contains a record outside its membership");
  if (Buffer.from(shard.indexBase64, "base64").toString("base64") !== shard.indexBase64) {
    fail("search shard index encoding differs");
  }
  miniSearchAdapter.deserialize(
    Buffer.from(shard.indexBase64, "base64"), documents,
    { evaluationId: "browser-search-shard-v1", shardId: expectedShardId },
  );
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
  const expected = buildBytes(projectionPath, limits);
  const expectedReceipt = receiptBytes(expected);
  const actualReceipt = readBounded(
    join(outputDirectory, SHARD_RECEIPT_FILENAME), expectedReceipt.length,
    "search shard completion receipt",
  );
  if (!actualReceipt.equals(expectedReceipt)) fail("search shard set is incomplete or its receipt differs");
  return Object.fromEntries(SHARD_ORDER.map((shard) => {
    const actual = readBounded(
      outputPath(outputDirectory, shard), limits.maxCompressedShardBytes, `${shard} search shard`
    );
    if (!actual.equals(expected[shard])) fail(`${shard} search shard differs from its exact projection`);
    const decoded = decodeBrowserShard(actual, shard, limits);
    return [shard, { byteSize: actual.length, sha256: sha256(actual), recordCount: decoded.recordCount }];
  })) as Record<ShardId, { byteSize: number; sha256: string; recordCount: number }>;
}

export function searchBrowserShard(shard: BrowserShard, query: string): BrowserSearchRecord[] {
  const documents = candidateDocuments(shard);
  const records = new Map(shard.records.map((record) => [record.placeId, record]));
  const restored = miniSearchAdapter.deserialize(
    Buffer.from(shard.indexBase64, "base64"), documents,
    { evaluationId: "browser-search-shard-v1", shardId: shard.shardId },
  );
  const byOrdinal = new Map(documents.map((document) => [document.ordinal, document]));
  const matches = miniSearchAdapter.search(restored, query, documents.length)
    .map((ordinal) => byOrdinal.get(ordinal)).filter((item): item is CandidateDocument => item !== undefined);
  return rankDocuments(query, matches).map(({ record }) => records.get(record.placeId)!);
}

export function mergeCoreFirst<T extends { placeId: string }>(
  core: readonly T[], coastal: readonly T[], limit: number
): T[] {
  positiveLimit(limit, "merge result limit");
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
