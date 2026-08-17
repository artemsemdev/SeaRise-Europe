import { createHash } from "node:crypto";
import { Buffer } from "node:buffer";
import { spawnSync } from "node:child_process";
import {
  closeSync, constants as fsConstants, fstatSync, fsyncSync, linkSync, lstatSync,
  openSync, readSync, unlinkSync, writeSync,
} from "node:fs";
import { basename, isAbsolute, resolve } from "node:path";
import { TextDecoder } from "node:util";
import { brotliCompressSync, brotliDecompressSync, constants as zlibConstants } from "node:zlib";

export const SHARD_IDS = Object.freeze(["europe-core", "europe-coastal"]);
export const SHARD_FILES = Object.freeze({
  "europe-core": "europe-core.codepoint-trie.json.br",
  "europe-coastal": "europe-coastal.codepoint-trie.json.br",
});
export const RECEIPT_FILE = "settlement-browser-search-shards.receipt.json";

const SCHEMA = "https://artemsemdev.github.io/SeaRise-Europe/contracts/settlements/v4/search-artifact.schema.json";
const FORMAT = "settlement-browser-search-shard-v2";
const SET_FORMAT = "settlement-browser-search-shard-set-v2";
const ENGINE = Object.freeze({ engineId: "searise-codepoint-trie", packageVersion: "1.0.0", serializationVersion: "codepoint-trie-json-v1" });
const COMPRESSION = Object.freeze({ algorithm: "brotli", mode: "text", quality: 11 });
const RUNTIME = Object.freeze({ brotli: "1.1.0", icu: "78.2", node: "20.20.1", unicode: "17.0", zlib: "1.3.1-e00f703" });
const RANKING = Object.freeze({ candidateLimit: 128, fuzzyDistance: "unicode-codepoint-levenshtein-max-2-v1", normalizationVersion: "unicode-nfkd-lowercase-v1", orderingVersion: "canonical-alternate-prefix-fuzzy-population-admin-coast-id-v1", queryWorkLimit: 250000, resultLimit: 100 });
const MERGE = Object.freeze({ order: SHARD_IDS, deduplicateBy: "placeId", resultOrder: "core-results-then-unseen-coastal-results" });
const OPTIONS = "searise-codepoint-trie-1.0.0|full-name-codepoints|qualified-context|prefix|levenshtein-max-2|global-rank-cap|work=250000";
const FALSE_CLAIMS = ["canonicalGeometryClaim", "hazardExtentClaim", "ownerApprovalClaim", "productionClaim", "publicationClaim", "scientificApprovalClaim", "signingClaim"];
const FEATURES = new Set(["PPL", "PPLA", "PPLA2", "PPLA3", "PPLA4", "PPLA5", "PPLC", "PPLF", "PPLG", "PPLL", "PPLR"]);
const ADMIN = new Set(["PPLC", "PPLA", "PPLA2", "PPLA3", "PPLA4", "PPLA5"]);
const RELEASE = /^searise-europe-v[0-9]+\.[0-9]+\.[0-9]+-[0-9]{8}-[a-f0-9]{12}$/;
const SHA = /^[a-f0-9]{64}$/;
const MAX_PROJECTION_BYTES = 1024 * 1024 * 1024;
const MAX_LINE_BYTES = 1024 * 1024;
const MAX_RECORDS = 5_000_000;
const MAX_RAW_BYTES = 768 * 1024 * 1024;
const MAX_COMPRESSED_BYTES = 256 * 1024 * 1024;

