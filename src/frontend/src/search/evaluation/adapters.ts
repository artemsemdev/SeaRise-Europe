import { createHash } from "node:crypto";
import { Index } from "flexsearch";
import MiniSearch from "minisearch";
import { normalizeSearchText, tokenizeSearchText } from "./search";
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
export const MINI_SEARCH_POSTING_VISIT_LIMIT = 250_000;
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
    const accepted = new Set<unknown>();
    let postingVisits = 0;
    const results = (built(value).index as MiniSearch<MiniDocument>).search(query, {
      prefix: true, fuzzy, maxFuzzy: 2, combineWith: "AND",
      boostDocument: (id) => {
        if (++postingVisits > MINI_SEARCH_POSTING_VISIT_LIMIT) {
          throw new Error("MiniSearch query exceeds its posting-visit limit");
        }
        if (accepted.has(id)) return 1;
        if (accepted.size >= limit) return 0;
        accepted.add(id);
        return 1;
      },
    });
    if (results.length > limit) throw new Error("MiniSearch materialized too many candidates");
    return results.map((result) => Number(result.id));
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
