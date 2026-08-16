import {
  compareRankedResults,
  hasQualifiedContext,
  normalizeSearchText,
  searchFuzzyAllowance,
} from "./ranking";
import { compareCodePoints, validateSearchShardDocument, type IndexEnvelope } from "./contract";
import type {
  RankedSearchResult,
  SearchShardAuthority,
  SettlementSearchRecord,
} from "./types";

const MAX_COMPRESSED_BYTES = 16 * 1024 * 1024;
const MAX_RAW_BYTES = 64 * 1024 * 1024;
const MAX_QUERY_POINTS = 128;
const MAX_QUERY_WORK = 250_000;
const CANDIDATE_LIMIT = 128;
const RESULT_LIMIT = 10;
const VERIFIED_ARTIFACT = Symbol("verified-search-artifact");

export interface VerifiedSearchArtifact {
  readonly authority: SearchShardAuthority;
  readonly [VERIFIED_ARTIFACT]: true;
}

interface CompactIndex {
  readonly entries: IndexEnvelope["payload"]["entries"];
  readonly lengths: Uint16Array;
  readonly signatureHigh: Uint32Array;
  readonly signatureLow: Uint32Array;
  readonly signatureCounts: Uint32Array;
  readonly byLength: ReadonlyMap<number, Uint32Array>;
}

