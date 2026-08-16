import type { DataReleaseId } from "../contracts/generated/release-contract";
import type { TechnicalError } from "./release";

export interface SearchQueryIdentity {
  readonly dataReleaseId: DataReleaseId;
  readonly normalizedQuery: string;
  readonly queryKey: string;
}

export interface SearchQueryOperation extends SearchQueryIdentity {
  readonly searchGeneration: number;
  readonly searchToken: number;
}

export type SearchOperationGuard = Pick<
  SearchQueryOperation,
  "dataReleaseId" | "queryKey" | "searchGeneration" | "searchToken"
>;

export type SearchLifecycleEvent =
  | { readonly type: "search-started"; readonly operation: SearchQueryOperation }
  | ({ readonly type: "search-completed" } & SearchOperationGuard)
  | ({ readonly type: "search-failed"; readonly error: TechnicalError } & SearchOperationGuard)
  | ({ readonly type: "search-cancelled" } & SearchOperationGuard);

export function searchQueryKey(
  dataReleaseId: DataReleaseId,
  normalizedQuery: string,
): string {
  return `search-v1:${JSON.stringify([dataReleaseId, normalizedQuery])}`;
}
