import fixture from "../../../../contracts/release/v2/fixtures/browser-release/searise-europe-v1.0.0-20260810-c096aeab4e09/manifest.json";
import legacyV1Fixture from "../../../../contracts/release/v1/fixtures/release/searise-europe-v1.0.0-20260810-c096aeab4e09/manifest.json";
import type { ErrorObject } from "ajv";
import { describe, expect, expectTypeOf, it } from "vitest";
import type { ReleaseManifestV2 } from "../contracts/generated/release-contract";
import validateManifest from "../contracts/generated/manifest-validator.mjs";
import validatePrivateManifest from "../contracts/generated/private-binding-validator.mjs";
import { TechnicalFailure, validateCoordinates } from "../domain/release";
import { ManifestRepository, type ManifestTransport } from "./manifest-repository";

const releaseId = "searise-europe-v1.0.0-20260810-c096aeab4e09";
const manifestUrl = `https://fixture.example/releases/${releaseId}/manifest.json`;

function response(value: unknown, init: ResponseInit = {}): Response {
  return new Response(JSON.stringify(value), {
    status: 200,
    headers: { "content-type": "application/json" },
    ...init,
  });
}

function repository(value: unknown): ManifestRepository {
  const transport: ManifestTransport = async () => response(value);
  return new ManifestRepository({
    manifestUrl,
    allowedOrigins: ["https://fixture.example"],
    expectedDisposition: "synthetic-fixture",
    transport,
  });
}

interface MutablePrivateEnvelope {
  $schema: string;
  schemaVersion: string;
  dataReleaseId: string;
  privateEngineeringOnly: boolean;
  verified: boolean;
  publicPromotionAuthorized: boolean;
  binding: {
    adapter: { createdAt: string; codeRevision: string };
    baseCandidate: {
      candidateId: string;
      dataReleaseId: string;
      manifestSha256: string;
      snapshotSha256: string;
      createdAt: string;
      codeRevision: string;
    };
    sourceGrid: { byteSize: number; sha256: string };
  };
  releaseManifest: {
    dataReleaseId: string;
    dataProvenanceClass: string;
    baseReleaseIdentity: {
      identityScope: string;
      schemaVersion: string;
      manifestSha256: string;
      createdAt: string;
      codeRevision: string;
    };
    releaseAuthority: {
      automatedValidation: string;
      releaseDisposition: string;
      dataProvenanceClass: string;
      statusDisclosureRequired: boolean;
    };
    publication: { cacheControl: string };
    contractArtifacts: {
      baseReleaseProvenance: string | null;
      browserDerivationProvenance: string;
      baseReleaseSignature: string | null;
    };
    artifacts: Array<{ dataProvenanceClass: string }>;
    [key: string]: unknown;
  };
}

function privateEnvelope(): MutablePrivateEnvelope {
  const releaseManifest = structuredClone(fixture) as unknown as MutablePrivateEnvelope["releaseManifest"];
  releaseManifest.dataProvenanceClass = "real-source";
  releaseManifest.$schema =
    "https://artemsemdev.github.io/SeaRise-Europe/contracts/release/v2/private-release-manifest.schema.json";
  releaseManifest.releaseAuthority = {
    automatedValidation: "pending",
    releaseDisposition: "pending-owner",
    dataProvenanceClass: "real-source",
    statusDisclosureRequired: true,
  };
  releaseManifest.publication.cacheControl = "private, no-store";
  releaseManifest.baseReleaseIdentity.identityScope = "private-phase-1-candidate";
  releaseManifest.baseReleaseIdentity.schemaVersion = "2.0.0";
  releaseManifest.baseReleaseIdentity.manifestSha256 = "b".repeat(64);
  releaseManifest.contractArtifacts.baseReleaseSignature = null;
  releaseManifest.contractArtifacts.baseReleaseProvenance = null;
  for (const artifact of releaseManifest.artifacts) artifact.dataProvenanceClass = "real-source";
  return {
    $schema:
      "https://artemsemdev.github.io/SeaRise-Europe/contracts/release/v2/private-binding-manifest.schema.json",
    schemaVersion: "1.0.0",
    dataReleaseId: releaseId,
    privateEngineeringOnly: true,
    verified: false,
    publicPromotionAuthorized: false,
    binding: {
      adapter: { createdAt: "2026-08-16T05:00:00Z", codeRevision: "a".repeat(40) },
      baseCandidate: {
        candidateId: "private-candidate-test",
        dataReleaseId: releaseId,
        manifestSha256: "b".repeat(64),
        snapshotSha256: "c".repeat(64),
        createdAt: releaseManifest.baseReleaseIdentity.createdAt,
        codeRevision: releaseManifest.baseReleaseIdentity.codeRevision,
      },
      sourceGrid: { byteSize: 7848, sha256: "d".repeat(64) },
    },
    releaseManifest,
  };
}

