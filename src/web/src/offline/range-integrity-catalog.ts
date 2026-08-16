import type { ResolvedArtifact, ReleaseContext } from "../domain/release";
import { TechnicalFailure } from "../domain/release";
import { sha256Hex } from "../data/artifact-integrity";
import {
  validateAppAuthority,
  validateRangeArtifactAuthority,
  validateRangeIdentity,
  validateWholeResourceAuthority,
  type AppAuthorityV1,
  type RangeArtifactAuthorityV1,
  type RangeIdentityV1,
  type WholeResourceAuthorityV1,
} from "./contracts/v1";
import { validateAppReleasePair } from "./contracts/keys";
import {
  createRangeAuthorityCatalog,
  type RangeAuthorityCatalogV1,
} from "./range-store";

export interface CogRangeChunkIdentityV1 {
  readonly start: number;
  readonly endExclusive: number;
  readonly sha256: string;
}

export interface CogRangeArtifactIdentityV1 {
  readonly artifactId: string;
  readonly path: string;
  readonly byteSize: number;
  readonly sha256: string;
  readonly chunks: readonly CogRangeChunkIdentityV1[];
}

export interface CogRangeIntegrityIndexV1 {
  readonly schemaVersion: 1;
  readonly dataReleaseId: string;
  readonly algorithm: "sha256";
  readonly chunkSize: 65_536;
  readonly artifacts: readonly CogRangeArtifactIdentityV1[];
}

const VERIFIED_RANGE_INDEX: unique symbol = Symbol("verified-cog-range-integrity-index");

export interface VerifiedCogRangeIntegrityIndexV1 extends CogRangeIntegrityIndexV1 {
  readonly indexAuthority: WholeResourceAuthorityV1;
  readonly [VERIFIED_RANGE_INDEX]: true;
}

function technical(
  code: "SchemaInvalid" | "DecodeFailed" | "IntegrityFailed" | "UnsupportedBrowser",
  message: string,
): TechnicalFailure {
  return new TechnicalFailure({ kind: "technical-error", code, message, recoverable: false });
}

function exactKeys(value: Record<string, unknown>, expected: readonly string[]): boolean {
  return Object.keys(value).sort().join("\0") === [...expected].sort().join("\0");
}

function sha256(value: unknown): value is string {
  return typeof value === "string" && /^[a-f0-9]{64}$/u.test(value);
}

function exactCogArtifacts(context: ReleaseContext): readonly ResolvedArtifact[] {
  return Object.freeze(
    Object.values(context.artifacts)
      .filter((artifact) => artifact.role === "projection-analysis-cog")
      .sort((left, right) => left.artifactId.localeCompare(right.artifactId)),
  );
}

export function bindAppAuthorityToRelease(
  context: ReleaseContext,
  authorityInput: AppAuthorityV1,
): AppAuthorityV1 {
  let authority: AppAuthorityV1;
  try {
    authority = validateAppAuthority(authorityInput);
  } catch (error) {
    throw technical("SchemaInvalid", error instanceof Error ? error.message : "App authority is invalid.");
  }
  if (
    authority.dataReleaseId !== context.dataReleaseId ||
    authority.manifestUrl !== context.manifestUrl ||
    authority.releaseDisposition !== context.disposition
  ) {
    throw technical("IntegrityFailed", "App and verified release authorities do not identify one exact release.");
  }
  const release = context.manifest;
  if (
    (authority.releaseDisposition === "synthetic-fixture" &&
      release.dataProvenanceClass !== "synthetic-fixture") ||
    (authority.releaseDisposition === "public-promoted" && (
      release.dataProvenanceClass !== "real-source" ||
      release.releaseAuthority.automatedValidation !== "passed" ||
      release.releaseAuthority.releaseDisposition !== "approved"
    )) ||
    (authority.releaseDisposition === "private-engineering" && (
      release.dataProvenanceClass !== "real-source" ||
      release.releaseAuthority.automatedValidation !== "pending" ||
      release.releaseAuthority.releaseDisposition !== "pending-owner" ||
      release.releaseAuthority.statusDisclosureRequired !== true ||
      release.publication.cacheControl !== "private, no-store" ||
      release.contractArtifacts.baseReleaseSignature !== null
    ))
  ) {
    throw technical("IntegrityFailed", "Release provenance and promotion state do not match the app disposition.");
  }
  return authority;
}