export class SearchShardBuildError extends Error {}
function fail(message) { throw new SearchShardBuildError(message); }
export function assertByteAffectingRuntime(versions = process.versions) {
  for (const [name, expected] of Object.entries(RUNTIME)) {
    if (versions[name] !== expected) {
      fail(`byte-affecting Node runtime ${name} must be ${expected}; received ${versions[name] ?? "missing"}`);
    }
  }
}
export function compareCodePoints(left, right) {
  const a = Array.from(left, (point) => point.codePointAt(0));
  const b = Array.from(right, (point) => point.codePointAt(0));
  for (let index = 0; index < Math.min(a.length, b.length); index += 1) if (a[index] !== b[index]) return a[index] - b[index];
  return a.length - b.length;
}
export function canonicalJson(value) {
  if (value === null || typeof value === "boolean" || typeof value === "string") return JSON.stringify(value);
  if (typeof value === "number" && Number.isFinite(value) && !Object.is(value, -0)) return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(",")}]`;
  if (value && typeof value === "object") {
    const entries = Object.entries(value).sort(([left], [right]) => compareCodePoints(left, right));
    return `{${entries.map(([key, item]) => `${JSON.stringify(key)}:${canonicalJson(item)}`).join(",")}}`;
  }
  return fail("search shard input contains a non-canonical JSON value");
}
function digest(value) { return createHash("sha256").update(value).digest("hex"); }
function exactKeys(value, keys) {
  return value && typeof value === "object" && !Array.isArray(value)
    && Object.keys(value).length === keys.length && Object.keys(value).every((key) => keys.includes(key));
}
function strictText(value, nullable = false) {
  if (nullable && value === null) return true;
  if (typeof value !== "string" || !value || value !== value.normalize("NFC") || Array.from(value).length > 256) return false;
  normalize(value);
  return true;
}
function normalize(value) {
  for (let index = 0; index < value.length; index += 1) {
    const unit = value.charCodeAt(index);
    if (unit >= 0xd800 && unit <= 0xdbff) {
      const next = value.charCodeAt(index + 1);
      if (!(next >= 0xdc00 && next <= 0xdfff)) fail("search text contains unpaired UTF-16");
      index += 1;
    } else if (unit >= 0xdc00 && unit <= 0xdfff) fail("search text contains unpaired UTF-16");
  }
  for (const point of value) {
    const code = point.codePointAt(0);
    if (code <= 0x1f || (code >= 0x7f && code <= 0x9f)) fail("search text contains control characters");
  }
  return value.normalize("NFKD").replace(/\p{M}+/gu, "").toLowerCase().trim().replace(/\s+/g, " ");
}
function tokenize(value) { return normalize(value).match(/[\p{L}\p{N}]+/gu) ?? []; }
function terms(record) {
  return [...new Set([record.displayName, ...record.searchNames, record.countryCode, record.admin1Name ?? ""].flatMap(tokenize))].join(" ");
}

function readRegular(path, maximum, label) {
  const before = lstatSync(path, { bigint: true });
  if (!before.isFile() || before.isSymbolicLink() || before.size > BigInt(maximum)) fail(`${label} must be a bounded regular non-symlink file`);
  const descriptor = openSync(path, fsConstants.O_RDONLY | fsConstants.O_NOFOLLOW);
  try {
    const opened = fstatSync(descriptor, { bigint: true });
    if (opened.dev !== before.dev || opened.ino !== before.ino || opened.size !== before.size) fail(`${label} changed while opened`);
    const bytes = Buffer.alloc(Number(opened.size));
    let offset = 0;
    while (offset < bytes.length) {
      const count = readSync(descriptor, bytes, offset, bytes.length - offset, offset);
      if (!count) fail(`${label} ended early`);
      offset += count;
    }
    const after = fstatSync(descriptor, { bigint: true });
    const linked = lstatSync(path, { bigint: true });
    if (after.dev !== before.dev || after.ino !== before.ino || after.size !== before.size
        || linked.dev !== before.dev || linked.ino !== before.ino || linked.size !== before.size) fail(`${label} changed while read`);
    return bytes;
  } finally { closeSync(descriptor); }
}
function parseCanonicalLine(bytes, label) {
  if (!bytes.length || bytes.includes(0x0d)) fail(`${label} is not canonical NDJSON`);
  let value;
  try { value = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes)); }
  catch { return fail(`${label} is not strict UTF-8 JSON`); }
  if (!value || typeof value !== "object" || Array.isArray(value) || canonicalJson(value) !== bytes.toString()) fail(`${label} is not canonical JSON`);
  return value;
}

function parseProjection(path) {
  const bytes = readRegular(path, MAX_PROJECTION_BYTES, "search projection");
  if (!bytes.length || bytes.at(-1) !== 0x0a) fail("search projection must end with a newline");
  const rawLines = bytes.subarray(0, -1).toString("utf8").split("\n");
  if (rawLines.length < 2 || rawLines.some((line) => Buffer.byteLength(line) > MAX_LINE_BYTES)) fail("search projection is incomplete or has an oversized line");
  const lines = rawLines.map((line, index) => parseCanonicalLine(Buffer.from(line), `search projection line ${index + 1}`));
  const header = lines[0];
  const footer = lines.at(-1);
  const documents = lines.slice(1, -1);
  const headerKeys = ["canonicalGeometryClaim", "dataProvenanceClass", "geometryStatus", "hazardExtentClaim", "kind", "normalizationVersion", "ownerApprovalClaim", "productionClaim", "publicationClaim", "publicationEligible", "schemaVersion", "scientificApprovalClaim", "signingClaim", "source"];
  if (!exactKeys(header, headerKeys) || header.kind !== "settlement-search-projection-header"
      || header.schemaVersion !== "settlement-search-projection-v1" || header.normalizationVersion !== "settlement-normalization-v2"
      || !["real-source", "synthetic-fixture"].includes(header.dataProvenanceClass)
      || header.geometryStatus !== "selected-scope-approximation" || header.publicationEligible !== false
      || FALSE_CLAIMS.some((claim) => header[claim] !== false)
      || !exactKeys(header.source, ["spatialCandidateIdentity", "spatialDatabaseSha256", "spatialReceiptSha256", "spatialStageSchemaVersion"])
      || header.source.spatialStageSchemaVersion !== "spatial-classification-stage-v1"
      || [header.source.spatialCandidateIdentity, header.source.spatialDatabaseSha256, header.source.spatialReceiptSha256].some((item) => !SHA.test(item))) fail("search projection header differs from the v1 contract");
  if (documents.length > MAX_RECORDS) fail("search projection exceeds its record limit");
  let previous = 0n;
  const shards = { "europe-core": [], "europe-coastal": [] };
  for (const value of documents) {
    const keys = ["admin1Code", "admin1Name", "alternateNames", "asciiName", "canonicalName", "countryCode", "featureCode", "kind", "lineage", "location", "placeId", "population", "sourceSpelling", "sourceUpdatedAt", "spatialClassification"];
    if (!exactKeys(value, keys) || value.kind !== "settlement-search-projection-document"
        || !exactKeys(value.canonicalName, ["language", "script", "value"]) || value.canonicalName.language !== null
        || !strictText(value.canonicalName.value) || value.canonicalName.value !== value.sourceSpelling.normalize("NFC")
        || !strictText(value.asciiName) || !strictText(value.sourceSpelling)
        || !Array.isArray(value.alternateNames) || value.alternateNames.length > 1024
        || value.alternateNames.some((item) => !exactKeys(item, ["language", "script", "value"]) || !strictText(item.value))
        || !/^[A-Z]{2}$/.test(value.countryCode) || !strictText(value.admin1Name, true)
        || !FEATURES.has(value.featureCode) || !(value.population === null || (Number.isSafeInteger(value.population) && value.population >= 0))
        || !exactKeys(value.location, ["latitude", "longitude"]) || !Number.isFinite(value.location.latitude) || value.location.latitude < -90 || value.location.latitude > 90
        || !Number.isFinite(value.location.longitude) || value.location.longitude < -180 || value.location.longitude > 180
        || !exactKeys(value.spatialClassification, ["catalogMembership", "distanceToShorelineMeters", "isCoastal"])
        || !Number.isSafeInteger(value.spatialClassification.distanceToShorelineMeters) || value.spatialClassification.distanceToShorelineMeters < 0
        || typeof value.spatialClassification.isCoastal !== "boolean") fail("search projection document differs from its bounded contract");
    const idMatch = /^geonames:([1-9][0-9]*)$/.exec(value.placeId);
    if (!idMatch || BigInt(idMatch[1]) <= previous) fail("search projection place IDs are not strictly ordered");
    previous = BigInt(idMatch[1]);
    const memberships = value.spatialClassification.catalogMembership;
    if (![[], ["europe-core"], ["europe-coastal"], SHARD_IDS].some((allowed) => canonicalJson(allowed) === canonicalJson(memberships))) fail("search projection memberships differ");
    const expectedCore = (value.population !== null && value.population >= 500) || ADMIN.has(value.featureCode);
    if (memberships.includes("europe-core") !== expectedCore || memberships.includes("europe-coastal") !== value.spatialClassification.isCoastal) fail("search projection membership policy differs");
    const searchNames = [...new Set([value.sourceSpelling.normalize("NFC"), value.asciiName.normalize("NFC"), ...value.alternateNames.map(({ value: name }) => name)])];
    const record = { placeId: value.placeId, displayName: value.canonicalName.value, searchNames, countryCode: value.countryCode, admin1Name: value.admin1Name === null ? null : value.admin1Name.normalize("NFC"), population: value.population, featureCode: value.featureCode, distanceToCoastMeters: value.spatialClassification.distanceToShorelineMeters, isCoastal: value.spatialClassification.isCoastal, latitude: value.location.latitude, longitude: value.location.longitude };
    [record.displayName, ...record.searchNames, record.countryCode, record.admin1Name ?? ""].forEach(normalize);
    memberships.forEach((membership) => shards[membership].push(record));
  }
  const documentBytes = rawLines.slice(1, -1).map((line) => `${line}\n`).join("");
  const documentsSha256 = digest(documentBytes);
  if (!exactKeys(footer, ["deterministicIdentity", "documentsSha256", "kind", "recordCount"])
      || footer.kind !== "settlement-search-projection-footer" || footer.recordCount !== documents.length
      || footer.documentsSha256 !== documentsSha256 || !SHA.test(footer.deterministicIdentity)
      || footer.deterministicIdentity !== digest(`${canonicalJson({ header, recordCount: documents.length, documentsSha256 })}\n`)) fail("search projection footer differs");
  return { bytes, header, footer, shards, sha256: digest(bytes) };
}

function parseAuthority(path, projection, releaseId) {
  const bytes = readRegular(path, 1024 * 1024, "projection authority");
  let value;
  try { value = JSON.parse(new TextDecoder("utf8", { fatal: true }).decode(bytes)); } catch { return fail("projection authority is not strict JSON"); }
  const authorityKeys = ["$schema", "artifactType", "canonicalGeometryClaim", "complete", "dataProvenanceClass", "dataReleaseId", "deterministicIdentity", "formatVersion", "hazardExtentClaim", "ownerApprovalClaim", "productionClaim", "projectionByteSize", "projectionDeterministicIdentity", "projectionDocumentsSha256", "projectionSha256", "publicationClaim", "publicationEligible", "recordCount", "schemaVersion", "scientificApprovalClaim", "signingClaim", "source", "spatialIdentity", "validator"];
  if (`${canonicalJson(value)}\n` !== bytes.toString() || !exactKeys(value, authorityKeys) || value.$schema !== SCHEMA || value.schemaVersion !== "4.0.0"
      || value.formatVersion !== "settlement-search-projection-authority-v1" || value.artifactType !== "settlement-search-projection-authority"
      || value.complete !== true || value.dataReleaseId !== releaseId || value.dataProvenanceClass !== projection.header.dataProvenanceClass
      || value.projectionByteSize !== projection.bytes.length || value.projectionSha256 !== projection.sha256
      || value.projectionDeterministicIdentity !== projection.footer.deterministicIdentity
      || value.projectionDocumentsSha256 !== projection.footer.documentsSha256 || value.recordCount !== projection.footer.recordCount
      || value.publicationEligible !== false || FALSE_CLAIMS.some((claim) => value[claim] !== false)
      || value.validator?.validatorId !== "searise_pipeline.settlements.search_projection.validate_search_projection" || value.validator?.version !== "1"
      || !SHA.test(value.deterministicIdentity)) fail("projection authority differs from the validated projection");
  const unsigned = { ...value }; delete unsigned.deterministicIdentity;
  if (digest(`${canonicalJson(unsigned)}\n`) !== value.deterministicIdentity) fail("projection authority deterministic identity differs");
  const expectedSource = { projectionDeterministicIdentity: projection.footer.deterministicIdentity, projectionDocumentsSha256: projection.footer.documentsSha256, projectionSchemaVersion: "settlement-search-projection-v1", projectionSha256: projection.sha256, ...projection.header.source };
  if (canonicalJson(value.source) !== canonicalJson(expectedSource)) fail("projection authority source binding differs");
  const spatial = value.spatialIdentity;
  if (!exactKeys(spatial, ["coastalGeometry", "distanceMethodVersion", "predicate", "shorelineGeometry", "supportGeometry"])
      || spatial.predicate !== "covers" || spatial.distanceMethodVersion !== "epsg3035-planar-whole-meter-half-even-v1"
      || [spatial.supportGeometry, spatial.coastalGeometry, spatial.shorelineGeometry].some((item) => !exactKeys(item, ["artifactId", "sha256", "version"]) || !item.artifactId || !item.version || !SHA.test(item.sha256))) fail("projection authority spatial identity differs");
  return { bytes, value, source: expectedSource };
}

function verifyAuthorityReplay(authorityBytes, { projectionPath, spatialDatabasePath, spatialReceiptPath, validationWorkDirectory, dataReleaseId }) {
  const validator = resolve(import.meta.dirname, "../../../scripts/release/validate_settlement_search_projection.py");
  const pipeline = resolve(import.meta.dirname, "../../pipeline");
  const result = spawnSync("python3", [validator, "--spatial-database", spatialDatabasePath, "--spatial-receipt", spatialReceiptPath, "--projection", projectionPath, "--data-release-id", dataReleaseId, "--work-dir", validationWorkDirectory], {
    encoding: "buffer", maxBuffer: 1024 * 1024,
    env: { ...process.env, PYTHONPATH: pipeline, PYTHONDONTWRITEBYTECODE: "1" },
  });
  if (result.error || result.status !== 0) fail(`projection replay validator failed: ${result.stderr.toString().trim()}`);
  if (!result.stdout.equals(authorityBytes)) fail("projection authority differs from its exact Python replay");
}

function buildShard(records, shardId, authority, source) {
  const prepared = records.map((record, index) => ({ ordinal: index + 1, ...record }));
  const postings = new Map();
  for (const record of prepared) for (const name of new Set([record.displayName, ...record.searchNames].map(normalize))) postings.set(name, [...(postings.get(name) ?? []), record.ordinal]);
  const envelope = { formatVersion: "search-evaluation-index-v1", engine: ENGINE, binding: { evaluationId: "browser-search-shard-v2", shardId, documentCount: prepared.length, documentsSha256: digest(JSON.stringify(prepared.map((record) => [record.ordinal, terms(record), record.placeId, record.displayName, record.searchNames, record.countryCode, record.admin1Name, record.population, record.featureCode, record.distanceToCoastMeters, record.isCoastal]))), optionsSha256: digest(OPTIONS) }, payload: { serializationVersion: 1, entries: [...postings].sort(([left], [right]) => compareCodePoints(left, right)) } };
  const value = { $schema: SCHEMA, schemaVersion: "4.0.0", dataReleaseId: authority.dataReleaseId, dataProvenanceClass: authority.dataProvenanceClass, artifactType: "settlement-browser-search-shard", mediaType: "application/vnd.searise.search-index+json", contentEncoding: "br", formatVersion: FORMAT, placeSchema: "https://artemsemdev.github.io/SeaRise-Europe/contracts/settlements/v3/place.schema.json", shardId, catalogMembership: shardId, normalizationVersion: "settlement-normalization-v2", spatialIdentity: authority.spatialIdentity, geometryStatus: "selected-scope-approximation", ...Object.fromEntries(FALSE_CLAIMS.map((claim) => [claim, false])), publicationEligible: false, recordCount: prepared.length, recordsSha256: digest(canonicalJson(prepared)), records: prepared, indexBase64: Buffer.from(JSON.stringify(envelope)).toString("base64"), source, engine: ENGINE, compression: COMPRESSION, runtime: RUNTIME, ranking: RANKING, merge: MERGE };
  const raw = Buffer.from(canonicalJson(value));
  if (raw.length > MAX_RAW_BYTES) fail(`${shardId} raw shard exceeds its byte limit`);
  const compressed = brotliCompressSync(raw, { params: { [zlibConstants.BROTLI_PARAM_MODE]: zlibConstants.BROTLI_MODE_TEXT, [zlibConstants.BROTLI_PARAM_QUALITY]: 11, [zlibConstants.BROTLI_PARAM_SIZE_HINT]: raw.length } });
  if (compressed.length > MAX_COMPRESSED_BYTES) fail(`${shardId} compressed shard exceeds its byte limit`);
  return compressed;
}

export function buildSearchShardSet({ projectionPath, authorityPath, dataReleaseId }) {
  assertByteAffectingRuntime();
  if (!RELEASE.test(dataReleaseId)) fail("data release ID differs from the public contract");
  const projection = parseProjection(projectionPath);
  const { value: authority, source } = parseAuthority(authorityPath, projection, dataReleaseId);
  const shards = Object.fromEntries(SHARD_IDS.map((id) => [id, buildShard(projection.shards[id], id, authority, source)]));
  const receipt = Buffer.from(canonicalJson({ $schema: SCHEMA, schemaVersion: "4.0.0", formatVersion: SET_FORMAT, complete: true, writeSequence: 3, dataReleaseId, dataProvenanceClass: authority.dataProvenanceClass, source, spatialIdentity: authority.spatialIdentity, shards: SHARD_IDS.map((id) => ({ byteSize: shards[id].length, contentEncoding: "br", formatVersion: FORMAT, path: SHARD_FILES[id], sha256: digest(shards[id]), shardId: id })) }));
  return Object.freeze({ shards: Object.freeze(shards), receipt });
}

export function buildValidatedSearchShardSet(options) {
  assertByteAffectingRuntime();
  for (const name of ["spatialDatabasePath", "spatialReceiptPath", "validationWorkDirectory"]) if (typeof options[name] !== "string" || !options[name]) fail(`${name} is required for exact projection replay`);
  const projection = parseProjection(options.projectionPath);
  const parsed = parseAuthority(options.authorityPath, projection, options.dataReleaseId);
  verifyAuthorityReplay(parsed.bytes, options);
  return buildSearchShardSet(options);
}

function safeOutputDirectory(path) {
  if (!isAbsolute(path) || resolve(path) !== path || basename(path) !== path.split("/").at(-1) || ["", ".", ".."].includes(basename(path))) fail("output directory must be an absolute canonical path");
  const metadata = lstatSync(path, { bigint: true });
  if (!metadata.isDirectory() || metadata.isSymbolicLink() || metadata.uid !== BigInt(process.geteuid()) || (metadata.mode & 0o22n) !== 0n) fail("output directory must be an owner-controlled non-symlink directory");
  return metadata;
}
function sameDirectory(path, expected) {
  const actual = lstatSync(path, { bigint: true });
  return actual.isDirectory() && !actual.isSymbolicLink() && actual.dev === expected.dev && actual.ino === expected.ino;
}
function safeUnlink(path, identity) {
  try { const item = lstatSync(path, { bigint: true }); if (item.dev === identity.dev && item.ino === identity.ino && item.isFile()) unlinkSync(path); } catch (error) { if (error.code !== "ENOENT") throw error; }
}
export function publishSearchShardSet(outputDirectory, built, hooks = {}) {
  const directory = safeOutputDirectory(outputDirectory);
  const artifacts = [...SHARD_IDS.map((id) => [SHARD_FILES[id], built.shards[id]]), [RECEIPT_FILE, built.receipt]];
  const staged = []; const promoted = [];
  try {
    for (const [name] of artifacts) { try { lstatSync(resolve(outputDirectory, name)); fail("search shard output exists; overwrite is refused"); } catch (error) { if (error.code !== "ENOENT") throw error; } }
    for (const [name, bytes] of artifacts) {
      const temporary = resolve(outputDirectory, `.search-shard-${process.pid}-${createHash("sha256").update(name).update(String(Date.now())).digest("hex").slice(0, 16)}`);
      const descriptor = openSync(temporary, fsConstants.O_CREAT | fsConstants.O_EXCL | fsConstants.O_WRONLY | fsConstants.O_NOFOLLOW, 0o400);
      let offset = 0;
      try { while (offset < bytes.length) offset += writeSync(descriptor, bytes, offset, bytes.length - offset); fsyncSync(descriptor); }
      finally { closeSync(descriptor); }
      const identity = lstatSync(temporary, { bigint: true });
      staged.push({ temporary, final: resolve(outputDirectory, name), identity });
    }
    hooks.beforePromote?.();
    if (!sameDirectory(outputDirectory, directory)) fail("search shard output directory changed before publication");
    for (const item of staged) {
      linkSync(item.temporary, item.final);
      promoted.push(item);
      hooks.afterPromote?.(promoted.length);
    }
    const directoryDescriptor = openSync(outputDirectory, fsConstants.O_RDONLY | fsConstants.O_DIRECTORY | fsConstants.O_NOFOLLOW);
    try { fsyncSync(directoryDescriptor); } finally { closeSync(directoryDescriptor); }
    for (const item of staged) safeUnlink(item.temporary, item.identity);
  } catch (error) {
    for (const item of promoted.reverse()) safeUnlink(item.final, item.identity);
    for (const item of staged) safeUnlink(item.temporary, item.identity);
    throw error;
  }
  return artifacts.map(([name, bytes]) => ({ path: resolve(outputDirectory, name), byteSize: bytes.length, sha256: digest(bytes) }));
}

export function validatePublishedSearchShardSet(outputDirectory, expected) {
  assertByteAffectingRuntime();
  safeOutputDirectory(outputDirectory);
  const receipt = readRegular(resolve(outputDirectory, RECEIPT_FILE), 1024 * 1024, "search shard receipt");
  if (!receipt.equals(expected.receipt)) fail("published search shard receipt differs");
  for (const id of SHARD_IDS) {
    const bytes = readRegular(resolve(outputDirectory, SHARD_FILES[id]), MAX_COMPRESSED_BYTES, `${id} shard`);
    if (!bytes.equals(expected.shards[id])) fail(`${id} published bytes differ`);
    const raw = brotliDecompressSync(bytes, { maxOutputLength: MAX_RAW_BYTES });
    const parsed = JSON.parse(new TextDecoder("utf8", { fatal: true }).decode(raw));
    if (canonicalJson(parsed) !== raw.toString() || parsed.shardId !== id || parsed.runtime.node !== "20.20.1" || canonicalJson(parsed.ranking) !== canonicalJson(RANKING)) fail(`${id} shard differs from the target decoder contract`);
  }
  return { complete: true, receiptSha256: digest(receipt) };
}
