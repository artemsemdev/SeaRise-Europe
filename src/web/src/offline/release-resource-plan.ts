import type { ArtifactRole } from "../contracts/generated/release-contract";
import type { ReleaseContext, ResolvedArtifact } from "../domain/release";
import { TechnicalFailure } from "../domain/release";
import { validateAppReleasePair } from "./contracts/keys";
import {
  WHOLE_RESOURCE_ROLES,
  persistenceEligibility,
  validateWholeResourceAuthority,
  type AppAuthorityV1,
  type PersistenceEligibilityV1,
  type RangeIdentityV1,
  type WholeResourceAuthorityV1,
} from "./contracts/v1";
import {
  bindAppAuthorityToRelease,
  createCogRangeAuthorityCatalog,
  verifyCogRangeIntegrityIndex,
  type VerifiedCogRangeIntegrityIndexV1,
} from "./range-integrity-catalog";
import type { RangeAuthorityCatalogV1 } from "./range-store";

const KNOWN_ARTIFACT_ROLES: ReadonlySet<ArtifactRole> = new Set([
  "release-manifest", "contract-schema", "scenario-config", "methodology",
  "source-attribution", "source-receipt", "build-receipt", "base-release-build-receipt",
  "browser-derivation-receipt", "support-boundary", "coastal-boundary",
  "settlement-search-index", "settlement-search-receipt", "settlement-geoparquet",
  "projection-analysis-cog", "source-grid-identity", "range-integrity-index", "sbom",
  "projection-visual-pmtiles", "projection-geoparquet", "quality-summary",
  "release-gate-report", "architecture-evidence", "stac-catalog", "stac-collection",
  "stac-item", "checksums", "provenance", "base-release-provenance",
  "browser-derivation-provenance", "base-release-signature", "signature",
]);

export interface ExactReleaseResourceIdentityV1 {
  readonly artifactId: string;
  readonly role: ArtifactRole;
  readonly canonicalUrl: string;
  readonly path: string;
  readonly mediaType: string;
  readonly byteSize: number;
  readonly sha256: string;
}

export type ReleaseResourceRouteV1 =
  | Readonly<{
      kind: "complete-resource";
      storage: "cache-storage" | "memory-only";
      authority: WholeResourceAuthorityV1;
    }>
  | Readonly<{
      kind: "analysis-cog-ranges";
      storage: "indexeddb" | "memory-only";
      identity: ExactReleaseResourceIdentityV1;
      ranges: readonly RangeIdentityV1[];
    }>
  | Readonly<{
      kind: "network-only";
      storage: "network-only" | "memory-only";
      requestCache: "no-store";
      reason: "visual-pmtiles" | "not-approved-for-persistence";
      identity: ExactReleaseResourceIdentityV1;
    }>;

export interface VerifiedReleaseResourcePlanV1 {
  readonly contractVersion: 1;
  readonly pair: Readonly<{ contractVersion: 1; appBuildId: string; dataReleaseId: string }>;
  readonly persistence: PersistenceEligibilityV1;
  readonly rangeIndex: VerifiedCogRangeIntegrityIndexV1;
  readonly rangeCatalog: RangeAuthorityCatalogV1;
  readonly routes: readonly ReleaseResourceRouteV1[];
}

function technical(message: string): TechnicalFailure {
  return new TechnicalFailure({
    kind: "technical-error",
    code: "IntegrityFailed",
    message,
    recoverable: false,
  });
}

function exactIdentity(artifact: ResolvedArtifact): ExactReleaseResourceIdentityV1 {
  return Object.freeze({
    artifactId: artifact.artifactId,
    role: artifact.role,
    canonicalUrl: artifact.url,
    path: artifact.path,
    mediaType: artifact.mediaType,
    byteSize: artifact.byteSize,
    sha256: artifact.sha256,
  });
}

function assertExactContextArtifacts(context: ReleaseContext): readonly ResolvedArtifact[] {
  const manifestArtifacts = new Map(context.manifest.artifacts.map((artifact) => [artifact.artifactId, artifact]));
  const resolved = Object.values(context.artifacts);
  if (manifestArtifacts.size !== context.manifest.artifacts.length || resolved.length !== manifestArtifacts.size) {
    throw technical("The verified release artifact set is duplicated or incomplete.");
  }
  const releaseRoot = new URL("./", context.manifestUrl);
  for (const artifact of resolved) {
    const declared = manifestArtifacts.get(artifact.artifactId);
    if (
      !declared ||
      !KNOWN_ARTIFACT_ROLES.has(artifact.role) ||
      artifact.dataReleaseId !== context.dataReleaseId ||
      artifact.dataProvenanceClass !== context.manifest.dataProvenanceClass ||
      artifact.role !== declared.role ||
      artifact.path !== declared.path ||
      artifact.mediaType !== declared.mediaType ||
      artifact.byteSize !== declared.byteSize ||
      artifact.sha256 !== declared.sha256 ||
      artifact.scientificUse !== declared.scientificUse ||
      artifact.url !== new URL(declared.path, releaseRoot).href
    ) {
      throw technical(`Artifact ${artifact.artifactId} does not match its exact verified manifest identity.`);
    }
  }
  return Object.freeze(resolved.sort((left, right) => left.artifactId.localeCompare(right.artifactId)));
}

