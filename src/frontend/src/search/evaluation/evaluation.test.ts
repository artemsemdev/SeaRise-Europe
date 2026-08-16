// @vitest-environment node

import Ajv2020 from "ajv/dist/2020";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import querySchema from "../../../../../contracts/search-evaluation/v1/query-fixtures.schema.json";
import reportSchema from "../../../../../contracts/search-evaluation/v1/evaluation-report.schema.json";
import queryFixture from "../../../../../contracts/search-evaluation/v1/fixtures/queries.synthetic.json";
import reportFixture from "../../../../../contracts/search-evaluation/v1/fixtures/report.synthetic.json";
import { flexSearchAdapter, miniSearchAdapter, searchEvaluationAdapters } from "./adapters";
import { normalizeSearchText, prepareCandidateDocuments, rankDocuments } from "./search";
import { validateEvaluationReportSemantics, validateQueryFixtureSemantics } from "./semantics";
import type { SearchDocument } from "./types";

const records: SearchDocument[] = [
  { placeId: "geonames:900000001", displayName: "Málaga", searchNames: ["Malaga City"], countryCode: "ES", admin1Name: "Andalucía", population: 578460, featureCode: "PPLA", distanceToCoastMeters: 50, isCoastal: true },
  { placeId: "geonames:900000002", displayName: "Αθήνα", searchNames: ["Athens", "Athina"], countryCode: "GR", admin1Name: "Attica", population: 637798, featureCode: "PPLC", distanceToCoastMeters: 7000, isCoastal: true },
  { placeId: "geonames:900000003", displayName: "Springfield", searchNames: [], countryCode: "AA", admin1Name: "North", population: 1000, featureCode: "PPL", distanceToCoastMeters: 50000, isCoastal: false },
  { placeId: "geonames:900000004", displayName: "Springfield", searchNames: [], countryCode: "BB", admin1Name: "South", population: 500, featureCode: "PPL", distanceToCoastMeters: 100, isCoastal: true },
  { placeId: "geonames:900000005", displayName: "Islet Village", searchNames: [], countryCode: "CC", admin1Name: "Island", population: 0, featureCode: "PPL", distanceToCoastMeters: 0, isCoastal: true },
  { placeId: "geonames:900000006", displayName: "Border City", searchNames: [], countryCode: "TR", admin1Name: "Boundary", population: 2000, featureCode: "PPL", distanceToCoastMeters: 10000, isCoastal: false },
];
const documents = prepareCandidateDocuments(records);
const byOrdinal = new Map(documents.map((document) => [document.ordinal, document]));
const identity = { evaluationId: "synthetic-evaluation", shardId: "synthetic-combined" };
const queryFixtureBytes = readFileSync(resolve(process.cwd(), "../../contracts/search-evaluation/v1/fixtures/queries.synthetic.json"));
const adapterEvidenceBytes = readFileSync(resolve(process.cwd(), "src/search/evaluation/evaluation.test.ts"));

