import { createHash } from "node:crypto";
import { Index } from "flexsearch";
import MiniSearch from "minisearch";
import {
  compareRankedCandidates,
  hasQualifiedSearchContext,
  normalizeSearchText,
  searchFuzzyAllowance,
  tokenizeSearchText,
} from "./search";
import type { RankedCandidateDocument, SearchMatchKey } from "./search";
import type { CandidateAdapter, CandidateDocument, EngineDescriptor, EvaluationIdentity } from "./types";

const FORMAT_VERSION = "search-evaluation-index-v1";
const encoder = new TextEncoder();
const decoder = new TextDecoder("utf-8", { fatal: true });
const sha256 = (value: string) => createHash("sha256").update(value).digest("hex");

interface Binding extends EvaluationIdentity {
  documentCount: number;
  documentsSha256: string;
  optionsSha256: string;
}
interface Envelope { formatVersion: typeof FORMAT_VERSION; engine: EngineDescriptor; binding: Binding; payload: unknown }
interface BuiltIndex { binding: Binding; index: unknown }

function exactKeys(value: unknown, keys: readonly string[]): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    && JSON.stringify(Object.keys(value).sort()) === JSON.stringify([...keys].sort());
}

function bindingFor(documents: readonly CandidateDocument[], identity: EvaluationIdentity, optionsSha256: string): Binding {
  if (!/^[a-z0-9][a-z0-9-]+$/.test(identity.evaluationId) || !/^[a-z0-9][a-z0-9-]+$/.test(identity.shardId)) {
    throw new Error("search evaluation and shard identities must be explicit stable identifiers");
  }
  const canonicalDocuments = documents.map(({ ordinal, terms, record }) => [
    ordinal, terms, record.placeId, record.displayName, record.searchNames, record.countryCode,
    record.admin1Name, record.population, record.featureCode, record.distanceToCoastMeters, record.isCoastal,
  ]);
  return {
    evaluationId: identity.evaluationId,
    shardId: identity.shardId,
    documentCount: documents.length,
    documentsSha256: sha256(JSON.stringify(canonicalDocuments)),
    optionsSha256,
  };
}

function encodeEnvelope(engine: EngineDescriptor, binding: Binding, payload: unknown): Uint8Array {
  return encoder.encode(JSON.stringify({ formatVersion: FORMAT_VERSION, engine, binding, payload }));
}

function decodeEnvelope(bytes: Uint8Array, expectedEngine: EngineDescriptor, expectedBinding: Binding): Envelope {
  let value: unknown;
  try {
    value = JSON.parse(decoder.decode(bytes));
  } catch {
    throw new Error("search evaluation index is not valid fatal UTF-8 JSON");
  }
  if (!exactKeys(value, ["formatVersion", "engine", "binding", "payload"])
      || !exactKeys(value.engine, ["engineId", "packageVersion", "serializationVersion"])
      || !exactKeys(value.binding, ["evaluationId", "shardId", "documentCount", "documentsSha256", "optionsSha256"])
      || value.formatVersion !== FORMAT_VERSION
      || JSON.stringify(value.engine) !== JSON.stringify(expectedEngine)
      || JSON.stringify(value.binding) !== JSON.stringify(expectedBinding)) {
    throw new Error("search evaluation index identity or document binding is incompatible");
  }
  return value as unknown as Envelope;
}

function built(value: unknown): BuiltIndex {
  if (!exactKeys(value, ["binding", "index"])) throw new Error("search evaluation adapter index is invalid");
  return value as unknown as BuiltIndex;
}

type MiniDocument = { id: number; terms: string };
const MINI_OPTIONS_SHA256 = sha256("minisearch-7.2.0|fields=terms|id=id|tokenize=unicode-v1|process=identity|store=none");
function miniOptions() {
  return {
    fields: ["terms"], idField: "id", storeFields: [],
    tokenize: (text: string) => tokenizeSearchText(text),
    processTerm: (term: string) => term,
  };
}

