// @vitest-environment node

import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { brotliDecompressSync } from "node:zlib";
import { describe, expect, it } from "vitest";
import manifest from "../../../../contracts/release/v1/fixtures/release/searise-europe-v1.0.0-20260810-c096aeab4e09/manifest.json";
import queryFixture from "../../../../contracts/search-evaluation/v1/fixtures/queries.synthetic.json";
import { mergeRankedResults, normalizeSearchText } from "./ranking";
import { canonicalJson } from "./contract";
import { assertCompatibleShardSet, decodeSearchShard, searchShard, verifySearchArtifactBytes } from "./runtime";
import type { SearchShardAuthority, SearchShardId } from "./types";

const releaseRoot = resolve(
  process.cwd(),
  "../../contracts/release/v1/fixtures/release",
  manifest.dataReleaseId,
);

function fixture(shardId: SearchShardId) {
  const artifact = manifest.artifacts.find(({ artifactId }) => artifactId === `settlements-${shardId}`)!;
  const raw = readFileSync(resolve(releaseRoot, artifact.path));
  const authority: SearchShardAuthority = {
    shardId,
    dataReleaseId: manifest.dataReleaseId,
    dataProvenanceClass: "synthetic-fixture",
    artifact: {
      artifactId: artifact.artifactId,
      byteSize: artifact.byteSize,
      sha256: artifact.sha256,
      url: `https://fixture.invalid/releases/${manifest.dataReleaseId}/${artifact.path}`,
    },
  };
  return { authority, raw, decoded: new Uint8Array(brotliDecompressSync(raw)) };
}

interface TestShardDocument {
  recordsSha256: string;
  runtime: Record<string, unknown>;
  ranking: Record<string, unknown>;
  merge: Record<string, unknown>;
  spatialIdentity: Record<string, unknown>;
  source: Record<string, unknown>;
  indexBase64: string;
}

function mutate(
  value: ReturnType<typeof fixture>,
  change: (document: TestShardDocument) => void,
): Uint8Array {
  const document = JSON.parse(new TextDecoder().decode(value.decoded)) as TestShardDocument;
  change(document);
  return new TextEncoder().encode(canonicalJson(document));
}

describe("release-bound settlement search runtime", () => {
  it("preserves the canonical synthetic ranking controls across core and coastal shards", async () => {
    const coreFixture = fixture("europe-core");
    const coastalFixture = fixture("europe-coastal");
    await verifySearchArtifactBytes(coreFixture.raw, coreFixture.authority);
    await verifySearchArtifactBytes(coastalFixture.raw, coastalFixture.authority);
    const core = await decodeSearchShard(coreFixture.decoded, coreFixture.authority);
    const coastal = await decodeSearchShard(coastalFixture.decoded, coastalFixture.authority);
    expect(() => assertCompatibleShardSet(core, coastal)).not.toThrow();

    for (const testCase of queryFixture.cases) {
      const actual = mergeRankedResults(
        searchShard(core, testCase.query),
        testCase.phase === "core-ready" ? [] : searchShard(coastal, testCase.query),
      ).map(({ placeId }) => placeId);
      expect(actual[0] ?? null, testCase.id).toBe(testCase.expected.top1PlaceId);
      expect(actual.slice(0, testCase.expected.exactOrder.length), testCase.id)
        .toEqual(testCase.expected.exactOrder);
      expect(testCase.expected.top5Contains.every((id) => actual.slice(0, 5).includes(id)), testCase.id)
        .toBe(true);
      expect(testCase.expected.absentPlaceIds.every((id) => !actual.includes(id)), testCase.id)
        .toBe(true);
    }
  });

  it("keeps source spelling and exact coordinates while folding accents and provider transliterations", async () => {
    const coreFixture = fixture("europe-core");
    const core = await decodeSearchShard(coreFixture.decoded, coreFixture.authority);
    expect(normalizeSearchText("  MÁLAGA  ")).toBe("malaga");
    expect(searchShard(core, "malagx")[0].record).toMatchObject({
      placeId: "geonames:900000001",
      displayName: "Málaga",
      latitude: 36.7213,
      longitude: -4.4214,
    });
    expect(searchShard(core, "Athens")[0].record.displayName).toBe("Αθήνα");
  });

  it("deduplicates overlap and appends unseen coastal results after core results", async () => {
    const coreFixture = fixture("europe-core");
    const coastalFixture = fixture("europe-coastal");
    const core = await decodeSearchShard(coreFixture.decoded, coreFixture.authority);
    const coastal = await decodeSearchShard(coastalFixture.decoded, coastalFixture.authority);
    expect(mergeRankedResults(searchShard(core, "Málaga"), searchShard(coastal, "Málaga")))
      .toHaveLength(1);
    expect(mergeRankedResults(searchShard(core, "Springfield"), searchShard(coastal, "Springfield"))
      .map(({ placeId }) => placeId)).toEqual(["geonames:900000003", "geonames:900000004"]);
  });

  it("fails closed on changed bytes, cross-release authority, and unsafe query text", async () => {
    const value = fixture("europe-core");
    const changed = Uint8Array.from(value.raw);
    changed[0] ^= 1;
    await expect(verifySearchArtifactBytes(changed, value.authority)).rejects.toThrow(/pinned release authority/);
    await expect(decodeSearchShard(value.decoded, { ...value.authority, dataReleaseId: "searise-europe-v1.0.0-20260810-aaaaaaaaaaaa" }))
      .rejects.toThrow(/authoritative v4 schema/);
    const runtime = await decodeSearchShard(value.decoded, value.authority);
    expect(() => searchShard(runtime, "bad\u0000query")).toThrow(/control characters/);
  });

  it.each([
    ["recordsSha256", (document: TestShardDocument) => { document.recordsSha256 = "0".repeat(64); }],
    ["runtime identity", (document: TestShardDocument) => { document.runtime.unicode = "16.0"; }],
    ["ranking identity", (document: TestShardDocument) => { document.ranking.resultLimit = 10; }],
    ["merge identity", (document: TestShardDocument) => { document.merge.resultOrder = "global-rerank"; }],
    ["spatial identity", (document: TestShardDocument) => { document.spatialIdentity.predicate = "intersects"; }],
    ["source identity", (document: TestShardDocument) => { document.source.projectionSchemaVersion = "unreviewed"; }],
    ["index binding", (document: TestShardDocument) => {
      const envelope = JSON.parse(Buffer.from(document.indexBase64, "base64").toString("utf8"));
      envelope.binding.documentCount += 1;
      document.indexBase64 = Buffer.from(JSON.stringify(envelope)).toString("base64");
    }],
  ])("rejects changed authoritative v4 %s", async (_name, change) => {
    const value = fixture("europe-core");
    await expect(decodeSearchShard(mutate(value, change), value.authority)).rejects.toThrow();
  });

  it("fails closed when individually valid core and coastal shards have different source identity", async () => {
    const coreValue = fixture("europe-core");
    const coastalValue = fixture("europe-coastal");
    const core = await decodeSearchShard(coreValue.decoded, coreValue.authority);
    const coastal = await decodeSearchShard(mutate(coastalValue, (document) => {
      document.source.projectionSha256 = "0".repeat(64);
    }), coastalValue.authority);
    expect(() => assertCompatibleShardSet(core, coastal)).toThrow(/one v4 release\/source\/spatial identity/);
  });
});
