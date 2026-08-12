import {
  compareRankedCandidates,
  hasQualifiedSearchContext,
  normalizeSearchText,
  searchFuzzyAllowance,
} from "../evaluation/search";
import type {
  RankedCandidateDocument,
  SearchMatchKey,
} from "../evaluation/search";
import type { CandidateDocument, SearchDocument } from "../evaluation/types";

export const BROWSER_RUNTIME_VERSION = "settlement-browser-worker-v1";
export const BROWSER_QUERY_WORK_LIMIT = 250_000;
export const BROWSER_RESULT_LIMIT = 10;
const MAX_QUERY_POINTS = 128;
const MAX_RAW_BYTES = 64 * 1024 * 1024;

export type BrowserShardId = "europe-core" | "europe-coastal";

export type BrowserShardAuthority = {
  dataReleaseId: string;
  rawByteSize: number;
  rawSha256: string;
  shardId: BrowserShardId;
};

type TrieNode = {
  children: Map<string, TrieNode>;
  maxNameLength: number;
  ordinals: number[];
  signatureHigh: number;
  signatureLow: number;
};

export type BrowserShardRuntime = {
  authority: BrowserShardAuthority;
  documents: Map<number, CandidateDocument>;
  records: Map<string, SearchDocument>;
  root: TrieNode;
};

type IndexEnvelope = {
  binding: {
    documentCount: number;
    evaluationId: string;
    shardId: string;
  };
  engine: {
    engineId: string;
    packageVersion: string;
    serializationVersion: string;
  };
  formatVersion: string;
  payload: { entries: Array<[string, number[]]>; serializationVersion: number };
};

type ShardDocument = {
  artifactType: string;
  contentEncoding: string;
  dataReleaseId: string;
  formatVersion: string;
  indexBase64: string;
  recordCount: number;
  records: Array<SearchDocument & { ordinal: number }>;
  shardId: BrowserShardId;
};

function fail(message: string): never {
  throw new Error(message);
}

function exactKeys(value: unknown, keys: readonly string[]): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    && JSON.stringify(Object.keys(value).sort()) === JSON.stringify([...keys].sort());
}

function hex(bytes: ArrayBuffer): string {
  return Array.from(new Uint8Array(bytes), (value) => value.toString(16).padStart(2, "0")).join("");
}

async function sha256(bytes: Uint8Array): Promise<string> {
  return hex(await crypto.subtle.digest("SHA-256", Uint8Array.from(bytes).buffer));
}

function decodeBase64(value: string): Uint8Array {
  if (!value || !/^[A-Za-z0-9+/]*={0,2}$/.test(value) || value.length % 4 !== 0) {
    return fail("search index is not canonical base64");
  }
  const binary = atob(value);
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) bytes[index] = binary.charCodeAt(index);
  return bytes;
}

function emptyNode(): TrieNode {
  return {
    children: new Map(),
    maxNameLength: 0,
    ordinals: [],
    signatureHigh: 0,
    signatureLow: 0,
  };
}

function signatureBucket(point: string): number {
  return Math.imul(point.codePointAt(0)!, 0x9e3779b1) >>> 26;
}

function hydrateIndex(
  envelope: IndexEnvelope,
  documents: readonly CandidateDocument[],
  shardId: BrowserShardId,
): TrieNode {
  if (envelope.formatVersion !== "search-evaluation-index-v1"
      || !exactKeys(envelope.engine, ["engineId", "packageVersion", "serializationVersion"])
      || envelope.engine.engineId !== "searise-codepoint-trie"
      || envelope.engine.packageVersion !== "1.0.0"
      || envelope.engine.serializationVersion !== "codepoint-trie-json-v1"
      || envelope.binding.documentCount !== documents.length
      || envelope.binding.evaluationId !== "browser-search-shard-v2"
      || envelope.binding.shardId !== shardId
      || envelope.payload.serializationVersion !== 1
      || !Array.isArray(envelope.payload.entries)) {
    return fail("search index envelope differs from the browser runtime contract");
  }
  const root = emptyNode();
  const path: TrieNode[] = [];
  let previous = "";
  for (const entry of envelope.payload.entries) {
    if (!Array.isArray(entry) || entry.length !== 2 || typeof entry[0] !== "string"
        || !entry[0] || entry[0] <= previous || !Array.isArray(entry[1])) {
      return fail("search index entries are not unique and sorted");
    }
    previous = entry[0];
    let previousOrdinal = 0;
    for (const ordinal of entry[1]) {
      if (!Number.isSafeInteger(ordinal) || ordinal <= previousOrdinal
          || ordinal > documents.length) {
        return fail("search index posting differs from the record inventory");
      }
      previousOrdinal = ordinal;
    }
    const points = Array.from(entry[0]);
    let signatureHigh = 0;
    let signatureLow = 0;
    for (const point of points) {
      const bucket = signatureBucket(point);
      if (bucket < 32) signatureLow |= 1 << bucket;
      else signatureHigh |= 1 << (bucket - 32);
    }
    path.length = 0;
    let node = root;
    path.push(node);
    for (const point of points) {
      let child = node.children.get(point);
      if (!child) {
        child = emptyNode();
        node.children.set(point, child);
      }
      node = child;
      path.push(node);
    }
    node.ordinals = entry[1];
    for (const item of path) {
      item.signatureHigh |= signatureHigh;
      item.signatureLow |= signatureLow;
      item.maxNameLength = Math.max(item.maxNameLength, points.length);
    }
  }
  return root;
}