function indexAuthority(
  context: ReleaseContext,
  authority: AppAuthorityV1,
): WholeResourceAuthorityV1 {
  const artifact = context.artifact(context.manifest.contractArtifacts.rangeIntegrityIndex);
  if (
    artifact.role !== "range-integrity-index" ||
    artifact.path !== "analysis/cog-range-integrity.json" ||
    artifact.mediaType !== "application/json" ||
    artifact.scientificUse !== "exact-lookup-support"
  ) {
    throw technical("IntegrityFailed", "The range-integrity artifact has a masqueraded release identity.");
  }
  try {
    return validateWholeResourceAuthority({
      contractVersion: 1,
      authorityKind: "release-artifact",
      pair: validateAppReleasePair({
        contractVersion: 1,
        appBuildId: authority.appBuildId,
        dataReleaseId: authority.dataReleaseId,
      }),
      artifactId: artifact.artifactId,
      role: artifact.role,
      canonicalUrl: artifact.url,
      path: artifact.path,
      mediaType: artifact.mediaType,
      byteSize: artifact.byteSize,
      sha256: artifact.sha256,
      etag: `"sha256-${artifact.sha256}"`,
    });
  } catch (error) {
    throw technical("IntegrityFailed", error instanceof Error ? error.message : "Range-integrity authority is invalid.");
  }
}

function decodeIndex(bytes: ArrayBuffer): unknown {
  try {
    return JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes));
  } catch {
    throw technical("DecodeFailed", "The verified COG range-integrity artifact is not valid UTF-8 JSON.");
  }
}

export function parseCogRangeIntegrityDocument(
  value: unknown,
  context: ReleaseContext,
): CogRangeIntegrityIndexV1 {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw technical("SchemaInvalid", "The COG range-integrity artifact is not an object.");
  }
  const document = value as Record<string, unknown>;
  if (
    !exactKeys(document, ["schemaVersion", "dataReleaseId", "algorithm", "chunkSize", "artifacts"]) ||
    document.schemaVersion !== 1 ||
    document.dataReleaseId !== context.dataReleaseId ||
    document.algorithm !== "sha256" ||
    document.chunkSize !== 65_536 ||
    !Array.isArray(document.artifacts)
  ) {
    throw technical("IntegrityFailed", "The COG range-integrity header is invalid.");
  }

  const expected = exactCogArtifacts(context);
  const expectedById = new Map(expected.map((artifact) => [artifact.artifactId, artifact]));
  const parsed = new Map<string, CogRangeArtifactIdentityV1>();
  for (const rawArtifact of document.artifacts) {
    if (!rawArtifact || typeof rawArtifact !== "object" || Array.isArray(rawArtifact)) {
      throw technical("IntegrityFailed", "The COG range-integrity index contains an invalid artifact.");
    }
    const record = rawArtifact as Record<string, unknown>;
    const artifact = typeof record.artifactId === "string" ? expectedById.get(record.artifactId) : undefined;
    if (
      !exactKeys(record, ["artifactId", "path", "byteSize", "sha256", "chunks"]) ||
      !artifact ||
      record.path !== artifact.path ||
      record.byteSize !== artifact.byteSize ||
      record.sha256 !== artifact.sha256 ||
      !Array.isArray(record.chunks) ||
      parsed.has(artifact.artifactId)
    ) {
      throw technical("IntegrityFailed", "The COG range-integrity index does not match the release manifest.");
    }
    const chunks = record.chunks.map((rawChunk, chunkIndex) => {
      if (!rawChunk || typeof rawChunk !== "object" || Array.isArray(rawChunk)) {
        throw technical("IntegrityFailed", "The COG range-integrity index contains an invalid chunk.");
      }
      const chunk = rawChunk as Record<string, unknown>;
      const start = chunkIndex * 65_536;
      const endExclusive = Math.min(start + 65_536, artifact.byteSize);
      if (
        !exactKeys(chunk, ["start", "endExclusive", "sha256"]) ||
        chunk.start !== start ||
        chunk.endExclusive !== endExclusive ||
        !sha256(chunk.sha256)
      ) {
        throw technical("IntegrityFailed", "The COG range-integrity index has non-canonical chunk coverage.");
      }
      return Object.freeze({ start, endExclusive, sha256: chunk.sha256 });
    });
    if (chunks.length !== Math.ceil(artifact.byteSize / 65_536)) {
      throw technical("IntegrityFailed", "The COG range-integrity index has incomplete object coverage.");
    }
    parsed.set(artifact.artifactId, Object.freeze({
      artifactId: artifact.artifactId,
      path: artifact.path,
      byteSize: artifact.byteSize,
      sha256: artifact.sha256,
      chunks: Object.freeze(chunks),
    }));
  }
  if (
    parsed.size !== expected.length ||
    expected.some((artifact) => !parsed.has(artifact.artifactId))
  ) {
    throw technical("IntegrityFailed", "The COG range-integrity index does not cover the exact release COG set.");
  }
  return Object.freeze({
    schemaVersion: 1,
    dataReleaseId: context.dataReleaseId,
    algorithm: "sha256",
    chunkSize: 65_536,
    artifacts: Object.freeze([...parsed.values()].sort((left, right) =>
      left.artifactId.localeCompare(right.artifactId))),
  });
}

