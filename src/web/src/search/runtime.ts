import {
  compareRankedResults,
  hasQualifiedContext,
  normalizeSearchText,
  searchFuzzyAllowance,
} from "./ranking";
import type {
  RankedSearchResult,
  SearchShardAuthority,
  SearchShardId,
  SettlementSearchRecord,
} from "./types";

const MAX_RAW_BYTES = 64 * 1024 * 1024;
const MAX_QUERY_POINTS = 128;
const MAX_QUERY_WORK = 250_000;
const RESULT_LIMIT = 10;

interface IndexedRecord extends SettlementSearchRecord {
  readonly ordinal: number;
}

interface IndexEnvelope {
  readonly formatVersion: "search-evaluation-index-v1";
  readonly engine: {
    readonly engineId: "searise-codepoint-trie";
    readonly packageVersion: "1.0.0";
    readonly serializationVersion: "codepoint-trie-json-v1";
  };
  readonly binding: {
    readonly documentCount: number;
    readonly evaluationId: "browser-search-shard-v2";
    readonly shardId: SearchShardId;
  };
  readonly payload: {
    readonly serializationVersion: 1;
    readonly entries: readonly (readonly [string, readonly number[]])[];
  };
}

interface ShardDocument {
  readonly artifactType: "settlement-browser-search-shard";
  readonly contentEncoding: "identity" | "br";
  readonly dataProvenanceClass: "real-source" | "synthetic-fixture";
  readonly dataReleaseId: string;
  readonly formatVersion: "settlement-browser-search-shard-v2";
  readonly indexBase64: string;
  readonly recordCount: number;
  readonly records: readonly IndexedRecord[];
  readonly shardId: SearchShardId;
}

interface TrieNode {
  readonly children: Map<string, TrieNode>;
  maxNameLength: number;
  ordinals: readonly number[];
  signatureHigh: number;
  signatureLow: number;
}

export interface SearchShardRuntime {
  readonly authority: SearchShardAuthority;
  readonly records: ReadonlyMap<number, SettlementSearchRecord>;
  readonly root: TrieNode;
}

function fail(message: string): never {
  throw new Error(message);
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
  return Uint8Array.from(binary, (point) => point.charCodeAt(0));
}

function emptyNode(): TrieNode {
  return { children: new Map(), maxNameLength: 0, ordinals: [], signatureHigh: 0, signatureLow: 0 };
}

function signatureBucket(point: string): number {
  return Math.imul(point.codePointAt(0)!, 0x9e3779b1) >>> 26;
}

function assertRecord(
  value: unknown,
  ordinal: number,
  authority: SearchShardAuthority,
): asserts value is IndexedRecord {
  if (typeof value !== "object" || value === null || Array.isArray(value)) fail("search record is not an object");
  const item = value as Record<string, unknown>;
  const identifier = authority.dataProvenanceClass === "synthetic-fixture"
    ? /^(?:synthetic|geonames):[1-9][0-9]*$/
    : /^geonames:[1-9][0-9]*$/;
  if (
    item.ordinal !== ordinal
    || typeof item.placeId !== "string" || !identifier.test(item.placeId)
    || typeof item.displayName !== "string" || !item.displayName
    || !Array.isArray(item.searchNames) || item.searchNames.some((name) => typeof name !== "string" || !name)
    || typeof item.countryCode !== "string" || !/^[A-Z]{2}$/.test(item.countryCode)
    || !(item.admin1Name === null || (typeof item.admin1Name === "string" && item.admin1Name.length > 0))
    || !(item.population === null || (Number.isSafeInteger(item.population) && Number(item.population) >= 0))
    || typeof item.featureCode !== "string"
    || !Number.isSafeInteger(item.distanceToCoastMeters) || Number(item.distanceToCoastMeters) < 0
    || typeof item.isCoastal !== "boolean"
    || typeof item.latitude !== "number" || !Number.isFinite(item.latitude) || item.latitude < -90 || item.latitude > 90
    || typeof item.longitude !== "number" || !Number.isFinite(item.longitude) || item.longitude < -180 || item.longitude > 180
  ) {
    fail("search record differs from the browser contract");
  }
  normalizeSearchText(item.displayName);
  for (const name of item.searchNames as string[]) normalizeSearchText(name);
}

function parseEnvelope(value: string, count: number, shardId: SearchShardId): IndexEnvelope {
  let envelope: IndexEnvelope;
  try {
    envelope = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(decodeBase64(value)));
  } catch {
    return fail("search index is not strict UTF-8 JSON");
  }
  if (
    envelope.formatVersion !== "search-evaluation-index-v1"
    || envelope.engine?.engineId !== "searise-codepoint-trie"
    || envelope.engine.packageVersion !== "1.0.0"
    || envelope.engine.serializationVersion !== "codepoint-trie-json-v1"
    || envelope.binding?.documentCount !== count
    || envelope.binding.evaluationId !== "browser-search-shard-v2"
    || envelope.binding.shardId !== shardId
    || envelope.payload?.serializationVersion !== 1
    || !Array.isArray(envelope.payload.entries)
  ) {
    return fail("search index envelope differs from the browser contract");
  }
  return envelope;
}

