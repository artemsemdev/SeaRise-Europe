/// <reference lib="webworker" />

import type { TechnicalError, TechnicalErrorCode } from "../domain/release";
import {
  assertCompatibleShardSet,
  decodeSearchShard,
  searchShard,
  verifySearchArtifactBytes,
  type SearchShardRuntime,
} from "./runtime";
import { SEARCH_WORKER_VERSION, type SearchWorkerRequest, type SearchWorkerResponse } from "./worker-protocol";
import type { RankedSearchResult, SearchShardAuthority, SearchShardId } from "./types";

interface WorkerScope {
  onmessage: ((event: MessageEvent<SearchWorkerRequest>) => void) | null;
  postMessage(message: SearchWorkerResponse): void;
  close(): void;
}

type WorkerTransport = (input: URL, init: RequestInit) => Promise<Response>;
export type BrotliDecoder = (bytes: Uint8Array) => Promise<Uint8Array>;

class SearchWorkerFailure extends Error {
  readonly code: TechnicalErrorCode;
  readonly recoverable: boolean;

  constructor(code: TechnicalErrorCode, message: string, recoverable: boolean) {
    super(message);
    this.code = code;
    this.recoverable = recoverable;
  }
}

function bounded(value: unknown): string {
  const message = value instanceof Error ? value.message : "Unknown settlement worker failure.";
  return Array.from(message, (point) => {
    const code = point.codePointAt(0)!;
    return code <= 0x1f || (code >= 0x7f && code <= 0x9f) ? " " : point;
  }).join("").slice(0, 240);
}

function technical(error: unknown): TechnicalError {
  if (error instanceof SearchWorkerFailure) {
    return Object.freeze({
      kind: "technical-error",
      code: error.code,
      message: bounded(error),
      recoverable: error.recoverable,
    });
  }
  return Object.freeze({
    kind: "technical-error",
    code: "DecodeFailed",
    message: bounded(error),
    recoverable: false,
  });
}

async function fetchShard(
  authority: SearchShardAuthority,
  signal: AbortSignal,
  transport: WorkerTransport,
  decodeBrotli: BrotliDecoder,
): Promise<SearchShardRuntime> {
  const url = new URL(authority.artifact.url);
  if (
    !["http:", "https:"].includes(url.protocol)
    || url.username || url.password || url.search || url.hash
    || !url.pathname.includes(`/releases/${authority.dataReleaseId}/`)
    || !url.pathname.endsWith(".codepoint-trie.json.br")
  ) {
    throw new SearchWorkerFailure("IntegrityFailed", "Settlement shard URL escapes the pinned release.", false);
  }
  let response: Response;
  try {
    response = await transport(url, {
      signal,
      cache: "force-cache",
      credentials: "omit",
      redirect: "error",
      referrerPolicy: "no-referrer",
      headers: { Accept: "application/vnd.searise.search-index+json, application/json" },
    });
  } catch (error) {
    if (signal.aborted) throw new SearchWorkerFailure("Aborted", "Settlement shard loading was cancelled.", false);
    throw new SearchWorkerFailure("FetchFailed", bounded(error), true);
  }
  if (!response.ok || response.type === "opaque") {
    throw new SearchWorkerFailure("FetchFailed", `Settlement shard returned HTTP ${response.status}.`, true);
  }
  let raw: Uint8Array;
  try {
    raw = new Uint8Array(await response.arrayBuffer());
  } catch {
    throw new SearchWorkerFailure("DecodeFailed", "Settlement shard bytes could not be read.", true);
  }
  try {
    await verifySearchArtifactBytes(raw, authority);
    const decoded = url.pathname.endsWith(".br") ? await decodeBrotli(raw) : raw;
    return await decodeSearchShard(decoded, authority);
  } catch (error) {
    if (error instanceof SearchWorkerFailure) throw error;
    const code = /authority|release|identity|SHA|bytes differ/i.test(bounded(error))
      ? "IntegrityFailed"
      : "DecodeFailed";
    throw new SearchWorkerFailure(code, bounded(error), false);
  }
}

