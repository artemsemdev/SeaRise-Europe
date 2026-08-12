import type { CandidateDocument, SearchDocument } from "./types";

const ADMIN_PRIORITY: Readonly<Record<string, number>> = {
  PPLC: 6, PPLA: 5, PPLA2: 4, PPLA3: 3, PPLA4: 2, PPLA5: 1,
};
const MARKS = new RegExp("\\p{M}+", "gu");
const TOKENS = new RegExp("[\\p{L}\\p{N}]+", "gu");

export function normalizeSearchText(value: string): string {
  for (let index = 0; index < value.length; index += 1) {
    const unit = value.charCodeAt(index);
    if (unit >= 0xd800 && unit <= 0xdbff) {
      const next = value.charCodeAt(index + 1);
      if (!(next >= 0xdc00 && next <= 0xdfff)) throw new Error("search text contains unpaired UTF-16");
      index += 1;
    } else if (unit >= 0xdc00 && unit <= 0xdfff) throw new Error("search text contains unpaired UTF-16");
  }
  if (/[\u0000-\u001f\u007f-\u009f]/.test(value)) throw new Error("search text contains control characters");
  return value
    .normalize("NFKD")
    .replace(MARKS, "")
    .toLowerCase()
    .trim()
    .replace(/\s+/g, " ");
}

export function tokenizeSearchText(value: string): string[] {
  return normalizeSearchText(value).match(TOKENS) ?? [];
}

function splitId(value: string): [string, bigint] {
  const match = /^(geonames|synthetic):([1-9][0-9]*)$/.exec(value);
  if (!match) throw new Error(`search evaluation placeId has no valid numeric suffix: ${value}`);
  return [match[1], BigInt(match[2])];
}

function compareId(left: string, right: string): number {
  const difference = splitId(left)[1] - splitId(right)[1];
  return difference < BigInt(0) ? -1 : difference > BigInt(0) ? 1 : 0;
}

export function prepareCandidateDocuments(records: readonly SearchDocument[]): CandidateDocument[] {
  const namespaces = new Set(records.map(({ placeId }) => splitId(placeId)[0]));
  if (namespaces.size > 1) throw new Error("search evaluation input mixes placeId namespaces");
  const sorted = [...records].sort((a, b) => compareId(a.placeId, b.placeId));
  if (new Set(sorted.map((record) => record.placeId)).size !== sorted.length) {
    throw new Error("search evaluation input contains duplicate placeId values");
  }
  return sorted.map((record, ordinal) => {
    const values = [record.displayName, ...record.searchNames, record.countryCode, record.admin1Name ?? ""];
    const terms = Array.from(new Set(values.flatMap(tokenizeSearchText))).join(" ");
    return { ordinal: ordinal + 1, record, terms };
  });
}

export function searchFuzzyAllowance(normalizedQuery: string): 0 | 1 | 2 {
  const length = Array.from(normalizedQuery).length;
  return length < 4 ? 0 : length < 8 ? 1 : 2;
}

export function boundedEditDistance(left: string, right: string, maximum: number): number {
  const leftPoints = Array.from(left);
  const rightPoints = Array.from(right);
  if (Math.abs(leftPoints.length - rightPoints.length) > maximum) return maximum + 1;
  let previous = Array.from({ length: rightPoints.length + 1 }, (_, index) => index);
  for (let leftIndex = 1; leftIndex <= leftPoints.length; leftIndex += 1) {
    const current = Array<number>(rightPoints.length + 1).fill(maximum + 1);
    current[0] = leftIndex;
    const first = Math.max(1, leftIndex - maximum);
    const last = Math.min(rightPoints.length, leftIndex + maximum);
    for (let rightIndex = first; rightIndex <= last; rightIndex += 1) {
      current[rightIndex] = Math.min(
        current[rightIndex - 1] + 1,
        previous[rightIndex] + 1,
        previous[rightIndex - 1] + (leftPoints[leftIndex - 1] === rightPoints[rightIndex - 1] ? 0 : 1),
      );
    }
    previous = current;
  }
  return previous[rightPoints.length];
}

export function hasQualifiedSearchContext(
  query: string, name: string, record: SearchDocument,
): boolean {
  if (!query.startsWith(`${name} `)) return false;
  const context = new Set(tokenizeSearchText(`${record.countryCode} ${record.admin1Name ?? ""}`));
  return tokenizeSearchText(query.slice(name.length)).every((term) => context.has(term));
}

export type SearchMatchKey = readonly [number, number];

export type RankedCandidateDocument = {
  document: CandidateDocument;
  match: SearchMatchKey;
};

function matchKey(query: string, record: SearchDocument): SearchMatchKey {
  const canonical = normalizeSearchText(record.displayName);
  const alternates = record.searchNames.map(normalizeSearchText).filter((name) => name !== canonical);
  const qualified = (name: string) => query === name || hasQualifiedSearchContext(query, name, record);
  if (qualified(canonical)) return [0, 0];
  if (alternates.some(qualified)) return [1, 0];
  if ([canonical, ...alternates].some((name) => name.startsWith(query))) return [2, 0];
  const allowance = searchFuzzyAllowance(query);
  if (allowance === 0) return [4, 1];
  let distance = boundedEditDistance(query, canonical, allowance);
  for (const alternate of alternates) {
    const candidate = boundedEditDistance(query, alternate, allowance);
    if (candidate < distance) distance = candidate;
    if (distance === 1) break;
  }
  return distance <= allowance ? [3, distance] : [4, distance];
}

export function compareRankedCandidates(
  left: RankedCandidateDocument, right: RankedCandidateDocument,
): number {
  return left.match[0] - right.match[0]
    || left.match[1] - right.match[1]
    || (right.document.record.population ?? -1) - (left.document.record.population ?? -1)
    || (ADMIN_PRIORITY[right.document.record.featureCode] ?? 0)
      - (ADMIN_PRIORITY[left.document.record.featureCode] ?? 0)
    || left.document.record.distanceToCoastMeters - right.document.record.distanceToCoastMeters
    || compareId(left.document.record.placeId, right.document.record.placeId);
}

export function rankDocuments(queryText: string, documents: readonly CandidateDocument[]): CandidateDocument[] {
  const query = normalizeSearchText(queryText);
  if (!query) return [];
  return documents.map((document) => ({ document, match: matchKey(query, document.record) }))
    .filter(({ match }) => match[0] < 4)
    .sort(compareRankedCandidates)
    .map(({ document }) => document);
}
