import { createHash, randomBytes } from "node:crypto";
import { Buffer } from "node:buffer";
import {
  closeSync, constants as fsConstants, fchmodSync, fstatSync, fsyncSync, linkSync,
  lstatSync, openSync, readFileSync, readSync, unlinkSync, writeSync,
} from "node:fs";
import { basename, dirname, isAbsolute, resolve, sep } from "node:path";
import { TextDecoder } from "node:util";

export const STARTUP_TARGET_MILLISECONDS = 1_000;
export const QUERY_TARGET_MILLISECONDS = 50;
export const SHARD_IDS = Object.freeze(["europe-core", "europe-coastal"]);
export const RECEIPT_ARTIFACT_ID = "settlements-search-shard-set-receipt";
const RECEIPT_FORMAT = "settlement-browser-search-shard-set-v2";
const SHARD_FORMAT = "settlement-browser-search-shard-v2";
const SHA256 = /^[a-f0-9]{64}$/;
const RELEASE_ID = /^searise-europe-v[0-9]+\.[0-9]+\.[0-9]+-[0-9]{8}-[a-f0-9]{12}$/;
const MAX_QUERY_BYTES = 1024 * 1024;
const MAX_RECEIPT_BYTES = 1024 * 1024;
const MAX_SHARD_BYTES = 16 * 1024 * 1024;
const FALSE_CLAIMS = Object.freeze({
  mobileDeviceClaim: false,
  ownerApprovalClaim: false,
  productionClaim: false,
  publicationClaim: false,
  scientificApprovalClaim: false,
});
const clone = (value) => JSON.parse(JSON.stringify(value));

export class SearchPerformanceEvidenceError extends Error {}
function fail(message) { throw new SearchPerformanceEvidenceError(message); }
export const sha256 = (value) => createHash("sha256").update(value).digest("hex");

