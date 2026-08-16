import type { DataReleaseId } from "../contracts/generated/release-contract";
import {
  searchQueryKey,
  type SearchQueryOperation,
} from "../domain/projection-search";
import { normalizeSearchText } from "./ranking";

export function createSearchQueryOperation(
  dataReleaseId: DataReleaseId,
  value: string,
  searchToken: number,
  searchGeneration = 1,
): SearchQueryOperation | null {
  if (!Number.isSafeInteger(searchToken) || searchToken < 1 ||
      !Number.isSafeInteger(searchGeneration) || searchGeneration < 1) {
    throw new Error("search generation and token must be positive safe integers");
  }
  const normalizedQuery = normalizeSearchText(value);
  if (!normalizedQuery) return null;
  return Object.freeze({
    dataReleaseId,
    normalizedQuery,
    queryKey: searchQueryKey(dataReleaseId, normalizedQuery),
    searchGeneration,
    searchToken,
  });
}