export const miniSearchAdapter: CandidateAdapter = {
  descriptor: { engineId: "minisearch", packageVersion: "7.2.0", serializationVersion: "minisearch-json-v1" },
  build(documents, identity) {
    const index = new MiniSearch<MiniDocument>(miniOptions());
    index.addAll(documents.map(({ ordinal, terms }) => ({ id: ordinal, terms })));
    return { binding: bindingFor(documents, identity, MINI_OPTIONS_SHA256), index };
  },
  serialize(value) {
    const { binding, index } = built(value);
    const payload = JSON.stringify(index as MiniSearch<MiniDocument>);
    if ((JSON.parse(payload) as { serializationVersion?: number }).serializationVersion !== 2) throw new Error("MiniSearch serialization version changed");
    return encodeEnvelope(this.descriptor, binding, payload);
  },
  deserialize(bytes, documents, identity) {
    const expected = bindingFor(documents, identity, MINI_OPTIONS_SHA256);
    const payload = decodeEnvelope(bytes, this.descriptor, expected).payload;
    if (typeof payload !== "string") throw new Error("MiniSearch payload is invalid");
    const serialized = JSON.parse(payload) as { serializationVersion?: number };
    if (serialized.serializationVersion !== 2) throw new Error("MiniSearch payload serialization is incompatible");
    return { binding: expected, index: MiniSearch.loadJSON<MiniDocument>(payload, miniOptions()) };
  },
  search(value, query, limit) {
    if (!Number.isSafeInteger(limit) || limit < 1) throw new Error("MiniSearch candidate limit is invalid");
    const length = Array.from(normalizeSearchText(query)).length;
    const fuzzy = length < 4 ? false : length < 8 ? 1 : 2;
    const results = (built(value).index as MiniSearch<MiniDocument>).search(query, {
      prefix: true, fuzzy, maxFuzzy: 2, combineWith: "AND",
    });
    return results.slice(0, limit).map((result) => Number(result.id));
  },
};

export const BOUNDED_SEARCH_WORK_LIMIT = 250_000;
export const MAX_NORMALIZED_SEARCH_CODE_POINTS = 1_024;
const BOUNDED_OPTIONS_SHA256 = sha256(
  "searise-codepoint-trie-1.0.0|full-name-codepoints|qualified-context|prefix|levenshtein-max-2|global-rank-cap|work=250000",
);

type TrieEntry = [string, number[]];
type TriePayload = { serializationVersion: 1; entries: TrieEntry[] };
type TrieNode = {
  children: Map<string, TrieNode>;
  ordinals: number[];
  // Admissible subtree filters. `maxNameLength` is the longest name under the
  // node; the signature bits are the union of every code point in those names.
  maxNameLength: number;
  signatureHigh: number;
  signatureLow: number;
};
type TrieRuntime = {
  documents: Map<number, CandidateDocument>;
  payload: TriePayload;
  root: TrieNode;
};

function normalizedName(value: string): string {
  const normalized = normalizeSearchText(value);
  const length = Array.from(normalized).length;
  if (!length || length > MAX_NORMALIZED_SEARCH_CODE_POINTS) {
    throw new Error("bounded search name has an invalid normalized length");
  }
  return normalized;
}

function triePayload(documents: readonly CandidateDocument[]): TriePayload {
  const names = new Map<string, Set<number>>();
  for (const document of documents) {
    if (!Number.isSafeInteger(document.ordinal) || document.ordinal < 1) {
      throw new Error("bounded search document ordinal is invalid");
    }
    for (const name of Array.from(new Set([
      document.record.displayName,
      ...document.record.searchNames,
    ].map(normalizedName)))) {
      const ordinals = names.get(name) ?? new Set<number>();
      ordinals.add(document.ordinal);
      names.set(name, ordinals);
    }
  }
  return {
    serializationVersion: 1,
    entries: Array.from(names.entries()).sort(([left], [right]) =>
      left < right ? -1 : left > right ? 1 : 0)
      .map(([name, ordinals]) => [name, Array.from(ordinals).sort((left, right) => left - right)]),
  };
}

function emptyTrieNode(): TrieNode {
  return { children: new Map(), maxNameLength: 0, ordinals: [], signatureHigh: 0, signatureLow: 0 };
}

/** Map one code point onto one of the 64 subtree-signature buckets. */
function signatureBucket(point: string): number {
  return Math.imul(point.codePointAt(0)!, 0x9e3779b1) >>> 26;
}

function trieFrom(payload: TriePayload): TrieNode {
  const root = emptyTrieNode();
  const path: TrieNode[] = [];
  for (const [name, ordinals] of payload.entries) {
    const points = Array.from(name);
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
        child = emptyTrieNode();
        node.children.set(point, child);
      }
      node = child;
      path.push(node);
    }
    node.ordinals = ordinals;
    for (const item of path) {
      item.signatureHigh |= signatureHigh;
      item.signatureLow |= signatureLow;
      if (points.length > item.maxNameLength) item.maxNameLength = points.length;
    }
  }
  return root;
}

function trieRuntime(documents: readonly CandidateDocument[]): TrieRuntime {
  const payload = triePayload(documents);
  return {
    documents: new Map(documents.map((document) => [document.ordinal, document])),
    payload,
    root: trieFrom(payload),
  };
}

function assertTriePayload(value: unknown, expected: TriePayload): asserts value is TriePayload {
  if (!exactKeys(value, ["entries", "serializationVersion"])
      || value.serializationVersion !== 1 || !Array.isArray(value.entries)
      || JSON.stringify(value) !== JSON.stringify(expected)) {
    throw new Error("bounded search payload is incompatible with its exact documents");
  }
}

