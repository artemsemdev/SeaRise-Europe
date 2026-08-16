import type { ReleaseDisposition } from "../../domain/release";
import {
  OFFLINE_CONTRACT_VERSION,
  type AppReleasePairV1,
  exactRecord,
  validateAppReleasePair,
} from "./keys";

export { OFFLINE_CONTRACT_VERSION } from "./keys";
export type { AppBuildId, AppReleasePairV1, OfflineDataReleaseId } from "./keys";

export type Sha256Hex = string & { readonly __sha256Hex: unique symbol };
export type CanonicalResourceUrl = string & { readonly __canonicalResourceUrl: unique symbol };

const SHA256_HEX = /^[0-9a-f]{64}$/u;
const SAFE_IDENTIFIER = /^[A-Za-z0-9][A-Za-z0-9._/-]{0,255}$/u;
const ETAG = /^"sha256-[0-9a-f]{64}"$/u;

export class OfflineContractError extends TypeError {
  constructor(message: string) {
    super(message);
    this.name = "OfflineContractError";
  }
}

function fail(message: string): never {
  throw new OfflineContractError(message);
}

function stringValue(value: unknown, name: string, maximum = 256): string {
  if (typeof value !== "string" || value.length === 0 || value.length > maximum) {
    fail(`${name} must be a non-empty string of at most ${maximum} characters.`);
  }
  return value;
}

function safeIdentifier(value: unknown, name: string): string {
  const text = stringValue(value, name);
  if (!SAFE_IDENTIFIER.test(text) || text.includes("..") || text.startsWith("/")) {
    fail(`${name} is not a canonical relative identifier.`);
  }
  return text;
}

function positiveSafeInteger(value: unknown, name: string): number {
  if (!Number.isSafeInteger(value) || (value as number) <= 0) {
    fail(`${name} must be a positive safe integer.`);
  }
  return value as number;
}

function nonNegativeSafeInteger(value: unknown, name: string): number {
  if (!Number.isSafeInteger(value) || (value as number) < 0) {
    fail(`${name} must be a non-negative safe integer.`);
  }
  return value as number;
}

function pairFromRecord(record: Record<string, unknown>): AppReleasePairV1 {
  return validateAppReleasePair({
    contractVersion: record.contractVersion,
    appBuildId: record.appBuildId,
    dataReleaseId: record.dataReleaseId,
  });
}

function assertReleaseScopedUrl(url: CanonicalResourceUrl, pair: AppReleasePairV1, name: string): void {
  const rawSegments = new URL(url).pathname.split("/");
  let segments: readonly string[];
  try {
    segments = rawSegments.map((segment) => decodeURIComponent(segment));
  } catch {
    fail(`${name} pathname contains invalid percent encoding.`);
  }
  if (
    !segments.some((segment) => segment === pair.dataReleaseId)
    || rawSegments.some(
      (segment, index) => segments[index] === pair.dataReleaseId && segment !== pair.dataReleaseId,
    )
  ) {
    fail(`${name} must contain the exact dataReleaseId path segment.`);
  }
}

export function sha256Hex(value: unknown, name = "sha256"): Sha256Hex {
  if (typeof value !== "string" || !SHA256_HEX.test(value)) {
    fail(`${name} must be a lowercase SHA-256 hexadecimal digest.`);
  }
  return value as Sha256Hex;
}

export function canonicalResourceUrl(value: unknown, name = "canonicalUrl"): CanonicalResourceUrl {
  const text = stringValue(value, name, 2048);
  let url: URL;
  try {
    url = new URL(text);
  } catch {
    fail(`${name} must be an absolute URL.`);
  }
  if (!new Set(["http:", "https:"]).has(url.protocol) || url.username || url.password || url.search || url.hash) {
    fail(`${name} must be an HTTP(S) URL without credentials, query, or fragment.`);
  }
  return url.href as CanonicalResourceUrl;
}

export interface AppAuthorityV1 extends AppReleasePairV1 {
  readonly manifestUrl: CanonicalResourceUrl;
  readonly releaseDisposition: ReleaseDisposition;
  readonly precacheSetSha256: Sha256Hex;
}

