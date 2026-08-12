// @vitest-environment node

import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { brotliDecompressSync } from "node:zlib";
import { describe, expect, it } from "vitest";

import {
  decodeBrowserShard,
  mergeBrowserResults,
  searchBrowserRuntime,
} from "./browser-runtime";
import type { BrowserShardAuthority, BrowserShardId } from "./browser-runtime";

const FIXTURES = resolve(process.cwd(), "src/search/performance/fixtures/browser-shards");
const RELEASE_ID = "searise-europe-v1.0.0-20260812-0123456789ab";

function fixture(shardId: BrowserShardId): {
  authority: BrowserShardAuthority;
  raw: Uint8Array;
} {
  const compressed = readFileSync(resolve(FIXTURES, `${shardId}.codepoint-trie.json.br`));
  const document = JSON.parse(brotliDecompressSync(compressed).toString("utf8"));
  const envelope = JSON.parse(Buffer.from(document.indexBase64, "base64").toString("utf8"));
  document.artifactType = "settlement-browser-search-shard";
  document.contentEncoding = "br";
  document.dataReleaseId = RELEASE_ID;
  document.formatVersion = "settlement-browser-search-shard-v2";
  envelope.binding.evaluationId = "browser-search-shard-v2";
  document.indexBase64 = Buffer.from(JSON.stringify(envelope)).toString("base64");
  const raw = Buffer.from(JSON.stringify(document));
  return {
    authority: {
      dataReleaseId: RELEASE_ID,
      rawByteSize: raw.length,
      rawSha256: createHash("sha256").update(raw).digest("hex"),
      shardId,
    },
    raw,
  };
}

describe("release-bound browser search runtime", () => {
  it("hydrates the trusted core index and preserves exact, alternate, prefix, and fuzzy search", async () => {
    const { raw, authority } = fixture("europe-core");
    const runtime = await decodeBrowserShard(raw, authority);

    expect(searchBrowserRuntime(runtime, "Alpha").map(({ placeId }) => placeId))
      .toEqual(["geonames:101"]);
    expect(searchBrowserRuntime(runtime, "Alpha Alt").map(({ placeId }) => placeId))
      .toEqual(["geonames:101"]);
    expect(searchBrowserRuntime(runtime, "Char").map(({ placeId }) => placeId))
      .toEqual(["geonames:104"]);
    expect(searchBrowserRuntime(runtime, "Alphx").map(({ placeId }) => placeId))
      .toEqual(["geonames:101"]);
  });

  it("rejects changed raw bytes before parsing or index hydration", async () => {
    const { raw, authority } = fixture("europe-core");
    const changed = Uint8Array.from(raw);
    changed[0] ^= 1;
    await expect(decodeBrowserShard(changed, authority))
      .rejects.toThrow("bytes differ from the release authority");
  });

  it("keeps core order and removes duplicates when coastal becomes ready", async () => {
    const coreFixture = fixture("europe-core");
    const coastalFixture = fixture("europe-coastal");
    const core = await decodeBrowserShard(coreFixture.raw, coreFixture.authority);
    const coastal = await decodeBrowserShard(coastalFixture.raw, coastalFixture.authority);

    expect(mergeBrowserResults(
      searchBrowserRuntime(core, "Charlie"),
      searchBrowserRuntime(coastal, "Charlie"),
    ).map(({ placeId }) => placeId)).toEqual(["geonames:104"]);
  });
});