export interface SearchShardRuntime {
  readonly authority: SearchShardAuthority;
  readonly commonIdentity: string;
  readonly records: readonly (SettlementSearchRecord | undefined)[];
  readonly index: CompactIndex;
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

function signatureBucket(point: string): number {
  return Math.imul(point.codePointAt(0)!, 0x9e3779b1) >>> 26;
}

function compactIndex(envelope: IndexEnvelope): CompactIndex {
  const entries = envelope.payload.entries;
  const lengths = new Uint16Array(entries.length);
  const signatureHigh = new Uint32Array(entries.length);
  const signatureLow = new Uint32Array(entries.length);
  const signatureCounts = new Uint32Array(entries.length * 4);
  const mutableByLength = new Map<number, number[]>();
  entries.forEach(([name], index) => {
    const points = Array.from(name);
    if (points.length > 0xffff) return fail("search index entry exceeds its browser limit");
    lengths[index] = points.length;
    let high = 0;
    let low = 0;
    for (const point of points) {
      const bucket = signatureBucket(point);
      if (bucket < 32) low |= 1 << bucket;
      else high |= 1 << (bucket - 32);
      const wordIndex = index * 4 + Math.floor(bucket / 16);
      const shift = (bucket % 16) * 2;
      const count = (signatureCounts[wordIndex] >>> shift) & 3;
      if (count < 3) signatureCounts[wordIndex] = (signatureCounts[wordIndex] + (1 << shift)) >>> 0;
    }
    signatureHigh[index] = high;
    signatureLow[index] = low;
    const bucket = mutableByLength.get(points.length) ?? [];
    bucket.push(index);
    mutableByLength.set(points.length, bucket);
  });
  return {
    entries,
    lengths,
    signatureHigh,
    signatureLow,
    signatureCounts,
    byLength: new Map([...mutableByLength].map(([length, indexes]) => [length, Uint32Array.from(indexes)])),
  };
}

export async function verifySearchArtifactBytes(
  raw: Uint8Array,
  authority: SearchShardAuthority,
): Promise<VerifiedSearchArtifact> {
  if (
    raw.length !== authority.artifact.byteSize
    || raw.length > MAX_COMPRESSED_BYTES
    || !/^[a-f0-9]{64}$/.test(authority.artifact.sha256)
    || await sha256(raw) !== authority.artifact.sha256
  ) {
    return fail("search shard bytes differ from the pinned release authority");
  }
  return Object.freeze({ authority, [VERIFIED_ARTIFACT]: true as const });
}

export async function decodeSearchShard(
  raw: Uint8Array,
  authority: SearchShardAuthority,
  verifiedArtifact?: VerifiedSearchArtifact,
): Promise<SearchShardRuntime> {
  if (raw.length > MAX_RAW_BYTES) return fail("decoded search shard exceeds its browser limit");
  const artifactVerified = verifiedArtifact?.authority === authority
    && verifiedArtifact[VERIFIED_ARTIFACT] === true;
  const value = await validateSearchShardDocument(raw, authority, artifactVerified);
  const records: (SettlementSearchRecord | undefined)[] = [undefined];
  for (const record of value.records) records.push(record);
  return Object.freeze({
    authority,
    commonIdentity: value.commonIdentity,
    records: Object.freeze(records),
    index: compactIndex(value.envelope),
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
  const coreById = new Map(core.records.slice(1).map((record) => [record!.placeId, record!]));
  for (const record of coastal.records.slice(1)) {
    if (!record) fail("coastal search record inventory is sparse");
    const overlap = coreById.get(record.placeId);
    if (overlap && (
      overlap.displayName !== record.displayName
      || overlap.countryCode !== record.countryCode
      || overlap.admin1Name !== record.admin1Name
      || overlap.population !== record.population
      || overlap.featureCode !== record.featureCode
      || overlap.distanceToCoastMeters !== record.distanceToCoastMeters
      || overlap.isCoastal !== record.isCoastal
      || overlap.latitude !== record.latitude
      || overlap.longitude !== record.longitude
      || overlap.searchNames.length !== record.searchNames.length
      || overlap.searchNames.some((name, index) => name !== record.searchNames[index])
    )) {
      fail("core and coastal shards disagree on an overlapping GeoNames record");
    }
  }
}

interface Work { value: number }
interface BestResults {
  readonly byOrdinal: Map<number, RankedSearchResult>;
  readonly ordinalByResult: Map<RankedSearchResult, number>;
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
  const record = runtime.records[ordinal];
  if (!record) return fail("search index posting has no record");
  const candidate: RankedSearchResult = { record, matchTier, editDistance, shardId: runtime.authority.shardId };
  const previous = best.byOrdinal.get(ordinal);
  if (previous && compareRankedResults(previous, candidate) <= 0) return;
  if (previous) {
    best.values.splice(best.values.indexOf(previous), 1);
    best.ordinalByResult.delete(previous);
  }
  best.byOrdinal.set(ordinal, candidate);
  best.ordinalByResult.set(candidate, ordinal);
  best.values.push(candidate);
  best.values.sort(compareRankedResults);
  if (best.values.length > CANDIDATE_LIMIT) {
    const removed = best.values.pop()!;
    const removedOrdinal = best.ordinalByResult.get(removed);
    if (removedOrdinal === undefined) return fail("search candidate identity is missing");
    best.ordinalByResult.delete(removed);
    best.byOrdinal.delete(removedOrdinal);
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
    const record = runtime.records[ordinal];
    if (!record) return fail("search index posting has no record");
    if (!predicate || predicate(record)) offer(runtime, best, ordinal, tier, distance);
  }
}

function lowerBound(entries: CompactIndex["entries"], query: string): number {
  let first = 0;
  let count = entries.length;
  while (count > 0) {
    const step = Math.floor(count / 2);
    const index = first + step;
    if (compareCodePoints(entries[index][0], query) < 0) {
      first = index + 1;
      count -= step + 1;
    } else {
      count = step;
    }
  }
  return first;
}

function outOfFuzzyReach(
  signatureHigh: number,
  signatureLow: number,
  queryBuckets: readonly number[],
  queryCounts: readonly (readonly [number, number])[],
  signatureCounts: Uint32Array,
  entryIndex: number,
  maximum: number,
): boolean {
  let missing = 0;
  for (const bucket of queryBuckets) {
    const present = bucket < 32 ? (signatureLow >>> bucket) & 1 : (signatureHigh >>> (bucket - 32)) & 1;
    if (!present && (missing += 1) > maximum) return true;
  }
  let deficit = 0;
  for (const [bucket, queryCount] of queryCounts) {
    const word = signatureCounts[entryIndex * 4 + Math.floor(bucket / 16)];
    const candidateCount = (word >>> ((bucket % 16) * 2)) & 3;
    deficit += Math.max(0, queryCount - candidateCount);
    if (deficit > maximum) return true;
  }
  return false;
}

function boundedDistance(
  candidate: readonly string[],
  query: readonly string[],
  maximum: number,
  work: Work,
): number {
  interface Row { readonly first: number; readonly values: readonly number[] }
  const valueAt = (row: Row, column: number) => {
    const offset = column - row.first;
    return offset >= 0 && offset < row.values.length ? row.values[offset] : maximum + 1;
  };
  let previous: Row = {
    first: 0,
    values: Array.from({ length: Math.min(query.length, maximum) + 1 }, (_, index) => index),
  };
  for (let row = 1; row <= candidate.length; row += 1) {
    const first = Math.max(0, row - maximum);
    const last = Math.min(query.length, row + maximum);
    const values: number[] = [];
    const current: Row = { first, values };
    let minimum = maximum + 1;
    for (let column = first; column <= last; column += 1) {
      spend(work);
      const distance = column === 0 ? row : Math.min(
        valueAt(previous, column) + 1,
        valueAt(current, column - 1) + 1,
        valueAt(previous, column - 1) + (candidate[row - 1] === query[column - 1] ? 0 : 1),
      );
      values.push(distance);
      minimum = Math.min(minimum, distance);
    }
    if (minimum > maximum) return maximum + 1;
    previous = current;
  }
  return valueAt(previous, query.length);
}

export function searchShard(runtime: SearchShardRuntime, rawQuery: string): readonly RankedSearchResult[] {
  const query = normalizeSearchText(rawQuery);
  const points = Array.from(query);
  if (!points.length) return [];
  if (points.length > MAX_QUERY_POINTS) return fail("search query exceeds its code-point limit");
  const best: BestResults = { byOrdinal: new Map(), ordinalByResult: new Map(), values: [] };
  const work = { value: 0 };
  const { entries } = runtime.index;
  const exactIndex = lowerBound(entries, query);
  if (entries[exactIndex]?.[0] === query) {
    for (const ordinal of entries[exactIndex][1]) {
      spend(work);
      const record = runtime.records[ordinal]!;
      offer(runtime, best, ordinal, normalizeSearchText(record.displayName) === query ? 0 : 1, 0);
    }
  }
  for (let offset = query.indexOf(" "); offset >= 0; offset = query.indexOf(" ", offset + 1)) {
    const name = query.slice(0, offset);
    const index = lowerBound(entries, name);
    if (entries[index]?.[0] !== name) continue;
    for (const ordinal of entries[index][1]) {
      spend(work);
      const record = runtime.records[ordinal]!;
      if (hasQualifiedContext(query, name, record)) {
        offer(runtime, best, ordinal, normalizeSearchText(record.displayName) === name ? 0 : 1, 0);
      }
    }
  }
  for (let index = exactIndex; index < entries.length && entries[index][0].startsWith(query); index += 1) {
    if (entries[index][0] === query) continue;
    spend(work);
    addPostings(runtime, entries[index][1], best, 2, 0, work);
  }
  const maximum = searchFuzzyAllowance(query);
  if (maximum && best.values.length < CANDIDATE_LIMIT) {
    const buckets = points.map(signatureBucket);
    const queryCounts = new Uint8Array(64);
    for (const bucket of buckets) queryCounts[bucket] = Math.min(3, queryCounts[bucket] + 1);
    const queryCountEntries = [...queryCounts.entries()].filter(([, count]) => count > 0);
    for (let length = Math.max(1, points.length - maximum); length <= points.length + maximum; length += 1) {
      for (const index of runtime.index.byLength.get(length) ?? []) {
        spend(work);
        if (outOfFuzzyReach(
          runtime.index.signatureHigh[index],
          runtime.index.signatureLow[index],
          buckets,
          queryCountEntries,
          runtime.index.signatureCounts,
          index,
          maximum,
        )) continue;
        const [name, postings] = entries[index];
        const distance = boundedDistance(Array.from(name), points, maximum, work);
        if (distance <= maximum) addPostings(runtime, postings, best, 3, distance, work);
      }
    }
  }
  return best.values.slice(0, RESULT_LIMIT);
}
