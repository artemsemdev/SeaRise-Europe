import { mkdtempSync, mkdirSync, readFileSync, symlinkSync, unlinkSync, writeFileSync } from "node:fs";
import { Buffer } from "node:buffer";
import { tmpdir } from "node:os";
import { resolve } from "node:path";
import { brotliDecompressSync } from "node:zlib";
import { describe, expect, it } from "vitest";
import {
  RECEIPT_FILE, SHARD_FILES, SHARD_IDS, buildSearchShardSet, canonicalJson,
  publishSearchShardSet, validatePublishedSearchShardSet,
} from "./search-shard-builder.mjs";
import { createHash } from "node:crypto";
import { validateSearchShardDocument } from "../src/search/contract";

const RELEASE = "searise-europe-v1.0.0-20260812-0123456789ab";
const sha = (value) => createHash("sha256").update(value).digest("hex");
const hash = (character) => character.repeat(64);

function fixture(root, mutate = (value) => value) {
  const header = {
    canonicalGeometryClaim: false, dataProvenanceClass: "synthetic-fixture",
    geometryStatus: "selected-scope-approximation", hazardExtentClaim: false,
    kind: "settlement-search-projection-header", normalizationVersion: "settlement-normalization-v2",
    ownerApprovalClaim: false, productionClaim: false, publicationClaim: false,
    publicationEligible: false, schemaVersion: "settlement-search-projection-v1",
    scientificApprovalClaim: false, signingClaim: false,
    source: { spatialCandidateIdentity: hash("7"), spatialDatabaseSha256: hash("a"), spatialReceiptSha256: hash("d"), spatialStageSchemaVersion: "spatial-classification-stage-v1" },
  };
  const lineage = (id) => [{ asset_id: "all-countries", source_file: "allCountries.txt", source_line: id, source_record_id: id, source_release: "2026-08-10", source_sha256: hash("4") }];
  const document = (id, name, population, memberships, coastal) => ({
    admin1Code: null, admin1Name: null, alternateNames: [{ language: "en", script: "Latn", value: `${name} Alt` }], asciiName: name,
    canonicalName: { language: null, script: "Latn", value: name }, countryCode: "XX", featureCode: "PPL",
    kind: "settlement-search-projection-document", lineage: lineage(id), location: { latitude: 50 + id / 10000, longitude: 2 + id / 10000 },
    placeId: `geonames:${id}`, population, sourceSpelling: name, sourceUpdatedAt: "2026-08-10",
    spatialClassification: { catalogMembership: memberships, distanceToShorelineMeters: id, isCoastal: coastal },
  });
  const documents = [document(101, "Álpha", 1000, ["europe-core"], false), document(102, "Bravo", null, ["europe-coastal"], true), document(104, "Charlie", 2000, SHARD_IDS, true)];
  const documentText = documents.map((value) => `${canonicalJson(value)}\n`).join("");
  const documentsSha256 = sha(documentText);
  const footer = { deterministicIdentity: sha(`${canonicalJson({ header, recordCount: documents.length, documentsSha256 })}\n`), documentsSha256, kind: "settlement-search-projection-footer", recordCount: documents.length };
  const projection = Buffer.from(`${canonicalJson(header)}\n${documentText}${canonicalJson(footer)}\n`);
  const source = { projectionDeterministicIdentity: footer.deterministicIdentity, projectionDocumentsSha256: documentsSha256, projectionSchemaVersion: "settlement-search-projection-v1", projectionSha256: sha(projection), ...header.source };
  const spatialIdentity = { coastalGeometry: { artifactId: "fixture-coastal", sha256: hash("2"), version: "v1" }, distanceMethodVersion: "epsg3035-planar-whole-meter-half-even-v1", predicate: "covers", shorelineGeometry: { artifactId: "fixture-shoreline", sha256: hash("3"), version: "v1" }, supportGeometry: { artifactId: "fixture-support", sha256: hash("1"), version: "v1" } };
  const unsigned = { $schema: "https://artemsemdev.github.io/SeaRise-Europe/contracts/settlements/v4/search-artifact.schema.json", artifactType: "settlement-search-projection-authority", canonicalGeometryClaim: false, complete: true, dataProvenanceClass: "synthetic-fixture", dataReleaseId: RELEASE, formatVersion: "settlement-search-projection-authority-v1", hazardExtentClaim: false, ownerApprovalClaim: false, productionClaim: false, projectionByteSize: projection.length, projectionDeterministicIdentity: footer.deterministicIdentity, projectionDocumentsSha256: documentsSha256, projectionSha256: sha(projection), publicationClaim: false, publicationEligible: false, recordCount: documents.length, schemaVersion: "4.0.0", scientificApprovalClaim: false, signingClaim: false, source, spatialIdentity, validator: { validatorId: "searise_pipeline.settlements.search_projection.validate_search_projection", version: "1" } };
  const authority = mutate({ ...unsigned, deterministicIdentity: sha(`${canonicalJson(unsigned)}\n`) });
  const projectionPath = resolve(root, "projection.ndjson"); const authorityPath = resolve(root, "authority.json");
  writeFileSync(projectionPath, projection); writeFileSync(authorityPath, `${canonicalJson(authority)}\n`);
  return { projectionPath, authorityPath, dataReleaseId: RELEASE };
}

