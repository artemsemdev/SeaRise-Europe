import type { RankedSearchResult, SettlementSearchRecord } from "./types";

const ADMIN_PRIORITY: Readonly<Record<string, number>> = Object.freeze({
  PPLC: 6,
  PPLA: 5,
  PPLA2: 4,
  PPLA3: 3,
  PPLA4: 2,
  PPLA5: 1,
});
const MARKS = new RegExp("\\p{M}+", "gu");

export function normalizeSearchText(value: string): string {
  for (let index = 0; index < value.length; index += 1) {
    const unit = value.charCodeAt(index);
    if (unit >= 0xd800 && unit <= 0xdbff) {
      const next = value.charCodeAt(index + 1);
      if (!(next >= 0xdc00 && next <= 0xdfff)) throw new Error("search text contains unpaired UTF-16");
      index += 1;
    } else if (unit >= 0xdc00 && unit <= 0xdfff) {
      throw new Error("search text contains unpaired UTF-16");
    }
  }
  for (const point of value) {
    const code = point.codePointAt(0)!;
    if (code <= 0x1f || (code >= 0x7f && code <= 0x9f)) {
      throw new Error("search text contains control characters");
    }
  }
  return value.normalize("NFKD").replace(MARKS, "").toLowerCase().trim().replace(/\s+/g, " ");
}

export function searchFuzzyAllowance(normalizedQuery: string): 0 | 1 | 2 {
  const length = Array.from(normalizedQuery).length;
  return length < 4 ? 0 : length < 8 ? 1 : 2;
}

export function hasQualifiedContext(
  query: string,
  normalizedName: string,
  record: SettlementSearchRecord,
): boolean {
  if (!query.startsWith(`${normalizedName} `)) return false;
  const context = new Set(
    normalizeSearchText(`${record.countryCode} ${record.admin1Name ?? ""}`).split(" "),
  );
  return query.slice(normalizedName.length + 1).split(" ").every((term) => context.has(term));
}

function numericId(value: string): bigint {
  const match = /^(?:geonames|synthetic):([1-9][0-9]*)$/.exec(value);
  if (!match) throw new Error("search place ID differs from the supported stable ID contract");
  return BigInt(match[1]);
}

export function compareRankedResults(left: RankedSearchResult, right: RankedSearchResult): number {
  const idDifference = numericId(left.record.placeId) - numericId(right.record.placeId);
  return left.matchTier - right.matchTier
    || left.editDistance - right.editDistance
    || (right.record.population ?? -1) - (left.record.population ?? -1)
    || (ADMIN_PRIORITY[right.record.featureCode] ?? 0) - (ADMIN_PRIORITY[left.record.featureCode] ?? 0)
    || left.record.distanceToCoastMeters - right.record.distanceToCoastMeters
    || (idDifference < 0n ? -1 : idDifference > 0n ? 1 : 0)
    || (left.shardId === right.shardId ? 0 : left.shardId === "europe-core" ? -1 : 1);
}

export function mergeRankedResults(
  core: readonly RankedSearchResult[],
  coastal: readonly RankedSearchResult[],
  limit = 10,
): readonly SettlementSearchRecord[] {
  const strongest = new Map<string, RankedSearchResult>();
  for (const result of [...core, ...coastal]) {
    const previous = strongest.get(result.record.placeId);
    if (!previous || compareRankedResults(result, previous) < 0) strongest.set(result.record.placeId, result);
  }
  return [...strongest.values()].sort(compareRankedResults).slice(0, limit).map(({ record }) => record);
}