function hydrateIndex(envelope: IndexEnvelope, count: number): TrieNode {
  const root = emptyNode();
  const path: TrieNode[] = [];
  let previous = "";
  for (const entry of envelope.payload.entries) {
    if (!Array.isArray(entry) || entry.length !== 2 || typeof entry[0] !== "string" || !entry[0] || entry[0] <= previous || !Array.isArray(entry[1])) {
      return fail("search index entries are not unique and sorted");
    }
    const normalized = normalizeSearchText(entry[0]);
    if (normalized !== entry[0]) return fail("search index entry is not normalized");
    previous = entry[0];
    let previousOrdinal = 0;
    for (const ordinal of entry[1]) {
      if (!Number.isSafeInteger(ordinal) || ordinal <= previousOrdinal || ordinal > count) {
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

export async function verifySearchArtifactBytes(
  raw: Uint8Array,
  authority: SearchShardAuthority,
): Promise<void> {
  if (
    raw.length !== authority.artifact.byteSize
    || raw.length > MAX_RAW_BYTES
    || !/^[a-f0-9]{64}$/.test(authority.artifact.sha256)
    || await sha256(raw) !== authority.artifact.sha256
  ) {
    return fail("search shard bytes differ from the pinned release authority");
  }
}

export async function decodeSearchShard(
  raw: Uint8Array,
  authority: SearchShardAuthority,
): Promise<SearchShardRuntime> {
  if (raw.length > MAX_RAW_BYTES) return fail("decoded search shard exceeds its browser limit");
  let value: ShardDocument;
  try {
    value = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(raw));
  } catch {
    return fail("search shard is not strict UTF-8 JSON");
  }
  if (
    value.artifactType !== "settlement-browser-search-shard"
    || !["identity", "br"].includes(value.contentEncoding)
    || value.dataReleaseId !== authority.dataReleaseId
    || value.dataProvenanceClass !== authority.dataProvenanceClass
    || value.formatVersion !== "settlement-browser-search-shard-v2"
    || value.shardId !== authority.shardId
    || !Array.isArray(value.records)
    || value.recordCount !== value.records.length
    || value.recordCount < 1 || value.recordCount > 250_000
  ) {
    return fail("search shard metadata differs from the pinned release authority");
  }
  const records = new Map<number, SettlementSearchRecord>();
  const identifiers = new Set<string>();
  value.records.forEach((record, index) => {
    assertRecord(record, index + 1, authority);
    if (identifiers.has(record.placeId)) fail("search shard contains a duplicate stable place ID");
    identifiers.add(record.placeId);
    const { ordinal, ...publicRecord } = record;
    void ordinal;
    records.set(index + 1, Object.freeze(publicRecord));
  });
  const envelope = parseEnvelope(value.indexBase64, records.size, value.shardId);
  return Object.freeze({ authority, records, root: hydrateIndex(envelope, records.size) });
}

interface Work { value: number }
interface BestResults {
  readonly byOrdinal: Map<number, RankedSearchResult>;
  readonly values: RankedSearchResult[];
}

function spend(work: Work, amount = 1): void {
  work.value += amount;
  if (work.value > MAX_QUERY_WORK) fail("search query exceeds its bounded work limit");
}

function offer(
  runtime: SearchShardRuntime,
  best: BestResults,
  ordinal: number,
  matchTier: RankedSearchResult["matchTier"],
  editDistance: number,
): void {
  const record = runtime.records.get(ordinal);
  if (!record) return fail("search index posting has no record");
  const candidate: RankedSearchResult = { record, matchTier, editDistance, shardId: runtime.authority.shardId };
  const previous = best.byOrdinal.get(ordinal);
  if (previous && compareRankedResults(previous, candidate) <= 0) return;
  if (previous) best.values.splice(best.values.indexOf(previous), 1);
  best.byOrdinal.set(ordinal, candidate);
  best.values.push(candidate);
  best.values.sort(compareRankedResults);
  if (best.values.length > RESULT_LIMIT) {
    const removed = best.values.pop()!;
    best.byOrdinal.delete([...runtime.records.entries()].find(([, item]) => item.placeId === removed.record.placeId)?.[0] ?? -1);
  }
}

function addPostings(
  runtime: SearchShardRuntime,
  postings: readonly number[],
  best: BestResults,
  tier: RankedSearchResult["matchTier"],
  distance: number,
  work: Work,
  predicate?: (record: SettlementSearchRecord) => boolean,
): void {
  for (const ordinal of postings) {
    spend(work);
    const record = runtime.records.get(ordinal);
    if (!record) return fail("search index posting has no record");
    if (!predicate || predicate(record)) offer(runtime, best, ordinal, tier, distance);
  }
}

function addPrefix(runtime: SearchShardRuntime, node: TrieNode, best: BestResults, work: Work): void {
  addPostings(runtime, node.ordinals, best, 2, 0, work);
  for (const child of node.children.values()) {
    spend(work);
    addPrefix(runtime, child, best, work);
  }
}

interface DistanceRow { readonly first: number; readonly values: readonly number[] }
function rowValue(row: DistanceRow, column: number, fallback: number): number {
  const offset = column - row.first;
  return offset >= 0 && offset < row.values.length ? row.values[offset] : fallback;
}

function outOfFuzzyReach(node: TrieNode, queryBuckets: readonly number[], maximum: number): boolean {
  if (node.maxNameLength + maximum < queryBuckets.length) return true;
  let missing = 0;
  for (const bucket of queryBuckets) {
    const present = bucket < 32 ? (node.signatureLow >>> bucket) & 1 : (node.signatureHigh >>> (bucket - 32)) & 1;
    if (!present && (missing += 1) > maximum) return true;
  }
  return false;
}

function fuzzyWalk(
  runtime: SearchShardRuntime,
  node: TrieNode,
  query: readonly string[],
  buckets: readonly number[],
  maximum: number,
  depth: number,
  previous: DistanceRow,
  best: BestResults,
  work: Work,
): void {
  for (const [point, child] of node.children) {
    spend(work);
    if (outOfFuzzyReach(child, buckets, maximum)) continue;
    const nextDepth = depth + 1;
    const first = Math.max(0, nextDepth - maximum);
    const last = Math.min(query.length, nextDepth + maximum);
    const values: number[] = [];
    let minimum = maximum + 1;
    for (let column = first; column <= last; column += 1) {
      spend(work);
      const current: DistanceRow = { first, values };
      const distance = column === 0 ? nextDepth : Math.min(
        rowValue(previous, column, maximum + 1) + 1,
        rowValue(current, column - 1, maximum + 1) + 1,
        rowValue(previous, column - 1, maximum + 1) + (point === query[column - 1] ? 0 : 1),
      );
      values.push(distance);
      minimum = Math.min(minimum, distance);
    }
    if (minimum > maximum) continue;
    const distance = rowValue({ first, values }, query.length, maximum + 1);
    if (distance <= maximum) addPostings(runtime, child.ordinals, best, 3, distance, work);
    fuzzyWalk(runtime, child, query, buckets, maximum, nextDepth, { first, values }, best, work);
  }
}

export function searchShard(runtime: SearchShardRuntime, rawQuery: string): readonly RankedSearchResult[] {
  const query = normalizeSearchText(rawQuery);
  const points = Array.from(query);
  if (!points.length) return [];
  if (points.length > MAX_QUERY_POINTS) return fail("search query exceeds its code-point limit");
  const best: BestResults = { byOrdinal: new Map(), values: [] };
  const work = { value: 0 };
  let node: TrieNode | undefined = runtime.root;
  let prefix = "";
  const qualified: Array<{ readonly name: string; readonly node: TrieNode }> = [];
  for (let index = 0; index < points.length && node; index += 1) {
    spend(work);
    node = node.children.get(points[index]);
    if (!node) break;
    prefix += points[index];
    if (node.ordinals.length && points[index + 1] === " ") qualified.push({ name: prefix, node });
  }
  if (node) {
    for (const ordinal of node.ordinals) {
      spend(work);
      const record = runtime.records.get(ordinal)!;
      offer(runtime, best, ordinal, normalizeSearchText(record.displayName) === query ? 0 : 1, 0);
    }
  }
  for (const item of qualified) {
    for (const ordinal of item.node.ordinals) {
      spend(work);
      const record = runtime.records.get(ordinal)!;
      if (hasQualifiedContext(query, item.name, record)) {
        offer(runtime, best, ordinal, normalizeSearchText(record.displayName) === item.name ? 0 : 1, 0);
      }
    }
  }
  if (node) for (const child of node.children.values()) addPrefix(runtime, child, best, work);
  const maximum = searchFuzzyAllowance(query);
  if (maximum && best.values.length < RESULT_LIMIT) {
    fuzzyWalk(
      runtime,
      runtime.root,
      points,
      points.map(signatureBucket),
      maximum,
      0,
      { first: 0, values: Array.from({ length: Math.min(points.length, maximum) + 1 }, (_, index) => index) },
      best,
      work,
    );
  }
  return best.values;
}
