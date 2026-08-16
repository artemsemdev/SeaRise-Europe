import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import Ajv2020 from "ajv/dist/2020.js";
import type { AnySchema } from "ajv";
import addFormats from "ajv-formats";
import { describe, expect, it } from "vitest";
import validateManifest from "../contracts/generated/manifest-validator.mjs";
import {
  CHECKSUM_SELF_REFERENCE_EXCLUSIONS,
  assertChecksumInventory,
  parseChecksumText,
} from "../../scripts/checksum-inventory.mjs";

const root = resolve(import.meta.dirname, "../../../..");
const releaseId = "searise-europe-v1.0.0-20260810-c096aeab4e09";
const baseRoot = resolve(root, `contracts/release/v1/fixtures/release/${releaseId}`);
const overlayRoot = resolve(
  root,
  `contracts/release/v2/fixtures/browser-release/${releaseId}`,
);
const read = (path: string) => readFileSync(resolve(root, path));
const json = (path: string): unknown => JSON.parse(read(path).toString("utf8"));
const sha256 = (bytes: Uint8Array) => createHash("sha256").update(bytes).digest("hex");

describe("honest browser-overlay evidence", () => {
  it("binds canonical checksums to the exact manifest artifact inventory", () => {
    const manifest = JSON.parse(readFileSync(resolve(overlayRoot, "manifest.json"), "utf8"));
    const checksums = readFileSync(resolve(overlayRoot, "checksums.txt"), "utf8");
    const parsed = assertChecksumInventory(manifest, checksums);

    expect(parsed.size).toBe(manifest.artifacts.length - 1);
    expect(CHECKSUM_SELF_REFERENCE_EXCLUSIONS).toEqual(["manifest.json", "checksums.txt"]);
    expect(Object.isFrozen(CHECKSUM_SELF_REFERENCE_EXCLUSIONS)).toBe(true);
    expect(parsed.has("manifest.json")).toBe(false);
    expect(parsed.has("checksums.txt")).toBe(false);
    expect([...parsed.keys()]).toEqual([...parsed.keys()].sort());
    for (const path of [
      "analysis/source-grid.json.gz",
      "analysis/cog-range-integrity.json",
      "boundaries/europe.parquet",
      "boundaries/coastal-analysis-zone.parquet",
    ]) {
      const artifact = manifest.artifacts.find(
        (candidate: { path: string }) => candidate.path === path,
      );
      expect(parsed.get(path), path).toBe(artifact.sha256);
    }
  });

  it("ignores v1 comments and blank lines instead of inventing artifacts", () => {
    const v1Checksums = readFileSync(resolve(baseRoot, "checksums.txt"), "utf8");
    const parsed = parseChecksumText(`${v1Checksums}\n# another comment\n\n`);
    expect(parsed.size).toBe(42);
    expect([...parsed.keys()].some((path) => path.startsWith("#"))).toBe(false);
  });

  it.each([
    ["duplicate", (lines: string[]) => [...lines, lines[0]]],
    ["comment as artifact", (lines: string[]) => [...lines, `${"a".repeat(64)}  # forged-comment`]],
    ["stale", (lines: string[]) => [`${"a".repeat(64)}${lines[0].slice(64)}`, ...lines.slice(1)]],
    ["missing", (lines: string[]) => lines.slice(1)],
    ["extra", (lines: string[]) => [...lines, `${"a".repeat(64)}  stale/extra.bin`]],
  ])("rejects a %s checksum inventory mutation", (_name, mutate) => {
    const manifest = JSON.parse(readFileSync(resolve(overlayRoot, "manifest.json"), "utf8"));
    const lines = readFileSync(resolve(overlayRoot, "checksums.txt"), "utf8")
      .split("\n")
      .filter((line) => line !== "" && !line.startsWith("#"));
    expect(() => assertChecksumInventory(manifest, `${mutate(lines).join("\n")}\n`)).toThrow();
  });

  it("validates the manifest and first-class derivation evidence contracts", () => {
    const defs = json("contracts/release/v2/defs.schema.json") as AnySchema;
    const ajv = new Ajv2020({ allErrors: true, strict: true, strictRequired: false });
    addFormats(ajv);
    ajv.addSchema(defs);

    for (const name of [
      "attribution.schema.json",
      "browser-derivation-receipt.schema.json",
      "browser-derivation-provenance.schema.json",
    ]) {
      const schema = json(`contracts/release/v2/${name}`) as AnySchema;
      const documentPath = name === "attribution.schema.json"
        ? `contracts/release/v2/fixtures/browser-release/${releaseId}/config/source-attribution.json`
        : name.includes("receipt")
          ? `contracts/release/v2/fixtures/browser-release/${releaseId}/receipts/browser-derivation.json`
          : `contracts/release/v2/fixtures/browser-release/${releaseId}/browser-derivation.intoto.json`;
      const document = json(documentPath);
      const validate = ajv.compile(schema);
      expect(validate(document), JSON.stringify(validate.errors)).toBe(true);
    }

    const manifest = json(
      `contracts/release/v2/fixtures/browser-release/${releaseId}/manifest.json`,
    );
    expect(validateManifest(manifest), JSON.stringify(validateManifest.errors)).toBe(true);
  });

  it("identifies the browser-only nodata control in every affected overlay contract", () => {
    const controlPath = "src/pipeline/fixtures/browser-release/adr-024-nodata-control-v1.json";
    const controlBytes = read(controlPath);
    const controlSha256 = sha256(controlBytes);
    const arrowSchemasPath =
      "src/pipeline/fixtures/browser-release/boundary-arrow-schemas-v1.json";
    const arrowSchemasBytes = read(arrowSchemasPath);
    const arrowSchemasSha256 = sha256(arrowSchemasBytes);
    const manifest = JSON.parse(readFileSync(resolve(overlayRoot, "manifest.json"), "utf8"));
    const receipt = JSON.parse(
      readFileSync(resolve(overlayRoot, "receipts/browser-derivation.json"), "utf8"),
    );
    const attribution = JSON.parse(
      readFileSync(resolve(overlayRoot, "config/source-attribution.json"), "utf8"),
    );
    const sbom = JSON.parse(
      readFileSync(resolve(overlayRoot, "sbom/browser-integrity.cdx.json"), "utf8"),
    );

    expect(JSON.parse(controlBytes.toString("utf8"))).toMatchObject({
      controlId: "browser-only-source-nodata-62n-44e",
      fixtureRole: "browser-only-adr-024-data-unavailable-control",
      dataProvenanceClass: "synthetic-fixture",
    });
    expect(receipt.materials).toContainEqual({ path: controlPath, sha256: controlSha256 });
    expect(receipt.materials).toContainEqual({
      path: arrowSchemasPath,
      sha256: arrowSchemasSha256,
    });
    expect(sbom.components).toContainEqual(expect.objectContaining({
      name: controlPath,
      hashes: [{ alg: "SHA-256", content: controlSha256 }],
    }));
    expect(sbom.components).toContainEqual(expect.objectContaining({
      name: arrowSchemasPath,
      hashes: [{ alg: "SHA-256", content: arrowSchemasSha256 }],
    }));
    expect(attribution.records).toContainEqual(expect.objectContaining({
      attributionId: "browser-nodata-control-fixture",
      sourceSha256: controlSha256,
      appliesToRoles: ["support-boundary", "coastal-boundary"],
    }));
    for (const artifact of manifest.artifacts.filter(
      (candidate: { role: string }) =>
        candidate.role === "support-boundary" || candidate.role === "coastal-boundary",
    )) {
      expect(artifact.spatialBounds[2]).toBe(44.001);
      expect(artifact.rights.attributionIds).toEqual([
        "browser-nodata-control-fixture",
        "natural-earth-boundaries",
      ]);
      expect(artifact.lineage).toContainEqual({ path: controlPath, sha256: controlSha256 });
      expect(artifact.lineage).toContainEqual({
        path: arrowSchemasPath,
        sha256: arrowSchemasSha256,
      });
    }
  });

  it("keeps authoritative v1 evidence byte-identical and scopes inherited identity", () => {
    expect(readFileSync(resolve(overlayRoot, "receipts/build.json"))).toEqual(
      readFileSync(resolve(baseRoot, "receipts/build.json")),
    );
    expect(readFileSync(resolve(overlayRoot, "provenance.intoto.jsonl"))).toEqual(
      readFileSync(resolve(baseRoot, "provenance.intoto.jsonl")),
    );

    const baseManifestBytes = readFileSync(resolve(baseRoot, "manifest.json"));
    const baseManifest = JSON.parse(baseManifestBytes.toString("utf8"));
    const overlayManifest = JSON.parse(
      readFileSync(resolve(overlayRoot, "manifest.json"), "utf8"),
    );
    expect(overlayManifest).not.toHaveProperty("createdAt");
    expect(overlayManifest).not.toHaveProperty("codeRevision");
    expect(overlayManifest.baseReleaseIdentity).toEqual({
      identityScope: "sealed-release-v1",
      schemaVersion: "1.0.0",
      manifestSha256: sha256(baseManifestBytes),
      createdAt: baseManifest.createdAt,
      codeRevision: baseManifest.codeRevision,
    });
    expect(overlayManifest.browserDerivationIdentity).toEqual({
      identityScope: "browser-overlay-derivation",
      executionIdentity: "not-recorded",
      receiptArtifactId: "browser-derivation-receipt",
      provenanceArtifactId: "browser-derivation-provenance",
    });
    expect(overlayManifest.contractArtifacts).not.toHaveProperty("signature");
    expect(overlayManifest.contractArtifacts.baseReleaseSignature).toBe("signature");
    expect(
      overlayManifest.artifacts.find(
        (artifact: { artifactId: string }) => artifact.artifactId === "signature",
      ).role,
    ).toBe("base-release-signature");
  });

  it("contains no fabricated execution identity and has an acyclic overlay digest DAG", () => {
    const receipt = JSON.parse(
      readFileSync(resolve(overlayRoot, "receipts/browser-derivation.json"), "utf8"),
    );
    const provenance = JSON.parse(
      readFileSync(resolve(overlayRoot, "browser-derivation.intoto.json"), "utf8"),
    );
    const manifest = JSON.parse(readFileSync(resolve(overlayRoot, "manifest.json"), "utf8"));
    const forbiddenKeys = /^(?:run|runId|workflow|workflowId|platform|timestamp|createdAt|codeRevision)$/i;
    const visit = (value: unknown): void => {
      if (Array.isArray(value)) for (const child of value) visit(child);
      else if (value !== null && typeof value === "object") {
        for (const [key, child] of Object.entries(value)) {
          expect(key).not.toMatch(forbiddenKeys);
          visit(child);
        }
      }
    };
    visit(receipt);
    visit(provenance);
    expect(receipt.executionIdentity).toBe("not-recorded");
    expect(provenance.predicate.executionIdentity).toBe("not-recorded");
    expect(provenance.predicate.materials).toEqual(receipt.materials);
    expect(provenance.predicate.nonClaims).toEqual(receipt.nonClaims);

    const manifestArtifactPaths = new Set(
      manifest.artifacts.map((artifact: { path: string }) => artifact.path),
    );
    const overlayPaths = new Set<string>([
      "receipts/browser-derivation.json",
      "browser-derivation.intoto.json",
      "checksums.txt",
      ...receipt.outputs.map((output: { path: string }) => output.path),
      ...receipt.materials
        .map((material: { path: string }) => material.path)
        .filter((path: string) => manifestArtifactPaths.has(path)),
    ]);
    const dependencies = new Map<string, string[]>();
    for (const artifact of manifest.artifacts) {
      if (!overlayPaths.has(artifact.path)) continue;
      dependencies.set(
        artifact.path,
        artifact.lineage
          .map((identity: { path: string }) => identity.path)
          .filter((path: string) => overlayPaths.has(path)),
      );
    }
    dependencies.set(
      "receipts/browser-derivation.json",
      receipt.materials
        .map((material: { path: string }) => material.path)
        .filter((path: string) => overlayPaths.has(path)),
    );
    dependencies.set(
      "browser-derivation.intoto.json",
      provenance.subject
        .map((subject: { name: string }) => subject.name)
        .filter((path: string) => overlayPaths.has(path)),
    );
    dependencies.set(
      "checksums.txt",
      [...parseChecksumText(readFileSync(resolve(overlayRoot, "checksums.txt"), "utf8")).keys()]
        .filter((path) => overlayPaths.has(path)),
    );
    const visiting = new Set<string>();
    const visited = new Set<string>();
    const traverse = (path: string): void => {
      expect(visiting.has(path), `overlay digest cycle at ${path}`).toBe(false);
      if (visited.has(path)) return;
      visiting.add(path);
      for (const dependency of dependencies.get(path) ?? []) traverse(dependency);
      visiting.delete(path);
      visited.add(path);
    };
    for (const path of overlayPaths) traverse(path);
    expect(visited).toEqual(overlayPaths);
  });
});