export async function decodeBrowserShard(
  raw: Uint8Array,
  authority: BrowserShardAuthority,
): Promise<BrowserShardRuntime> {
  if (raw.length !== authority.rawByteSize || raw.length > MAX_RAW_BYTES
      || !/^[a-f0-9]{64}$/.test(authority.rawSha256)
      || await sha256(raw) !== authority.rawSha256) {
    return fail("browser shard bytes differ from the release authority");
  }
  let value: ShardDocument;
  try {
    value = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(raw));
  } catch {
    return fail("browser shard is not strict UTF-8 JSON");
  }
  if (value.artifactType !== "settlement-browser-search-shard"
      || value.contentEncoding !== "br"
      || value.formatVersion !== "settlement-browser-search-shard-v2"
      || value.dataReleaseId !== authority.dataReleaseId
      || value.shardId !== authority.shardId
      || !Array.isArray(value.records)
      || value.recordCount !== value.records.length
      || value.recordCount < 1 || value.recordCount > 250_000) {
    return fail("browser shard metadata differs from the release authority");
  }
  const documents: CandidateDocument[] = value.records.map((item, index) => {
    if (item.ordinal !== index + 1) fail("browser shard record ordinals differ");
    const { ordinal, ...record } = item;
    return { ordinal, record, terms: "" };
  });
  let envelope: IndexEnvelope;
  try {
    envelope = JSON.parse(
      new TextDecoder("utf-8", { fatal: true }).decode(decodeBase64(value.indexBase64)),
    );
  } catch {
    return fail("browser search index is not strict UTF-8 JSON");
  }
  return {
    authority,
    documents: new Map(documents.map((document) => [document.ordinal, document])),
    records: new Map(documents.map(({ record }) => [record.placeId, record])),
    root: hydrateIndex(envelope, documents, authority.shardId),
  };
}

type Work = { value: number };
type BestCandidates = {
  byOrdinal: Map<number, RankedCandidateDocument>;
  limit: number;
  values: RankedCandidateDocument[];
};

function spend(work: Work, amount = 1): void {
  work.value += amount;
  if (work.value > BROWSER_QUERY_WORK_LIMIT) fail("search query exceeds its work limit");
}

function insertCandidate(best: BestCandidates, candidate: RankedCandidateDocument): void {
  let low = 0;
  let high = best.values.length;
  while (low < high) {
    const middle = Math.floor((low + high) / 2);
    if (compareRankedCandidates(candidate, best.values[middle]) < 0) high = middle;
    else low = middle + 1;
  }
  best.values.splice(low, 0, candidate);
  best.byOrdinal.set(candidate.document.ordinal, candidate);
}

function offerCandidate(
  best: BestCandidates,
  document: CandidateDocument,
  match: SearchMatchKey,
): void {
  const candidate = { document, match };
  const existing = best.byOrdinal.get(document.ordinal);
  if (existing) {
    if (compareRankedCandidates(candidate, existing) >= 0) return;
    best.values.splice(best.values.indexOf(existing), 1);
    best.byOrdinal.delete(document.ordinal);
  } else if (best.values.length >= best.limit) {
    const worst = best.values.at(-1)!;
    if (compareRankedCandidates(candidate, worst) >= 0) return;
    best.values.pop();
    best.byOrdinal.delete(worst.document.ordinal);
  }
  insertCandidate(best, candidate);
}

function addOrdinals(
  runtime: BrowserShardRuntime,
  ordinals: readonly number[],
  best: BestCandidates,
  match: SearchMatchKey | ((document: CandidateDocument) => SearchMatchKey),
  work: Work,
  predicate?: (document: CandidateDocument) => boolean,
): void {
  for (const ordinal of ordinals) {
    spend(work);
    const document = runtime.documents.get(ordinal);
    if (!document) return fail("search index posting has no record");
    if (!predicate || predicate(document)) {
      offerCandidate(best, document, typeof match === "function" ? match(document) : match);
    }
  }
}

function addPrefix(
  runtime: BrowserShardRuntime,
  node: TrieNode,
  best: BestCandidates,
  work: Work,
): void {
  addOrdinals(runtime, node.ordinals, best, [2, 0], work);
  const children = node.children.values();
  for (let item = children.next(); !item.done; item = children.next()) {
    spend(work);
    addPrefix(runtime, item.value, best, work);
  }
}