export async function verifyCogRangeIntegrityIndex(
  context: ReleaseContext,
  authorityInput: AppAuthorityV1,
  bytes: ArrayBuffer,
): Promise<VerifiedCogRangeIntegrityIndexV1> {
  const authority = bindAppAuthorityToRelease(context, authorityInput);
  const verifiedIndexAuthority = indexAuthority(context, authority);
  if (
    bytes.byteLength !== verifiedIndexAuthority.byteSize ||
    await sha256Hex(bytes) !== verifiedIndexAuthority.sha256
  ) {
    throw technical("IntegrityFailed", "The COG range-integrity bytes do not match their release authority.");
  }
  const parsed = parseCogRangeIntegrityDocument(decodeIndex(bytes), context);
  return Object.freeze({
    ...parsed,
    indexAuthority: verifiedIndexAuthority,
    [VERIFIED_RANGE_INDEX]: true as const,
  });
}

function rangeAuthority(
  context: ReleaseContext,
  appAuthority: AppAuthorityV1,
  indexed: CogRangeArtifactIdentityV1,
): RangeArtifactAuthorityV1 {
  const artifact = context.artifact(indexed.artifactId);
  try {
    return validateRangeArtifactAuthority({
      contractVersion: 1,
      pair: validateAppReleasePair({
        contractVersion: 1,
        appBuildId: appAuthority.appBuildId,
        dataReleaseId: appAuthority.dataReleaseId,
      }),
      artifactId: artifact.artifactId,
      role: artifact.role,
      canonicalUrl: artifact.url,
      path: artifact.path,
      mediaType: artifact.mediaType,
      totalByteSize: artifact.byteSize,
      artifactSha256: artifact.sha256,
      etag: `"sha256-${artifact.sha256}"`,
      integrityChunkSize: 65_536,
    });
  } catch (error) {
    throw technical("IntegrityFailed", error instanceof Error ? error.message : "COG range authority is invalid.");
  }
}

export function createCogRangeAuthorityCatalog(
  context: ReleaseContext,
  authorityInput: AppAuthorityV1,
  index: VerifiedCogRangeIntegrityIndexV1,
): RangeAuthorityCatalogV1 {
  const authority = bindAppAuthorityToRelease(context, authorityInput);
  const expectedIndexAuthority = indexAuthority(context, authority);
  const expectedCogs = exactCogArtifacts(context);
  const indexedById = new Map(index.artifacts.map((artifact) => [artifact.artifactId, artifact]));
  if (
    index[VERIFIED_RANGE_INDEX] !== true ||
    index.dataReleaseId !== context.dataReleaseId ||
    index.chunkSize !== 65_536 ||
    index.indexAuthority.authorityKind !== "release-artifact" ||
    expectedIndexAuthority.authorityKind !== "release-artifact" ||
    index.indexAuthority.artifactId !== expectedIndexAuthority.artifactId ||
    index.indexAuthority.canonicalUrl !== expectedIndexAuthority.canonicalUrl ||
    index.indexAuthority.path !== expectedIndexAuthority.path ||
    index.indexAuthority.mediaType !== expectedIndexAuthority.mediaType ||
    index.indexAuthority.byteSize !== expectedIndexAuthority.byteSize ||
    index.indexAuthority.sha256 !== expectedIndexAuthority.sha256 ||
    indexedById.size !== expectedCogs.length ||
    expectedCogs.some((artifact) => {
      const indexed = indexedById.get(artifact.artifactId);
      return !indexed || indexed.path !== artifact.path || indexed.byteSize !== artifact.byteSize ||
        indexed.sha256 !== artifact.sha256;
    })
  ) {
    throw technical("IntegrityFailed", "The verified range index belongs to another release.");
  }
  const identities: RangeIdentityV1[] = [];
  for (const indexed of index.artifacts) {
    const artifactAuthority = rangeAuthority(context, authority, indexed);
    for (const chunk of indexed.chunks) {
      try {
        identities.push(validateRangeIdentity({
          contractVersion: 1,
          authority: artifactAuthority,
          interval: { start: chunk.start, endExclusive: chunk.endExclusive },
          authorizedIntervalSha256: chunk.sha256,
        }));
      } catch (error) {
        throw technical("IntegrityFailed", error instanceof Error ? error.message : "COG range identity is invalid.");
      }
    }
  }
  return createRangeAuthorityCatalog(identities);
}
