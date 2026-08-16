import {
  compareRankedResults,
  hasQualifiedContext,
  normalizeSearchText,
  searchFuzzyAllowance,
} from "./ranking";
import { canonicalJson, compareCodePoints, validateSearchShardDocument, type IndexEnvelope } from "./contract";
import type {
  RankedSearchResult,
  SearchShardAuthority,
  SettlementSearchRecord,
} from "./types";

const MAX_COMPRESSED_BYTES = 256 * 1024 * 1024;
const MAX_RAW_BYTES = 768 * 1024 * 1024;
const MAX_QUERY_POINTS = 128;
const MAX_QUERY_WORK = 250_000;
const CANDIDATE_LIMIT = 128;
const RESULT_LIMIT = 10;

interface TrieNode {
  readonly children: Map<string, TrieNode>;
  maxNameLength: number;
  ordinals: readonly number[];
  signatureHigh: number;
  signatureLow: number;
}

export interface SearchShardRuntime {
  readonly authority: SearchShardAuthority;
  readonly commonIdentity: string;
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

function emptyNode(): TrieNode {
  return { children: new Map(), maxNameLength: 0, ordinals: [], signatureHigh: 0, signatureLow: 0 };
}

function signatureBucket(point: string): number {
  return Math.imul(point.codePointAt(0)!, 0x9e3779b1) >>> 26;
}

function hydrateIndex(envelope: IndexEnvelope, count: number): TrieNode {
  const root = emptyNode();
  const path: TrieNode[] = [];
  let previous = "";
  for (const entry of envelope.payload.entries) {
    if (!Array.isArray(entry) || entry.length !== 2 || typeof entry[0] !== "string" || !entry[0]
        || (previous && compareCodePoints(entry[0], previous) <= 0) || !Array.isArray(entry[1])) {
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
    || raw.length > MAX_COMPRESSED_BYTES
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
  const value = await validateSearchShardDocument(raw, authority);
  const records = new Map<number, SettlementSearchRecord>();
  value.records.forEach((record, index) => {
    const { ordinal, ...publicRecord } = record;
    void ordinal;
    records.set(index + 1, Object.freeze(publicRecord));
  });
  return Object.freeze({
    authority,
    commonIdentity: value.commonIdentity,
    records,
    root: hydrateIndex(value.envelope, records.size),
  });
}

export function assertCompatibleShardSet(
  core: SearchShardRuntime,
  coastal: SearchShardRuntime,
): void {
  if (core.authority.shardId !== "europe-core" || coastal.authority.shardId !== "europe-coastal"
      || core.commonIdentity !== coastal.commonIdentity) {
    fail("core and coastal shards do not share one v4 release/source/spatial identity");
  }
  const coreById = new Map([...core.records.values()].map((record) => [record.placeId, record]));
  for (const record of coastal.records.values()) {
    const overlap = coreById.get(record.placeId);
    if (overlap && canonicalJson(overlap) !== canonicalJson(record)) {
      fail("core and coastal shards disagree on an overlapping GeoNames record");
    }
  }
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
  if (best.values.length > CANDIDATE_LIMIT) {
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
  if (maximum && best.values.length < CANDIDATE_LIMIT) {
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
  return best.values.slice(0, RESULT_LIMIT);
}