describe("search evaluation v1 contracts", () => {
  it("validates neutral synthetic query and report fixtures", () => {
    const ajv = new Ajv2020({ allErrors: true, strict: true });
    expect(ajv.compile(querySchema)(queryFixture)).toBe(true);
    expect(ajv.compile(reportSchema)(reportFixture)).toBe(true);
    expect(reportFixture.selection).toEqual({ status: "deferred", selectedEngineId: null });
    expect(new Set(reportFixture.engines.map(({ engineId }) => engineId))).toEqual(new Set(["minisearch", "flexsearch"]));
  });

  it("enforces cross-field identity, ordering, arithmetic, gaps, metrics, hashes, and evidence", () => {
    validateQueryFixtureSemantics(queryFixture);
    validateEvaluationReportSemantics(reportFixture, queryFixtureBytes, adapterEvidenceBytes);
  });

  it("rejects semantic mutations that JSON Schema cannot express", () => {
    const fixture = structuredClone(queryFixture);
    fixture.cases[1].id = fixture.cases[0].id;
    expect(() => validateQueryFixtureSemantics(fixture)).toThrow(/unique and sorted/);

    const badCount = structuredClone(reportFixture);
    badCount.corpus.uniqueRecords += 1;
    expect(() => validateEvaluationReportSemantics(badCount, queryFixtureBytes, adapterEvidenceBytes)).toThrow(/corpus count/);
    const badMetric = structuredClone(reportFixture);
    badMetric.engines[0].measurements.status = "measured";
    expect(() => validateEvaluationReportSemantics(badMetric, queryFixtureBytes, adapterEvidenceBytes)).toThrow(/measurement status/);
    const badGap = structuredClone(reportFixture);
    badGap.engines[0].quality.knownGapIds = ["unknown-gap"];
    expect(() => validateEvaluationReportSemantics(badGap, queryFixtureBytes, adapterEvidenceBytes)).toThrow(/unknown gap/);
    const badEvidence = structuredClone(reportFixture);
    badEvidence.engines[0].adapterEvidence.sourceSha256 = "f".repeat(64);
    expect(() => validateEvaluationReportSemantics(badEvidence, queryFixtureBytes, adapterEvidenceBytes)).toThrow(/adapter evidence/);
  });

  it("names every required issue #50 query category", () => {
    const categories = new Set(queryFixture.cases.flatMap(({ categories: values }) => values));
    expect(categories).toEqual(new Set(["canonical", "alternate", "diacritic", "transliteration", "duplicate-name", "country-disambiguation", "admin-disambiguation", "inland", "coastal-village", "zero-population", "island", "transcontinental", "negative"]));
  });
});

describe("shared search semantics", () => {
  it("normalizes accents and ranks canonical, alternate, prefix, fuzzy, and stable ties", () => {
    expect(normalizeSearchText("  MÁLAGA  ")).toBe("malaga");
    expect(rankDocuments("malaga", documents)[0].record.placeId).toBe("geonames:900000001");
    expect(rankDocuments("malaga city", documents)[0].record.placeId).toBe("geonames:900000001");
    expect(rankDocuments("mal", documents)[0].record.placeId).toBe("geonames:900000001");
    expect(rankDocuments("malagx", documents)[0].record.placeId).toBe("geonames:900000001");
    expect(rankDocuments("springfield", documents).slice(0, 2).map(({ record }) => record.placeId))
      .toEqual(["geonames:900000003", "geonames:900000004"]);
    expect(rankDocuments("", documents)).toEqual([]);
    expect(rankDocuments("not present", documents)).toEqual([]);
  });

  it("rejects duplicate stable IDs", () => {
    expect(() => prepareCandidateDocuments([...records, records[0]])).toThrow(/duplicate placeId/);
  });

  it("rejects unsafe text and orders numeric ID suffixes", () => {
    expect(() => normalizeSearchText("bad\u0000name")).toThrow(/control/);
    expect(() => normalizeSearchText("bad\ud800name")).toThrow(/unpaired UTF-16/);
    const ordered = prepareCandidateDocuments([
      { ...records[0], placeId: "geonames:900000010" },
      { ...records[1], placeId: "geonames:900000002" },
    ]);
    expect(ordered.map(({ record }) => record.placeId)).toEqual(["geonames:900000002", "geonames:900000010"]);
    expect(() => prepareCandidateDocuments([{ ...records[0], placeId: "synthetic:1" }, records[1]]))
      .toThrow(/mixes placeId namespaces/);
  });

});

