import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import Ajv2020 from "ajv/dist/2020.js";
import type { AnySchema } from "ajv";
import addFormats from "ajv-formats";
import { describe, expect, it } from "vitest";
import validateManifest from "../contracts/generated/manifest-validator.mjs";

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
  it("validates the manifest and first-class derivation evidence contracts", () => {
    const defs = json("contracts/release/v2/defs.schema.json") as AnySchema;
    const ajv = new Ajv2020({ allErrors: true, strict: true });
    addFormats(ajv);
    ajv.addSchema(defs);

    for (const name of [
      "browser-derivation-receipt.schema.json",
      "browser-derivation-provenance.schema.json",
    ]) {
      const schema = json(`contracts/release/v2/${name}`) as AnySchema;
      const document = json(
        name.includes("receipt")
          ? `contracts/release/v2/fixtures/browser-release/${releaseId}/receipts/browser-derivation.json`
          : `contracts/release/v2/fixtures/browser-release/${releaseId}/browser-derivation.intoto.json`,
      );
      const validate = ajv.compile(schema);
      expect(validate(document), JSON.stringify(validate.errors)).toBe(true);
    }

    const manifest = json(
      `contracts/release/v2/fixtures/browser-release/${releaseId}/manifest.json`,
    );
    expect(validateManifest(manifest), JSON.stringify(validateManifest.errors)).toBe(true);
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
      readFileSync(resolve(overlayRoot, "checksums.txt"), "utf8")
        .trimEnd()
        .split("\n")
        .map((line) => line.slice(line.indexOf("  ") + 2))
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
