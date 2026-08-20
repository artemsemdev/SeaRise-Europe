/// <reference lib="webworker" />

import type { TechnicalError, TechnicalErrorCode } from "../domain/release";
import {
  assertCompatibleShardSet,
  decodeVerifiedCompressedSearchShard,
  searchShard,
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

interface BrotliStreamResult {
  readonly buf: Uint8Array;
  readonly code: number;
  readonly input_offset: number;
  free?(): void;
}

interface BrotliRuntime {
  readonly BrotliStreamResultCode: {
    readonly ResultSuccess: number;
    readonly NeedsMoreInput: number;
    readonly NeedsMoreOutput: number;
  };
  readonly DecompressStream: new () => {
    decompress(input: Uint8Array, outputSize: number): BrotliStreamResult;
    free(): void;
  };
}

const MAX_DECODED_BYTES = 64 * 1024 * 1024;
const MAX_COMPRESSED_BYTES = 16 * 1024 * 1024;
const DECODE_CHUNK_BYTES = 1024 * 1024;

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

function expectedCompressedBytes(authority: SearchShardAuthority): number {
  const expected = authority.artifact.byteSize;
  if (!Number.isSafeInteger(expected) || expected < 1 || expected > MAX_COMPRESSED_BYTES) {
    throw new SearchWorkerFailure(
      "IntegrityFailed",
      "Settlement shard compressed size differs from its browser authority.",
      false,
    );
  }
  return expected;
}

function contentLength(response: Response): number | null {
  const header = response.headers.get("content-length");
  if (header === null) return null;
  if (!/^(0|[1-9][0-9]*)$/.test(header)) {
    throw new SearchWorkerFailure("IntegrityFailed", "Settlement shard Content-Length is invalid.", false);
  }
  const value = Number(header);
  if (!Number.isSafeInteger(value)) {
    throw new SearchWorkerFailure("IntegrityFailed", "Settlement shard Content-Length is invalid.", false);
  }
  return value;
}

async function readCompressedBody(
  response: Response,
  authority: SearchShardAuthority,
  signal: AbortSignal,
): Promise<Uint8Array> {
  const expected = expectedCompressedBytes(authority);
  const declared = contentLength(response);
  if (declared !== null && declared !== expected) {
    throw new SearchWorkerFailure(
      "IntegrityFailed",
      "Settlement shard Content-Length differs from its pinned release authority.",
      false,
    );
  }
  if (!response.body) {
    throw new SearchWorkerFailure("DecodeFailed", "Settlement shard response has no readable body.", true);
  }

  const reader = response.body.getReader();
  const raw = new Uint8Array(expected);
  let received = 0;
  try {
    while (true) {
      if (signal.aborted) {
        throw new SearchWorkerFailure("Aborted", "Settlement shard loading was cancelled.", false);
      }
      const { done, value } = await reader.read();
      if (done) break;
      if (!(value instanceof Uint8Array) || received + value.byteLength > expected) {
        throw new SearchWorkerFailure(
          "IntegrityFailed",
          "Settlement shard response exceeds its pinned compressed size.",
          false,
        );
      }
      if (value.byteLength > 0) {
        raw.set(value, received);
        received += value.byteLength;
      }
    }
  } catch (error) {
    await reader.cancel().catch(() => undefined);
    throw error;
  } finally {
    reader.releaseLock();
  }
  if (received !== expected) {
    throw new SearchWorkerFailure(
      "IntegrityFailed",
      "Settlement shard response is truncated against its pinned compressed size.",
      false,
    );
  }
  return raw;
}

async function fetchShard(
  authority: SearchShardAuthority,
  signal: AbortSignal,
  transport: WorkerTransport,
  decodeBrotli: BrotliDecoder,
  verifiedBytes?: ArrayBuffer,
): Promise<SearchShardRuntime> {
  expectedCompressedBytes(authority);
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
  if (verifiedBytes) {
    response = new Response(verifiedBytes, {
      status: 200,
      headers: { "content-length": String(verifiedBytes.byteLength) },
    });
  } else {
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
  }
  if (!response.ok || response.type === "opaque") {
    throw new SearchWorkerFailure("FetchFailed", `Settlement shard returned HTTP ${response.status}.`, true);
  }
  let raw: Uint8Array;
  try {
    raw = await readCompressedBody(response, authority, signal);
  } catch (error) {
    if (error instanceof SearchWorkerFailure) throw error;
    if (signal.aborted) throw new SearchWorkerFailure("Aborted", "Settlement shard loading was cancelled.", false);
    throw new SearchWorkerFailure("DecodeFailed", "Settlement shard bytes could not be read.", true);
  }
  try {
    return await decodeVerifiedCompressedSearchShard(raw, authority, decodeBrotli);
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
  let brotli: BrotliRuntime;
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
    return decodeBrotliStream(bytes, brotli);
  } catch {
    throw new SearchWorkerFailure("DecodeFailed", "The Brotli settlement shard is malformed.", false);
  }
}

export function decodeBrotliStream(
  bytes: Uint8Array,
  brotli: BrotliRuntime,
  maximumBytes = MAX_DECODED_BYTES,
): Uint8Array {
  if (!Number.isSafeInteger(maximumBytes) || maximumBytes < 1 || maximumBytes > MAX_DECODED_BYTES) {
    throw new Error("decoded search shard limit is invalid");
  }
  const stream = new brotli.DecompressStream();
  const chunks: Uint8Array[] = [];
  let inputOffset = 0;
  let outputBytes = 0;
  let complete = false;
  try {
    while (!complete) {
      const remainingBytes = maximumBytes - outputBytes;
      if (remainingBytes === 0) throw new Error("decoded search shard exceeds its browser limit");
      const outputSize = Math.min(DECODE_CHUNK_BYTES, remainingBytes);
      const result = stream.decompress(bytes.subarray(inputOffset), outputSize);
      const chunk = Uint8Array.from(result.buf);
      const resultCode = result.code;
      const consumedInputBytes = result.input_offset;
      const previousInputOffset = inputOffset;
      inputOffset += consumedInputBytes;
      result.free?.();
      if (inputOffset > bytes.length || outputBytes + chunk.length > maximumBytes) {
        throw new Error("decoded search shard exceeds its browser limit");
      }
      if (chunk.length) {
        chunks.push(chunk);
        outputBytes += chunk.length;
      }
      if (resultCode === brotli.BrotliStreamResultCode.ResultSuccess) {
        if (inputOffset !== bytes.length) throw new Error("Brotli settlement shard has trailing bytes");
        complete = true;
      } else if (resultCode === brotli.BrotliStreamResultCode.NeedsMoreOutput) {
        if (outputBytes === maximumBytes) {
          throw new Error("decoded search shard exceeds its browser limit");
        }
        if (inputOffset === previousInputOffset && chunk.length === 0) {
          throw new Error("Brotli settlement shard decoder made no progress");
        }
      } else if (resultCode === brotli.BrotliStreamResultCode.NeedsMoreInput) {
        if (inputOffset >= bytes.length) throw new Error("Brotli settlement shard is truncated");
      } else {
        throw new Error(`Brotli settlement shard decoder returned code ${resultCode}`);
      }
    }
    const decoded = new Uint8Array(outputBytes);
    let offset = 0;
    for (const chunk of chunks) {
      decoded.set(chunk, offset);
      offset += chunk.length;
    }
    return decoded;
  } finally {
    stream.free();
  }
}

async function importBrotli(): Promise<BrotliRuntime> {
  const module = await import("brotli-wasm");
  return await module.default as BrotliRuntime;
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
        const runtime = await fetchShard(
          data.authority,
          controller.signal,
          transport,
          decodeBrotli,
          data.verifiedBytes,
        );
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
