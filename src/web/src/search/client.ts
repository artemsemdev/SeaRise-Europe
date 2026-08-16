import type { ReleaseContext, ResolvedArtifact, TechnicalError } from "../domain/release";
import { verifiedArtifactBytes, type ArtifactTransport } from "../data/artifact-integrity";
import type { SearchLifecycleEvent, SearchQueryOperation } from "../domain/projection-search";
import type { SearchWorkerPort, SearchWorkerResponse } from "./worker-protocol";
import type { SearchShardAuthority, SearchShardId, SettlementSearchState } from "./types";
import {
  createSearchQueryOperation,
} from "./lifecycle";

const ARTIFACT_IDS: Readonly<Record<SearchShardId, string>> = Object.freeze({
  "europe-core": "settlements-europe-core",
  "europe-coastal": "settlements-europe-coastal",
});

type Listener = (state: SettlementSearchState) => void;
type LifecycleListener = (event: SearchLifecycleEvent) => void;
export type SearchWorkerFactory = () => SearchWorkerPort;
let nextSearchGeneration = 0;

const initialState: SettlementSearchState = Object.freeze({
  readiness: "idle",
  query: "",
  results: [],
  pending: false,
  error: null,
  coastalError: null,
  durationMilliseconds: null,
  initializationMilliseconds: null,
  operation: null,
  completedOperation: null,
});

function technical(message: string): TechnicalError {
  return Object.freeze({ kind: "technical-error", code: "SchemaInvalid", message, recoverable: false });
}

function searchArtifact(context: ReleaseContext, shardId: SearchShardId): ResolvedArtifact {
  const artifact = context.artifact(ARTIFACT_IDS[shardId]);
  if (artifact.role !== "settlement-search-index") {
    throw new Error(`Artifact ${artifact.artifactId} is not a settlement search index.`);
  }
  return artifact;
}

function authority(context: ReleaseContext, shardId: SearchShardId): SearchShardAuthority {
  const artifact = searchArtifact(context, shardId);
  return Object.freeze({
    shardId,
    dataReleaseId: context.dataReleaseId,
    dataProvenanceClass: context.manifest.dataProvenanceClass,
    artifact: Object.freeze({
      artifactId: artifact.artifactId,
      byteSize: artifact.byteSize,
      sha256: artifact.sha256,
      url: artifact.url,
    }),
  });
}

export class SettlementSearchClient {
  readonly #context: ReleaseContext;
  readonly #factory: SearchWorkerFactory;
  readonly #artifactTransport: ArtifactTransport | undefined;
  readonly #listeners = new Set<Listener>();
  readonly #lifecycleListeners = new Set<LifecycleListener>();
  readonly #searchGeneration = ++nextSearchGeneration;
  #worker: SearchWorkerPort | null = null;
  #state = initialState;
  #token = 0;
  #latestQueryToken = -1;
  #nextSearchToken = 0;
  #pendingQuery = "";
  #disposed = false;
  #loadController: AbortController | null = null;

  constructor(context: ReleaseContext, factory: SearchWorkerFactory = () => new Worker(
    new URL("./search.worker.ts", import.meta.url),
    { name: `settlement-search-${context.dataReleaseId}`, type: "module" },
  ), artifactTransport?: ArtifactTransport) {
    this.#context = context;
    this.#factory = factory;
    this.#artifactTransport = artifactTransport;
  }

  get snapshot(): SettlementSearchState {
    return this.#state;
  }

  get generation(): number {
    return this.#searchGeneration;
  }

  subscribe(listener: Listener): () => void {
    this.#listeners.add(listener);
    listener(this.#state);
    return () => this.#listeners.delete(listener);
  }

  subscribeLifecycle(listener: LifecycleListener): () => void {
    this.#lifecycleListeners.add(listener);
    return () => this.#lifecycleListeners.delete(listener);
  }

  #publish(patch: Partial<SettlementSearchState>): void {
    this.#state = Object.freeze({ ...this.#state, ...patch });
    for (const listener of this.#listeners) listener(this.#state);
  }

  #emit(event: SearchLifecycleEvent): void {
    for (const listener of this.#lifecycleListeners) listener(event);
  }

  #guard(operation: SearchQueryOperation) {
    return {
      searchToken: operation.searchToken,
      searchGeneration: operation.searchGeneration,
      queryKey: operation.queryKey,
      dataReleaseId: operation.dataReleaseId,
    } as const;
  }