function wholeAuthority(
  artifact: ResolvedArtifact,
  appAuthority: AppAuthorityV1,
): WholeResourceAuthorityV1 {
  try {
    return validateWholeResourceAuthority({
      contractVersion: 1,
      authorityKind: "release-artifact",
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
      byteSize: artifact.byteSize,
      sha256: artifact.sha256,
      etag: `"sha256-${artifact.sha256}"`,
    });
  } catch (error) {
    throw technical(error instanceof Error ? error.message : "Whole-resource authority is invalid.");
  }
}

function assertPmtiles(artifact: ResolvedArtifact): void {
  if (
    artifact.mediaType !== "application/vnd.pmtiles" ||
    artifact.scientificUse !== "visual-only" ||
    !/^layers\/(ssp1-26|ssp2-45|ssp5-85)\/(2030|2050|2100)\.pmtiles$/u.test(artifact.path)
  ) {
    throw technical(`Artifact ${artifact.artifactId} masquerades as visual PMTiles.`);
  }
}

export async function createVerifiedReleaseResourcePlan(input: Readonly<{
  context: ReleaseContext;
  appAuthority: AppAuthorityV1;
  rangeIntegrityBytes: ArrayBuffer;
  localCandidate?: boolean;
}>): Promise<VerifiedReleaseResourcePlanV1> {
  const appAuthority = bindAppAuthorityToRelease(
    input.context,
    input.appAuthority,
  );
  const artifacts = assertExactContextArtifacts(input.context);
  const persistence = persistenceEligibility(appAuthority, input.localCandidate === true);
  const rangeIndex = await verifyCogRangeIntegrityIndex(
    input.context,
    appAuthority,
    input.rangeIntegrityBytes,
  );
  const rangeCatalog = createCogRangeAuthorityCatalog(input.context, appAuthority, rangeIndex);
  const rangesByArtifact = new Map<string, RangeIdentityV1[]>();
  for (const identity of rangeCatalog.identities) {
    const existing = rangesByArtifact.get(identity.authority.artifactId) ?? [];
    existing.push(identity);
    rangesByArtifact.set(identity.authority.artifactId, existing);
  }

  const routes = artifacts.map((artifact): ReleaseResourceRouteV1 => {
    if (artifact.role === "projection-analysis-cog") {
      const ranges = rangesByArtifact.get(artifact.artifactId);
      if (!ranges?.length) throw technical(`Analysis COG ${artifact.artifactId} has no trusted ranges.`);
      return Object.freeze({
        kind: "analysis-cog-ranges",
        storage: persistence.mode === "persistent" ? "indexeddb" : "memory-only",
        identity: exactIdentity(artifact),
        ranges: Object.freeze([...ranges]),
      });
    }
    if (artifact.role === "projection-visual-pmtiles") {
      assertPmtiles(artifact);
      return Object.freeze({
        kind: "network-only",
        storage: "network-only",
        requestCache: "no-store",
        reason: "visual-pmtiles",
        identity: exactIdentity(artifact),
      });
    }
    if ((WHOLE_RESOURCE_ROLES as readonly ArtifactRole[]).includes(artifact.role)) {
      return Object.freeze({
        kind: "complete-resource",
        storage: persistence.mode === "persistent" ? "cache-storage" : "memory-only",
        authority: wholeAuthority(artifact, appAuthority),
      });
    }
    return Object.freeze({
      kind: "network-only",
      storage: persistence.mode === "persistent" ? "network-only" : "memory-only",
      requestCache: "no-store",
      reason: "not-approved-for-persistence",
      identity: exactIdentity(artifact),
    });
  });

  return Object.freeze({
    contractVersion: 1,
    pair: validateAppReleasePair({
      contractVersion: 1,
      appBuildId: appAuthority.appBuildId,
      dataReleaseId: appAuthority.dataReleaseId,
    }),
    persistence,
    rangeIndex,
    rangeCatalog,
    routes: Object.freeze(routes),
  });
}