function trieBuilt(value: unknown): { binding: Binding; index: TrieRuntime } {
  const result = built(value);
  const index = result.index as Partial<TrieRuntime>;
  if (!(index.documents instanceof Map) || !(index.root?.children instanceof Map)
      || !exactKeys(index.payload, ["entries", "serializationVersion"])) {
    throw new Error("bounded search runtime is invalid");
  }
  return result as { binding: Binding; index: TrieRuntime };
}

type Work = { value: number };
function spend(work: Work, amount = 1): void {
  work.value += amount;
  if (work.value > BOUNDED_SEARCH_WORK_LIMIT) {
    throw new Error("bounded search query exceeds its traversal-work limit");
  }
}

type BestCandidates = {
  byOrdinal: Map<number, RankedCandidateDocument>;
  limit: number;
  values: RankedCandidateDocument[];
};

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
  best: BestCandidates, document: CandidateDocument, match: SearchMatchKey,
): void {
  const candidate = { document, match };
  const existing = best.byOrdinal.get(document.ordinal);
  if (existing) {
    if (compareRankedCandidates(candidate, existing) >= 0) return;
    const index = best.values.indexOf(existing);
    if (index < 0) throw new Error("bounded search candidate set is inconsistent");
    best.values.splice(index, 1);
    best.byOrdinal.delete(document.ordinal);
    insertCandidate(best, candidate);
    return;
  }
  if (best.values.length >= best.limit) {
    const worst = best.values.at(-1)!;
    if (compareRankedCandidates(candidate, worst) >= 0) return;
    best.values.pop();
    best.byOrdinal.delete(worst.document.ordinal);
  }
  insertCandidate(best, candidate);
}

function addOrdinals(
  runtime: TrieRuntime,
  ordinals: readonly number[],
  best: BestCandidates,
  match: SearchMatchKey | ((document: CandidateDocument) => SearchMatchKey),
  work: Work,
  predicate?: (document: CandidateDocument) => boolean,
): void {
  for (const ordinal of ordinals) {
    spend(work);
    const document = runtime.documents.get(ordinal);
    if (!document) throw new Error("bounded search posting has no document");
    if (!predicate || predicate(document)) {
      offerCandidate(best, document, typeof match === "function" ? match(document) : match);
    }
  }
}

function addPrefix(
  runtime: TrieRuntime, node: TrieNode, best: BestCandidates, work: Work,
): void {
  addOrdinals(runtime, node.ordinals, best, [2, 0], work);
  const children = node.children.values();
  for (let item = children.next(); !item.done; item = children.next()) {
    const child = item.value;
    spend(work);
    addPrefix(runtime, child, best, work);
  }
}

type DistanceRow = { first: number; values: number[] };
function rowValue(row: DistanceRow, column: number, fallback: number): number {
  const offset = column - row.first;
  return offset >= 0 && offset < row.values.length ? row.values[offset] : fallback;
}

/**
 * Report whether every name under `node` is provably further than `maximum`
 * edits from the query. Both tests are admissible lower bounds on the edit
 * distance, so pruning here can never drop a match:
 * a name of length `L` needs at least `query.length - L` edits, and every query
 * position whose code point is absent from the subtree needs at least one edit.
 * The signature is a union over the subtree and its buckets may collide, which
 * can only understate the bound.
 */
function outOfFuzzyReach(
  node: TrieNode, queryBuckets: readonly number[], maximum: number,
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
  runtime: TrieRuntime,
  node: TrieNode,
  query: readonly string[],
  queryBuckets: readonly number[],
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
    if (outOfFuzzyReach(child, queryBuckets, maximum)) continue;
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
        rowValue(previous, column - 1, maximum + 1) + (point === query[column - 1] ? 0 : 1),
      );
      current.values.push(distance);
      minimum = Math.min(minimum, distance);
    }
    if (minimum > maximum) continue;
    const distance = rowValue(current, query.length, maximum + 1);
    if (distance <= maximum) {
      addOrdinals(runtime, child.ordinals, best, [3, distance], work);
    }
    fuzzyWalk(runtime, child, query, queryBuckets, maximum, nextDepth, current, best, work);
  }
}