export interface VerifiedReleaseAuthorityV1 extends AppAuthorityV1 {
  readonly manifest: Readonly<{
    canonicalUrl: CanonicalResourceUrl;
    byteSize: number;
    sha256: Sha256Hex;
    etag: string | null;
    methodologyVersion: "ar6-regional-projection-v1";
    dataProvenanceClass: "real-source" | "synthetic-fixture";
  }>;
}

const RELEASE_DISPOSITIONS = new Set<unknown>([
  "synthetic-fixture", "private-engineering", "public-promoted",
]);

export function validateAppAuthority(value: unknown): AppAuthorityV1 {
  const record = exactRecord(value, [
    "contractVersion", "appBuildId", "dataReleaseId", "manifestUrl",
    "releaseDisposition", "precacheSetSha256",
  ], "app authority");
  const pair = pairFromRecord(record);
  if (!RELEASE_DISPOSITIONS.has(record.releaseDisposition)) fail("releaseDisposition is unsupported.");
  const manifestUrl = canonicalResourceUrl(record.manifestUrl, "manifestUrl");
  assertReleaseScopedUrl(manifestUrl, pair, "manifestUrl");
  return Object.freeze({
    ...pair,
    manifestUrl,
    releaseDisposition: record.releaseDisposition as ReleaseDisposition,
    precacheSetSha256: sha256Hex(record.precacheSetSha256, "precacheSetSha256"),
  });
}

export function validateVerifiedReleaseAuthority(value: unknown): VerifiedReleaseAuthorityV1 {
  const record = exactRecord(value, [
    "contractVersion", "appBuildId", "dataReleaseId", "manifestUrl",
    "releaseDisposition", "precacheSetSha256", "manifest",
  ], "verified release authority");
  const authority = validateAppAuthority({
    contractVersion: record.contractVersion,
    appBuildId: record.appBuildId,
    dataReleaseId: record.dataReleaseId,
    manifestUrl: record.manifestUrl,
    releaseDisposition: record.releaseDisposition,
    precacheSetSha256: record.precacheSetSha256,
  });
  const manifest = exactRecord(record.manifest, [
    "canonicalUrl", "byteSize", "sha256", "etag", "methodologyVersion", "dataProvenanceClass",
  ], "verified manifest authority");
  const canonicalUrl = canonicalResourceUrl(manifest.canonicalUrl, "manifest.canonicalUrl");
  if (canonicalUrl !== authority.manifestUrl) fail("The verified manifest URL must equal the app authority manifest URL.");
  if (manifest.methodologyVersion !== "ar6-regional-projection-v1") fail("The verified manifest methodology is unsupported.");
  if (manifest.dataProvenanceClass !== "real-source" && manifest.dataProvenanceClass !== "synthetic-fixture") fail("The verified manifest provenance class is unsupported.");
  return Object.freeze({
    ...authority,
    manifest: Object.freeze({
      canonicalUrl,
      byteSize: positiveSafeInteger(manifest.byteSize, "manifest.byteSize"),
      sha256: sha256Hex(manifest.sha256, "manifest.sha256"),
      etag: validateOptionalEtag(manifest.etag, "manifest.etag"),
      methodologyVersion: manifest.methodologyVersion,
      dataProvenanceClass: manifest.dataProvenanceClass,
    }),
  });
}

export type PersistenceEligibilityV1 =
  | Readonly<{ mode: "persistent"; pair: AppReleasePairV1 }>
  | Readonly<{ mode: "memory-only"; reason: "private-engineering" | "local-candidate" }>;

export function persistenceEligibility(authority: AppAuthorityV1, localCandidate = false): PersistenceEligibilityV1 {
  const validated = validateAppAuthority(authority);
  if (localCandidate) return Object.freeze({ mode: "memory-only", reason: "local-candidate" });
  if (validated.releaseDisposition === "private-engineering") {
    return Object.freeze({ mode: "memory-only", reason: "private-engineering" });
  }
  return Object.freeze({ mode: "persistent", pair: pairFromRecord(validated as unknown as Record<string, unknown>) });
}

export function assertPersistentEligibility(eligibility: PersistenceEligibilityV1): AppReleasePairV1 {
  if (eligibility.mode !== "persistent") fail(`${eligibility.reason} releases may use session memory only.`);
  return validateAppReleasePair(eligibility.pair);
}

