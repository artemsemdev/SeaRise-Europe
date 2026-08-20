// @vitest-environment node

import { readFile } from "node:fs/promises";
import { resolve } from "node:path";
import fixture from "../../../../contracts/release/v2/fixtures/browser-release/searise-europe-v1.0.0-20260810-c096aeab4e09/manifest.json";
import { describe, expect, it } from "vitest";
import type { BrowserReleaseManifestV2 } from "../contracts/generated/release-contract";
import { ReleaseContext, TechnicalFailure, type ResolvedArtifact } from "../domain/release";
import { ManifestRepository } from "../data/manifest-repository";
import { validateAppAuthority } from "./contracts/v1";
import {
  createCogRangeAuthorityCatalog,
  parseCogRangeIntegrityDocument,
  verifyCogRangeIntegrityIndex,
  type VerifiedCogRangeIntegrityIndexV1,
} from "./range-integrity-catalog";
import { createVerifiedReleaseResourcePlan } from "./release-resource-plan";

const RELEASE_ID = "searise-europe-v1.0.0-20260810-c096aeab4e09";
const MANIFEST_URL = `https://fixture.example/releases/${RELEASE_ID}/manifest.json`;
const INDEX_PATH = resolve(
  process.cwd(),
  "../../contracts/release/v2/fixtures/browser-release",
  RELEASE_ID,
  "analysis/cog-range-integrity.json",
);

async function context(): Promise<ReleaseContext> {
  return new ManifestRepository({
    manifestUrl: MANIFEST_URL,
    allowedOrigins: ["https://fixture.example"],
    expectedDisposition: "synthetic-fixture",
    transport: async () => new Response(JSON.stringify(fixture), {
      headers: { "content-type": "application/json" },
    }),
  }).load(RELEASE_ID, new AbortController().signal);
}

function appAuthority(
  releaseDisposition: "synthetic-fixture" | "private-engineering" | "public-promoted" = "synthetic-fixture",
) {
  return validateAppAuthority({
    contractVersion: 1,
    appBuildId: "app-build-60",
    dataReleaseId: RELEASE_ID,
    manifestUrl: MANIFEST_URL,
    releaseDisposition,
    precacheSetSha256: "a".repeat(64),
  });
}

async function indexBytes(): Promise<ArrayBuffer> {
  const value = await readFile(INDEX_PATH);
  return value.buffer.slice(value.byteOffset, value.byteOffset + value.byteLength);
}

async function indexDocument(): Promise<Record<string, unknown>> {
  return JSON.parse(await readFile(INDEX_PATH, "utf8")) as Record<string, unknown>;
}

function forgedContext(
  source: ReleaseContext,
  transform: (artifacts: Record<string, ResolvedArtifact>) => void,
): ReleaseContext {
  const artifacts = Object.fromEntries(Object.entries(source.artifacts).map(([key, value]) => [
    key,
    { ...value },
  ])) as Record<string, ResolvedArtifact>;
  transform(artifacts);
  return new ReleaseContext({
    manifest: source.manifest,
    manifestUrl: source.manifestUrl,
    disposition: source.disposition,
    artifacts,
    datasets: { ...source.datasets },
  });
}

function privateContext(source: ReleaseContext): ReleaseContext {
  const manifest = {
    ...source.manifest,
    dataProvenanceClass: "real-source",
    releaseAuthority: {
      automatedValidation: "pending",
      releaseDisposition: "pending-owner",
      dataProvenanceClass: "real-source",
      statusDisclosureRequired: true,
    },
    publication: { ...source.manifest.publication, cacheControl: "private, no-store" },
    contractArtifacts: {
      ...source.manifest.contractArtifacts,
      baseReleaseProvenance: null,
      baseReleaseSignature: null,
    },
    artifacts: source.manifest.artifacts.map((artifact) => ({
      ...artifact,
      dataProvenanceClass: "real-source",
    })),
  } as unknown as BrowserReleaseManifestV2;
  const artifacts = Object.fromEntries(Object.entries(source.artifacts).map(([key, artifact]) => [
    key,
    { ...artifact, dataProvenanceClass: "real-source" },
  ])) as Record<string, ResolvedArtifact>;
  return new ReleaseContext({
    manifest,
    manifestUrl: source.manifestUrl,
    disposition: "private-engineering",
    artifacts,
    datasets: { ...source.datasets },
  });
}

