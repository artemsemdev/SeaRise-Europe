import {
  BROWSER_RUNTIME_VERSION,
  decodeBrowserShard,
  mergeBrowserResults,
  searchBrowserRuntime,
} from "./browser-runtime";
import type {
  BrowserShardAuthority,
  BrowserShardId,
  BrowserShardRuntime,
} from "./browser-runtime";

export type BrowserWorkerRequest =
  | {
    kind: "initialize" | "load-shard";
    authority: BrowserShardAuthority;
    token: number;
    url: string;
  }
  | { kind: "query"; query: string; token: number }
  | { kind: "terminate"; token: number };

export type BrowserWorkerResponse =
  | {
    durationMilliseconds: number;
    kind: "ready";
    runtimeVersion: typeof BROWSER_RUNTIME_VERSION;
    shardId: BrowserShardId;
    token: number;
  }
  | {
    durationMilliseconds: number;
    kind: "results";
    results: ReturnType<typeof searchBrowserRuntime>;
    token: number;
  }
  | { code: string; kind: "error"; message: string; token: number };

type WorkerScope = {
  close(): void;
  onmessage: ((event: MessageEvent<BrowserWorkerRequest>) => void) | null;
  postMessage(message: BrowserWorkerResponse): void;
};

function boundedError(error: unknown): string {
  const message = error instanceof Error ? error.message : "unknown browser worker failure";
  return message.replace(/[\u0000-\u001f\u007f-\u009f]/g, " ").slice(0, 240);
}

async function fetchShard(
  url: string,
  authority: BrowserShardAuthority,
): Promise<BrowserShardRuntime> {
  const response = await fetch(url, {
    cache: "force-cache",
    credentials: "omit",
    redirect: "error",
    referrerPolicy: "no-referrer",
  });
  if (!response.ok || response.type === "opaque") {
    throw new Error(`browser shard fetch failed with status ${response.status}`);
  }
  const raw = new Uint8Array(await response.arrayBuffer());
  return decodeBrowserShard(raw, authority);
}

export function installBrowserSearchWorker(scope: WorkerScope): void {
  const shards = new Map<BrowserShardId, BrowserShardRuntime>();
  let lastQueryToken = -1;
  let terminated = false;

  scope.onmessage = async ({ data }: MessageEvent<BrowserWorkerRequest>) => {
    if (terminated) return;
    const token = Number.isSafeInteger(data?.token) ? data.token : -1;
    try {
      if (data.kind === "terminate") {
        terminated = true;
        shards.clear();
        scope.close();
        return;
      }
      if (data.kind === "initialize" || data.kind === "load-shard") {
        if (data.kind === "initialize" && data.authority.shardId !== "europe-core") {
          throw new Error("browser worker must initialize with the core shard");
        }
        if (data.kind === "load-shard" && !shards.has("europe-core")) {
          throw new Error("coastal shard cannot load before the core shard");
        }
        const started = performance.now();
        const runtime = await fetchShard(data.url, data.authority);
        shards.set(data.authority.shardId, runtime);
        scope.postMessage({
          durationMilliseconds: performance.now() - started,
          kind: "ready",
          runtimeVersion: BROWSER_RUNTIME_VERSION,
          shardId: data.authority.shardId,
          token,
        });
        return;
      }
      if (data.kind !== "query" || typeof data.query !== "string") {
        throw new Error("browser worker message differs from its protocol");
      }
      if (!shards.has("europe-core")) throw new Error("browser search core is not ready");
      if (token <= lastQueryToken) return;
      lastQueryToken = token;
      const started = performance.now();
      const core = searchBrowserRuntime(shards.get("europe-core")!, data.query);
      const coastalRuntime = shards.get("europe-coastal");
      const coastal = coastalRuntime ? searchBrowserRuntime(coastalRuntime, data.query) : [];
      scope.postMessage({
        durationMilliseconds: performance.now() - started,
        kind: "results",
        results: mergeBrowserResults(core, coastal),
        token,
      });
    } catch (error) {
      scope.postMessage({
        code: "browser-worker-failure",
        kind: "error",
        message: boundedError(error),
        token,
      });
    }
  };
}

installBrowserSearchWorker(self as unknown as WorkerScope);