describe("static search shard builder", () => {
  it("emits byte-identical v4 shards accepted by the production decoder", async () => {
    const root = mkdtempSync(resolve(tmpdir(), "search-builder-"));
    const input = fixture(root); const first = buildSearchShardSet(input); const second = buildSearchShardSet(input);
    expect(first.receipt).toEqual(second.receipt);
    for (const id of SHARD_IDS) {
      expect(first.shards[id]).toEqual(second.shards[id]);
      const shard = JSON.parse(brotliDecompressSync(first.shards[id]).toString());
      expect(shard.runtime.node).toBe("20.20.1"); expect(shard.ranking.queryWorkLimit).toBe(250000);
      expect(shard.records.map(({ placeId }) => placeId)).toEqual([...shard.records.map(({ placeId }) => placeId)].sort((a, b) => Number(a.slice(9)) - Number(b.slice(9))));
      await expect(validateSearchShardDocument(brotliDecompressSync(first.shards[id]), {
        shardId: id, dataReleaseId: RELEASE, dataProvenanceClass: "synthetic-fixture",
        artifact: { artifactId: `settlements-${id}`, byteSize: first.shards[id].length, sha256: sha(first.shards[id]), url: new URL(`https://example.invalid/${SHARD_FILES[id]}`) },
      })).resolves.toMatchObject({ records: shard.records });
    }
    const receipt = JSON.parse(first.receipt.toString());
    expect(receipt.dataReleaseId).toBe(RELEASE); expect(receipt.source.projectionSha256).toMatch(/^[a-f0-9]{64}$/);
    expect(receipt.shards.map(({ shardId }) => shardId)).toEqual(SHARD_IDS);
    expect(receipt.shards.every(({ byteSize, sha256 }) => byteSize > 0 && /^[a-f0-9]{64}$/.test(sha256))).toBe(true);
  });

  it("publishes the complete set without overwrite and validates exact bytes", () => {
    const root = mkdtempSync(resolve(tmpdir(), "search-builder-")); const output = resolve(root, "output"); mkdirSync(output, 0o700);
    const built = buildSearchShardSet(fixture(root)); publishSearchShardSet(output, built);
    expect(validatePublishedSearchShardSet(output, built).complete).toBe(true);
    expect(readFileSync(resolve(output, RECEIPT_FILE))).toEqual(built.receipt);
    expect(() => publishSearchShardSet(output, built)).toThrow(/overwrite is refused/);
  });

  it("rolls back its own promoted paths after an injected publication failure", () => {
    const root = mkdtempSync(resolve(tmpdir(), "search-builder-")); const output = resolve(root, "output"); mkdirSync(output, 0o700);
    const built = buildSearchShardSet(fixture(root));
    expect(() => publishSearchShardSet(output, built, { afterPromote: (count) => { if (count === 1) throw new Error("injected"); } })).toThrow("injected");
    for (const name of [...Object.values(SHARD_FILES), RECEIPT_FILE]) expect(() => readFileSync(resolve(output, name))).toThrow();
  });

  it("does not delete a foreign replacement during rollback", () => {
    const root = mkdtempSync(resolve(tmpdir(), "search-builder-")); const output = resolve(root, "output"); mkdirSync(output, 0o700);
    const built = buildSearchShardSet(fixture(root)); const core = resolve(output, SHARD_FILES["europe-core"]);
    expect(() => publishSearchShardSet(output, built, { afterPromote: (count) => {
      if (count === 1) { unlinkSync(core); writeFileSync(core, "foreign"); throw new Error("injected replacement"); }
    } })).toThrow("injected replacement");
    expect(readFileSync(core, "utf8")).toBe("foreign");
  });

  it("rejects a symlink output and authority/projection mutations", () => {
    const root = mkdtempSync(resolve(tmpdir(), "search-builder-")); const real = resolve(root, "real"); mkdirSync(real, 0o700); const linked = resolve(root, "linked"); symlinkSync(real, linked);
    const input = fixture(root); const built = buildSearchShardSet(input);
    expect(() => publishSearchShardSet(linked, built)).toThrow(/absolute canonical|non-symlink/);
    const authority = JSON.parse(readFileSync(input.authorityPath, "utf8")); authority.projectionSha256 = hash("f"); writeFileSync(input.authorityPath, `${canonicalJson(authority)}\n`);
    expect(() => buildSearchShardSet(input)).toThrow(/authority differs/);
  });
});
