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

function editDistance(left: string, right: string): number {
  const leftPoints = Array.from(left);
  const rightPoints = Array.from(right);
  let previous = Array.from({ length: rightPoints.length + 1 }, (_, index) => index);
  for (let leftIndex = 1; leftIndex <= leftPoints.length; leftIndex += 1) {
    const current = [leftIndex];
    for (let rightIndex = 1; rightIndex <= rightPoints.length; rightIndex += 1) {
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

function matchKey(query: string, record: SearchDocument): [number, number] {
  const canonical = normalizeSearchText(record.displayName);
  const alternates = record.searchNames.map(normalizeSearchText).filter((name) => name !== canonical);
  const context = new Set(tokenizeSearchText(`${record.countryCode} ${record.admin1Name ?? ""}`));
  const qualified = (name: string) => query === name
    || (query.startsWith(`${name} `) && tokenizeSearchText(query.slice(name.length)).every((term) => context.has(term)));
  if (qualified(canonical)) return [0, 0];
  if (alternates.some(qualified)) return [1, 0];
  if ([canonical, ...alternates].some((name) => name.startsWith(query))) return [2, 0];
  const queryLength = Array.from(query).length;
  const allowance = queryLength < 4 ? 0 : queryLength < 8 ? 1 : 2;
  const distance = Math.min(...[canonical, ...alternates].map((name) => editDistance(query, name)));
  return allowance > 0 && distance <= allowance ? [3, distance] : [4, distance];
}

export function rankDocuments(queryText: string, documents: readonly CandidateDocument[]): CandidateDocument[] {
  const query = normalizeSearchText(queryText);
  if (!query) return [];
  return [...documents].filter((document) => matchKey(query, document.record)[0] < 4).sort((left, right) => {
    const leftMatch = matchKey(query, left.record);
    const rightMatch = matchKey(query, right.record);
    return leftMatch[0] - rightMatch[0]
      || leftMatch[1] - rightMatch[1]
      || (right.record.population ?? -1) - (left.record.population ?? -1)
      || (ADMIN_PRIORITY[right.record.featureCode] ?? 0) - (ADMIN_PRIORITY[left.record.featureCode] ?? 0)
      || left.record.distanceToCoastMeters - right.record.distanceToCoastMeters
      || compareId(left.record.placeId, right.record.placeId);
  });
}
