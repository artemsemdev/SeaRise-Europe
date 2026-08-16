import { Buffer } from "node:buffer";
import { createHash } from "node:crypto";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";

const RELEASE_ID = "searise-europe-v1.0.0-20260810-c096aeab4e09";
const checking = process.argv.includes("--check");
const repositoryRoot = resolve(import.meta.dirname, "../../..");
const payloadRoot = resolve(
  repositoryRoot,
  `contracts/release/v1/fixtures/release/${RELEASE_ID}`,
);
const overlayRoot = resolve(
  repositoryRoot,
  `contracts/release/v2/fixtures/browser-release/${RELEASE_ID}`,
);
const sha256 = (bytes) => createHash("sha256").update(bytes).digest("hex");
const compactJson = (value) => Buffer.from(`${JSON.stringify(value)}\n`, "utf8");
const clone = (value) => JSON.parse(JSON.stringify(value));
const writeOverlay = (relative, bytes) => {
  const path = resolve(overlayRoot, relative);
  if (checking) {
    if (!readFileSync(path).equals(bytes)) {
      throw new Error(`Scientific fixture overlay is stale: ${relative}`);
    }
    return;
  }
  mkdirSync(dirname(path), { recursive: true });
  writeFileSync(path, bytes);
};

// v1 is a byte-sealed payload source. This generator only writes the separate
// committed v2 overlay assembled by the static build.
const v1Manifest = JSON.parse(readFileSync(resolve(payloadRoot, "manifest.json"), "utf8"));
// These two scientific inputs are produced only by the reusable Python release
// writers. Node deliberately cannot synthesize source IDs or range hashes.
const sourceGridBytes = readFileSync(resolve(overlayRoot, "analysis/source-grid.json.gz"));
const rangeIntegrityBytes = readFileSync(
  resolve(overlayRoot, "analysis/cog-range-integrity.json"),
);

const cogArtifacts = v1Manifest.artifacts.filter(
  (artifact) => artifact.role === "projection-analysis-cog",
);
const rangeIntegrity = JSON.parse(rangeIntegrityBytes.toString("utf8"));
if (
  rangeIntegrity.dataReleaseId !== RELEASE_ID ||
  rangeIntegrity.algorithm !== "sha256" ||
  rangeIntegrity.artifacts.length !== cogArtifacts.length
) {
  throw new Error("Python range-integrity output does not match the v1 payload manifest");
}
for (const artifact of cogArtifacts) {
  const record = rangeIntegrity.artifacts.find(
    (candidate) => candidate.artifactId === artifact.artifactId,
  );
  if (
    record?.path !== artifact.path ||
    record.byteSize !== artifact.byteSize ||
    record.sha256 !== artifact.sha256
  ) {
    throw new Error(`Range-integrity identity differs for ${artifact.artifactId}`);
  }
}

const sbom = {
  bomFormat: "CycloneDX",
  specVersion: "1.6",
  serialNumber: "urn:uuid:adf7094d-0ac7-5c27-964b-e48a392c0e27",
  version: 1,
  metadata: {
    component: {
      type: "data",
      name: "SeaRise Europe browser integrity metadata",
      version: RELEASE_ID,
    },
  },
  components: [
    ["analysis/source-grid.json.gz", sourceGridBytes],
    ["analysis/cog-range-integrity.json", rangeIntegrityBytes],
  ].map(([path, bytes]) => ({
    type: "data",
    name: path,
    version: RELEASE_ID,
    hashes: [{ alg: "SHA-256", content: sha256(bytes) }],
  })),
};
const sbomBytes = compactJson(sbom);
writeOverlay("sbom/browser-integrity.cdx.json", sbomBytes);

const attribution = JSON.parse(
  readFileSync(resolve(payloadRoot, "config/source-attribution.json"), "utf8"),
);
const ipcc = attribution.records.find(
  (record) => record.attributionId === "ipcc-ar6-sl-projections-20210809",
);
ipcc.appliesToRoles = [
  ...new Set([...ipcc.appliesToRoles, "source-grid-identity", "range-integrity-index"]),
].sort();
const fixture = attribution.records.find(
  (record) => record.attributionId === "geonames-fixture",
);
fixture.appliesToRoles = [...new Set([...fixture.appliesToRoles, "sbom"])].sort();
const attributionBytes = compactJson(attribution);
writeOverlay("config/source-attribution.json", attributionBytes);

const buildReceipt = JSON.parse(readFileSync(resolve(payloadRoot, "receipts/build.json"), "utf8"));
buildReceipt.$schema =
  "https://artemsemdev.github.io/SeaRise-Europe/contracts/release/v2/build-receipt.schema.json";
buildReceipt.schemaVersion = "2.0.0";
buildReceipt.outputs.push(
  { path: "analysis/source-grid.json.gz", role: "source-grid-identity", mediaType: "application/gzip", byteSize: sourceGridBytes.length, sha256: sha256(sourceGridBytes) },
  { path: "analysis/cog-range-integrity.json", role: "range-integrity-index", mediaType: "application/json", byteSize: rangeIntegrityBytes.length, sha256: sha256(rangeIntegrityBytes) },
  { path: "sbom/browser-integrity.cdx.json", role: "sbom", mediaType: "application/json", byteSize: sbomBytes.length, sha256: sha256(sbomBytes) },
  { path: "config/source-attribution.json", role: "source-attribution", mediaType: "application/json", byteSize: attributionBytes.length, sha256: sha256(attributionBytes) },
);
buildReceipt.outputs.sort((left, right) =>
  left.path < right.path ? -1 : left.path > right.path ? 1 : 0,
);
const buildReceiptBytes = compactJson(buildReceipt);
writeOverlay("receipts/build.json", buildReceiptBytes);

