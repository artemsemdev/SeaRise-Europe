// @vitest-environment node

import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import type { BrowserReleaseManifestV2 } from "../contracts/generated/release-contract";
import { ReleaseContext, type ResolvedArtifact } from "../domain/release";
import {
  fixtureArtifactPath,
  fixtureBytes,
  FIXTURE_PAYLOAD_ROOT,
  fixtureReleaseContext,
  responseBody,
} from "../test/release-fixture";
import { MethodologyRepository, type ReleaseMethodology } from "./methodology-repository";

const methodologyPath = "config/methodology.json";
const attributionPath = "config/source-attribution.json";
type MutableObject = Record<string, unknown>;
type Mutation = (value: MutableObject) => void;
const sha256 = (bytes: Uint8Array): string => createHash("sha256").update(bytes).digest("hex");
const encode = (value: unknown): Uint8Array => new TextEncoder().encode(`${JSON.stringify(value)}\n`);
const document = (path: string): MutableObject => JSON.parse(fixtureBytes(path).toString());
const nestedObject = (value: unknown): MutableObject => value as MutableObject;
const nestedArray = (value: unknown): unknown[] => value as unknown[];
const attributionMutations: readonly (readonly [string, Mutation])[] = [
  ["source hash", (value) => {
    nestedObject(nestedArray(value.records)[0]).sourceSha256 = "0".repeat(64);
  }],
  ...(["projection-analysis-cog", "projection-geoparquet", "projection-visual-pmtiles"] as const).map<
    readonly [string, Mutation]
  >((missingRole) => [`source role ${missingRole}`, (value) => {
    const source = nestedObject(nestedArray(value.records)[0]);
    source.appliesToRoles = nestedArray(source.appliesToRoles).filter(
      (role) => role !== missingRole,
    );
  }]),
  ["release identity", (value) => {
    value.dataReleaseId = "searise-europe-v9.9.9-20990101-aaaaaaaaaaaa";
  }],
];

function contextWithBytes(
  context: ReleaseContext,
  replacements: Readonly<Record<string, Uint8Array>>,
  artifactOverrides: Readonly<Record<string, Partial<ResolvedArtifact>>> = {},
): ReleaseContext {
  const artifacts = Object.fromEntries(Object.values(context.artifacts).map((artifact) => {
    const bytes = replacements[artifact.path];
    const override = artifactOverrides[artifact.artifactId];
    const next = {
      ...artifact,
      ...(bytes ? { byteSize: bytes.byteLength, sha256: sha256(bytes) } : {}),
      ...override,
    } as ResolvedArtifact;
    return [next.artifactId, Object.freeze(next)];
  }));
  return new ReleaseContext({
    manifest: context.manifest,
    manifestUrl: context.manifestUrl,
    disposition: context.disposition,
    artifacts,
    datasets: { ...context.datasets },
  });
}

function contextWithRevision(context: ReleaseContext, codeRevision: string): ReleaseContext {
  const manifest = structuredClone(context.manifest) as BrowserReleaseManifestV2;
  (manifest.baseReleaseIdentity as { codeRevision: string }).codeRevision = codeRevision;
  return new ReleaseContext({
    manifest,
    manifestUrl: context.manifestUrl,
    disposition: context.disposition,
    artifacts: { ...context.artifacts },
    datasets: { ...context.datasets },
  });
}

function transport(
  replacements: Readonly<Record<string, Uint8Array>> = {},
  calls: string[] = [],
) {
  return async (input: URL, init: { readonly signal: AbortSignal }) => {
    if (init.signal.aborted) throw new DOMException("aborted", "AbortError");
    const path = fixtureArtifactPath(input);
    calls.push(path);
    const bytes = replacements[path] ?? fixtureBytes(path);
    return new Response(responseBody(bytes), {
      status: 200,
      headers: { "content-type": "application/json" },
    });
  };
}

