import type { ResolvedArtifact, TechnicalError } from "../domain/release";

export const SEARCH_SHARD_IDS = ["europe-core", "europe-coastal"] as const;
export type SearchShardId = (typeof SEARCH_SHARD_IDS)[number];

export interface SettlementSearchRecord {
  readonly placeId: string;
  readonly displayName: string;
  readonly searchNames: readonly string[];
  readonly countryCode: string;
  readonly admin1Name: string | null;
  readonly population: number | null;
  readonly featureCode: string;
  readonly distanceToCoastMeters: number;
  readonly isCoastal: boolean;
  readonly latitude: number;
  readonly longitude: number;
}

export interface SearchShardAuthority {
  readonly shardId: SearchShardId;
  readonly dataReleaseId: string;
  readonly dataProvenanceClass: "real-source" | "synthetic-fixture";
  readonly artifact: Pick<ResolvedArtifact, "artifactId" | "byteSize" | "sha256" | "url">;
}

export interface RankedSearchResult {
  readonly record: SettlementSearchRecord;
  readonly matchTier: 0 | 1 | 2 | 3;
  readonly editDistance: number;
  readonly shardId: SearchShardId;
}

export type SearchReadiness = "idle" | "loading-core" | "core-ready" | "all-ready";

export interface SettlementSearchState {
  readonly readiness: SearchReadiness;
  readonly query: string;
  readonly results: readonly SettlementSearchRecord[];
  readonly pending: boolean;
  readonly error: TechnicalError | null;
  readonly durationMilliseconds: number | null;
  readonly initializationMilliseconds: number | null;
}
