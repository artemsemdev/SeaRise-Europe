import type { ReleaseContext, ResolvedArtifact, TechnicalError } from "../domain/release";
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

  constructor(context: ReleaseContext, factory: SearchWorkerFactory = () => new Worker(
    new URL("./search.worker.ts", import.meta.url),
    { name: `settlement-search-${context.dataReleaseId}`, type: "module" },
  )) {
    this.#context = context;
    this.#factory = factory;
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
      worker.postMessage({ kind: "initialize", token: ++this.#token, authority: authority(this.#context, "europe-core") });
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

  query(value: string): void {
    if (this.#disposed) return;
    this.#cancelPending();
    this.#pendingQuery = value;
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
        try {
          this.#worker!.postMessage({
            kind: "load-shard",
            token: ++this.#token,
            authority: authority(this.#context, "europe-coastal"),
          });
        } catch (error) {
          this.#publish({
            readiness: "core-ready",
            coastalError: technical(error instanceof Error
              ? error.message
              : "Pinned release has no coastal settlement index."),
          });
        }
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
