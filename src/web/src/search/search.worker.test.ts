// @vitest-environment node

import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { createHash } from "node:crypto";
import { brotliCompressSync, brotliDecompressSync } from "node:zlib";
import { describe, expect, it, vi } from "vitest";
import manifest from "../../../../contracts/release/v1/fixtures/release/searise-europe-v1.0.0-20260810-c096aeab4e09/manifest.json";
import { installSearchWorker } from "./search.worker";
import type { SearchWorkerRequest, SearchWorkerResponse } from "./worker-protocol";
import type { SearchShardAuthority, SearchShardId } from "./types";

const releaseRoot = resolve(process.cwd(), "../../contracts/release/v1/fixtures/release", manifest.dataReleaseId);

function authority(shardId: SearchShardId): SearchShardAuthority {
  const artifact = manifest.artifacts.find(({ artifactId }) => artifactId === `settlements-${shardId}`)!;
  return {
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
}

function scope() {
  const messages: SearchWorkerResponse[] = [];
  const target = {
    onmessage: null as ((event: MessageEvent<SearchWorkerRequest>) => void) | null,
    postMessage: (message: SearchWorkerResponse) => messages.push(message),
    close: vi.fn(),
  };
  return { messages, target };
}

function transport(requests: string[] = []) {
  return vi.fn(async (input: URL, init: RequestInit) => {
    requests.push(input.href);
    expect(init.credentials).toBe("omit");
    expect(init.referrerPolicy).toBe("no-referrer");
    const path = input.pathname.slice(input.pathname.indexOf("/releases/") + 1);
    return new Response(readFileSync(resolve(releaseRoot, path.split("/").slice(2).join("/"))), {
      headers: { "content-type": "application/vnd.searise.search-index+json" },
    });
  });
}

function compressedFixture() {
  const base = authority("europe-core");
  const document = JSON.parse(readFileSync(resolve(releaseRoot, "search/europe-core.fixture.json"), "utf8"));
  document.contentEncoding = "br";
  const decoded = Buffer.from(`${JSON.stringify(document)}\n`);
  const compressed = brotliCompressSync(decoded);
  const value: SearchShardAuthority = {
    ...base,
    artifact: {
      ...base.artifact,
      url: base.artifact.url.replace(".fixture.json", ".codepoint-trie.json.br"),
      byteSize: compressed.length,
      sha256: createHash("sha256").update(compressed).digest("hex"),
    },
  };
  return { authority: value, compressed, decoded };
}

async function send(worker: ReturnType<typeof scope>, data: SearchWorkerRequest, expectResponse = true) {
  const previous = worker.messages.length;
  worker.target.onmessage?.({ data } as MessageEvent<SearchWorkerRequest>);
  if (expectResponse) {
    await vi.waitFor(() => expect(worker.messages.length).toBeGreaterThan(previous));
  } else {
    await new Promise((resolvePromise) => setTimeout(resolvePromise, 0));
  }
}

describe("settlement search worker protocol", () => {
  it("makes core useful before coastal, merges without duplicates, and never transmits query text", async () => {
    const requests: string[] = [];
    const worker = scope();
    installSearchWorker(worker.target, transport(requests));
    await send(worker, { kind: "initialize", token: 1, authority: authority("europe-core") });
    expect(worker.messages.at(-1)).toMatchObject({ kind: "ready", shardId: "europe-core" });
    await send(worker, { kind: "query", token: 2, query: "Málaga" });
    expect(worker.messages.at(-1)).toMatchObject({ kind: "results", readyShards: ["europe-core"] });
    await send(worker, { kind: "load-shard", token: 3, authority: authority("europe-coastal") });
    await send(worker, { kind: "query", token: 4, query: "Málaga" });
    const result = worker.messages.at(-1);
    expect(result).toMatchObject({ kind: "results", readyShards: ["europe-core", "europe-coastal"] });
    if (result?.kind === "results") expect(result.results).toHaveLength(1);
    expect(requests).toHaveLength(2);
    expect(requests.every((url) => !url.toLowerCase().includes("malaga"))).toBe(true);
  });

  it("ignores stale query tokens and reports malformed index as a technical failure", async () => {
    const worker = scope();
    installSearchWorker(worker.target, transport());
    await send(worker, { kind: "initialize", token: 1, authority: authority("europe-core") });
    await send(worker, { kind: "query", token: 5, query: "Athens" });
    const count = worker.messages.length;
    await send(worker, { kind: "query", token: 4, query: "Málaga" }, false);
    expect(worker.messages).toHaveLength(count);

    const malformed = scope();
    installSearchWorker(malformed.target, async () => new Response("{}"));
    await send(malformed, { kind: "initialize", token: 1, authority: authority("europe-core") });
    expect(malformed.messages.at(-1)).toMatchObject({
      kind: "error",
      error: { kind: "technical-error", code: "IntegrityFailed" },
    });
  });

  it("hashes exact generic-static Brotli bytes before explicit decoding", async () => {
    const fixture = compressedFixture();
    const worker = scope();
    const decoder = vi.fn(async (bytes: Uint8Array) => new Uint8Array(brotliDecompressSync(bytes)));
    installSearchWorker(
      worker.target,
      async () => new Response(Uint8Array.from(fixture.compressed)),
      decoder,
    );
    await send(worker, { kind: "initialize", token: 1, authority: fixture.authority });
    expect(worker.messages.at(-1)).toMatchObject({ kind: "ready", shardId: "europe-core" });
    expect(decoder).toHaveBeenCalledOnce();

    const hostDecoded = scope();
    installSearchWorker(
      hostDecoded.target,
      async () => new Response(Uint8Array.from(fixture.decoded), { headers: { "content-encoding": "br" } }),
      decoder,
    );
    await send(hostDecoded, { kind: "initialize", token: 1, authority: fixture.authority });
    expect(hostDecoded.messages.at(-1)).toMatchObject({
      kind: "error",
      error: { code: "IntegrityFailed" },
    });
  });

  it("maps unsupported and malformed Brotli decoding to bounded technical errors", async () => {
    const fixture = compressedFixture();
    const unsupported = scope();
    vi.stubGlobal("WebAssembly", undefined);
    installSearchWorker(
      unsupported.target,
      async () => new Response(Uint8Array.from(fixture.compressed)),
    );
    await send(unsupported, { kind: "initialize", token: 1, authority: fixture.authority });
    expect(unsupported.messages.at(-1)).toMatchObject({
      kind: "error",
      error: { code: "UnsupportedBrowser", kind: "technical-error" },
    });
    vi.unstubAllGlobals();

    const malformed = scope();
    installSearchWorker(
      malformed.target,
      async () => new Response(Uint8Array.from(fixture.compressed)),
      async () => { throw new DOMException("malformed", "DataError"); },
    );
    await send(malformed, { kind: "initialize", token: 1, authority: fixture.authority });
    expect(malformed.messages.at(-1)).toMatchObject({ kind: "error", error: { code: "DecodeFailed" } });
  });

  it("aborts safely and closes without posting a scientific outcome", async () => {
    const worker = scope();
    installSearchWorker(worker.target, (_input, init) => new Promise((resolvePromise, reject) => {
      void resolvePromise;
      init.signal?.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")));
    }));
    worker.target.onmessage?.({ data: { kind: "initialize", token: 1, authority: authority("europe-core") } } as MessageEvent<SearchWorkerRequest>);
    await new Promise((resolvePromise) => setTimeout(resolvePromise, 0));
    await send(worker, { kind: "terminate", token: 2 }, false);
    await new Promise((resolvePromise) => setTimeout(resolvePromise, 0));
    expect(worker.target.close).toHaveBeenCalledOnce();
    expect(worker.messages).toEqual([]);
  });
});