function boundedTrieSearch(runtime: TrieRuntime, rawQuery: string, limit: number): number[] {
  if (!Number.isSafeInteger(limit) || limit < 1) throw new Error("bounded search candidate limit is invalid");
  const query = normalizeSearchText(rawQuery);
  const points = Array.from(query);
  if (!points.length) return [];
  if (points.length > MAX_NORMALIZED_SEARCH_CODE_POINTS) {
    throw new Error("bounded search query has an invalid normalized length");
  }
  const best: BestCandidates = { byOrdinal: new Map(), limit, values: [] };
  const work: Work = { value: 0 };
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
    addOrdinals(runtime, node.ordinals, best, ({ record }) =>
      [normalizeSearchText(record.displayName) === query ? 0 : 1, 0], work);
  }
  for (const item of qualified) {
    addOrdinals(runtime, item.node.ordinals, best, ({ record }) =>
      [normalizeSearchText(record.displayName) === item.name ? 0 : 1, 0], work,
    ({ record }) => hasQualifiedSearchContext(query, item.name, record));
  }
  if (node) {
    const children = node.children.values();
    for (let item = children.next(); !item.done; item = children.next()) {
      spend(work);
      addPrefix(runtime, item.value, best, work);
    }
  }
  const maximum = searchFuzzyAllowance(query);
  // Every fuzzy key ranks below every exact, qualified, and prefix key, so a
  // saturated candidate set cannot accept one and the walk cannot change it.
  if (maximum && best.values.length < limit) {
    const first = Math.max(0, -maximum);
    const last = Math.min(points.length, maximum);
    fuzzyWalk(runtime, runtime.root, points, points.map(signatureBucket), maximum, 0, {
      first,
      values: Array.from({ length: last - first + 1 }, (_, index) => first + index),
    }, best, work);
  }
  return best.values.map(({ document }) => document.ordinal);
}

export const boundedTrieAdapter: CandidateAdapter = {
  descriptor: {
    engineId: "searise-codepoint-trie",
    packageVersion: "1.0.0",
    serializationVersion: "codepoint-trie-json-v1",
  },
  build(documents, identity) {
    return { binding: bindingFor(documents, identity, BOUNDED_OPTIONS_SHA256), index: trieRuntime(documents) };
  },
  serialize(value) {
    const { binding, index } = trieBuilt(value);
    return encodeEnvelope(this.descriptor, binding, index.payload);
  },
  deserialize(bytes, documents, identity) {
    const expectedBinding = bindingFor(documents, identity, BOUNDED_OPTIONS_SHA256);
    const payload = decodeEnvelope(bytes, this.descriptor, expectedBinding).payload;
    const expectedPayload = triePayload(documents);
    assertTriePayload(payload, expectedPayload);
    return {
      binding: expectedBinding,
      index: {
        documents: new Map(documents.map((document) => [document.ordinal, document])),
        payload,
        root: trieFrom(payload),
      },
    };
  },
  search(value, query, limit) {
    return boundedTrieSearch(trieBuilt(value).index, query, limit);
  },
};

const FLEX_OPTIONS_SHA256 = sha256("flexsearch-0.8.212|index|tokenize=forward|encoder=Exact|cache=false");
function flexIndex(): Index { return new Index({ tokenize: "forward", encoder: "Exact", cache: false }); }
function assertFlexChunks(payload: unknown): asserts payload is [string, string][] {
  if (!Array.isArray(payload) || payload.length !== 2
      || !payload.every((chunk) => Array.isArray(chunk) && chunk.length === 2 && typeof chunk[0] === "string" && typeof chunk[1] === "string")) {
    throw new Error("FlexSearch export chunks are incompatible");
  }
  const prefix = /^([1-9][0-9]*)\.reg$/.exec(payload[0][0])?.[1];
  if (!prefix || payload[1][0] !== `${prefix}.map`) throw new Error("FlexSearch export chunk order or set is incompatible");
}

export const flexSearchAdapter: CandidateAdapter = {
  descriptor: { engineId: "flexsearch", packageVersion: "0.8.212", serializationVersion: "flexsearch-export-v1" },
  build(documents, identity) {
    const index = flexIndex();
    documents.forEach(({ ordinal, terms }) => index.add(ordinal, terms));
    return { binding: bindingFor(documents, identity, FLEX_OPTIONS_SHA256), index };
  },
  serialize(value) {
    const { binding, index } = built(value);
    const chunks: [string, string][] = [];
    (index as Index).export((key, data) => chunks.push([key, data]));
    assertFlexChunks(chunks);
    return encodeEnvelope(this.descriptor, binding, chunks);
  },
  deserialize(bytes, documents, identity) {
    const expected = bindingFor(documents, identity, FLEX_OPTIONS_SHA256);
    const payload = decodeEnvelope(bytes, this.descriptor, expected).payload;
    assertFlexChunks(payload);
    const index = flexIndex();
    payload.forEach(([key, data]) => index.import(key, data));
    return { binding: expected, index };
  },
  search(value, query, limit) {
    return (built(value).index as Index).search(normalizeSearchText(query), { limit, suggest: true }).map(Number);
  },
};

export const searchEvaluationAdapters: readonly CandidateAdapter[] = [miniSearchAdapter, flexSearchAdapter];
