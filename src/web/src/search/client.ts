import type { ReleaseContext, ResolvedArtifact, TechnicalError } from "../domain/release";
import type { SearchWorkerPort, SearchWorkerResponse } from "./worker-protocol";
import type { SearchShardAuthority, SearchShardId, SettlementSearchState } from "./types";

const ARTIFACT_IDS: Readonly<Record<SearchShardId, string>> = Object.freeze({
  "europe-core": "settlements-europe-core",
  "europe-coastal": "settlements-europe-coastal",
});

type Listener = (state: SettlementSearchState) => void;
export type SearchWorkerFactory = () => SearchWorkerPort;

const initialState: SettlementSearchState = Object.freeze({
  readiness: "idle",
  query: "",
  results: [],
  pending: false,
  error: null,
  coastalError: null,
  durationMilliseconds: null,
  initializationMilliseconds: null,
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
  #worker: SearchWorkerPort | null = null;
  #state = initialState;
  #token = 0;
  #latestQueryToken = -1;
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

  subscribe(listener: Listener): () => void {
    this.#listeners.add(listener);
    listener(this.#state);
    return () => this.#listeners.delete(listener);
  }

  #publish(patch: Partial<SettlementSearchState>): void {
    this.#state = Object.freeze({ ...this.#state, ...patch });
    for (const listener of this.#listeners) listener(this.#state);
  }

  start(): void {
    if (this.#disposed || this.#worker) return;
    try {
      this.#worker = this.#factory();
      this.#worker.onmessage = ({ data }) => this.#receive(data);
      this.#worker.onerror = () => this.#publish({
        pending: false,
        results: [],
        error: Object.freeze({
          kind: "technical-error",
          code: "DecodeFailed",
          message: "The settlement search worker stopped unexpectedly.",
          recoverable: true,
        }),
      });
      this.#publish({ readiness: "loading-core", pending: true, results: [], error: null, coastalError: null });
      this.#worker.postMessage({ kind: "initialize", token: ++this.#token, authority: authority(this.#context, "europe-core") });
    } catch (error) {
      this.#publish({
        readiness: "idle",
        pending: false,
        results: [],
        error: technical(error instanceof Error ? error.message : "Pinned release has no settlement indexes."),
      });
    }
  }

  query(value: string): void {
    if (this.#disposed) return;
    this.#pendingQuery = value;
    if (this.#state.error && !["core-ready", "all-ready"].includes(this.#state.readiness)) {
      this.#publish({ query: value, results: [], pending: false, durationMilliseconds: null });
      return;
    }
    this.#publish({
      query: value,
      results: [],
      pending: Boolean(value.trim()),
      error: null,
      durationMilliseconds: null,
    });
    this.start();
    if (this.#state.readiness === "core-ready" || this.#state.readiness === "all-ready") {
      this.#sendQuery(value);
    }
  }

  #sendQuery(value: string): void {
    if (!this.#worker) return;
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
        this.#worker!.postMessage({
          kind: "load-shard",
          token: ++this.#token,
          authority: authority(this.#context, "europe-coastal"),
        });
        if (this.#pendingQuery.trim()) this.#sendQuery(this.#pendingQuery);
      } else {
        this.#publish({ readiness: "all-ready", error: null, coastalError: null });
        if (this.#pendingQuery.trim()) this.#sendQuery(this.#pendingQuery);
      }
      return;
    }
    if (message.kind === "results") {
      if (message.token !== this.#latestQueryToken) return;
      this.#publish({
        readiness: message.readyShards.length === 2 ? "all-ready" : "core-ready",
        results: message.results.map(({ record }) => record),
        pending: false,
        error: null,
        durationMilliseconds: message.durationMilliseconds,
      });
      return;
    }
    if (message.operation === "load-shard") {
      this.#publish({ readiness: "core-ready", coastalError: message.error });
      return;
    }
    if (message.operation === "query" && message.token !== this.#latestQueryToken) return;
    this.#publish({ pending: false, results: [], error: message.error, durationMilliseconds: null });
  }

  dispose(): void {
    if (this.#disposed) return;
    this.#disposed = true;
    if (this.#worker) {
      this.#worker.postMessage({ kind: "terminate", token: ++this.#token });
      this.#worker.terminate();
    }
    this.#worker = null;
    this.#listeners.clear();
    this.#pendingQuery = "";
  }
}