const provenance = JSON.parse(
  readFileSync(resolve(payloadRoot, "provenance.intoto.jsonl"), "utf8"),
);
provenance.predicate.buildDefinition.buildType =
  "https://artemsemdev.github.io/SeaRise-Europe/contracts/release/v2/manifest.schema.json";
const subjects = new Map(provenance.subject.map((subject) => [subject.name, subject]));
for (const [name, bytes] of [
  ["analysis/source-grid.json.gz", sourceGridBytes],
  ["analysis/cog-range-integrity.json", rangeIntegrityBytes],
  ["sbom/browser-integrity.cdx.json", sbomBytes],
  ["config/source-attribution.json", attributionBytes],
  ["receipts/build.json", buildReceiptBytes],
]) {
  subjects.set(name, { name, digest: { sha256: sha256(bytes) } });
}
provenance.subject = [...subjects.values()].sort((left, right) =>
  left.name < right.name ? -1 : left.name > right.name ? 1 : 0,
);
const provenanceBytes = compactJson(provenance);
writeOverlay("provenance.intoto.jsonl", provenanceBytes);

const manifest = clone(v1Manifest);
manifest.$schema =
  "https://artemsemdev.github.io/SeaRise-Europe/contracts/release/v2/manifest.schema.json";
manifest.schemaVersion = "2.0.0";
for (const artifact of manifest.artifacts) {
  artifact.$schema =
    "https://artemsemdev.github.io/SeaRise-Europe/contracts/release/v2/artifact.schema.json";
  artifact.schemaVersion = "2.0.0";
}
const buildSha256 = sha256(buildReceiptBytes);
for (const artifact of manifest.artifacts) {
  artifact.lineage = artifact.lineage.map((identity) =>
    identity.path === "receipts/build.json"
      ? { ...identity, sha256: buildSha256 }
      : identity,
  );
}
const common = {
  $schema: "https://artemsemdev.github.io/SeaRise-Europe/contracts/release/v2/artifact.schema.json",
  schemaVersion: "2.0.0",
  dataReleaseId: RELEASE_ID,
  dataProvenanceClass: "synthetic-fixture",
  immutable: true,
  lineage: [{ path: "receipts/build.json", sha256: buildSha256 }],
  spatialBounds: null,
};
const additions = [
  { ...common, artifactId: "source-grid-identity", path: "analysis/source-grid.json.gz", role: "source-grid-identity", mediaType: "application/gzip", scientificUse: "exact-lookup-support", byteSize: sourceGridBytes.length, sha256: sha256(sourceGridBytes), rights: { attributionIds: ["ipcc-ar6-sl-projections-20210809"], redistribution: "allowed" } },
  { ...common, artifactId: "cog-range-integrity", path: "analysis/cog-range-integrity.json", role: "range-integrity-index", mediaType: "application/json", scientificUse: "exact-lookup-support", byteSize: rangeIntegrityBytes.length, sha256: sha256(rangeIntegrityBytes), rights: { attributionIds: ["ipcc-ar6-sl-projections-20210809"], redistribution: "allowed" } },
  { ...common, artifactId: "browser-integrity-sbom", path: "sbom/browser-integrity.cdx.json", role: "sbom", mediaType: "application/json", scientificUse: "not-applicable", byteSize: sbomBytes.length, sha256: sha256(sbomBytes), rights: { attributionIds: ["geonames-fixture"], redistribution: "allowed" } },
];
const firstProjection = manifest.artifacts.findIndex(
  (artifact) => artifact.role === "projection-analysis-cog",
);
manifest.artifacts.splice(firstProjection, 0, ...additions);
manifest.contractArtifacts.sourceGridIdentity = "source-grid-identity";
manifest.contractArtifacts.rangeIntegrityIndex = "cog-range-integrity";
manifest.contractArtifacts.sbom = "browser-integrity-sbom";

const replaceArtifact = (artifactId, bytes) => {
  const artifact = manifest.artifacts.find((candidate) => candidate.artifactId === artifactId);
  artifact.byteSize = bytes.length;
  artifact.sha256 = sha256(bytes);
};
replaceArtifact("attribution", attributionBytes);
replaceArtifact("build-receipt", buildReceiptBytes);
replaceArtifact("provenance", provenanceBytes);

const replacements = new Map([
  ["config/source-attribution.json", attributionBytes],
  ["receipts/build.json", buildReceiptBytes],
  ["provenance.intoto.jsonl", provenanceBytes],
]);
const checksums = readFileSync(resolve(payloadRoot, "checksums.txt"), "utf8")
  .trimEnd()
  .split("\n")
  .map((line) => {
    const path = line.slice(line.indexOf("  ") + 2);
    const bytes = replacements.get(path);
    return bytes ? `${sha256(bytes)}  ${path}` : line;
  });
checksums.splice(1, 0,
  `${sha256(rangeIntegrityBytes)}  analysis/cog-range-integrity.json`,
  `${sha256(sourceGridBytes)}  analysis/source-grid.json.gz`,
  `${sha256(sbomBytes)}  sbom/browser-integrity.cdx.json`,
);
const checksumsBytes = Buffer.from(`${checksums.join("\n")}\n`, "utf8");
writeOverlay("checksums.txt", checksumsBytes);
replaceArtifact("checksums", checksumsBytes);

writeOverlay("manifest.json", compactJson(manifest));