export const WHOLE_RESOURCE_ROLES = [
  "methodology", "source-attribution", "support-boundary", "coastal-boundary",
  "settlement-search-index", "source-grid-identity", "range-integrity-index",
] as const;
export type WholeResourceRoleV1 = (typeof WHOLE_RESOURCE_ROLES)[number];

interface WholeResourceCommonV1 {
  readonly contractVersion: 1;
  readonly pair: AppReleasePairV1;
  readonly canonicalUrl: CanonicalResourceUrl;
  readonly path: string;
  readonly mediaType: string;
  readonly byteSize: number;
  readonly sha256: Sha256Hex;
}

export type WholeResourceAuthorityV1 =
  | (WholeResourceCommonV1 & Readonly<{ authorityKind: "app-asset"; resourceId: string }>)
  | (WholeResourceCommonV1 & Readonly<{
      authorityKind: "release-artifact"; artifactId: string; role: WholeResourceRoleV1; etag: string | null;
    }>)
  | (WholeResourceCommonV1 & Readonly<{ authorityKind: "release-manifest" }>);

function validateWholeCommon(record: Record<string, unknown>): WholeResourceCommonV1 {
  if (record.contractVersion !== OFFLINE_CONTRACT_VERSION) fail("Unsupported offline contract version.");
  const canonicalUrl = canonicalResourceUrl(record.canonicalUrl);
  const path = safeIdentifier(record.path, "path");
  if (!new URL(canonicalUrl).pathname.endsWith(`/${path}`)) fail("canonicalUrl pathname must end with the declared path.");
  return {
    contractVersion: OFFLINE_CONTRACT_VERSION,
    pair: validateAppReleasePair(record.pair),
    canonicalUrl,
    path,
    mediaType: stringValue(record.mediaType, "mediaType", 160),
    byteSize: positiveSafeInteger(record.byteSize, "byteSize"),
    sha256: sha256Hex(record.sha256),
  };
}

export function validateWholeResourceAuthority(value: unknown): WholeResourceAuthorityV1 {
  if (typeof value !== "object" || value === null || Array.isArray(value)) fail("whole resource authority must be an object.");
  const kind = (value as Record<string, unknown>).authorityKind;
  const common = ["contractVersion", "authorityKind", "pair", "canonicalUrl", "path", "mediaType", "byteSize", "sha256"];
  if (kind === "app-asset") {
    const record = exactRecord(value, [...common, "resourceId"], "app asset authority");
    return Object.freeze({ ...validateWholeCommon(record), authorityKind: kind, resourceId: safeIdentifier(record.resourceId, "resourceId") });
  }
  if (kind === "release-manifest") {
    const validated = validateWholeCommon(exactRecord(value, common, "release manifest resource authority"));
    assertReleaseScopedUrl(validated.canonicalUrl, validated.pair, "release manifest URL");
    return Object.freeze({ ...validated, authorityKind: kind });
  }
  if (kind === "release-artifact") {
    const record = exactRecord(value, [...common, "artifactId", "role", "etag"], "release artifact authority");
    if (!(WHOLE_RESOURCE_ROLES as readonly unknown[]).includes(record.role)) fail("release artifact role is not approved for whole-resource persistence.");
    const validated = validateWholeCommon(record);
    assertReleaseScopedUrl(validated.canonicalUrl, validated.pair, "release artifact URL");
    return Object.freeze({
      ...validated,
      authorityKind: kind,
      artifactId: safeIdentifier(record.artifactId, "artifactId"),
      role: record.role as WholeResourceRoleV1,
      etag: validateOptionalEtag(record.etag, "etag"),
    });
  }
  return fail("whole resource authorityKind is unsupported.");
}

export interface ByteIntervalV1 { readonly start: number; readonly endExclusive: number }

export function validateByteInterval(value: unknown, totalByteSize?: number): ByteIntervalV1 {
  const record = exactRecord(value, ["start", "endExclusive"], "byte interval");
  const start = nonNegativeSafeInteger(record.start, "start");
  const endExclusive = positiveSafeInteger(record.endExclusive, "endExclusive");
  if (start >= endExclusive) fail("Byte intervals must be non-empty and half-open.");
  if (totalByteSize !== undefined && endExclusive > positiveSafeInteger(totalByteSize, "totalByteSize")) fail("Byte interval exceeds the artifact size.");
  return Object.freeze({ start, endExclusive });
}