async function pinnedBrotli(bytes: Uint8Array): Promise<Uint8Array> {
  if (typeof WebAssembly === "undefined") {
    throw new SearchWorkerFailure(
      "UnsupportedBrowser",
      "This browser cannot initialize the pinned Brotli decoder.",
      false,
    );
  }
  let brotli: { decompress(input: Uint8Array): Uint8Array };
  try {
    brotli = await importBrotli();
  } catch {
    throw new SearchWorkerFailure(
      "UnsupportedBrowser",
      "This browser cannot initialize the pinned Brotli decoder.",
      false,
    );
  }
  try {
    return Uint8Array.from(brotli.decompress(bytes));
  } catch {
    throw new SearchWorkerFailure("DecodeFailed", "The Brotli settlement shard is malformed.", false);
  }
}

async function importBrotli() {
  const module = await import("brotli-wasm");
  return await module.default;
}

function mergeRanked(
  core: readonly RankedSearchResult[],
  coastal: readonly RankedSearchResult[],
): readonly RankedSearchResult[] {
  const result: RankedSearchResult[] = [];
  const seen = new Set<string>();
  for (const shard of [core, coastal]) {
    for (const item of shard) {
      if (!seen.has(item.record.placeId) && result.length < 10) result.push(item);
      seen.add(item.record.placeId);
    }
  }
  return result;
}

export function installSearchWorker(
  scope: WorkerScope,
  transport: WorkerTransport = (input, init) => fetch(input, init),
  decodeBrotli: BrotliDecoder = pinnedBrotli,
): void {
  const shards = new Map<SearchShardId, SearchShardRuntime>();
  const controllers = new Map<SearchShardId, AbortController>();
  let lastQueryToken = -1;
  let terminated = false;

  scope.onmessage = async ({ data }: MessageEvent<SearchWorkerRequest>) => {
    if (terminated) return;
    const token = Number.isSafeInteger(data?.token) ? data.token : -1;
    try {
      if (data.kind === "terminate") {
        terminated = true;
        for (const controller of controllers.values()) controller.abort();
        controllers.clear();
        shards.clear();
        scope.close();
        return;
      }
      if (data.kind === "initialize" || data.kind === "load-shard") {
        if (data.kind === "initialize" && data.authority.shardId !== "europe-core") {
          throw new SearchWorkerFailure("SchemaInvalid", "Settlement worker must initialize with the core shard.", false);
        }
        if (data.kind === "load-shard" && (!shards.has("europe-core") || data.authority.shardId !== "europe-coastal")) {
          throw new SearchWorkerFailure("SchemaInvalid", "Coastal shard cannot load before the core shard.", false);
        }
        const controller = new AbortController();
        controllers.set(data.authority.shardId, controller);
        const started = performance.now();
        const runtime = await fetchShard(data.authority, controller.signal, transport, decodeBrotli);
        if (terminated || controller.signal.aborted) return;
        if (data.authority.shardId === "europe-coastal") {
          try {
            assertCompatibleShardSet(shards.get("europe-core")!, runtime);
          } catch (error) {
            throw new SearchWorkerFailure("IntegrityFailed", bounded(error), false);
          }
        }
        shards.set(data.authority.shardId, runtime);
        controllers.delete(data.authority.shardId);
        scope.postMessage({
          kind: "ready",
          token,
          shardId: data.authority.shardId,
          runtimeVersion: SEARCH_WORKER_VERSION,
          durationMilliseconds: performance.now() - started,
        });
        return;
      }
      if (data.kind !== "query" || typeof data.query !== "string") {
        throw new SearchWorkerFailure("DecodeFailed", "Settlement worker message differs from its protocol.", false);
      }
      if (!shards.has("europe-core")) {
        throw new SearchWorkerFailure("DecodeFailed", "Core settlement index is not ready.", true);
      }
      if (token <= lastQueryToken) return;
      lastQueryToken = token;
      const started = performance.now();
      const core = searchShard(shards.get("europe-core")!, data.query);
      const coastal = shards.has("europe-coastal") ? searchShard(shards.get("europe-coastal")!, data.query) : [];
      scope.postMessage({
        kind: "results",
        token,
        results: mergeRanked(core, coastal),
        durationMilliseconds: performance.now() - started,
        readyShards: shards.has("europe-coastal")
          ? ["europe-core", "europe-coastal"]
          : ["europe-core"],
      });
    } catch (error) {
      if (terminated) return;
      const operation = data?.kind === "initialize" || data?.kind === "load-shard" || data?.kind === "query"
        ? data.kind
        : "protocol";
      scope.postMessage({ kind: "error", token, operation, error: technical(error) });
    }
  };
}

if (typeof self !== "undefined" && "postMessage" in self && "close" in self) {
  installSearchWorker(self as unknown as WorkerScope);
}