async function errorCode(value: unknown): Promise<string> {
  try {
    await repository(value).load(releaseId, new AbortController().signal);
    throw new Error("Expected manifest load to fail");
  } catch (error) {
    if (!(error instanceof TechnicalFailure)) throw error;
    return error.detail.code;
  }
}

describe("ManifestRepository", () => {
  it("types the generated standalone validator against the release v2 manifest", () => {
    expectTypeOf(validateManifest).toEqualTypeOf<{
      (value: unknown): value is ReleaseManifestV2;
      errors?: ErrorObject[] | null;
    }>();
    expect(validateManifest(structuredClone(fixture))).toBe(true);
  });

  it("loads the complete fixture into an immutable, release-scoped context", async () => {
    const context = await repository(structuredClone(fixture)).load(
      releaseId,
      new AbortController().signal,
    );

    expect(context.dataReleaseId).toBe(releaseId);
    expect(context.disposition).toBe("synthetic-fixture");
    expect(Object.keys(context.datasets)).toHaveLength(9);
    expect(context.dataset("ssp2-45", 2050).analysisArtifactId).toBe(
      "projection-ssp2-45-2050-cog",
    );
    expect(context.artifact("projection-ssp2-45-2050-cog").url).toBe(
      `https://fixture.example/releases/${releaseId}/analysis/ssp2-45/2050.tif`,
    );
    expect(context.artifact("source-grid-identity")).toMatchObject({
      artifactId: "source-grid-identity",
      role: "source-grid-identity",
      mediaType: "application/gzip",
    });
    expect(context.artifact("cog-range-integrity")).toMatchObject({
      artifactId: "cog-range-integrity",
      role: "range-integrity-index",
      mediaType: "application/json",
    });
    expect(Object.isFrozen(context)).toBe(true);
    expect(Object.isFrozen(context.manifest.artifacts[0])).toBe(true);
    expect(Reflect.set(context.manifest.defaults, "horizon", 2100)).toBe(false);
    expect(new Set(fixture.artifacts.map((artifact) => artifact.$schema))).toEqual(
      new Set([
        "https://artemsemdev.github.io/SeaRise-Europe/contracts/release/v2/artifact.schema.json",
      ]),
    );
    expect(JSON.stringify(fixture.artifacts)).not.toContain("/contracts/release/v1/");
  });

  it("rejects the byte-sealed v1 manifest because it has no v2 scientific integrity metadata", async () => {
    expect(await errorCode(structuredClone(legacyV1Fixture))).toBe("SchemaInvalid");
  });

  it("rejects private no-store semantics in the public manifest contract", () => {
    const pending = structuredClone(fixture);
    pending.publication.cacheControl = "private, no-store";
    expect(validateManifest(pending)).toBe(false);
    expect(validateManifest.errors).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          instancePath: "/publication/cacheControl",
          keyword: "const",
        }),
      ]),
    );
  });

  it("requires the versioned fail-closed envelope for private engineering", async () => {
    const envelope = privateEnvelope();
    expect(validatePrivateManifest(envelope)).toBe(true);
    const target = (value: unknown) =>
      new ManifestRepository({
        manifestUrl,
        allowedOrigins: ["https://fixture.example"],
        expectedDisposition: "private-engineering",
        transport: async () => response(value),
      });
    await expect(
      target(envelope).load(releaseId, new AbortController().signal),
    ).resolves.toMatchObject({ disposition: "private-engineering", dataReleaseId: releaseId });
    await expect(
      target(envelope.releaseManifest).load(releaseId, new AbortController().signal),
    ).rejects.toMatchObject({ detail: { code: "SchemaInvalid" } });
  });

  it.each([
    ["verified", (value: MutablePrivateEnvelope) => { value.verified = true; }],
    ["promotion", (value: MutablePrivateEnvelope) => { value.publicPromotionAuthorized = true; }],
    ["approved", (value: MutablePrivateEnvelope) => { value.releaseManifest.releaseAuthority.releaseDisposition = "approved"; }],
    ["passed", (value: MutablePrivateEnvelope) => { value.releaseManifest.releaseAuthority.automatedValidation = "passed"; }],
    ["cacheable", (value: MutablePrivateEnvelope) => { value.releaseManifest.publication.cacheControl = "public, max-age=31536000, immutable"; }],
    ["signed", (value: MutablePrivateEnvelope) => { value.releaseManifest.contractArtifacts.baseReleaseSignature = "base-release-signature"; }],
  ])("rejects a private envelope mutated to %s semantics", async (_label, mutate) => {
    const envelope = privateEnvelope();
    mutate(envelope);
    const target = new ManifestRepository({
      manifestUrl,
      allowedOrigins: ["https://fixture.example"],
      expectedDisposition: "private-engineering",
      transport: async () => response(envelope),
    });
    await expect(target.load(releaseId, new AbortController().signal)).rejects.toMatchObject({
      detail: { code: "SchemaInvalid" },
    });
  });

  it("requests only the pinned manifest with omitted credentials and an abort signal", async () => {
    let observed: Parameters<ManifestTransport> | undefined;
    const transport: ManifestTransport = async (...input) => {
      observed = input;
      return response(fixture);
    };
    const target = new ManifestRepository({
      manifestUrl,
      allowedOrigins: ["https://fixture.example"],
      expectedDisposition: "synthetic-fixture",
      transport,
    });
    const controller = new AbortController();
    await target.load(releaseId, controller.signal);

    expect(observed?.[0].href).toBe(manifestUrl);
    expect(observed?.[1].headers).toEqual({ Accept: "application/json" });
    expect(observed?.[1].signal).toBe(controller.signal);
  });

  it.each([
    ["unsupported schema", (value: typeof fixture) => { value.schemaVersion = "9.0.0"; }],
    ["missing combination", (value: typeof fixture) => { value.datasets.pop(); }],
    ["duplicate combination", (value: typeof fixture) => { value.datasets[1] = structuredClone(value.datasets[0]); }],
    ["bad hash", (value: typeof fixture) => { value.artifacts[0].sha256 = "bad"; }],
    ["bad size", (value: typeof fixture) => { value.artifacts[0].byteSize = 0; }],
    ["bad bounds", (value: typeof fixture) => { value.artifacts[0].spatialBounds = [-181, 0, 1, 1]; }],
    ["impossible sealed-release date", (value: typeof fixture) => { value.baseReleaseIdentity.createdAt = "2026-02-31T12:05:00Z"; }],
    ["bad defaults", (value: typeof fixture) => { value.defaults.horizon = 2100; }],
    ["unsafe path", (value: typeof fixture) => { value.artifacts[0].path = "../escape.json"; }],
  ])("fails closed for %s", async (_label, mutate) => {
    const value = structuredClone(fixture);
    mutate(value);
    expect(await errorCode(value)).toBe("SchemaInvalid");
  });

  it("rejects release, path, artifact, and build-disposition identity mismatches", async () => {
    const wrongRelease = structuredClone(fixture);
    wrongRelease.dataReleaseId = "searise-europe-v1.0.0-20260810-aaaaaaaaaaaa";
    expect(await errorCode(wrongRelease)).toBe("ReleaseIdentityMismatch");

    const wrongArtifact = structuredClone(fixture);
    wrongArtifact.artifacts[0].dataReleaseId = "searise-europe-v1.0.0-20260810-aaaaaaaaaaaa";
    expect(await errorCode(wrongArtifact)).toBe("ReleaseIdentityMismatch");

    const publicRepository = new ManifestRepository({
      manifestUrl,
      allowedOrigins: ["https://fixture.example"],
      expectedDisposition: "public-promoted",
      transport: async () => response(fixture),
    });
    await expect(publicRepository.load(releaseId, new AbortController().signal)).rejects.toMatchObject({
      detail: { code: "ReleaseIdentityMismatch" },
    });
  });

  it("rejects a referenced artifact whose role changed without changing its ID", async () => {
    const value = structuredClone(fixture);
    const scenarioConfig = value.artifacts.find((artifact) => artifact.artifactId === "scenario-config");
    if (!scenarioConfig) throw new Error("Fixture scenario config is missing");
    scenarioConfig.role = "methodology";
    expect(await errorCode(value)).toBe("SchemaInvalid");
  });

  it("rejects a manifest origin outside the explicit allowlist before fetching", () => {
    expect(
      () =>
        new ManifestRepository({
          manifestUrl,
          allowedOrigins: ["https://other.example"],
          expectedDisposition: "synthetic-fixture",
        }),
    ).toThrowError(TechnicalFailure);
  });

  it("keeps fetch, decode, and abort failures outside the outcome vocabulary", async () => {
    const make = (transport: ManifestTransport) =>
      new ManifestRepository({
        manifestUrl,
        allowedOrigins: ["https://fixture.example"],
        expectedDisposition: "synthetic-fixture",
        transport,
      });
    await expect(
      make(async () => new Response("", { status: 503 })).load(releaseId, new AbortController().signal),
    ).rejects.toMatchObject({ detail: { code: "FetchFailed", recoverable: true } });
    await expect(
      make(async () => new Response("not json", { headers: { "content-type": "text/plain" } })).load(
        releaseId,
        new AbortController().signal,
      ),
    ).rejects.toMatchObject({ detail: { code: "DecodeFailed" } });

    const controller = new AbortController();
    controller.abort();
    await expect(
      make(async () => { throw new DOMException("aborted", "AbortError"); }).load(releaseId, controller.signal),
    ).rejects.toMatchObject({ detail: { code: "Aborted" } });
  });

  it("treats invalid coordinates as validation failures, never geography outcomes", () => {
    expect(() => validateCoordinates({ latitude: Number.NaN, longitude: 0 })).toThrowError(
      TechnicalFailure,
    );
    try {
      validateCoordinates({ latitude: 91, longitude: 0 });
    } catch (error) {
      expect(error).toMatchObject({ detail: { code: "SchemaInvalid" } });
    }
  });
});
