// @vitest-environment node

import { createHash } from "node:crypto";
import fs, { mkdtempSync, mkdirSync, readFileSync, statSync, symlinkSync, writeFileSync } from "node:fs";
import { syncBuiltinESMExports } from "node:module";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { spawnSync } from "node:child_process";
import { brotliCompressSync, brotliDecompressSync, constants as zlibConstants } from "node:zlib";
import { describe, expect, it, vi } from "vitest";
import {
  BOUNDED_SEARCH_WORK_LIMIT,
  boundedTrieAdapter,
} from "../evaluation/adapters";
import { prepareCandidateDocuments, rankDocuments } from "../evaluation/search";
import {
  BrowserShardError,
  DEFAULT_SHARD_LIMITS,
  SHARD_FILENAMES,
  SHARD_RECEIPT_FILENAME,
  buildBrowserSearchShards,
  decodeBrowserShard,
  loadBrowserSearchShards,
  mergeCoreFirst,
  searchBrowserShard,
  validateBrowserSearchShards,
} from "./browser-shards";

const fixture = resolve(process.cwd(), "src/search/shards/fixtures/projection.synthetic.ndjson");
const spatialReceipt = resolve(
  process.cwd(), "src/search/shards/fixtures/spatial-receipt.synthetic.json"
);
const dataReleaseId = "searise-europe-v1.0.0-20260812-0123456789ab";
const temporary = () => mkdtempSync(join(tmpdir(), "searise-browser-shards-"));
const canonicalBrotli = (raw: Buffer) => brotliCompressSync(raw, { params: {
  [zlibConstants.BROTLI_PARAM_MODE]: zlibConstants.BROTLI_MODE_TEXT,
  [zlibConstants.BROTLI_PARAM_QUALITY]: 11,
  [zlibConstants.BROTLI_PARAM_SIZE_HINT]: raw.length,
} });
const digest = (value: string | Buffer) => createHash("sha256").update(value).digest("hex");
const canonicalJson = (value: unknown): string => {
  if (value === null || typeof value !== "object") return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(",")}]`;
  return `{${Object.entries(value).sort(([a], [b]) => a.localeCompare(b))
    .map(([key, item]) => `${JSON.stringify(key)}:${canonicalJson(item)}`).join(",")}}`;
};

function withFsPatch<T>(patch: Record<string, unknown>, action: () => T): T {
  const mutable = fs as unknown as Record<string, unknown>;
  const originals = Object.fromEntries(Object.keys(patch).map((key) => [key, mutable[key]]));
  Object.assign(mutable, patch); syncBuiltinESMExports();
  try { return action(); } finally { Object.assign(mutable, originals); syncBuiltinESMExports(); }
}

function withRuntimeVersion<T>(
  name: keyof NodeJS.ProcessVersions, value: string, action: () => T,
): T {
  const original = Object.getOwnPropertyDescriptor(process.versions, name);
  if (!original) throw new Error(`missing runtime version ${name}`);
  Object.defineProperty(process.versions, name, { ...original, value });
  try { return action(); } finally { Object.defineProperty(process.versions, name, original); }
}

function build(): { output: string; core: Buffer; coastal: Buffer } {
  const output = temporary();
  buildBrowserSearchShards(fixture, spatialReceipt, dataReleaseId, output);
  return {
    output,
    core: readFileSync(join(output, SHARD_FILENAMES["europe-core"])),
    coastal: readFileSync(join(output, SHARD_FILENAMES["europe-coastal"])),
  };
}

function projectionFrom(
  mutate: (header: Record<string, unknown>, documents: Array<Record<string, any>>) => void,
): { projection: string; output: string } {
  const values = readFileSync(fixture, "utf8").trimEnd().split("\n").map((line) => JSON.parse(line));
  const header = values[0] as Record<string, unknown>;
  const documents = values.slice(1, -1) as Array<Record<string, any>>;
  mutate(header, documents);
  const lines = documents.map((document) => canonicalJson(document));
  const documentsSha256 = digest(lines.map((line) => `${line}\n`).join(""));
  const footer = {
    deterministicIdentity: digest(`${canonicalJson({
      documentsSha256, header, recordCount: documents.length,
    })}\n`), documentsSha256, kind: "settlement-search-projection-footer",
    recordCount: documents.length,
  };
  const root = temporary(); const projection = join(root, "projection.ndjson");
  const output = join(root, "output"); mkdirSync(output);
  writeFileSync(projection, `${[canonicalJson(header), ...lines, canonicalJson(footer)].join("\n")}\n`);
  return { projection, output };
}

describe("receipt-bound browser search shards", () => {
  it("builds deterministic Brotli code-point-trie shards with exact false claims", () => {
    const first = build();
    const second = build();
    expect(first.core).toEqual(second.core);
    expect(first.coastal).toEqual(second.coastal);
    expect(validateBrowserSearchShards(
      fixture, spatialReceipt, dataReleaseId, first.output
    )).toMatchObject({
      "europe-core": { recordCount: 2 },
      "europe-coastal": { recordCount: 2 },
    });

    const core = decodeBrowserShard(first.core, "europe-core", dataReleaseId);
    expect(core.engine).toEqual({
      engineId: "searise-codepoint-trie", packageVersion: "1.0.0",
      serializationVersion: "codepoint-trie-json-v1",
    });
    expect(core.runtime).toEqual({
      brotli: "1.1.0", icu: "78.2", node: "20.20.1", unicode: "17.0",
      zlib: "1.3.1-e00f703",
    });
    expect(core.source).toMatchObject({
      spatialDatabaseSha256: "a".repeat(64),
      spatialReceiptSha256: digest(readFileSync(spatialReceipt)),
    });
    expect(core).toMatchObject({
      $schema:
        "https://artemsemdev.github.io/SeaRise-Europe/contracts/settlements/v4/search-artifact.schema.json",
      schemaVersion: "4.0.0",
      formatVersion: "settlement-browser-search-shard-v2",
      dataReleaseId,
      artifactType: "settlement-browser-search-shard",
      contentEncoding: "br",
      catalogMembership: "europe-core",
      normalizationVersion: "settlement-normalization-v2",
      spatialIdentity: {
        supportGeometry: { artifactId: "fixture-support", sha256: "1".repeat(64), version: "v1" },
        coastalGeometry: { artifactId: "fixture-coastal", sha256: "2".repeat(64), version: "v1" },
        shorelineGeometry: { artifactId: "fixture-shoreline", sha256: "3".repeat(64), version: "v1" },
        predicate: "covers",
        distanceMethodVersion: "epsg3035-planar-whole-meter-half-even-v1",
      },
    });
    expect(core.records.map(({ placeId }) => placeId)).toEqual(["geonames:101", "geonames:104"]);
    expect([
      core.productionClaim, core.publicationClaim, core.publicationEligible,
      core.ownerApprovalClaim, core.scientificApprovalClaim, core.canonicalGeometryClaim,
      core.hazardExtentClaim, core.signingClaim,
    ]).toEqual(Array(8).fill(false));
  });

  it("rejects a nonofficial Node runtime library profile", () => {
    withRuntimeVersion("brotli", "1.2.0", () => {
      expect(() => buildBrowserSearchShards(
        fixture, spatialReceipt, dataReleaseId, temporary()
      ))
        .toThrow(/runtime brotli differs from its exact binding/);
    });
  });

  it("restores both indexes and merges core first without duplicate place IDs", () => {
    const built = build();
    const core = decodeBrowserShard(built.core, "europe-core", dataReleaseId);
    const coastal = decodeBrowserShard(built.coastal, "europe-coastal", dataReleaseId);
    expect(searchBrowserShard(core, "alpha alt").map(({ placeId }) => placeId))
      .toEqual(["geonames:101"]);
    const coreMatches = searchBrowserShard(core, "charlie");
    const coastalMatches = searchBrowserShard(coastal, "charlie");
    expect(mergeCoreFirst(coreMatches, coastalMatches, 5).map(({ placeId }) => placeId))
      .toEqual(["geonames:104"]);
    expect(() => mergeCoreFirst([...coreMatches, ...coreMatches], coastalMatches, 5))
      .toThrow(/core results contain a duplicate/);
    expect(() => mergeCoreFirst(coreMatches, coastalMatches, 101)).toThrow(/result cap/);
    expect(() => searchBrowserShard(core, "x".repeat(257))).toThrow(/query exceeds/);
  });

  it("reuses decoded runtime state and rejects unvalidated structural copies", () => {
    const built = build();
    const core = decodeBrowserShard(built.core, "europe-core", dataReleaseId);
    const deserialize = vi.spyOn(boundedTrieAdapter, "deserialize");
    const prepare = vi.spyOn(boundedTrieAdapter, "build");
    try {
      expect(searchBrowserShard(core, "alpha")).toHaveLength(1);
      expect(searchBrowserShard(core, "charlie")).toHaveLength(1);
      expect(deserialize).not.toHaveBeenCalled();
      expect(prepare).not.toHaveBeenCalled();
      expect(() => searchBrowserShard(structuredClone(core), "alpha")).toThrow(/not validated/);
    } finally {
      deserialize.mockRestore(); prepare.mockRestore();
    }
  });

  it("bounds fuzzy distance work for many long alternate names", () => {
    const candidates = prepareCandidateDocuments(Array.from({ length: 100 }, (_, index) => ({
      placeId: `synthetic:${index + 100}`,
      displayName: `${"q".repeat(250)}${index}`,
      searchNames: Array.from({ length: 64 }, (_, alternate) =>
        `${"z".repeat(248)}${String(alternate).padStart(2, "0")}`),
      countryCode: "AA", admin1Name: null, population: 1, featureCode: "PPL",
      distanceToCoastMeters: 1, isCoastal: false,
    })));
    expect(rankDocuments("x".repeat(250), candidates)).toEqual([]);
  });

  it.each([
    ["Cafe\u0301", "Café", "Latn"],
    ["東京ー", "東京ー", "Jpan"],
  ])("consumes producer-emitted source and script metadata for %s", (source, canonical, script) => {
    const { projection, output } = projectionFrom((_header, documents) => {
      const document = documents[0];
      document.sourceSpelling = source; document.canonicalName = { language: null, script, value: canonical };
      document.asciiName = "Cafe"; document.admin1Name = "Exam\u0301ple";
    });
    buildBrowserSearchShards(projection, spatialReceipt, dataReleaseId, output);
    const record = loadBrowserSearchShards(
      projection, spatialReceipt, dataReleaseId, output
    ).shards["europe-core"].shard.records[0];
    expect(record.displayName).toBe(canonical);
    expect(record.admin1Name).toBe("Exaḿple");
  });

  it("retrieves an advertised two-edit fuzzy match", () => {
    const { projection, output } = projectionFrom((_header, documents) => {
      const document = documents[0];
      document.sourceSpelling = document.canonicalName.value = document.asciiName = "Springfield";
    });
    buildBrowserSearchShards(projection, spatialReceipt, dataReleaseId, output);
    const shard = loadBrowserSearchShards(
      projection, spatialReceipt, dataReleaseId, output
    ).shards["europe-core"].shard;
    expect(searchBrowserShard(shard, "sprangfiold")[0]?.placeId).toBe("geonames:101");
  });

  it.each([
    ["New York", "newyork"],
    [`abcdefgh\u{10428}\u{10429}`, `abcdefgh\u{1e922}\u{1e923}`],
  ])("uses the ranker's exact code-point distance for %s", (name, query) => {
    const { projection, output } = projectionFrom((_header, documents) => {
      const document = documents[0];
      document.sourceSpelling = document.canonicalName.value = document.asciiName = name;
      document.canonicalName.script = null;
    });
    buildBrowserSearchShards(projection, spatialReceipt, dataReleaseId, output);
    const shard = loadBrowserSearchShards(
      projection, spatialReceipt, dataReleaseId, output
    ).shards["europe-core"].shard;
    expect(searchBrowserShard(shard, query)[0]?.placeId).toBe("geonames:101");
  });

  it("hands receipt-gated decoded bytes to the consumer without reopening paths", () => {
    const built = build();
    const loaded = loadBrowserSearchShards(
      fixture, spatialReceipt, dataReleaseId, built.output
    );
    writeFileSync(join(built.output, SHARD_FILENAMES["europe-core"]), "changed after handoff");
    writeFileSync(join(built.output, SHARD_RECEIPT_FILENAME), "changed after handoff");
    expect(loaded.shards["europe-core"].bytes).toEqual(built.core);
    expect(searchBrowserShard(loaded.shards["europe-core"].shard, "alpha")
      .map(({ placeId }) => placeId)).toEqual(["geonames:101"]);
  });

  it("rejects a symlinked output root at the consumer handoff", () => {
    const built = build(); const alias = join(temporary(), "artifact-set");
    symlinkSync(built.output, alias);
    expect(() => loadBrowserSearchShards(
      fixture, spatialReceipt, dataReleaseId, alias
    )).toThrow(/filesystem helper failed/);
  });

  it("rejects cross-release and cross-source authority drift", () => {
    const built = build();
    expect(() => loadBrowserSearchShards(
      fixture, spatialReceipt, "searise-europe-v1.0.1-20260812-0123456789ab", built.output
    )).toThrow(/exact projection, receipt, or release|unsafe/);
    expect(() => decodeBrowserShard(
      built.core, "europe-core", "searise-europe-v1.0.1-20260812-0123456789ab"
    )).toThrow(/format/);
    const root = temporary();
    const changedReceipt = join(root, "spatial-receipt.json");
    writeFileSync(changedReceipt, readFileSync(spatialReceipt).toString("utf8").replace(
      '"fixture-support"', '"different-support"'
    ));
    expect(() => buildBrowserSearchShards(
      fixture, changedReceipt, dataReleaseId, root
    )).toThrow(/receipt authority differs/);
  });

  it("rejects incompatible shard format and changed exact bytes", () => {
    const built = build();
    const raw = brotliDecompressSync(built.core).toString("utf8");
    const incompatible = canonicalBrotli(Buffer.from(raw.replace(
      "settlement-browser-search-shard-v2", "settlement-browser-search-shard-v3"
    )));
    expect(() => decodeBrowserShard(
      incompatible, "europe-core", dataReleaseId
    )).toThrow(/format/);

    writeFileSync(join(built.output, SHARD_FILENAMES["europe-core"]), incompatible);
    expect(() => validateBrowserSearchShards(
      fixture, spatialReceipt, dataReleaseId, built.output
    )).toThrow(/unsafe|exact projection/);
  });

  it.each(["duplicate", "reordered", "footer", "schema", "noncanonical", "duplicate-key"])(
    "rejects %s projection drift before writing outputs",
    (mutation) => {
      const lines = readFileSync(fixture, "utf8").trimEnd().split("\n");
      if (mutation === "duplicate") lines.splice(2, 0, lines[1]);
      if (mutation === "reordered") [lines[1], lines[2]] = [lines[2], lines[1]];
      if (mutation === "footer") lines[lines.length - 1] = lines.at(-1)!.replace('"recordCount":3', '"recordCount":4');
      if (mutation === "schema") lines[0] = lines[0].replace(PROJECTION_VERSION, "unknown-projection-v1");
      if (mutation === "noncanonical") lines[0] = ` ${lines[0]}`;
      if (mutation === "duplicate-key") lines[0] =
        `{"kind":"settlement-search-projection-header",${lines[0].slice(1)}`;
      const root = temporary();
      const projection = join(root, "projection.ndjson");
      const output = join(root, "output");
      mkdirSync(output);
      writeFileSync(projection, `${lines.join("\n")}\n`);
      expect(() => buildBrowserSearchShards(
        projection, spatialReceipt, dataReleaseId, output
      )).toThrow(BrowserShardError);
      expect(() => statSync(join(output, SHARD_FILENAMES["europe-core"]))).toThrow();
    }
  );

  it.each(["admin1Code", "sourceUpdatedAt", "lineage", "canonicalLanguage"])(
    "rejects malformed %s projection metadata",
    (mutation) => {
      const values = readFileSync(fixture, "utf8").trimEnd().split("\n")
        .map((line) => JSON.parse(line));
      const header = values[0]; const documents = values.slice(1, -1); const document = documents[0];
      if (mutation === "admin1Code") document.admin1Code = 17;
      if (mutation === "sourceUpdatedAt") document.sourceUpdatedAt = { unexpected: true };
      if (mutation === "lineage") document.lineage = [null];
      if (mutation === "canonicalLanguage") document.canonicalName.language = 99;
      const lines = documents.map((document) => JSON.stringify(document));
      const documentsSha256 = digest(lines.map((line) => `${line}\n`).join(""));
      const footer = {
        deterministicIdentity: digest(`${canonicalJson({
          documentsSha256, header, recordCount: documents.length,
        })}\n`), documentsSha256, kind: "settlement-search-projection-footer",
        recordCount: documents.length,
      };
      const root = temporary(); const projection = join(root, "projection.ndjson");
      const output = join(root, "output"); mkdirSync(output);
      writeFileSync(projection, `${[JSON.stringify(header), ...lines, JSON.stringify(footer)].join("\n")}\n`);
      expect(() => buildBrowserSearchShards(
        projection, spatialReceipt, dataReleaseId, output
      )).toThrow(/document (fields|values)/);
    }
  );

  it.each([
    "calendar-date", "year-zero", "feature-code", "empty-ascii", "empty-admin", "duplicate-alternate",
    "canonical-language", "script", "source-spelling", "first-lineage-id", "lineage-pin",
    "lineage-order", "missing-alternate-lineage", "provenance", "geometry", "stage-version",
  ])("rejects producer-impossible or public-contract-invalid %s semantics", (mutation) => {
    const { projection, output } = projectionFrom((header, documents) => {
      const document = documents[0];
      if (mutation === "calendar-date") document.sourceUpdatedAt = "2026-99-99";
      if (mutation === "year-zero") document.sourceUpdatedAt = "0000-01-01";
      if (mutation === "feature-code") document.featureCode = "PPLX";
      if (mutation === "empty-ascii") document.asciiName = "";
      if (mutation === "empty-admin") document.admin1Name = "";
      if (mutation === "duplicate-alternate") {
        document.alternateNames.push(structuredClone(document.alternateNames[0]));
        document.lineage.push({ ...document.lineage.at(-1), source_line: 9101, source_record_id: 9101 });
      }
      if (mutation === "canonical-language") document.canonicalName.language = "en";
      if (mutation === "script") document.canonicalName.script = "Unknown";
      if (mutation === "source-spelling") document.sourceSpelling = "Different";
      if (mutation === "first-lineage-id") document.lineage[0].source_record_id = 999;
      if (mutation === "lineage-pin") document.lineage[0].source_sha256 = "0".repeat(64);
      if (mutation === "lineage-order") [document.lineage[0], document.lineage[1]] = [
        document.lineage[1], document.lineage[0],
      ];
      if (mutation === "missing-alternate-lineage") document.lineage.pop();
      if (mutation === "provenance") header.dataProvenanceClass = "unknown";
      if (mutation === "geometry") header.geometryStatus = "canonical";
      if (mutation === "stage-version") {
        (header.source as Record<string, unknown>).spatialStageSchemaVersion = "unknown";
      }
    });
    expect(() => buildBrowserSearchShards(
      projection, spatialReceipt, dataReleaseId, output
    )).toThrow(BrowserShardError);
    expect(() => statSync(join(output, SHARD_FILENAMES["europe-core"]))).toThrow();
  });

  it("preserves an intentional empty internal-audit membership", () => {
    const { projection, output } = projectionFrom((_header, documents) => {
      documents[0].population = null;
      documents[0].spatialClassification.catalogMembership = [];
    });
    expect(() => buildBrowserSearchShards(
      projection, spatialReceipt, dataReleaseId, output
    )).not.toThrow();
  });

  it.each(["single-name", "alternate-count", "record-names"])(
    "enforces the corpus-derived %s resource bound", (mutation) => {
      const { projection, output } = projectionFrom((_header, documents) => {
        const document = documents[0];
        if (mutation === "single-name") {
          document.sourceSpelling = "A".repeat(257);
          document.canonicalName.value = document.sourceSpelling;
          document.asciiName = document.sourceSpelling;
        } else {
          const count = mutation === "alternate-count" ? 1025 : 65;
          document.alternateNames = Array.from({ length: count }, (_, index) => ({
            language: "en", script: "Latn", value: `${"A".repeat(250)}${String(index).padStart(6, "0")}`,
          }));
          document.lineage = [document.lineage[0], document.lineage[1],
            ...Array.from({ length: count }, (_, index) => ({
              ...document.lineage[2], source_line: 20_000 + index, source_record_id: 20_000 + index,
            }))];
        }
      });
      expect(() => buildBrowserSearchShards(
        projection, spatialReceipt, dataReleaseId, output
      )).toThrow(/limit|bounded|alternate/);
    }
  );

  it("caps candidates and does not lose a later exact multi-word match", () => {
    const { projection, output } = projectionFrom((_header, documents) => {
      const template = documents[0];
      documents.splice(0, documents.length, ...Array.from({ length: 150 }, (_, index) => {
        const id = 1000 + index;
        const document = structuredClone(template);
        document.placeId = `geonames:${id}`;
        document.sourceSpelling = index === 149 ? "Common Rare" : `Common Place ${id}`;
        document.canonicalName.value = document.sourceSpelling;
        document.asciiName = document.sourceSpelling;
        document.alternateNames = [];
        document.lineage = [{
          ...document.lineage[0], source_line: id, source_record_id: id,
        }, { ...document.lineage[1], source_line: id + 10_000, source_record_id: id + 10_000 }];
        return document;
      }));
    });
    buildBrowserSearchShards(projection, spatialReceipt, dataReleaseId, output);
    const loaded = loadBrowserSearchShards(
      projection, spatialReceipt, dataReleaseId, output
    );
    expect(searchBrowserShard(loaded.shards["europe-core"].shard, "common")).toHaveLength(100);
    expect(searchBrowserShard(loaded.shards["europe-core"].shard, "common rare")
      .map(({ placeId }) => placeId)).toEqual(["geonames:1149"]);
  });

  it("applies the candidate cap after global qualified-match ranking", () => {
    const records = [
      ...Array.from({ length: 128 }, (_, index) => ({
        placeId: `synthetic:${index + 1}`, displayName: "New", searchNames: [],
        countryCode: "US", admin1Name: "York", population: 1, featureCode: "PPL",
        distanceToCoastMeters: 1, isCoastal: false,
      })),
      {
        placeId: "synthetic:1000", displayName: "New York", searchNames: [],
        countryCode: "US", admin1Name: "Other", population: 1_000_000, featureCode: "PPL",
        distanceToCoastMeters: 1, isCoastal: false,
      },
    ];
    const documents = prepareCandidateDocuments(records);
    const index = boundedTrieAdapter.build(documents, {
      evaluationId: "bounded-audit", shardId: "qualified",
    });
    const matches = boundedTrieAdapter.search(index, "new york us", 128)
      .map((ordinal) => documents.find((document) => document.ordinal === ordinal)!);
    expect(matches).toHaveLength(128);
    expect(rankDocuments("new york us", matches)[0].record.placeId).toBe("synthetic:1000");
  });

  it("applies the candidate cap after global full-name fuzzy ranking", () => {
    const records = [
      ...Array.from({ length: 128 }, (_, index) => ({
        placeId: `synthetic:${index + 1}`, displayName: "llmmmmmm", searchNames: [],
        countryCode: "AA", admin1Name: null, population: 1, featureCode: "PPL",
        distanceToCoastMeters: 1, isCoastal: false,
      })),
      {
        placeId: "synthetic:1000", displayName: "lmmmmmmm", searchNames: [],
        countryCode: "AA", admin1Name: null, population: 1_000_000, featureCode: "PPL",
        distanceToCoastMeters: 1, isCoastal: false,
      },
    ];
    const documents = prepareCandidateDocuments(records);
    const index = boundedTrieAdapter.build(documents, {
      evaluationId: "bounded-audit", shardId: "fuzzy-rank",
    });
    const matches = boundedTrieAdapter.search(index, "mmmmmmmm", 128)
      .map((ordinal) => documents.find((document) => document.ordinal === ordinal)!);
    expect(matches).toHaveLength(128);
    expect(rankDocuments("mmmmmmmm", matches)[0].record.placeId).toBe("synthetic:1000");
  });

  it("bounds fuzzy term traversal before an unbounded match map can materialize", () => {
    const characters = Array.from({ length: 501 }, (_, index) => String.fromCodePoint(0x4e00 + index));
    const searchNames: string[] = [];
    outer: for (const left of characters) {
      for (const right of characters) {
        searchNames.push(`aaaaaa${left}${right}`);
        if (searchNames.length === BOUNDED_SEARCH_WORK_LIMIT + 1) break outer;
      }
    }
    const record = {
      placeId: "synthetic:1", displayName: searchNames[0], searchNames,
      countryCode: "AA", admin1Name: null, population: 1, featureCode: "PPL",
      distanceToCoastMeters: 1, isCoastal: false,
    };
    const documents = prepareCandidateDocuments([record]);
    const index = boundedTrieAdapter.build(documents, { evaluationId: "bounded-audit", shardId: "fuzzy" });
    expect(() => boundedTrieAdapter.search(index, "aaaaaaaa", BOUNDED_SEARCH_WORK_LIMIT + 1))
      .toThrow(/traversal-work limit/);
  });

  it("applies public-contract value checks when decoding standalone shards", () => {
    const built = build();
    for (const mutation of ["feature", "provenance"] as const) {
      const value = JSON.parse(brotliDecompressSync(built.core).toString("utf8"));
      if (mutation === "feature") {
        value.records[0].featureCode = "PPLX";
        value.recordsSha256 = digest(canonicalJson(value.records));
      } else value.dataProvenanceClass = "unknown";
      expect(() => decodeBrowserShard(
        canonicalBrotli(Buffer.from(canonicalJson(value))), "europe-core", dataReleaseId
      ))
        .toThrow(BrowserShardError);
    }
  });

  it.each([[50, "50.0"], [0.00001, "1e-05"]])(
    "accepts producer-canonical coordinate %s encoded as %s", (coordinate, encoded) => {
      const values = readFileSync(fixture, "utf8").trimEnd().split("\n").map((line) => JSON.parse(line));
      const header = values[0]; const documents = values.slice(1, -1);
      documents[0].location.latitude = coordinate;
      const lines = documents.map((document) => JSON.stringify(document));
      lines[0] = lines[0].replace(`"latitude":${JSON.stringify(coordinate)}`, `"latitude":${encoded}`);
      const documentsSha256 = digest(lines.map((line) => `${line}\n`).join(""));
      const footer = {
        deterministicIdentity: digest(`${canonicalJson({
          documentsSha256, header, recordCount: documents.length,
        })}\n`), documentsSha256, kind: "settlement-search-projection-footer",
        recordCount: documents.length,
      };
      const root = temporary(); const projection = join(root, "projection.ndjson");
      const output = join(root, "output"); mkdirSync(output);
      writeFileSync(projection, `${[JSON.stringify(header), ...lines, JSON.stringify(footer)].join("\n")}\n`);
      expect(() => buildBrowserSearchShards(
        projection, spatialReceipt, dataReleaseId, output
      )).not.toThrow();
    }
  );

  it("enforces bounded input and rejects symlinks and existing outputs", () => {
    const root = temporary();
    const linked = join(root, "projection.ndjson");
    symlinkSync(fixture, linked);
    expect(() => buildBrowserSearchShards(
      linked, spatialReceipt, dataReleaseId, root
    )).toThrow(/non-symlink/);
    expect(() => buildBrowserSearchShards(fixture, spatialReceipt, dataReleaseId, root, {
      ...DEFAULT_SHARD_LIMITS,
      maxProjectionBytes: statSync(fixture).size - 1,
    })).toThrow(/bounded|byte limit/);
    expect(() => buildBrowserSearchShards(fixture, spatialReceipt, dataReleaseId, root, {
      ...DEFAULT_SHARD_LIMITS, maxRecords: DEFAULT_SHARD_LIMITS.maxRecords + 1,
    })).toThrow(/hard cap/);
    expect(() => buildBrowserSearchShards(fixture, spatialReceipt, dataReleaseId, root, {
      maxRecords: 3,
    } as typeof DEFAULT_SHARD_LIMITS)).toThrow(/limit fields/);

    const existing = join(root, SHARD_FILENAMES["europe-core"]);
    writeFileSync(existing, "preserve");
    expect(() => buildBrowserSearchShards(
      fixture, spatialReceipt, dataReleaseId, root
    )).toThrow(/overwrite/);
    expect(readFileSync(existing, "utf8")).toBe("preserve");
    expect(() => statSync(join(root, SHARD_FILENAMES["europe-coastal"]))).toThrow();
  });

  it("rejects same-inode source mutation with nanosecond identity", () => {
    const root = temporary(); const projection = join(root, "projection.ndjson");
    writeFileSync(projection, readFileSync(fixture)); mkdirSync(join(root, "source-output"));
    const originalRead = fs.readSync; let changed = false;
    withFsPatch({ readSync: (...args: Parameters<typeof fs.readSync>) => {
      const length = originalRead(...args);
      if (!changed && length) { changed = true; const bytes = readFileSync(projection);
        const altered = Buffer.from(bytes); altered[10] ^= 1; writeFileSync(projection, altered);
        writeFileSync(projection, bytes); fs.utimesSync(projection, new Date(), new Date(Date.now() + 1000)); }
      return length;
    } }, () => expect(() => buildBrowserSearchShards(
      projection, spatialReceipt, dataReleaseId, join(root, "source-output")
    ))
      .toThrow(/changed while read/));
  });

  it("passes descriptor-relative displacement, rollback, receipt, and fsync probes", () => {
    const result = spawnSync("python3", [resolve(process.cwd(), "scripts/test-browser-shard-fs.py")], {
      encoding: "utf8", env: { ...process.env, PYTHONDONTWRITEBYTECODE: "1" },
    });
    expect(result.status, result.stderr).toBe(0);
    expect(result.stdout).toContain("adversarial checks passed");
  });

  it("rejects alternate Brotli parameters and reordered records", () => {
    const built = build(); const raw = brotliDecompressSync(built.core);
    const alternate = brotliCompressSync(raw, { params: {
      [zlibConstants.BROTLI_PARAM_MODE]: zlibConstants.BROTLI_MODE_TEXT,
      [zlibConstants.BROTLI_PARAM_QUALITY]: 4,
    } });
    expect(() => decodeBrowserShard(
      alternate, "europe-core", dataReleaseId
    )).toThrow(/canonical quality-11/);
    const value = JSON.parse(raw.toString("utf8")); value.records.reverse();
    value.records.forEach((record: { ordinal: number }, index: number) => { record.ordinal = index + 1; });
    value.recordsSha256 = createHash("sha256").update(JSON.stringify(value.records)).digest("hex");
    expect(() => decodeBrowserShard(
      canonicalBrotli(Buffer.from(JSON.stringify(value))), "europe-core", dataReleaseId
    ))
      .toThrow(/record values differ/);

    const tampered = JSON.parse(raw.toString("utf8"));
    const envelope = JSON.parse(Buffer.from(tampered.indexBase64, "base64").toString("utf8"));
    envelope.payload.entries[0][0] = "zzzz";
    tampered.indexBase64 = Buffer.from(JSON.stringify(envelope)).toString("base64");
    expect(() => decodeBrowserShard(
      canonicalBrotli(Buffer.from(JSON.stringify(tampered))), "europe-core", dataReleaseId
    )).toThrow(/index differs from its exact records/);
  });

  it("provides build and validation CLI commands", () => {
    const output = temporary();
    const script = resolve(process.cwd(), "scripts/build-settlement-search-shards.ts");
    for (const command of ["build", "validate"]) {
      const result = spawnSync(process.execPath, [
        "--import", "tsx", script, command,
        "--projection", fixture, "--spatial-receipt", spatialReceipt,
        "--data-release-id", dataReleaseId, "--output-dir", output,
      ], { encoding: "utf8" });
      expect(result.status, result.stderr).toBe(0);
      expect(JSON.parse(result.stdout)).toHaveProperty("europe-core");
    }
  });
});

const PROJECTION_VERSION = "settlement-search-projection-v1";
