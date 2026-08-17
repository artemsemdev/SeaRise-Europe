import type { TechnicalError } from "../domain/release";
import type { RankedSearchResult, SearchShardAuthority, SearchShardId } from "./types";

export const SEARCH_WORKER_VERSION = "settlement-browser-worker-v2" as const;

export type SearchWorkerRequest =
  | { readonly kind: "initialize"; readonly token: number; readonly authority: SearchShardAuthority; readonly verifiedBytes?: ArrayBuffer }
  | { readonly kind: "load-shard"; readonly token: number; readonly authority: SearchShardAuthority; readonly verifiedBytes?: ArrayBuffer }
  | { readonly kind: "query"; readonly token: number; readonly query: string }
  | { readonly kind: "terminate"; readonly token: number };

export type SearchWorkerResponse =
  | {
      readonly kind: "ready";
      readonly token: number;
      readonly shardId: SearchShardId;
      readonly runtimeVersion: typeof SEARCH_WORKER_VERSION;
      readonly durationMilliseconds: number;
    }
  | {
      readonly kind: "results";
      readonly token: number;
      readonly results: readonly RankedSearchResult[];
      readonly durationMilliseconds: number;
      readonly readyShards: readonly SearchShardId[];
    }
  | {
      readonly kind: "error";
      readonly token: number;
      readonly operation: "initialize" | "load-shard" | "query" | "protocol";
      readonly error: TechnicalError;
    };

export interface SearchWorkerPort {
  onmessage: ((event: MessageEvent<SearchWorkerResponse>) => void) | null;
  onerror: ((event: ErrorEvent) => void) | null;
  postMessage(message: SearchWorkerRequest, transfer?: Transferable[]): void;
  terminate(): void;
}
