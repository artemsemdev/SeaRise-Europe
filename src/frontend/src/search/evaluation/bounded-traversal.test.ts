// @vitest-environment node

import { describe, expect, it } from "vitest";
import qualifiedContextGolden from "../../../../../contracts/search-evaluation/v1/fixtures/qualified-context-unicode.synthetic.json";
import { boundedTrieAdapter } from "./adapters";
import { prepareCandidateDocuments, rankDocuments, searchFuzzyAllowance } from "./search";
import type { SearchDocument } from "./types";

// Production settlement shards index every accepted GeoNames alternate name, so
// one trie holds names from many writing systems. Before the subtree filters,
// the fuzzy walk enumerated every node down to depth three regardless of the
// query, and that query-independent cost alone exceeded the traversal-work
// guard on the real europe-core and europe-coastal shards.
const SCRIPT_BASES = [
  0x0061, 0x0430, 0x03b1, 0x0627, 0x05d0, 0x0e01, 0x0915, 0x0561, 0x10d0, 0x3041,
];
const ALPHABET_SIZE = 24;
const NAMES_PER_SCRIPT = 6_000;
const NAMES_PER_RECORD = 200;
const identity = { evaluationId: "bounded-traversal", shardId: "multi-script" };

function letter(base: number, index: number): string {
  return String.fromCodePoint(base + (index % ALPHABET_SIZE));
}

/** Build one deterministic multi-script corpus with a wide shallow trie. */
function multiScriptNames(namesPerScript: number): string[] {
  const names: string[] = [];
  for (const base of SCRIPT_BASES) {
    const tail = Array.from({ length: 6 }, (_, index) => letter(base, index * 5)).join("");
    for (let index = 0; index < namesPerScript; index += 1) {
      const head = [
        letter(base, Math.floor(index / (ALPHABET_SIZE * ALPHABET_SIZE))),
        letter(base, Math.floor(index / ALPHABET_SIZE)),
        letter(base, index),
      ].join("");
      names.push(head + tail);
    }
  }
  return names;
}

/** Group the corpus so one record owns a contiguous block of alternate names. */
function recordsFrom(names: readonly string[]): SearchDocument[] {
  const records: SearchDocument[] = [];
  for (let start = 0; start < names.length; start += NAMES_PER_RECORD) {
    const group = names.slice(start, start + NAMES_PER_RECORD);
    records.push({
      placeId: `synthetic:${records.length + 1}`,
      displayName: group[0],
      searchNames: group.slice(1),
      countryCode: "AA",
      admin1Name: null,
      population: names.length - start,
      featureCode: "PPL",
      distanceToCoastMeters: 1,
      isCoastal: false,
    });
  }
  return records;
}

function ownerPlaceId(nameIndex: number): string {
  return `synthetic:${Math.floor(nameIndex / NAMES_PER_RECORD) + 1}`;
}

describe("qualified-context Unicode golden", () => {
  it("preserves the receipt-bound punctuation tokenization", () => {
    const documents = prepareCandidateDocuments([{
      ...qualifiedContextGolden.record,
      searchNames: [...qualifiedContextGolden.record.searchNames],
    }]);
    const index = boundedTrieAdapter.build(documents, {
      evaluationId: "qualified-context-golden",
      shardId: "europe-core",
    });
    const envelope = JSON.parse(new TextDecoder().decode(boundedTrieAdapter.serialize(index)));
    const candidates = boundedTrieAdapter.search(index, qualifiedContextGolden.query, 100)
      .map((ordinal) => documents.find((document) => document.ordinal === ordinal)!);

    expect(envelope.binding.optionsSha256).toBe(qualifiedContextGolden.optionsSha256);
    expect(rankDocuments(qualifiedContextGolden.query, candidates).map(({ record }) => record.placeId))
      .toEqual(qualifiedContextGolden.expectedPlaceIds);
  });
});

describe("bounded trie traversal at settlement-shard scale", () => {
  const names = multiScriptNames(NAMES_PER_SCRIPT);
  const documents = prepareCandidateDocuments(recordsFrom(names));
  const byOrdinal = new Map(documents.map((document) => [document.ordinal, document]));
  const index = boundedTrieAdapter.build(documents, identity);

  function candidates(query: string): SearchDocument[] {
    return boundedTrieAdapter.search(index, query, 100)
      .map((ordinal) => byOrdinal.get(ordinal)!.record);
  }

  it("answers a two-edit query over a multi-script corpus within the traversal guard", () => {
    // Latin and nine code points, so the ranker allows two edits and no exact,
    // qualified, or prefix match can saturate the candidate set beforehand.
    const target = names[0];
    const query = `${letter(0x0061, 1)}${target.slice(1, 8)}${letter(0x0061, 23)}`;
    expect(searchFuzzyAllowance(query)).toBe(2);
    expect(query).not.toBe(target);

    const matched = candidates(query);
    expect(matched.map(({ placeId }) => placeId)).toContain(ownerPlaceId(0));
    expect(rankDocuments(query, matched.map((record, ordinal) => ({
      ordinal: ordinal + 1, record, terms: "",
    })))).not.toHaveLength(0);
  });

  it("keeps every script whose names can still be within the edit allowance", () => {
    // The subtree filters are lower bounds on the edit distance, so a query
    // written in one script must still reach that script's names.
    SCRIPT_BASES.forEach((base, script) => {
      const nameIndex = script * NAMES_PER_SCRIPT;
      const query = names[nameIndex].slice(0, 8) + letter(base, 23);
      expect(candidates(query).map(({ placeId }) => placeId), `script ${script}`)
        .toContain(ownerPlaceId(nameIndex));
    });
  });
});

describe("bounded trie traversal completeness", () => {
  // Small enough that the unfiltered walk also stays inside the guard, so the
  // filtered candidate set can be compared with the exhaustive ranker.
  const names = multiScriptNames(60);
  const records = recordsFrom(names);
  const documents = prepareCandidateDocuments(records);
  const index = boundedTrieAdapter.build(documents, identity);

  it("returns every document the exhaustive ranker accepts", () => {
    for (const base of SCRIPT_BASES) {
      for (const mutation of [0, 3, 8]) {
        const source = names[SCRIPT_BASES.indexOf(base) * 60 + 17];
        const query = source.slice(0, mutation) + letter(base, 23) + source.slice(mutation + 1);
        const expected = rankDocuments(query, documents).map(({ record }) => record.placeId);
        const actual = boundedTrieAdapter.search(index, query, 100)
          .map((ordinal) => documents.find((item) => item.ordinal === ordinal)!.record.placeId);
        expect(expected.every((placeId) => actual.includes(placeId)), `${query}`).toBe(true);
      }
    }
  });
});
