import { createHash } from "node:crypto";
import { performance } from "node:perf_hooks";
import { getHeapStatistics } from "node:v8";
import { parentPort, workerData } from "node:worker_threads";

import {
  decodeBrowserShard,
  mergeCoreFirst,
  searchBrowserShard,
} from "../shards/browser-shards";
import type { BrowserShard } from "../shards/browser-shards";

const SHARD_IDS = ["europe-core", "europe-coastal"] as const;
type ShardId = (typeof SHARD_IDS)[number];

function memory() {
  const values = getHeapStatistics();
  return {
    usedHeapBytes: values.used_heap_size,
    externalBytes: values.external_memory,
    observedWorkerBytes: values.used_heap_size + values.external_memory,
  };
}

function digest(bytes: Uint8Array): string {
  return createHash("sha256").update(bytes).digest("hex");
}

try {
  if (!parentPort || typeof workerData !== "object" || workerData === null
      || typeof workerData.shards !== "object" || workerData.shards === null) {
    throw new Error("worker initialization message differs");
  }
  const shards = {} as Record<ShardId, BrowserShard>;
  const shardSha256 = {} as Record<ShardId, string>;
  for (const shardId of SHARD_IDS) {
    const bytes = workerData.shards[shardId];
    if (!(bytes instanceof Uint8Array)) throw new Error(`${shardId} worker bytes differ`);
    shardSha256[shardId] = digest(bytes);
    shards[shardId] = decodeBrowserShard(Buffer.from(bytes), shardId);
  }
  parentPort.postMessage({ kind: "ready", shardSha256, memory: memory() });
  parentPort.on("message", (message: unknown) => {
    try {
      if (typeof message !== "object" || message === null
          || (message as { kind?: unknown }).kind !== "query"
          || typeof (message as { id?: unknown }).id !== "string"
          || typeof (message as { query?: unknown }).query !== "string") {
        throw new Error("worker query message differs");
      }
      const { id, query } = message as { id: string; query: string };
      const started = performance.now();
      const core = searchBrowserShard(shards["europe-core"], query);
      const coastal = searchBrowserShard(shards["europe-coastal"], query);
      const results = mergeCoreFirst(core, coastal, 100);
      parentPort!.postMessage({
        kind: "query-result",
        id,
        durationMilliseconds: performance.now() - started,
        resultCount: results.length,
        memory: memory(),
      });
    } catch (error) {
      parentPort!.postMessage({ kind: "failure", message: String(error) });
    }
  });
} catch (error) {
  parentPort?.postMessage({ kind: "failure", message: String(error) });
}