async function load(
  mutateMethodology?: (value: MutableObject) => void,
  mutateAttribution?: (value: MutableObject) => void,
): Promise<ReleaseMethodology> {
  const base = await fixtureReleaseContext();
  const replacements: Record<string, Uint8Array> = {};
  if (mutateMethodology) {
    const value = document(methodologyPath);
    mutateMethodology(value);
    replacements[methodologyPath] = encode(value);
  }
  if (mutateAttribution) {
    const value = document(attributionPath);
    mutateAttribution(value);
    replacements[attributionPath] = encode(value);
  }
  const context = contextWithBytes(base, replacements);
  return new MethodologyRepository({ transport: transport(replacements) }).load(
    context,
    new AbortController().signal,
  );
}

describe("verified release methodology repository", () => {
  it("returns the immutable release-scoped ADR-024 method and scientific attribution", async () => {
    const context = await fixtureReleaseContext();
    const result = await new MethodologyRepository({ transport: transport() }).load(
      context,
      new AbortController().signal,
    );

    expect(result).toEqual({
      dataReleaseId: context.dataReleaseId,
      disposition: "synthetic-fixture",
      methodologyVersion: "ar6-regional-projection-v1",
      baseline: "1995-2014 mean",
      likelyRange: {
        confidence: "medium",
        lowerQuantile: 0.167,
        medianQuantile: 0.5,
        upperQuantile: 0.833,
      },
      lookup: {
        operator: "nearest-source-grid-location",
        nativeResolutionDegrees: 1,
        maximumDistanceKilometres: 100,
        distanceLimitInclusive: true,
        interpolation: "prohibited",
        extrapolation: "prohibited",
        nodataSubstitution: "prohibited",
        tideGaugeFallback: "prohibited",
      },
      resultStates: ["ProjectionAvailable", "DataUnavailable", "OutOfScope", "UnsupportedGeography"],
      limitations: [
        "Reports regional relative sea-level projection, not an absolute water level.",
        "Does not model flooding, terrain exposure, probability, or property risk.",
      ],
      prohibitedClaims: ["flooding", "inundation", "terrain-exposure", "flood-probability", "property-risk"],
      decision: {
        id: "ADR-024",
        href: "https://github.com/artemsemdev/SeaRise-Europe/blob/c096aeab4e0994faa7a9d2253b47215ef897dfcb/docs/architecture/adr/ADR-024-ar6-regional-projection-contract.md",
      },
      source: {
        title: "IPCC AR6 Sea Level Projections",
        attributionText: expect.stringContaining("Garner et al. (2021)"),
        sourceUrl: "https://doi.org/10.5281/zenodo.6382554",
        licence: {
          spdxId: "CC-BY-4.0",
          name: "Creative Commons Attribution 4.0 International",
          url: "https://creativecommons.org/licenses/by/4.0/",
        },
      },
    });
    expect(Object.isFrozen(result)).toBe(true);
    expect(Object.isFrozen(result.lookup)).toBe(true);
    expect(Object.isFrozen(result.source.licence)).toBe(true);
  });

  it("shares and caches the exact pair of immutable artifacts", async () => {
    const context = await fixtureReleaseContext();
    const calls: string[] = [];
    const repository = new MethodologyRepository({ transport: transport({}, calls) });

    const [first, second] = await Promise.all([
      repository.load(context, new AbortController().signal),
      repository.load(context, new AbortController().signal),
    ]);
    const third = await repository.load(context, new AbortController().signal);

    expect(first).toBe(second);
    expect(second).toBe(third);
    expect(calls.sort()).toEqual([methodologyPath, attributionPath]);
  });

  it("rejects an artifact whose bytes do not match the manifest SHA-256", async () => {
    const context = await fixtureReleaseContext();
    const changed = fixtureBytes(methodologyPath).slice();
    changed[changed.byteLength - 2] ^= 1;
    const repository = new MethodologyRepository({
      transport: transport({ [methodologyPath]: changed }),
    });

    await expect(repository.load(context, new AbortController().signal)).rejects.toMatchObject({
      detail: { kind: "technical-error", code: "IntegrityFailed" },
    });
  });

  it("reports validly hashed malformed JSON as a technical decode failure", async () => {
    const base = await fixtureReleaseContext();
    const malformed = new TextEncoder().encode("{");
    const context = contextWithBytes(base, { [methodologyPath]: malformed });
    const repository = new MethodologyRepository({
      transport: transport({ [methodologyPath]: malformed }),
    });

    await expect(repository.load(context, new AbortController().signal)).rejects.toMatchObject({
      detail: { kind: "technical-error", code: "DecodeFailed" },
    });
  });

  it("rejects methodology and attribution artifacts with mismatched roles", async () => {
    const base = await fixtureReleaseContext();
    const methodologyId = base.manifest.contractArtifacts.methodology;
    const invalid = contextWithBytes(base, {}, {
      [methodologyId]: { role: "source-attribution" },
    });

    await expect(
      new MethodologyRepository({ transport: transport() }).load(invalid, new AbortController().signal),
    ).rejects.toMatchObject({ detail: { code: "SchemaInvalid" } });
  });

  it.each([
    ["unknown field", (value: MutableObject) => { value.unreviewed = true; }],
    ["fifth outcome", (value: MutableObject) => { nestedArray(value.resultStates).push("TechnicalError"); }],
    ["interpolation", (value: MutableObject) => { nestedObject(value.lookup).interpolation = "bilinear"; }],
    ["exclusive distance", (value: MutableObject) => { nestedObject(value.lookup).distanceLimitInclusive = false; }],
    ["wrong likely range", (value: MutableObject) => { nestedObject(value.likelyRange).lowerQuantile = 0.05; }],
    ["missing baseline limitation", (value: MutableObject) => {
      value.limitations = ["A replacement limitation that omits the approved baseline."];
    }],
  ])("fails closed on prohibited or malformed methodology semantics: %s", async (_name, mutate) => {
    await expect(load(mutate)).rejects.toMatchObject({ detail: { code: "SchemaInvalid" } });
  });

  it("rejects a validly hashed methodology document from another release", async () => {
    await expect(load((value) => {
      value.dataReleaseId = "searise-europe-v9.9.9-20990101-aaaaaaaaaaaa";
    })).rejects.toMatchObject({ detail: { code: "ReleaseIdentityMismatch" } });
  });

  it("derives the exact ADR-024 reference from the release code revision", async () => {
    const base = await fixtureReleaseContext();
    const revision = "a".repeat(40);
    const value = document(methodologyPath);
    const href = `https://github.com/artemsemdev/SeaRise-Europe/blob/${revision}/docs/architecture/adr/ADR-024-ar6-regional-projection-contract.md`;
    nestedObject(value.decision).href = href;
    const bytes = encode(value);
    const context = contextWithRevision(
      contextWithBytes(base, { [methodologyPath]: bytes }),
      revision,
    );

    await expect(
      new MethodologyRepository({ transport: transport({ [methodologyPath]: bytes }) }).load(
        context,
        new AbortController().signal,
      ),
    ).resolves.toMatchObject({ decision: { id: "ADR-024", href } });
  });

  it("rejects a decision URL that does not match the release code revision", async () => {
    await expect(load((value) => {
      nestedObject(value.decision).href =
        `https://github.com/artemsemdev/SeaRise-Europe/blob/${"b".repeat(40)}/docs/architecture/adr/ADR-024-ar6-regional-projection-contract.md`;
    })).rejects.toMatchObject({ detail: { code: "SchemaInvalid" } });
  });

  it("rejects a release decision reference without an exact Git revision", async () => {
    const context = contextWithRevision(await fixtureReleaseContext(), "main");
    await expect(
      new MethodologyRepository({ transport: transport() }).load(
        context,
        new AbortController().signal,
      ),
    ).rejects.toMatchObject({ detail: { code: "ReleaseIdentityMismatch" } });
  });

  it("retains additional release-bound limitations after the approved baseline", async () => {
    await expect(load((value) => {
      nestedArray(value.limitations).push("Synthetic fixture values are not public scientific output.");
    })).resolves.toMatchObject({
      limitations: [
        "Reports regional relative sea-level projection, not an absolute water level.",
        "Does not model flooding, terrain exposure, probability, or property risk.",
        "Synthetic fixture values are not public scientific output.",
      ],
    });
  });

  it.each(attributionMutations)("rejects attribution mismatch: %s", async (_name, mutate) => {
    await expect(load(undefined, mutate)).rejects.toMatchObject({
      detail: { code: "ReleaseIdentityMismatch" },
    });
  });

  it("accepts the genuine committed v1 attribution body", async () => {
    const base = await fixtureReleaseContext();
    const bytes = readFileSync(resolve(FIXTURE_PAYLOAD_ROOT, attributionPath));
    const context = contextWithBytes(base, { [attributionPath]: bytes });

    await expect(
      new MethodologyRepository({ transport: transport({ [attributionPath]: bytes }) }).load(
        context,
        new AbortController().signal,
      ),
    ).resolves.toMatchObject({
      source: { title: "IPCC AR6 Sea Level Projections", licence: { spdxId: "CC-BY-4.0" } },
    });
  });

  it.each(["analysisArtifactId", "analyticalArtifactId", "visualArtifactId"] as const)(
    "rejects a dataset whose %s omits the scientific attribution",
    async (artifactReference) => {
      const base = await fixtureReleaseContext();
      const dataset = base.dataset("ssp2-45", 2050);
      const artifact = base.artifact(dataset[artifactReference]);
      const context = contextWithBytes(base, {}, {
        [artifact.artifactId]: {
          rights: {
            ...artifact.rights,
            attributionIds: artifact.rights.attributionIds.filter(
              (id) => id !== base.manifest.sources[0].attributionId,
            ),
          },
        },
      });

      await expect(
        new MethodologyRepository({ transport: transport() }).load(
          context,
          new AbortController().signal,
        ),
      ).rejects.toMatchObject({ detail: { code: "ReleaseIdentityMismatch" } });
    },
  );

  it("allows one caller to cancel without poisoning a shared load", async () => {
    const context = await fixtureReleaseContext();
    const resourceSignals: AbortSignal[] = [];
    const firstController = new AbortController();
    const repository = new MethodologyRepository({
      transport: async (input, init) => {
        resourceSignals.push(init.signal);
        await new Promise((resolveDelay) => setTimeout(resolveDelay, 10));
        return transport()(input, init);
      },
    });
    const first = repository.load(context, firstController.signal);
    const second = repository.load(context, new AbortController().signal);
    firstController.abort("superseded");

    await expect(first).rejects.toMatchObject({ detail: { code: "Aborted" } });
    await expect(second).resolves.toMatchObject({ methodologyVersion: "ar6-regional-projection-v1" });
    expect(resourceSignals).toHaveLength(2);
    expect(new Set(resourceSignals).size).toBe(1);
    expect(resourceSignals[0].aborted).toBe(false);
  });

  it("aborts the underlying artifact requests after the final caller cancels", async () => {
    const context = await fixtureReleaseContext();
    const resourceSignals: AbortSignal[] = [];
    const controller = new AbortController();
    const repository = new MethodologyRepository({
      transport: async (_input, init) => {
        resourceSignals.push(init.signal);
        return new Promise<Response>((_resolve, reject) => {
          init.signal.addEventListener(
            "abort",
            () => reject(new DOMException("aborted", "AbortError")),
            { once: true },
          );
        });
      },
    });
    const pending = repository.load(context, controller.signal);
    await Promise.resolve();
    controller.abort("navigation");

    await expect(pending).rejects.toMatchObject({ detail: { code: "Aborted" } });
    await new Promise((resolveDelay) => setTimeout(resolveDelay, 0));
    expect(resourceSignals).toHaveLength(2);
    expect(resourceSignals.every((signal) => signal.aborted)).toBe(true);
  });
});
