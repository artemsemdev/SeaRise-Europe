import type { ArtifactRole } from "../contracts/generated/release-contract";
import validateManifest from "../contracts/generated/manifest-validator.mjs";
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

function boundaryIdentity(
  artifact: ResolvedArtifact,
  basename: "europe" | "coastal-analysis-zone",
): boolean {
  const parquet = artifact.path === `boundaries/${basename}.parquet` &&
    artifact.mediaType === "application/vnd.apache.parquet";
  const geojson = artifact.path === `boundaries/${basename}.geojson` &&
    artifact.mediaType === "application/geo+json";
  return (parquet || geojson) && artifact.scientificUse === "not-applicable";
}

function projectionIdentity(
  artifact: ResolvedArtifact,
  suffix: "cog" | "pmtiles",
  root: "analysis" | "layers",
  extension: "tif" | "pmtiles",
  mediaType: string,
  scientificUse: "exact-lookup" | "visual-only",
): boolean {
  const id = new RegExp(`^projection-(ssp1-26|ssp2-45|ssp5-85)-(2030|2050|2100)-${suffix}$`, "u")
    .exec(artifact.artifactId);
  const path = new RegExp(`^${root}/(ssp1-26|ssp2-45|ssp5-85)/(2030|2050|2100)\\.${extension}$`, "u")
    .exec(artifact.path);
  return Boolean(id && path && id[1] === path[1] && id[2] === path[2]) &&
    artifact.mediaType === mediaType && artifact.scientificUse === scientificUse;
}

function assertCanonicalPersistedSemantics(
  context: ReleaseContext,
  artifacts: readonly ResolvedArtifact[],
): void {
  const counts = new Map<ArtifactRole, number>();
  for (const artifact of artifacts) counts.set(artifact.role, (counts.get(artifact.role) ?? 0) + 1);
  for (const role of [
    "methodology", "source-attribution", "support-boundary", "coastal-boundary",
    "source-grid-identity", "range-integrity-index",
  ] as const) {
    if (counts.get(role) !== 1) throw technical(`The release must contain exactly one canonical ${role} resource.`);
  }
  if (counts.get("settlement-search-index") !== 2) {
    throw technical("The release must contain exactly two canonical settlement search shards.");
  }
  if (counts.get("projection-analysis-cog") !== 9 || counts.get("projection-visual-pmtiles") !== 9) {
    throw technical("The release must contain the exact nine COG and nine PMTiles projection identities.");
  }
  const searchPaths = new Set(artifacts
    .filter((artifact) => artifact.role === "settlement-search-index")
    .map((artifact) => artifact.path));
  if (
    searchPaths.size !== 2 ||
    !searchPaths.has("search/europe-core.codepoint-trie.json.br") ||
    !searchPaths.has("search/europe-coastal.codepoint-trie.json.br")
  ) {
    throw technical("The release search shard set is not canonical.");
  }

  const contracts = context.manifest.contractArtifacts;
  for (const artifact of artifacts) {
    let valid = true;
    switch (artifact.role) {
      case "methodology":
        valid = artifact.artifactId === contracts.methodology &&
          artifact.path === "config/methodology.json" && artifact.mediaType === "application/json" &&
          artifact.scientificUse === "not-applicable";
        break;
      case "source-attribution":
        valid = artifact.artifactId === contracts.attribution &&
          artifact.path === "config/source-attribution.json" && artifact.mediaType === "application/json" &&
          artifact.scientificUse === "not-applicable";
        break;
      case "support-boundary":
        valid = boundaryIdentity(artifact, "europe");
        break;
      case "coastal-boundary":
        valid = boundaryIdentity(artifact, "coastal-analysis-zone");
        break;
      case "settlement-search-index":
        valid = /^search\/europe-(core|coastal)\.codepoint-trie\.json\.br$/u.test(artifact.path) &&
          artifact.mediaType === "application/vnd.searise.search-index+json" &&
          artifact.scientificUse === "not-applicable";
        break;
      case "source-grid-identity":
        valid = artifact.artifactId === contracts.sourceGridIdentity &&
          artifact.path === "analysis/source-grid.json.gz" && artifact.mediaType === "application/gzip" &&
          artifact.scientificUse === "exact-lookup-support";
        break;
      case "range-integrity-index":
        valid = artifact.artifactId === contracts.rangeIntegrityIndex &&
          artifact.path === "analysis/cog-range-integrity.json" && artifact.mediaType === "application/json" &&
          artifact.scientificUse === "exact-lookup-support";
        break;
      case "projection-analysis-cog":
        valid = projectionIdentity(
          artifact, "cog", "analysis", "tif",
          "image/tiff; application=geotiff; profile=cloud-optimized", "exact-lookup",
        );
        break;
      case "projection-visual-pmtiles":
        valid = projectionIdentity(
          artifact, "pmtiles", "layers", "pmtiles", "application/vnd.pmtiles", "visual-only",
        );
        break;
      default:
        break;
    }
    if (!valid) throw technical(`Artifact ${artifact.artifactId} violates canonical ${artifact.role} semantics.`);
  }
}

function assertExactContextArtifacts(context: ReleaseContext): readonly ResolvedArtifact[] {
  if (context.disposition !== "private-engineering" && !validateManifest(context.manifest)) {
    throw technical("The release context does not contain a schema-valid public manifest.");
  }
  const manifestArtifacts = new Map(context.manifest.artifacts.map((artifact) => [artifact.artifactId, artifact]));
  const resolvedEntries = Object.entries(context.artifacts);
  const resolved = resolvedEntries.map(([, artifact]) => artifact);
  if (manifestArtifacts.size !== context.manifest.artifacts.length || resolved.length !== manifestArtifacts.size) {
    throw technical("The verified release artifact set is duplicated or incomplete.");
  }
  const releaseRoot = new URL("./", context.manifestUrl);
  const seen = new Set<string>();
  for (const [key, artifact] of resolvedEntries) {
    const declared = manifestArtifacts.get(artifact.artifactId);
    if (
      key !== artifact.artifactId ||
      seen.has(artifact.artifactId) ||
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
    seen.add(artifact.artifactId);
  }
  if ([...manifestArtifacts.keys()].some((artifactId) => !seen.has(artifactId))) {
    throw technical("The resolved release context does not cover the exact manifest artifact ID set.");
  }
  const ordered = Object.freeze(resolved.sort((left, right) => left.artifactId.localeCompare(right.artifactId)));
  assertCanonicalPersistedSemantics(context, ordered);
  return ordered;
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