function withBoundaryPmtiles(source: ReleaseContext): ReleaseContext {
  const artifacts = { ...source.artifacts } as Record<string, ResolvedArtifact>;
  const additions: ResolvedArtifact[] = [];
  for (const definition of [
    {
      sourceId: "europe-support-geoparquet",
      artifactId: "support-boundary-pmtiles",
      path: "boundaries/europe.pmtiles",
      sha256: "b".repeat(64),
    },
    {
      sourceId: "coastal-analysis-zone-geoparquet",
      artifactId: "coastal-boundary-pmtiles",
      path: "boundaries/coastal-analysis-zone.pmtiles",
      sha256: "c".repeat(64),
    },
  ] as const) {
    const sourceArtifact = source.artifact(definition.sourceId);
    const addition = {
      ...sourceArtifact,
      artifactId: definition.artifactId,
      path: definition.path,
      mediaType: "application/vnd.pmtiles",
      scientificUse: "not-applicable",
      byteSize: 128,
      sha256: definition.sha256,
      url: new URL(definition.path, new URL("./", source.manifestUrl)).href,
    } as unknown as ResolvedArtifact;
    artifacts[addition.artifactId] = addition;
    additions.push(addition);
  }
  const manifestAdditions = additions.map((addition) => {
    const artifact = { ...addition } as Record<string, unknown>;
    delete artifact.url;
    return artifact as unknown as BrowserReleaseManifestV2["artifacts"][number];
  });
  return new ReleaseContext({
    manifest: {
      ...source.manifest,
      artifacts: [...source.manifest.artifacts, ...manifestAdditions],
    } as BrowserReleaseManifestV2,
    manifestUrl: source.manifestUrl,
    disposition: source.disposition,
    artifacts,
    datasets: { ...source.datasets },
  });
}

function relabeledPmtilesContext(source: ReleaseContext): ReleaseContext {
  const artifactId = "projection-ssp2-45-2050-pmtiles";
  const path = "config/visual-context.json";
  const manifestArtifacts = source.manifest.artifacts.map((artifact) => {
    if (artifact.artifactId !== artifactId) return artifact;
    const relabeled = { ...artifact } as Record<string, unknown>;
    delete relabeled.projectionContext;
    relabeled.role = "methodology";
    relabeled.path = path;
    relabeled.mediaType = "application/json";
    relabeled.scientificUse = "not-applicable";
    return relabeled;
  });
  const manifest = {
    ...source.manifest,
    artifacts: manifestArtifacts,
  } as unknown as BrowserReleaseManifestV2;
  const artifacts = Object.fromEntries(Object.entries(source.artifacts).map(([key, artifact]) => {
    if (key !== artifactId) return [key, artifact];
    const relabeled = { ...artifact } as Record<string, unknown>;
    delete relabeled.projectionContext;
    relabeled.role = "methodology";
    relabeled.path = path;
    relabeled.url = `https://fixture.example/releases/${RELEASE_ID}/${path}`;
    relabeled.mediaType = "application/json";
    relabeled.scientificUse = "not-applicable";
    return [key, relabeled];
  })) as Record<string, ResolvedArtifact>;
  return new ReleaseContext({
    manifest,
    manifestUrl: source.manifestUrl,
    disposition: source.disposition,
    artifacts,
    datasets: { ...source.datasets },
  });
}

function allKeys(value: unknown, result = new Set<string>()): ReadonlySet<string> {
  if (value && typeof value === "object") {
    if (!Array.isArray(value)) for (const key of Object.keys(value)) result.add(key);
    for (const child of Object.values(value)) allKeys(child, result);
  }
  return result;
}