  #cancelPending(): void {
    const operation = this.#state.pending ? this.#state.operation : null;
    if (!operation) return;
    this.#latestQueryToken = -1;
    this.#emit({ type: "search-cancelled", ...this.#guard(operation) });
  }

  #failActive(error: TechnicalError): void {
    const operation = this.#state.operation;
    this.#publish({
      pending: false,
      results: [],
      completedOperation: null,
      error,
      durationMilliseconds: null,
    });
    if (operation) this.#emit({ type: "search-failed", ...this.#guard(operation), error });
  }

  #workerCrashed(worker: SearchWorkerPort): void {
    if (this.#disposed || this.#worker !== worker) return;
    worker.onmessage = null;
    worker.onerror = null;
    worker.terminate();
    this.#worker = null;
    this.#latestQueryToken = -1;
    const error = Object.freeze({
      kind: "technical-error" as const,
      code: "DecodeFailed" as const,
      message: "The settlement search worker stopped unexpectedly.",
      recoverable: true,
    });
    this.#publish({
      readiness: "idle",
      coastalError: null,
    });
    this.#failActive(error);
  }

  #retireWorkerForCoreRetry(): void {
    this.#loadController?.abort("retrying core shard load");
    this.#loadController = null;
    if (this.#worker) {
      this.#worker.onmessage = null;
      this.#worker.onerror = null;
      this.#worker.terminate();
    }
    this.#worker = null;
    this.#latestQueryToken = -1;
    this.#publish({ readiness: "idle", coastalError: null });
  }

  start(): void {
    if (this.#disposed || this.#worker) return;
    try {
      const worker = this.#factory();
      this.#worker = worker;
      worker.onmessage = ({ data }) => {
        if (this.#worker === worker) this.#receive(data);
      };
      worker.onerror = () => this.#workerCrashed(worker);
      this.#publish({ readiness: "loading-core", pending: true, results: [], error: null, coastalError: null });
      void this.#loadShard(worker, "initialize", "europe-core");
    } catch (error) {
      this.#worker?.terminate();
      this.#worker = null;
      const detail = technical(error instanceof Error ? error.message : "Pinned release has no settlement indexes.");
      this.#publish({
        readiness: "idle",
      });
      this.#failActive(detail);
    }
  }

  async #loadShard(
    worker: SearchWorkerPort,
    kind: "initialize" | "load-shard",
    shardId: SearchShardId,
  ): Promise<void> {
    const controller = new AbortController();
    this.#loadController?.abort("superseded shard load");
    this.#loadController = controller;
    try {
      const shardAuthority = authority(this.#context, shardId);
      if (!this.#artifactTransport) {
        worker.postMessage({ kind, token: ++this.#token, authority: shardAuthority });
        return;
      }
      const artifact = searchArtifact(this.#context, shardId);
      const bytes = await verifiedArtifactBytes(artifact, controller.signal, this.#artifactTransport);
      if (this.#disposed || this.#worker !== worker || controller.signal.aborted) return;
      worker.postMessage({ kind, token: ++this.#token, authority: shardAuthority, verifiedBytes: bytes }, [bytes]);
    } catch (error) {
      if (controller.signal.aborted || this.#disposed || this.#worker !== worker) return;
      const detail = error && typeof error === "object" && "detail" in error
        ? (error as { detail: TechnicalError }).detail
        : technical(error instanceof Error ? error.message : "Pinned settlement index is unavailable.");
      if (kind === "load-shard") this.#publish({ readiness: "core-ready", coastalError: detail });
      else this.#failActive(detail);
    } finally {
      if (this.#loadController === controller) this.#loadController = null;
    }
  }

  query(value: string): void {
    if (this.#disposed) return;
    this.#cancelPending();
    this.#pendingQuery = value;
    if (this.#state.error?.recoverable &&
        !["core-ready", "all-ready"].includes(this.#state.readiness)) {
      this.#retireWorkerForCoreRetry();
    }
    let operation: SearchQueryOperation | null;
    try {
      operation = createSearchQueryOperation(
        this.#context.dataReleaseId,
        value,
        ++this.#nextSearchToken,
        this.#searchGeneration,
      );
    } catch (error) {
      const detail = technical(error instanceof Error ? error.message : "Search query is invalid.");
      this.#publish({
        query: value, operation: null, completedOperation: null,
        results: [], pending: false, durationMilliseconds: null, error: detail,
      });
      return;
    }
    if (!operation) {
      this.#latestQueryToken = -1;
      this.#publish({
        query: value, operation: null, completedOperation: null,
        results: [], pending: false, durationMilliseconds: null, error: null,
      });
      return;
    }
    if (this.#state.error && !this.#state.error.recoverable
        && !["core-ready", "all-ready"].includes(this.#state.readiness)) {
      this.#publish({ query: value, operation, completedOperation: null, results: [], pending: false, durationMilliseconds: null });
      this.#emit({ type: "search-started", operation });
      this.#emit({ type: "search-failed", ...this.#guard(operation), error: this.#state.error });
      return;
    }
    this.#publish({
      query: value,
      operation,
      completedOperation: null,
      results: [],
      pending: true,
      error: null,
      durationMilliseconds: null,
    });
    this.#emit({ type: "search-started", operation });
    this.start();
    if (this.#state.readiness === "core-ready" || this.#state.readiness === "all-ready") {
      this.#sendQuery(value);
    }
  }

  #sendQuery(value: string): void {
    if (!this.#worker || !this.#state.operation) return;
    const token = ++this.#token;
    this.#latestQueryToken = token;
    this.#worker.postMessage({ kind: "query", token, query: value });
  }

  #receive(message: SearchWorkerResponse): void {
    if (this.#disposed) return;
    if (message.kind === "ready") {
      if (message.shardId === "europe-core") {
        this.#publish({
          readiness: "core-ready",
          pending: Boolean(this.#pendingQuery.trim()),
          error: null,
          coastalError: null,
          initializationMilliseconds: message.durationMilliseconds,
        });
        void this.#loadShard(this.#worker!, "load-shard", "europe-coastal");
        if (this.#pendingQuery.trim()) this.#sendQuery(this.#pendingQuery);
      } else {
        this.#publish({ readiness: "all-ready", error: null, coastalError: null });
        if (this.#pendingQuery.trim()) this.#sendQuery(this.#pendingQuery);
      }
      return;
    }
    if (message.kind === "results") {
      if (message.token !== this.#latestQueryToken) return;
      const operation = this.#state.operation;
      if (!operation) return;
      this.#publish({
        readiness: message.readyShards.length === 2 ? "all-ready" : "core-ready",
        results: message.results.map(({ record }) => record),
        pending: false,
        error: null,
        durationMilliseconds: message.durationMilliseconds,
        completedOperation: operation,
      });
      this.#emit({ type: "search-completed", ...this.#guard(operation) });
      return;
    }
    if (message.operation === "load-shard") {
      this.#publish({ readiness: "core-ready", coastalError: message.error });
      return;
    }
    if (message.operation === "query" && message.token !== this.#latestQueryToken) return;
    this.#failActive(message.error);
  }

  dispose(): void {
    if (this.#disposed) return;
    this.#disposed = true;
    this.#loadController?.abort("settlement search disposed");
    this.#loadController = null;
    this.#cancelPending();
    if (this.#worker) {
      this.#worker.postMessage({ kind: "terminate", token: ++this.#token });
      this.#worker.terminate();
    }
    this.#worker = null;
    this.#listeners.clear();
    this.#lifecycleListeners.clear();
    this.#pendingQuery = "";
  }
}