describe.each(searchEvaluationAdapters)("$descriptor.engineId adapter", (adapter) => {
  it("builds deterministic bytes and preserves synthetic query outcomes after round trip", () => {
    const first = adapter.serialize(adapter.build(documents, identity));
    const second = adapter.serialize(adapter.build(documents, identity));
    expect(Array.from(first)).toEqual(Array.from(second));
    const reorderedDocuments = documents.map(({ ordinal, record: { placeId, ...record }, terms }) => (
      { terms, record: { ...record, placeId }, ordinal }
    ));
    expect(Array.from(adapter.serialize(adapter.build(reorderedDocuments, identity)))).toEqual(Array.from(first));

    const restored = adapter.deserialize(first, documents, identity);
    for (const fixture of queryFixture.cases) {
      const candidates = adapter.search(restored, fixture.query, 20)
        .map((ordinal) => byOrdinal.get(ordinal)).filter((value) => value !== undefined);
      const actual = rankDocuments(fixture.query, candidates).map(({ record }) => record.placeId);
      expect(actual.slice(0, fixture.expected.exactOrder.length), fixture.id).toEqual(fixture.expected.exactOrder);
      expect(actual[0] ?? null, fixture.id).toBe(fixture.expected.top1PlaceId);
      expect(fixture.expected.top5Contains.every((id) => actual.slice(0, 5).includes(id)), fixture.id).toBe(true);
      expect(fixture.expected.absentPlaceIds.every((id) => !actual.includes(id)), fixture.id).toBe(true);
      if (fixture.expected.resultCount !== null) expect(actual, fixture.id).toHaveLength(fixture.expected.resultCount);
    }
  });
});

describe("serialized compatibility", () => {
  const textDecoder = new TextDecoder();
  const textEncoder = new TextEncoder();

  it("rejects cross-engine and package-version identities", () => {
    const miniBytes = miniSearchAdapter.serialize(miniSearchAdapter.build(documents, identity));
    expect(() => flexSearchAdapter.deserialize(miniBytes, documents, identity)).toThrow(/identity or document binding/);
    const envelope = JSON.parse(textDecoder.decode(miniBytes));
    envelope.engine.packageVersion = "7.2.1";
    expect(() => miniSearchAdapter.deserialize(textEncoder.encode(JSON.stringify(envelope)), documents, identity))
      .toThrow(/identity or document binding/);
  });

  it("rejects incomplete, reordered, and duplicated FlexSearch chunks", () => {
    const flexBytes = flexSearchAdapter.serialize(flexSearchAdapter.build(documents, identity));
    const envelope = JSON.parse(textDecoder.decode(flexBytes));
    envelope.payload.pop();
    expect(() => flexSearchAdapter.deserialize(textEncoder.encode(JSON.stringify(envelope)), documents, identity))
      .toThrow(/export chunks are incompatible/);
    const reordered = JSON.parse(textDecoder.decode(flexBytes));
    reordered.payload.reverse();
    expect(() => flexSearchAdapter.deserialize(textEncoder.encode(JSON.stringify(reordered)), documents, identity)).toThrow(/chunk order/);
    const duplicated = JSON.parse(textDecoder.decode(flexBytes));
    duplicated.payload[1] = duplicated.payload[0];
    expect(() => flexSearchAdapter.deserialize(textEncoder.encode(JSON.stringify(duplicated)), documents, identity)).toThrow(/chunk order/);
  });

  it("rejects corrupt bytes, options drift, extra fields, and a different document corpus", () => {
    const miniBytes = miniSearchAdapter.serialize(miniSearchAdapter.build(documents, identity));
    expect(() => miniSearchAdapter.deserialize(Uint8Array.from([0xc3, 0x28]), documents, identity)).toThrow(/fatal UTF-8/);
    const optionsDrift = JSON.parse(textDecoder.decode(miniBytes));
    optionsDrift.binding.optionsSha256 = "f".repeat(64);
    expect(() => miniSearchAdapter.deserialize(textEncoder.encode(JSON.stringify(optionsDrift)), documents, identity)).toThrow(/document binding/);
    const extraField = JSON.parse(textDecoder.decode(miniBytes));
    extraField.unexpected = true;
    expect(() => miniSearchAdapter.deserialize(textEncoder.encode(JSON.stringify(extraField)), documents, identity)).toThrow(/document binding/);
    const otherDocuments = prepareCandidateDocuments([{ ...records[0], population: 1 }]);
    expect(() => miniSearchAdapter.deserialize(miniBytes, otherDocuments, identity)).toThrow(/document binding/);
  });
});
