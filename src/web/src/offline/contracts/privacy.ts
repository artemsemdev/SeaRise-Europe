import { exactRecord } from "./keys";
import { validateClientLease, type ClientLeaseV1 } from "./policy";
import {
  OfflineContractError,
  validateRangeIdentity,
  validateWholeResourceAuthority,
  type RangeIdentityV1,
  type WholeResourceAuthorityV1,
} from "./v1";

export const PERSISTENCE_EXCLUSIONS_V1 = Object.freeze([
  "searchText", "placeLabel", "latitude", "longitude", "coordinates",
  "history", "query", "profile", "selection", "browserUrl", "urlSearchParameters",
] as const);

export type PersistedOfflineRecordV1 =
  | Readonly<{
      recordType: "whole-resource";
      authority: WholeResourceAuthorityV1;
      state: "verified";
      byteLength: number;
      lastAccessSequence: number;
    }>
  | Readonly<{
      recordType: "range";
      identity: RangeIdentityV1;
      state: "verified";
      byteLength: number;
      lastAccessSequence: number;
    }>
  | Readonly<{
      recordType: "lease";
      lease: ClientLeaseV1;
    }>;

function safeCount(value: unknown, name: string): number {
  if (!Number.isSafeInteger(value) || (value as number) < 0) {
    throw new OfflineContractError(`${name} must be a non-negative safe integer.`);
  }
  return value as number;
}

export function validatePersistedOfflineRecord(value: unknown): PersistedOfflineRecordV1 {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new OfflineContractError("Persisted offline record must be an object.");
  }
  const recordType = (value as Record<string, unknown>).recordType;
  if (recordType === "whole-resource") {
    const record = exactRecord(value, ["recordType", "authority", "state", "byteLength", "lastAccessSequence"], "persisted whole resource");
    if (record.state !== "verified") throw new OfflineContractError("Only verified whole resources may be persisted.");
    const authority = validateWholeResourceAuthority(record.authority);
    const byteLength = safeCount(record.byteLength, "byteLength");
    if (byteLength !== authority.byteSize) throw new OfflineContractError("Persisted whole-resource length must equal its authority.");
    return Object.freeze({ recordType, authority, state: "verified", byteLength, lastAccessSequence: safeCount(record.lastAccessSequence, "lastAccessSequence") });
  }
  if (recordType === "range") {
    const record = exactRecord(value, ["recordType", "identity", "state", "byteLength", "lastAccessSequence"], "persisted range");
    if (record.state !== "verified") throw new OfflineContractError("Only verified ranges may be persisted.");
    const identity = validateRangeIdentity(record.identity);
    const byteLength = safeCount(record.byteLength, "byteLength");
    if (byteLength !== identity.interval.endExclusive - identity.interval.start) throw new OfflineContractError("Persisted range length must equal its half-open interval.");
    return Object.freeze({ recordType, identity, state: "verified", byteLength, lastAccessSequence: safeCount(record.lastAccessSequence, "lastAccessSequence") });
  }
  if (recordType === "lease") {
    const record = exactRecord(value, ["recordType", "lease"], "persisted lease");
    return Object.freeze({ recordType, lease: validateClientLease(record.lease) });
  }
  throw new OfflineContractError("Persisted offline record type is unsupported.");
}