export interface RangeArtifactAuthorityV1 {
  readonly contractVersion: 1;
  readonly pair: AppReleasePairV1;
  readonly artifactId: string;
  readonly role: "projection-analysis-cog" | "projection-visual-pmtiles";
  readonly canonicalUrl: CanonicalResourceUrl;
  readonly path: string;
  readonly mediaType: string;
  readonly totalByteSize: number;
  readonly artifactSha256: Sha256Hex;
  readonly etag: string;
  readonly integrityChunkSize: number;
}

export interface RangeIdentityV1 {
  readonly contractVersion: 1;
  readonly authority: RangeArtifactAuthorityV1;
  readonly interval: ByteIntervalV1;
  readonly authorizedIntervalSha256: Sha256Hex;
}

export function validateRangeArtifactAuthority(value: unknown): RangeArtifactAuthorityV1 {
  const record = exactRecord(value, [
    "contractVersion", "pair", "artifactId", "role", "canonicalUrl", "path", "mediaType",
    "totalByteSize", "artifactSha256", "etag", "integrityChunkSize",
  ], "range artifact authority");
  if (record.contractVersion !== OFFLINE_CONTRACT_VERSION) fail("Unsupported offline contract version.");
  if (record.role !== "projection-analysis-cog" && record.role !== "projection-visual-pmtiles") fail("Range persistence is limited to analysis COGs and visual-only PMTiles.");
  const artifactSha256 = sha256Hex(record.artifactSha256, "artifactSha256");
  const etag = validateRequiredEtag(record.etag, "etag");
  if (etag !== `"sha256-${artifactSha256}"`) fail("Range ETag must bind the complete artifact SHA-256.");
  const canonicalUrl = canonicalResourceUrl(record.canonicalUrl);
  const path = safeIdentifier(record.path, "path");
  if (!new URL(canonicalUrl).pathname.endsWith(`/${path}`)) fail("canonicalUrl pathname must end with the declared path.");
  const pair = validateAppReleasePair(record.pair);
  assertReleaseScopedUrl(canonicalUrl, pair, "range artifact URL");
  return Object.freeze({
    contractVersion: OFFLINE_CONTRACT_VERSION,
    pair,
    artifactId: safeIdentifier(record.artifactId, "artifactId"),
    role: record.role,
    canonicalUrl,
    path,
    mediaType: stringValue(record.mediaType, "mediaType", 160),
    totalByteSize: positiveSafeInteger(record.totalByteSize, "totalByteSize"),
    artifactSha256,
    etag,
    integrityChunkSize: positiveSafeInteger(record.integrityChunkSize, "integrityChunkSize"),
  });
}

export function validateRangeIdentity(value: unknown): RangeIdentityV1 {
  const record = exactRecord(value, ["contractVersion", "authority", "interval", "authorizedIntervalSha256"], "range identity");
  if (record.contractVersion !== OFFLINE_CONTRACT_VERSION) fail("Unsupported offline contract version.");
  const authority = validateRangeArtifactAuthority(record.authority);
  const interval = validateByteInterval(record.interval, authority.totalByteSize);
  if (interval.start % authority.integrityChunkSize !== 0) fail("Persisted intervals must start at an authorized integrity chunk boundary.");
  const expectedEnd = Math.min(interval.start + authority.integrityChunkSize, authority.totalByteSize);
  if (interval.endExclusive !== expectedEnd) fail("Persisted intervals must equal one complete authorized integrity chunk.");
  return Object.freeze({
    contractVersion: OFFLINE_CONTRACT_VERSION,
    authority,
    interval,
    authorizedIntervalSha256: sha256Hex(record.authorizedIntervalSha256, "authorizedIntervalSha256"),
  });
}

function validateRequiredEtag(value: unknown, name: string): string {
  if (typeof value !== "string" || !ETAG.test(value)) fail(`${name} must be a manifest SHA-256 ETag.`);
  return value;
}

function validateOptionalEtag(value: unknown, name: string): string | null {
  return value === null ? null : validateRequiredEtag(value, name);
}