type DistanceRow = { first: number; values: number[] };
function rowValue(row: DistanceRow, column: number, fallback: number): number {
  const offset = column - row.first;
  return offset >= 0 && offset < row.values.length ? row.values[offset] : fallback;
}

function outOfFuzzyReach(
  node: TrieNode,
  queryBuckets: readonly number[],
  maximum: number,
): boolean {
  if (node.maxNameLength + maximum < queryBuckets.length) return true;
  let missing = 0;
  for (const bucket of queryBuckets) {
    const present = bucket < 32
      ? (node.signatureLow >>> bucket) & 1
      : (node.signatureHigh >>> (bucket - 32)) & 1;
    if (!present && (missing += 1) > maximum) return true;
  }
  return false;
}

function fuzzyWalk(
  runtime: BrowserShardRuntime,
  node: TrieNode,
  query: readonly string[],
  buckets: readonly number[],
  maximum: number,
  depth: number,
  previous: DistanceRow,
  best: BestCandidates,
  work: Work,
): void {
  const children = node.children.entries();
  for (let item = children.next(); !item.done; item = children.next()) {
    const [point, child] = item.value;
    spend(work);
    if (outOfFuzzyReach(child, buckets, maximum)) continue;
    const nextDepth = depth + 1;
    const first = Math.max(0, nextDepth - maximum);
    const last = Math.min(query.length, nextDepth + maximum);
    const current: DistanceRow = { first, values: [] };
    let minimum = maximum + 1;
    for (let column = first; column <= last; column += 1) {
      spend(work);
      const distance = column === 0 ? nextDepth : Math.min(
        rowValue(previous, column, maximum + 1) + 1,
        rowValue(current, column - 1, maximum + 1) + 1,
        rowValue(previous, column - 1, maximum + 1)
          + (point === query[column - 1] ? 0 : 1),
      );
      current.values.push(distance);
      minimum = Math.min(minimum, distance);
    }
    if (minimum > maximum) continue;
    const distance = rowValue(current, query.length, maximum + 1);
    if (distance <= maximum) addOrdinals(runtime, child.ordinals, best, [3, distance], work);
    fuzzyWalk(runtime, child, query, buckets, maximum, nextDepth, current, best, work);
  }
}

export function searchBrowserRuntime(
  runtime: BrowserShardRuntime,
  rawQuery: string,
  limit = BROWSER_RESULT_LIMIT,
): SearchDocument[] {
  if (!Number.isSafeInteger(limit) || limit < 1 || limit > BROWSER_RESULT_LIMIT) {
    return fail("browser search result limit is invalid");
  }
  const query = normalizeSearchText(rawQuery);
  const points = Array.from(query);
  if (!points.length) return [];
  if (points.length > MAX_QUERY_POINTS) return fail("browser search query exceeds its limit");
  const best: BestCandidates = { byOrdinal: new Map(), limit, values: [] };
  const work = { value: 0 };
  let node: TrieNode | undefined = runtime.root;
  let prefix = "";
  const qualified: Array<{ name: string; node: TrieNode }> = [];
  for (let index = 0; index < points.length && node; index += 1) {
    spend(work);
    node = node.children.get(points[index]);
    if (!node) break;
    prefix += points[index];
    if (node.ordinals.length && points[index + 1] === " ") {
      qualified.push({ name: prefix, node });
    }
  }
  if (node) {
    addOrdinals(runtime, node.ordinals, best, ({ record }) => [
      normalizeSearchText(record.displayName) === query ? 0 : 1, 0,
    ], work);
  }
  for (const item of qualified) {
    addOrdinals(runtime, item.node.ordinals, best, ({ record }) => [
      normalizeSearchText(record.displayName) === item.name ? 0 : 1, 0,
    ], work, ({ record }) => hasQualifiedSearchContext(query, item.name, record));
  }
  if (node) {
    const children = node.children.values();
    for (let item = children.next(); !item.done; item = children.next()) {
      spend(work);
      addPrefix(runtime, item.value, best, work);
    }
  }
  const maximum = searchFuzzyAllowance(query);
  if (maximum && best.values.length < limit) {
    const first = Math.max(0, -maximum);
    const last = Math.min(points.length, maximum);
    fuzzyWalk(runtime, runtime.root, points, points.map(signatureBucket), maximum, 0, {
      first,
      values: Array.from({ length: last - first + 1 }, (_, index) => first + index),
    }, best, work);
  }
  return best.values.map(({ document }) => runtime.records.get(document.record.placeId)!);
}

export function mergeBrowserResults(
  core: readonly SearchDocument[],
  coastal: readonly SearchDocument[],
  limit = BROWSER_RESULT_LIMIT,
): SearchDocument[] {
  const result: SearchDocument[] = [];
  const seen = new Set<string>();
  for (const values of [core, coastal]) {
    for (const value of values) {
      if (!seen.has(value.placeId) && result.length < limit) result.push(value);
      seen.add(value.placeId);
    }
  }
  return result;
}
