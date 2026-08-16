// @vitest-environment node

import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import manifest from "../../../../contracts/release/v1/fixtures/release/searise-europe-v1.0.0-20260810-c096aeab4e09/manifest.json";
import queryFixture from "../../../../contracts/search-evaluation/v1/fixtures/queries.synthetic.json";
import { mergeRankedResults, normalizeSearchText } from "./ranking";
import { decodeSearchShard, searchShard, verifySearchArtifactBytes } from "./runtime";
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
  return { authority, raw };
}

describe("release-bound settlement search runtime", () => {
  it("preserves the canonical synthetic ranking controls across core and coastal shards", async () => {
    const coreFixture = fixture("europe-core");
    const coastalFixture = fixture("europe-coastal");
    await verifySearchArtifactBytes(coreFixture.raw, coreFixture.authority);
    await verifySearchArtifactBytes(coastalFixture.raw, coastalFixture.authority);
    const core = await decodeSearchShard(coreFixture.raw, coreFixture.authority);
    const coastal = await decodeSearchShard(coastalFixture.raw, coastalFixture.authority);

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
    const core = await decodeSearchShard(coreFixture.raw, coreFixture.authority);
    expect(normalizeSearchText("  MÁLAGA  ")).toBe("malaga");
    expect(searchShard(core, "malagx")[0].record).toMatchObject({
      placeId: "synthetic:1",
      displayName: "Málaga",
      latitude: 36.7213,
      longitude: -4.4214,
    });
    expect(searchShard(core, "Athens")[0].record.displayName).toBe("Αθήνα");
  });

  it("deduplicates overlap and lets a stronger exact result outrank weaker matches", async () => {
    const coreFixture = fixture("europe-core");
    const coastalFixture = fixture("europe-coastal");
    const core = await decodeSearchShard(coreFixture.raw, coreFixture.authority);
    const coastal = await decodeSearchShard(coastalFixture.raw, coastalFixture.authority);
    expect(mergeRankedResults(searchShard(core, "Málaga"), searchShard(coastal, "Málaga")))
      .toHaveLength(1);
    expect(mergeRankedResults(searchShard(core, "Springfield"), searchShard(coastal, "Springfield"))
      .map(({ placeId }) => placeId)).toEqual(["synthetic:3", "synthetic:4"]);
  });

  it("fails closed on changed bytes, cross-release authority, and unsafe query text", async () => {
    const value = fixture("europe-core");
    const changed = Uint8Array.from(value.raw);
    changed[0] ^= 1;
    await expect(verifySearchArtifactBytes(changed, value.authority)).rejects.toThrow(/pinned release authority/);
    await expect(decodeSearchShard(value.raw, { ...value.authority, dataReleaseId: "searise-europe-v1.0.0-20260810-aaaaaaaaaaaa" }))
      .rejects.toThrow(/metadata differs/);
    const runtime = await decodeSearchShard(value.raw, value.authority);
    expect(() => searchShard(runtime, "bad\u0000query")).toThrow(/control characters/);
  });
});