describe("verified COG range-integrity authority", () => {
  it("verifies the exact index bytes and produces only immutable COG chunk authorities", async () => {
    const release = await context();
    const verified = await verifyCogRangeIntegrityIndex(release, appAuthority(), await indexBytes());

    expect(verified.indexAuthority).toMatchObject({
      artifactId: "cog-range-integrity",
      role: "range-integrity-index",
      canonicalUrl: `https://fixture.example/releases/${RELEASE_ID}/analysis/cog-range-integrity.json`,
      path: "analysis/cog-range-integrity.json",
      mediaType: "application/json",
      byteSize: 3117,
      sha256: "97b289260d185381c9d5b11653a3856cde2b7bcc0aa71ad6d703d0cd8e40da27",
    });
    expect(verified.artifacts).toHaveLength(9);
    expect(verified.artifacts.flatMap((artifact) => artifact.chunks)).toHaveLength(12);
    expect(verified.artifacts.map((artifact) => artifact.artifactId)).toEqual(
      [...verified.artifacts.map((artifact) => artifact.artifactId)].sort(),
    );
    expect(Object.isFrozen(verified)).toBe(true);
    expect(Object.isFrozen(verified.artifacts[0].chunks)).toBe(true);
  });

  it("rejects corrupt bytes and strict semantic changes as technical failures", async () => {
    const release = await context();
    const corrupt = await indexBytes();
    new Uint8Array(corrupt)[0] ^= 1;
    await expect(verifyCogRangeIntegrityIndex(release, appAuthority(), corrupt)).rejects.toMatchObject({
      detail: { kind: "technical-error", code: "IntegrityFailed" },
    });

    const missing = await indexDocument();
    (missing.artifacts as unknown[]).pop();
    expect(() => parseCogRangeIntegrityDocument(missing, release)).toThrowError(TechnicalFailure);

    const masqueraded = await indexDocument();
    const pmtiles = release.artifact("projection-ssp2-45-2050-pmtiles");
    (masqueraded.artifacts as Record<string, unknown>[])[0] = {
      artifactId: pmtiles.artifactId,
      path: pmtiles.path,
      byteSize: pmtiles.byteSize,
      sha256: pmtiles.sha256,
      chunks: [{ start: 0, endExclusive: pmtiles.byteSize, sha256: pmtiles.sha256 }],
    };
    expect(() => parseCogRangeIntegrityDocument(masqueraded, release)).toThrowError(
      /does not match the release manifest/,
    );

    const extra = await indexDocument();
    (extra.artifacts as Record<string, unknown>[])[0].query = "Berlin";
    expect(() => parseCogRangeIntegrityDocument(extra, release)).toThrowError(
      /does not match the release manifest/,
    );

    const unverified = parseCogRangeIntegrityDocument(await indexDocument(), release);
    expect(() => createCogRangeAuthorityCatalog(
      release,
      appAuthority(),
      unverified as unknown as VerifiedCogRangeIntegrityIndexV1,
    )).toThrowError(/not verified/);
  });

  it("keeps verification authority module-private and rejects reflected or mutated copies", async () => {
    const release = await context();
    const verified = await verifyCogRangeIntegrityIndex(release, appAuthority(), await indexBytes());
    expect(Object.getOwnPropertySymbols(verified)).toEqual([]);
    expect(Reflect.set(verified.artifacts[0].chunks[0], "sha256", "f".repeat(64))).toBe(false);

    const copied = {
      ...verified,
      artifacts: verified.artifacts.map((artifact, index) => index === 0
        ? { ...artifact, chunks: [{ ...artifact.chunks[0], sha256: "f".repeat(64) }, ...artifact.chunks.slice(1)] }
        : artifact),
    } as unknown as VerifiedCogRangeIntegrityIndexV1;
    expect(() => createCogRangeAuthorityCatalog(release, appAuthority(), copied)).toThrowError(
      /not verified by this module instance/,
    );
  });
});

