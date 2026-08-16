// @vitest-environment node

import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { resolve } from "node:path";
import { brotliCompressSync, brotliDecompressSync } from "node:zlib";
import { describe, expect, it, vi } from "vitest";
import manifest from "../../../../contracts/release/v1/fixtures/release/searise-europe-v1.0.0-20260810-c096aeab4e09/manifest.json";
import { decodeBrotliStream, installSearchWorker } from "./search.worker";
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
  const compressed = readFileSync(resolve(releaseRoot, "search/europe-core.codepoint-trie.json.br"));
  return { authority: base, compressed, decoded: brotliDecompressSync(compressed) };
}

const decodeFixture = async (bytes: Uint8Array) => new Uint8Array(brotliDecompressSync(bytes));

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
    installSearchWorker(worker.target, transport(requests), decodeFixture);
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
    installSearchWorker(worker.target, transport(), decodeFixture);
    await send(worker, { kind: "initialize", token: 1, authority: authority("europe-core") });
    await send(worker, { kind: "query", token: 5, query: "Athens" });
    const count = worker.messages.length;
    await send(worker, { kind: "query", token: 4, query: "Málaga" }, false);
    expect(worker.messages).toHaveLength(count);

    const malformed = scope();
    installSearchWorker(malformed.target, async () => new Response("{}"), decodeFixture);
    await send(malformed, { kind: "initialize", token: 1, authority: authority("europe-core") });
    expect(malformed.messages.at(-1)).toMatchObject({
      kind: "error",
      error: { kind: "technical-error", code: "IntegrityFailed" },
    });
  });

  it("hashes exact generic-static Brotli bytes before explicit decoding", async () => {
    const fixture = compressedFixture();
    const worker = scope();
    const decoder = vi.fn(decodeFixture);
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

  it("rejects an invalid authority and mismatched Content-Length before reading a body", async () => {
    const fixture = compressedFixture();
    const transportSpy = vi.fn(async () => new Response());
    const invalidAuthority = {
      ...fixture.authority,
      artifact: { ...fixture.authority.artifact, byteSize: 16 * 1024 * 1024 + 1 },
    };
    const invalid = scope();
    installSearchWorker(invalid.target, transportSpy, decodeFixture);
    await send(invalid, { kind: "initialize", token: 1, authority: invalidAuthority });
    expect(invalid.messages.at(-1)).toMatchObject({ kind: "error", error: { code: "IntegrityFailed" } });
    expect(transportSpy).not.toHaveBeenCalled();

    const getReader = vi.fn();
    const declared = scope();
    installSearchWorker(declared.target, async () => ({
      ok: true,
      status: 200,
      type: "default",
      headers: new Headers({ "content-length": String(fixture.compressed.byteLength + 1) }),
      body: { getReader },
    }) as unknown as Response, decodeFixture);
    await send(declared, { kind: "initialize", token: 1, authority: fixture.authority });
    expect(declared.messages.at(-1)).toMatchObject({ kind: "error", error: { code: "IntegrityFailed" } });
    expect(getReader).not.toHaveBeenCalled();
  });

  it("rejects a search authority that is not the exact opaque Brotli artifact", async () => {
    const fixture = compressedFixture();
    const transportSpy = vi.fn(async () => new Response(fixture.compressed));
    const worker = scope();
    installSearchWorker(worker.target, transportSpy, decodeFixture);
    await send(worker, { kind: "initialize", token: 1, authority: {
      ...fixture.authority,
      artifact: {
        ...fixture.authority.artifact,
        url: fixture.authority.artifact.url.replace(/\.br$/, ""),
      },
    } });
    expect(worker.messages.at(-1)).toMatchObject({ kind: "error", error: { code: "IntegrityFailed" } });
    expect(transportSpy).not.toHaveBeenCalled();
  });

  it.each([
    ["oversized", (bytes: Uint8Array) => [bytes, Uint8Array.of(0)]],
    ["truncated", (bytes: Uint8Array) => [bytes.subarray(0, bytes.byteLength - 1)]],
  ])("rejects a chunked %s compressed response before decoding", async (_name, chunks) => {
    const fixture = compressedFixture();
    const decoder = vi.fn(decodeFixture);
    const worker = scope();
    installSearchWorker(worker.target, async () => {
      const queue = [...chunks(new Uint8Array(fixture.compressed))];
      return new Response(new ReadableStream({
        pull(controller) {
          const chunk = queue.shift();
          if (chunk) controller.enqueue(chunk);
          else controller.close();
        },
      }));
    }, decoder);
    await send(worker, { kind: "initialize", token: 1, authority: fixture.authority });
    expect(worker.messages.at(-1)).toMatchObject({ kind: "error", error: { code: "IntegrityFailed" } });
    expect(decoder).not.toHaveBeenCalled();
  });

  it.each([
    ["non-string search name", (document: { records: Array<{ searchNames: unknown[] }> }) => {
      document.records[0].searchNames = [42];
    }],
    ["out-of-range latitude", (document: { records: Array<{ latitude: number }> }) => {
      document.records[0].latitude = 900;
    }],
  ])("rejects an unsafe verified-artifact runtime shape: %s", async (_name, mutate) => {
    const fixture = compressedFixture();
    const document = JSON.parse(fixture.decoded.toString()) as {
      records: Array<{ searchNames: unknown[]; latitude: number }>;
    };
    mutate(document);
    const worker = scope();
    installSearchWorker(
      worker.target,
      async () => new Response(Uint8Array.from(fixture.compressed)),
      async () => new TextEncoder().encode(JSON.stringify(document)),
    );
    await send(worker, { kind: "initialize", token: 1, authority: fixture.authority });
    expect(worker.messages.at(-1)).toMatchObject({
      kind: "error",
      error: { kind: "technical-error", code: "IntegrityFailed" },
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

  it("streams Brotli output and rejects expansion at the cumulative limit", async () => {
    const brotli = createRequire(import.meta.url)("brotli-wasm");
    const fixture = compressedFixture();
    expect(decodeBrotliStream(
      new Uint8Array(fixture.compressed),
      brotli,
      fixture.decoded.byteLength,
    )).toEqual(new Uint8Array(fixture.decoded));

    const compressedBomb = new Uint8Array(brotliCompressSync(Buffer.alloc(4096, 0x61)));
    expect(() => decodeBrotliStream(compressedBomb, brotli, 128))
      .toThrow(/exceeds its browser limit/);
  });

  it("rejects a coastal shard with a different source identity without losing core search", async () => {
    const worker = scope();
    const core = authority("europe-core");
    const coastal = authority("europe-coastal");
    const changedCoastal = JSON.parse(brotliDecompressSync(readFileSync(resolve(
      releaseRoot,
      "search/europe-coastal.codepoint-trie.json.br",
    ))).toString("utf8"));
    changedCoastal.source.projectionSha256 = "0".repeat(64);
    const transportWithDifferentIdentity = vi.fn(async (input: URL) => {
      if (input.pathname.includes("europe-coastal")) {
        const bytes = Buffer.from(JSON.stringify(changedCoastal));
        return new Response(bytes);
      }
      return new Response(readFileSync(resolve(releaseRoot, "search/europe-core.codepoint-trie.json.br")));
    });
    const decode = async (bytes: Uint8Array) => {
      try { return new Uint8Array(brotliDecompressSync(bytes)); }
      catch { return bytes; }
    };
    installSearchWorker(worker.target, transportWithDifferentIdentity, decode);
    await send(worker, { kind: "initialize", token: 1, authority: core });
    await send(worker, { kind: "load-shard", token: 2, authority: {
      ...coastal,
      artifact: {
        ...coastal.artifact,
        byteSize: Buffer.byteLength(JSON.stringify(changedCoastal)),
        sha256: await crypto.subtle.digest("SHA-256", Buffer.from(JSON.stringify(changedCoastal)))
          .then((hash) => Buffer.from(hash).toString("hex")),
      },
    } });
    expect(worker.messages.at(-1)).toMatchObject({
      kind: "error",
      operation: "load-shard",
      error: { code: "IntegrityFailed" },
    });
    await send(worker, { kind: "query", token: 3, query: "Athens" });
    expect(worker.messages.at(-1)).toMatchObject({ kind: "results", readyShards: ["europe-core"] });
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
