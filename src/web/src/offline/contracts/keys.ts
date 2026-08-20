export const OFFLINE_CONTRACT_VERSION = 1 as const;
export const OFFLINE_CACHE_PREFIX = "searise-offline:v1" as const;
export const OFFLINE_RANGE_DATABASE = "searise-offline:v1" as const;

export type AppBuildId = string & { readonly __appBuildId: unique symbol };
export type OfflineDataReleaseId = string & { readonly __dataReleaseId: unique symbol };

const AUTHORITY_ID = /^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/u;

function authorityId(value: unknown, name: string): string {
  if (typeof value !== "string" || !AUTHORITY_ID.test(value)) {
    throw new TypeError(`${name} must be 1-128 ASCII letters, digits, dots, underscores, or hyphens.`);
  }
  return value;
}
export function appBuildId(value: unknown): AppBuildId {
  return authorityId(value, "appBuildId") as AppBuildId;
}

export function offlineDataReleaseId(value: unknown): OfflineDataReleaseId {
  return authorityId(value, "dataReleaseId") as OfflineDataReleaseId;
}

export interface AppReleasePairV1 {
  readonly contractVersion: typeof OFFLINE_CONTRACT_VERSION;
  readonly appBuildId: AppBuildId;
  readonly dataReleaseId: OfflineDataReleaseId;
}

export interface OfflineCacheNamespacesV1 {
  readonly pairKey: string;
  readonly shell: string;
  readonly release: string;
  readonly rangeDatabase: typeof OFFLINE_RANGE_DATABASE;
}

export function validateAppReleasePair(value: unknown): AppReleasePairV1 {
  const record = exactRecord(value, ["contractVersion", "appBuildId", "dataReleaseId"], "app/release pair");
  if (record.contractVersion !== OFFLINE_CONTRACT_VERSION) {
    throw new TypeError("Unsupported offline contract version.");
  }
  return Object.freeze({
    contractVersion: OFFLINE_CONTRACT_VERSION,
    appBuildId: appBuildId(record.appBuildId),
    dataReleaseId: offlineDataReleaseId(record.dataReleaseId),
  });
}

export function cacheNamespaces(pair: AppReleasePairV1): OfflineCacheNamespacesV1 {
  const validated = validateAppReleasePair(pair);
  const pairKey = `${validated.appBuildId}::${validated.dataReleaseId}`;
  return Object.freeze({
    pairKey,
    shell: `${OFFLINE_CACHE_PREFIX}:shell:${pairKey}`,
    release: `${OFFLINE_CACHE_PREFIX}:release:${pairKey}`,
    rangeDatabase: OFFLINE_RANGE_DATABASE,
  });
}

export function exactRecord(
  value: unknown,
  keys: readonly string[],
  name: string,
): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new TypeError(`${name} must be an object.`);
  }
  const record = value as Record<string, unknown>;
  const expected = new Set(keys);
  const actual = Object.keys(record);
  if (actual.length !== expected.size || actual.some((key) => !expected.has(key))) {
    throw new TypeError(`${name} contains missing or additional properties.`);
  }
  return record;
}