export function canonicalJson(value) {
  if (value === null || typeof value === "boolean" || typeof value === "string") return JSON.stringify(value);
  if (typeof value === "number" && Number.isFinite(value) && !Object.is(value, -0)) return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(",")}]`;
  if (value && typeof value === "object") {
    return `{${Object.entries(value).sort(([left], [right]) => left < right ? -1 : left > right ? 1 : 0)
      .map(([key, item]) => `${JSON.stringify(key)}:${canonicalJson(item)}`).join(",")}}`;
  }
  return fail("performance evidence contains a non-canonical JSON value");
}

function exactKeys(value, keys) {
  return value && typeof value === "object" && !Array.isArray(value)
    && Object.keys(value).length === keys.length && Object.keys(value).every((key) => keys.includes(key));
}

function strictJson(bytes, label, newline = true) {
  let value;
  try { value = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes)); }
  catch { return fail(`${label} is not strict UTF-8 JSON`); }
  const expected = `${canonicalJson(value)}${newline ? "\n" : ""}`;
  if (bytes.toString() !== expected) fail(`${label} is not canonical JSON`);
  return value;
}

function readRegular(path, maximum, label) {
  const before = lstatSync(path, { bigint: true });
  if (!before.isFile() || before.isSymbolicLink() || before.size < 1n || before.size > BigInt(maximum)) {
    fail(`${label} must be a bounded regular non-symlink file`);
  }
  const descriptor = openSync(path, fsConstants.O_RDONLY | fsConstants.O_NOFOLLOW);
  try {
    const opened = fstatSync(descriptor, { bigint: true });
    if (before.dev !== opened.dev || before.ino !== opened.ino || before.size !== opened.size) fail(`${label} changed while opened`);
    const bytes = Buffer.alloc(Number(opened.size)); let offset = 0;
    while (offset < bytes.length) {
      const count = readSync(descriptor, bytes, offset, bytes.length - offset, offset);
      if (count < 1) fail(`${label} ended early`); offset += count;
    }
    const after = lstatSync(path, { bigint: true });
    const retained = fstatSync(descriptor, { bigint: true });
    if (before.dev !== after.dev || before.ino !== after.ino || before.size !== after.size
        || before.dev !== retained.dev || before.ino !== retained.ino || before.size !== retained.size) fail(`${label} changed while read`);
    return bytes;
  } finally { closeSync(descriptor); }
}

function candidatePath(root, relativePath, label) {
  if (typeof relativePath !== "string" || !relativePath || isAbsolute(relativePath)) fail(`${label} path is invalid`);
  const path = resolve(root, relativePath);
  if (!path.startsWith(`${root}${sep}`)) fail(`${label} escapes the candidate root`);
  return path;
}

export function parsePerformanceQuerySet(bytes, expectedProvenance) {
  if (!Buffer.isBuffer(bytes) || bytes.length < 1 || bytes.length > MAX_QUERY_BYTES) {
    fail("performance query set exceeds its byte limit");
  }
  const value = strictJson(Buffer.from(bytes), "performance query set");
  if (!exactKeys(value, ["corpusScale", "dataProvenanceClass", "queries", "schemaVersion"])
      || value.schemaVersion !== 1 || value.dataProvenanceClass !== expectedProvenance
      || value.corpusScale !== (expectedProvenance === "synthetic-fixture" ? "synthetic-fixture" : "production-candidate")
      || !Array.isArray(value.queries) || value.queries.length < 1 || value.queries.length > 100) {
    fail("performance query set differs from the candidate provenance contract");
  }
  const identifiers = new Set();
  for (const item of value.queries) {
    if (!exactKeys(item, ["id", "query"]) || typeof item.id !== "string"
        || !/^[a-z0-9][a-z0-9-]{0,63}$/.test(item.id) || identifiers.has(item.id)
        || typeof item.query !== "string" || !item.query.trim() || Array.from(item.query).length > 256
        || Array.from(item.query).some((point) => {
          const code = point.codePointAt(0); return code <= 0x1f || (code >= 0x7f && code <= 0x9f);
        })) fail("performance query entry is invalid");
    identifiers.add(item.id);
  }
  return Object.freeze(value);
}

export function loadPerformanceInputs(candidateRoot, querySetPath) {
  const manifestPath = resolve(candidateRoot, "manifest.json");
  const manifestBytes = readRegular(manifestPath, 16 * 1024 * 1024, "candidate manifest");
  let manifest;
  try { manifest = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(manifestBytes)); }
  catch { return fail("candidate manifest is not strict UTF-8 JSON"); }
  if (!RELEASE_ID.test(manifest.dataReleaseId) || !["real-source", "synthetic-fixture"].includes(manifest.dataProvenanceClass)
      || !Array.isArray(manifest.artifacts)) fail("candidate manifest differs from the performance contract");
  const queryBytes = readRegular(querySetPath, MAX_QUERY_BYTES, "performance query set");
  const querySet = parsePerformanceQuerySet(queryBytes, manifest.dataProvenanceClass);
  const receiptArtifact = manifest.artifacts.find((item) => item?.artifactId === RECEIPT_ARTIFACT_ID);
  if (!receiptArtifact) fail("candidate manifest omits the search shard receipt");
  const receiptPath = candidatePath(candidateRoot, receiptArtifact.path, "search shard receipt");
  const receiptBytes = readRegular(receiptPath, MAX_RECEIPT_BYTES, "search shard receipt");
  if (receiptArtifact.byteSize !== receiptBytes.length || receiptArtifact.sha256 !== sha256(receiptBytes)) {
    fail("search shard receipt differs from manifest authority");
  }
  const receipt = strictJson(receiptBytes, "search shard receipt");
  if (!exactKeys(receipt, ["$schema", "complete", "dataProvenanceClass", "dataReleaseId", "formatVersion", "schemaVersion", "shards", "source", "spatialIdentity", "writeSequence"])
      || receipt.formatVersion !== RECEIPT_FORMAT || receipt.schemaVersion !== "4.0.0" || receipt.complete !== true
      || receipt.dataReleaseId !== manifest.dataReleaseId
      || receipt.dataProvenanceClass !== manifest.dataProvenanceClass
      || receipt.writeSequence !== 3 || !Array.isArray(receipt.shards) || receipt.shards.length !== SHARD_IDS.length) {
    fail("search shard receipt differs from the candidate release");
  }
  const shards = {};
  for (const shardId of SHARD_IDS) {
    const artifact = manifest.artifacts.find((item) => item?.artifactId === `settlements-${shardId}`);
    const authority = receipt.shards.find((item) => item?.shardId === shardId);
    if (!artifact || !authority) fail(`candidate omits ${shardId} authority`);
    const path = candidatePath(candidateRoot, artifact.path, `${shardId} shard`);
    const bytes = readRegular(path, MAX_SHARD_BYTES, `${shardId} shard`);
    if (artifact.byteSize !== bytes.length || artifact.sha256 !== sha256(bytes)
        || !exactKeys(authority, ["byteSize", "contentEncoding", "formatVersion", "path", "sha256", "shardId"])
        || authority.path !== basename(artifact.path) || authority.byteSize !== bytes.length
        || authority.sha256 !== artifact.sha256 || authority.contentEncoding !== "br"
        || authority.formatVersion !== SHARD_FORMAT) fail(`${shardId} differs from manifest and receipt authority`);
    shards[shardId] = Object.freeze({ artifact, path });
  }
  return Object.freeze({ manifest, manifestBytes, queryBytes, querySet, receiptBytes, shards: Object.freeze(shards) });
}

export function distribution(observations) {
  if (!Array.isArray(observations) || observations.length < 1
      || observations.some((value) => !Number.isFinite(value) || value < 0)) fail("performance observations are invalid");
  const values = observations.map((value) => Number(value.toFixed(6)));
  const sorted = [...values].sort((left, right) => left - right);
  const percentile = (fraction) => sorted[Math.ceil(sorted.length * fraction) - 1];
  return Object.freeze({
    maximumMilliseconds: sorted.at(-1),
    meanMilliseconds: Number((values.reduce((sum, value) => sum + value, 0) / values.length).toFixed(6)),
    minimumMilliseconds: sorted[0], observationsMilliseconds: values,
    p50Milliseconds: percentile(0.5), p95Milliseconds: percentile(0.95), sampleCount: values.length,
  });
}

export function finalizePerformanceReport(report) {
  const unsigned = clone(report);
  delete unsigned.deterministicIdentity;
  const value = { ...unsigned, deterministicIdentity: sha256(`${canonicalJson(unsigned)}\n`) };
  validatePerformanceReport(value);
  return Object.freeze(value);
}

export function validatePerformanceReport(report, expected = null) {
  if (!exactKeys(report, ["artifacts", "claims", "dataReleaseId", "deterministicIdentity", "gateOutcome", "measurements", "network", "profile", "provenance", "querySet", "recordedAt", "schemaVersion"])) fail("performance report envelope differs");
  const unsigned = { ...report }; delete unsigned.deterministicIdentity;
  if (!SHA256.test(report.deterministicIdentity) || report.deterministicIdentity !== sha256(`${canonicalJson(unsigned)}\n`)) fail("performance report identity differs");
  if (report.schemaVersion !== "static-search-browser-performance-v2" || !RELEASE_ID.test(report.dataReleaseId)
      || Number.isNaN(Date.parse(report.recordedAt)) || canonicalJson(report.claims) !== canonicalJson(FALSE_CLAIMS)) fail("performance report identity or nonclaims differ");
  if (!exactKeys(report.artifacts, ["manifest", "receipt", "shards"])
      || !exactKeys(report.artifacts.manifest, ["byteSize", "sha256"])
      || !exactKeys(report.artifacts.receipt, ["byteSize", "sha256"])
      || !Number.isSafeInteger(report.artifacts.manifest.byteSize) || report.artifacts.manifest.byteSize < 1
      || !Number.isSafeInteger(report.artifacts.receipt.byteSize) || report.artifacts.receipt.byteSize < 1
      || !SHA256.test(report.artifacts.manifest.sha256) || !SHA256.test(report.artifacts.receipt.sha256)
      || !Array.isArray(report.artifacts.shards) || report.artifacts.shards.length !== SHARD_IDS.length
      || SHARD_IDS.some((shardId) => {
        const item = report.artifacts.shards.find(({ artifactId }) => artifactId === `settlements-${shardId}`);
        return !item || !exactKeys(item, ["artifactId", "byteSize", "path", "sha256"])
          || !Number.isSafeInteger(item.byteSize) || item.byteSize < 1 || !SHA256.test(item.sha256)
          || typeof item.path !== "string" || basename(item.path) !== `${shardId}.codepoint-trie.json.br`;
      })
      || !exactKeys(report.querySet, ["byteSize", "queryCount", "resultCountsSha256", "sha256"])
      || !Number.isSafeInteger(report.querySet.byteSize) || report.querySet.byteSize < 1
      || !Number.isSafeInteger(report.querySet.queryCount) || report.querySet.queryCount < 1
      || !SHA256.test(report.querySet.sha256) || !SHA256.test(report.querySet.resultCountsSha256)) fail("performance report artifact binding differs");
  const initialization = distribution(report.measurements.initialization.distribution.observationsMilliseconds);
  const query = distribution(report.measurements.query.distribution.observationsMilliseconds);
  const responsiveness = distribution(report.measurements.responsiveness.distribution.observationsMilliseconds);
  const expectedInitialization = initialization.p95Milliseconds < STARTUP_TARGET_MILLISECONDS ? "pass" : "fail";
  const expectedQuery = query.p95Milliseconds < QUERY_TARGET_MILLISECONDS ? "pass" : "fail";
  if (canonicalJson(initialization) !== canonicalJson(report.measurements.initialization.distribution)
      || report.measurements.initialization.targetMilliseconds !== STARTUP_TARGET_MILLISECONDS
      || report.measurements.initialization.outcome !== expectedInitialization
      || canonicalJson(query) !== canonicalJson(report.measurements.query.distribution)
      || report.measurements.query.targetMilliseconds !== QUERY_TARGET_MILLISECONDS
      || report.measurements.query.outcome !== expectedQuery
      || canonicalJson(responsiveness) !== canonicalJson(report.measurements.responsiveness.distribution)) fail("performance report measurement derivation differs");
  const requests = report.network.requests;
  if (!Array.isArray(requests) || !Array.isArray(report.network.unexpectedRequests)
      || requests.some((item) => !exactKeys(item, ["method", "path"]) || item.method !== "GET" || typeof item.path !== "string" || item.path.includes("?"))
      || report.network.unexpectedRequests.length !== 0 || report.network.queryTransmissionOutcome !== "pass") fail("performance report network privacy gate differs");
  const expectedGate = expectedInitialization === "pass" && expectedQuery === "pass" ? "pass" : "fail";
  if (report.gateOutcome !== expectedGate) fail("performance report gate outcome differs");
  if (!exactKeys(report.provenance, ["corpusScale", "dataProvenanceClass", "scope"])
      || report.provenance.scope !== "local-read-only-candidate"
      || report.provenance.corpusScale !== (report.provenance.dataProvenanceClass === "synthetic-fixture" ? "synthetic-fixture" : "production-candidate")) fail("performance report provenance differs");
  if (expected && (report.dataReleaseId !== expected.dataReleaseId
      || report.provenance.dataProvenanceClass !== expected.dataProvenanceClass
      || canonicalJson(report.artifacts) !== canonicalJson(expected.artifacts)
      || canonicalJson({
        byteSize: report.querySet.byteSize, queryCount: report.querySet.queryCount, sha256: report.querySet.sha256,
      }) !== canonicalJson(expected.querySet))) fail("performance report input binding differs");
  return report;
}

function sameDirectory(path, expected) {
  const actual = lstatSync(path, { bigint: true });
  return actual.isDirectory() && !actual.isSymbolicLink() && actual.dev === expected.dev && actual.ino === expected.ino;
}
function safeUnlink(path, identity) {
  try {
    const item = lstatSync(path, { bigint: true });
    if (item.isFile() && item.dev === identity.dev && item.ino === identity.ino) unlinkSync(path);
  } catch (error) { if (error.code !== "ENOENT") throw error; }
}

export function publishPerformanceReport(outputPath, bytes, hooks = {}) {
  if (!isAbsolute(outputPath) || resolve(outputPath) !== outputPath || basename(outputPath) === "") fail("performance report path must be absolute and canonical");
  const directoryPath = dirname(outputPath);
  const directory = lstatSync(directoryPath, { bigint: true });
  if (!directory.isDirectory() || directory.isSymbolicLink() || directory.uid !== BigInt(process.geteuid()) || (directory.mode & 0o22n) !== 0n) fail("performance report directory must be owner-controlled");
  try { lstatSync(outputPath); fail("performance report exists; overwrite is refused"); }
  catch (error) { if (error.code !== "ENOENT") throw error; }
  const temporary = resolve(directoryPath, `.search-performance-${process.pid}-${randomBytes(12).toString("hex")}.partial`);
  let descriptor = -1; let identity = null; let promoted = false;
  const writer = hooks.write ?? writeSync;
  const sync = hooks.fsync ?? fsyncSync;
  try {
    descriptor = openSync(temporary, fsConstants.O_CREAT | fsConstants.O_EXCL | fsConstants.O_RDWR | fsConstants.O_NOFOLLOW, 0o600);
    identity = lstatSync(temporary, { bigint: true });
    let offset = 0;
    while (offset < bytes.length) {
      const count = writer(descriptor, bytes, offset, bytes.length - offset);
      if (!Number.isSafeInteger(count) || count < 1) fail("performance report write made no progress");
      offset += count;
    }
    fchmodSync(descriptor, 0o400); sync(descriptor);
    const staged = fstatSync(descriptor, { bigint: true });
    if (staged.dev !== identity.dev || staged.ino !== identity.ino || staged.size !== BigInt(bytes.length)) fail("performance report stage changed");
    hooks.afterStage?.(temporary);
    if (!sameDirectory(directoryPath, directory)) fail("performance report directory changed before promotion");
    const linkedStage = lstatSync(temporary, { bigint: true });
    if (linkedStage.dev !== identity.dev || linkedStage.ino !== identity.ino) fail("performance report stage ownership changed");
    linkSync(temporary, outputPath); promoted = true; hooks.afterPromote?.(outputPath);
    const finalIdentity = lstatSync(outputPath, { bigint: true });
    const retained = readFileSync(outputPath);
    if (finalIdentity.dev !== identity.dev || finalIdentity.ino !== identity.ino || !retained.equals(bytes)) fail("retained performance report bytes differ");
    safeUnlink(temporary, identity);
    const directoryDescriptor = openSync(directoryPath, fsConstants.O_RDONLY | fsConstants.O_DIRECTORY | fsConstants.O_NOFOLLOW);
    try { sync(directoryDescriptor); } finally { closeSync(directoryDescriptor); }
    return Object.freeze({ byteSize: bytes.length, path: outputPath, sha256: sha256(bytes) });
  } catch (error) {
    if (promoted && identity) safeUnlink(outputPath, identity);
    if (identity) safeUnlink(temporary, identity);
    try {
      const directoryDescriptor = openSync(directoryPath, fsConstants.O_RDONLY | fsConstants.O_DIRECTORY | fsConstants.O_NOFOLLOW);
      try { fsyncSync(directoryDescriptor); } finally { closeSync(directoryDescriptor); }
    } catch { /* preserve the primary publication failure */ }
    throw error;
  } finally { if (descriptor >= 0) closeSync(descriptor); }
}

export function performanceReportBytes(report) {
  validatePerformanceReport(report);
  return Buffer.from(`${canonicalJson(report)}\n`);
}