describe("deterministic release resource plan", () => {
  it("routes exact public resources without granting PMTiles scientific or persistence authority", async () => {
    const release = await context();
    const plan = await createVerifiedReleaseResourcePlan({
      context: release,
      appAuthority: appAuthority(),
      rangeIntegrityBytes: await indexBytes(),
    });
    const complete = plan.routes.filter((route) => route.kind === "complete-resource");
    const cogs = plan.routes.filter((route) => route.kind === "analysis-cog-ranges");
    const pmtiles = plan.routes.filter((route) =>
      route.kind === "network-only" && route.reason === "visual-pmtiles");
    const completeIdentity = (route: (typeof complete)[number]) => {
      if (route.authority.authorityKind !== "release-artifact") {
        throw new Error("Release plans may contain only release-artifact complete authorities.");
      }
      return {
        artifactId: route.authority.artifactId,
        role: route.authority.role,
      };
    };

    expect(plan.persistence.mode).toBe("persistent");
    expect(plan.storageProfile).toMatchObject({
      releaseDisposition: "synthetic-fixture", mode: "persistent", memoryReason: null,
    });
    expect(complete.map(completeIdentity)).toEqual([
      { artifactId: "attribution", role: "source-attribution" },
      { artifactId: "coastal-analysis-zone-geoparquet", role: "coastal-boundary" },
      { artifactId: "cog-range-integrity", role: "range-integrity-index" },
      { artifactId: "europe-support-geoparquet", role: "support-boundary" },
      { artifactId: "methodology", role: "methodology" },
      { artifactId: "scenario-config", role: "scenario-config" },
      { artifactId: "settlements-europe-coastal", role: "settlement-search-index" },
      { artifactId: "settlements-europe-core", role: "settlement-search-index" },
      { artifactId: "source-grid-identity", role: "source-grid-identity" },
    ]);
    expect(complete.every((route) => route.storage === "cache-storage")).toBe(true);
    expect(complete.every((route) => !route.authority.path.endsWith(".pmtiles"))).toBe(true);
    expect(cogs).toHaveLength(9);
    expect(cogs.every((route) => route.storage === "indexeddb")).toBe(true);
    expect(plan.rangeCatalog.identities).toHaveLength(12);
    expect(plan.rangeCatalog.identities.every((identity) =>
      identity.authority.role === "projection-analysis-cog" &&
      identity.authority.mediaType === "image/tiff; application=geotiff; profile=cloud-optimized" &&
      identity.authority.pair.appBuildId === "app-build-60" &&
      identity.authority.pair.dataReleaseId === RELEASE_ID &&
      identity.authority.canonicalUrl.endsWith(`/${identity.authority.path}`) &&
      identity.authority.etag === `"sha256-${identity.authority.artifactSha256}"`
    )).toBe(true);
    expect(pmtiles).toHaveLength(9);
    expect(pmtiles.every((route) => route.storage === "network-only" && route.requestCache === "no-store")).toBe(true);
    expect(plan.rangeCatalog.identities.some((identity) => identity.authority.path.endsWith(".pmtiles"))).toBe(false);
    const routeId = (route: (typeof plan.routes)[number]): string => {
      if (route.kind !== "complete-resource") return route.identity.artifactId;
      if (route.authority.authorityKind !== "release-artifact") {
        throw new Error("Release plans may contain only release-artifact complete authorities.");
      }
      return route.authority.artifactId;
    };
    expect(plan.routes.map(routeId)).toEqual([...plan.routes].map(routeId).sort());
  });

  it("makes every durable-eligible route memory-only for an explicit local Candidate", async () => {
    const plan = await createVerifiedReleaseResourcePlan({
      context: await context(),
      appAuthority: appAuthority(),
      rangeIntegrityBytes: await indexBytes(),
      localCandidate: true,
    });

    expect(plan.persistence).toEqual({ mode: "memory-only", reason: "local-candidate" });
    expect(plan.storageProfile).toMatchObject({
      releaseDisposition: "synthetic-fixture", mode: "memory-only", memoryReason: "local-candidate",
    });
    expect(plan.routes.every((route) =>
      route.kind === "network-only" && route.reason === "visual-pmtiles"
        ? route.storage === "network-only"
        : route.storage === "memory-only",
    )).toBe(true);
  });

  it("keeps a private engineering release session-only", async () => {
    const release = privateContext(await context());
    const plan = await createVerifiedReleaseResourcePlan({
      context: release,
      appAuthority: appAuthority("private-engineering"),
      rangeIntegrityBytes: await indexBytes(),
    });

    expect(plan.persistence).toEqual({ mode: "memory-only", reason: "private-engineering" });
    expect(plan.storageProfile).toMatchObject({
      releaseDisposition: "private-engineering", mode: "memory-only", memoryReason: "private-engineering",
    });
    expect(plan.routes.every((route) =>
      route.kind === "network-only" && route.reason === "visual-pmtiles"
        ? route.storage === "network-only"
        : route.storage === "memory-only",
    )).toBe(true);
  });

  it("keeps canonical boundary PMTiles network-only in public, private, and local Candidate plans", async () => {
    const publicRelease = withBoundaryPmtiles(await context());
    const cases = [
      { context: publicRelease, authority: appAuthority(), localCandidate: false },
      { context: publicRelease, authority: appAuthority(), localCandidate: true },
      {
        context: withBoundaryPmtiles(privateContext(await context())),
        authority: appAuthority("private-engineering"),
        localCandidate: false,
      },
    ];

    for (const testCase of cases) {
      const plan = await createVerifiedReleaseResourcePlan({
        context: testCase.context,
        appAuthority: testCase.authority,
        rangeIntegrityBytes: await indexBytes(),
        localCandidate: testCase.localCandidate,
      });
      const boundaryPmtiles = plan.routes.filter((route) =>
        route.kind === "network-only" &&
        ["support-boundary-pmtiles", "coastal-boundary-pmtiles"].includes(route.identity.artifactId));
      expect(boundaryPmtiles).toHaveLength(2);
      expect(boundaryPmtiles.every((route) =>
        route.storage === "network-only" && route.requestCache === "no-store" &&
        route.reason === "visual-pmtiles"
      )).toBe(true);
      expect(plan.routes.some((route) =>
        route.kind === "complete-resource" && route.authority.path.endsWith(".pmtiles")
      )).toBe(false);
      expect(plan.routes.some((route) =>
        route.kind === "analysis-cog-ranges" && route.identity.path.endsWith(".pmtiles")
      )).toBe(false);
    }
  });

  it("fails closed on release, URL, role, MIME, and manifest identity masquerades", async () => {
    const release = await context();
    const bytes = await indexBytes();
    await expect(createVerifiedReleaseResourcePlan({
      context: release,
      appAuthority: validateAppAuthority({
        ...appAuthority(),
        dataReleaseId: "other-release",
        manifestUrl: "https://fixture.example/releases/other-release/manifest.json",
      }),
      rangeIntegrityBytes: bytes,
    })).rejects.toBeInstanceOf(TechnicalFailure);

    for (const replacement of [
      { url: `${release.artifact("projection-ssp2-45-2050-cog").url}?query=Berlin` },
      { role: "projection-visual-pmtiles" },
      { mediaType: "application/vnd.pmtiles" },
      { sha256: "f".repeat(64) },
    ]) {
      const forged = forgedContext(release, (artifacts) => {
        artifacts["projection-ssp2-45-2050-cog"] = {
          ...artifacts["projection-ssp2-45-2050-cog"],
          ...replacement,
        } as ResolvedArtifact;
      });
      await expect(createVerifiedReleaseResourcePlan({
        context: forged,
        appAuthority: appAuthority(),
        rangeIntegrityBytes: bytes,
      })).rejects.toMatchObject({ detail: { kind: "technical-error", code: "IntegrityFailed" } });
    }

    const duplicatedUnderPmtilesKey = forgedContext(release, (artifacts) => {
      artifacts["projection-ssp2-45-2050-pmtiles"] = artifacts.methodology;
    });
    await expect(createVerifiedReleaseResourcePlan({
      context: duplicatedUnderPmtilesKey,
      appAuthority: appAuthority(),
      rangeIntegrityBytes: bytes,
    })).rejects.toMatchObject({ detail: { kind: "technical-error", code: "IntegrityFailed" } });

    await expect(createVerifiedReleaseResourcePlan({
      context: relabeledPmtilesContext(release),
      appAuthority: appAuthority(),
      rangeIntegrityBytes: bytes,
    })).rejects.toMatchObject({ detail: { kind: "technical-error", code: "IntegrityFailed" } });

    await expect(createVerifiedReleaseResourcePlan({
      context: relabeledPmtilesContext(privateContext(release)),
      appAuthority: appAuthority("private-engineering"),
      rangeIntegrityBytes: bytes,
    })).rejects.toMatchObject({ detail: { kind: "technical-error", code: "IntegrityFailed" } });
  });

  it("is resource-only and cannot persist queries, coordinates, selections, or a scientific outcome", async () => {
    const plan = await createVerifiedReleaseResourcePlan({
      context: await context(),
      appAuthority: appAuthority(),
      rangeIntegrityBytes: await indexBytes(),
    });
    const keys = allKeys(plan);
    for (const forbidden of [
      "searchText", "placeLabel", "latitude", "longitude", "coordinates",
      "history", "query", "profile", "selection", "browserUrl", "urlSearchParameters",
      "resultState",
    ]) {
      expect(keys.has(forbidden)).toBe(false);
    }
    expect(JSON.stringify(plan)).not.toMatch(/ProjectionAvailable|DataUnavailable|OutOfScope|UnsupportedGeography/u);
  });
});
