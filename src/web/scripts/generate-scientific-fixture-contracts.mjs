import { Buffer } from "node:buffer";
import { createHash } from "node:crypto";
import { existsSync, mkdirSync, readdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { inflateSync } from "node:zlib";
import {
  assertChecksumInventory,
  canonicalChecksumText,
  parseChecksumText,
} from "./checksum-inventory.mjs";

const RELEASE_ID = "searise-europe-v1.0.0-20260810-c096aeab4e09";
const checking = process.argv.includes("--check");
const repositoryRoot = resolve(import.meta.dirname, "../../..");
const payloadRoot = resolve(
  repositoryRoot,
  `contracts/release/v1/fixtures/release/${RELEASE_ID}`,
);
const sealedFixtureRoot = resolve(repositoryRoot, "contracts/release/v1/fixtures");
const overlayRoot = resolve(
  repositoryRoot,
  `contracts/release/v2/fixtures/browser-release/${RELEASE_ID}`,
);
const nodataControlPath =
  "src/pipeline/fixtures/browser-release/adr-024-nodata-control-v1.json";
const nodataControlBytes = readFileSync(resolve(repositoryRoot, nodataControlPath));
const nodataControl = JSON.parse(nodataControlBytes.toString("utf8"));
const boundaryArrowSchemasPath =
  "src/pipeline/fixtures/browser-release/boundary-arrow-schemas-v1.json";
const boundaryArrowSchemasBytes = readFileSync(resolve(repositoryRoot, boundaryArrowSchemasPath));
const boundaryArrowSchemas = JSON.parse(boundaryArrowSchemasBytes.toString("utf8"));
const sha256 = (bytes) => createHash("sha256").update(bytes).digest("hex");
const treeDigest = (root) => {
  const digest = createHash("sha256");
  const visit = (directory, prefix = "") => {
    for (const entry of readdirSync(directory, { withFileTypes: true }).sort((a, b) =>
      a.name.localeCompare(b.name))) {
      const relative = prefix ? `${prefix}/${entry.name}` : entry.name;
      const path = resolve(directory, entry.name);
      digest.update(`${entry.isDirectory() ? "d" : "f"}\0${relative}\0`);
      if (entry.isDirectory()) visit(path, relative);
      else if (entry.isFile()) digest.update(readFileSync(path));
      else throw new Error(`The byte-sealed v1 payload contains a non-file entry: ${relative}`);
    }
  };
  visit(root);
  return digest.digest("hex");
};
const sealedFixtureDigest = treeDigest(sealedFixtureRoot);
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
const v1ChecksumsText = readFileSync(resolve(payloadRoot, "checksums.txt"), "utf8");
// The sealed v1 file contains an explanatory comment and may contain blank
// lines. Parse those as metadata/spacing, never as artifact identities, and
// retain an exact semantic check before using the v1 manifest as input.
parseChecksumText(v1ChecksumsText);
assertChecksumInventory(v1Manifest, v1ChecksumsText);
// These two scientific inputs are produced only by the reusable Python release
// writers. Node deliberately cannot synthesize source IDs or range hashes.
const sourceGridBytes = readFileSync(resolve(overlayRoot, "analysis/source-grid.json.gz"));
const rangeIntegrityBytes = readFileSync(
  resolve(overlayRoot, "analysis/cog-range-integrity.json"),
);
const boundaries = [
  {
    artifactId: "europe-support-geoparquet",
    path: "boundaries/europe.parquet",
    role: "support-boundary",
    spatialBounds: [-28.851018, 30.021176, 44.001, 74.536347],
  },
  {
    artifactId: "coastal-analysis-zone-geoparquet",
    path: "boundaries/coastal-analysis-zone.parquet",
    role: "coastal-boundary",
    spatialBounds: [-28.850986, 30.021211, 44.001, 74.536318],
  },
].map((boundary) => ({
  ...boundary,
  bytes: readFileSync(resolve(overlayRoot, boundary.path)),
}));
if (
  nodataControl.controlId !== "browser-only-source-nodata-62n-44e" ||
  nodataControl.fixtureRole !== "browser-only-adr-024-data-unavailable-control" ||
  nodataControl.dataProvenanceClass !== "synthetic-fixture" ||
  nodataControl.dataReleaseId !== RELEASE_ID
) {
  throw new Error("The browser-only nodata control identity differs from the pin");
}
if (
  boundaryArrowSchemas.fixtureRole !== "browser-only-boundary-canonical-arrow-schemas" ||
  boundaryArrowSchemas.encoding !== "base64-zlib" ||
  Object.keys(boundaryArrowSchemas.schemas).sort().join(",") !==
    "coastal-boundary,support-boundary"
) {
  throw new Error("The browser-only canonical Arrow schema identity differs from the pin");
}
for (const record of Object.values(boundaryArrowSchemas.schemas)) {
  const decoded = inflateSync(Buffer.from(record.payload, "base64"));
  if (decoded.length !== record.decodedLength || sha256(decoded) !== record.decodedSha256) {
    throw new Error("The browser-only canonical Arrow schema payload differs from the pin");
  }
}

const cogBodies = new Map();
const cogArtifacts = v1Manifest.artifacts
  .filter((artifact) => artifact.role === "projection-analysis-cog")
  .map((artifact) => {
    const overlayPath = resolve(overlayRoot, artifact.path);
    const bytes = readFileSync(existsSync(overlayPath) ? overlayPath : resolve(payloadRoot, artifact.path));
    cogBodies.set(artifact.path, bytes);
    return { ...artifact, byteSize: bytes.length, sha256: sha256(bytes) };
  });
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
    ...cogArtifacts
      .filter((artifact) => existsSync(resolve(overlayRoot, artifact.path)))
      .map((artifact) => [artifact.path, cogBodies.get(artifact.path)]),
    ...boundaries.map((boundary) => [boundary.path, boundary.bytes]),
    [nodataControlPath, nodataControlBytes],
    [boundaryArrowSchemasPath, boundaryArrowSchemasBytes],
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
attribution.$schema =
  "https://artemsemdev.github.io/SeaRise-Europe/contracts/release/v2/attribution.schema.json";
attribution.schemaVersion = "2.0.0";
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
attribution.records.push({
  attributionId: "natural-earth-boundaries",
  sourceId: "natural-earth-10m/5.1.1",
  title: "Natural Earth 1:10m physical and cultural vectors",
  sourceUrl: "https://www.naturalearthdata.com/",
  sourceSha256: "2623fc05db56e8f67de95b555b7a5e43f54012f824fbf3154d04283313b7a6e8",
  attributionText: "Made with Natural Earth.",
  licence: {
    spdxId: "LicenseRef-Natural-Earth-Public-Domain",
    name: "Natural Earth public domain dedication",
    url: "https://www.naturalearthdata.com/about/terms-of-use/",
  },
  redistribution: "allowed",
  appliesToRoles: ["support-boundary", "coastal-boundary"],
});
attribution.records.push({
  attributionId: "browser-nodata-control-fixture",
  sourceId: "searise-browser-nodata-control/v1",
  title: "SeaRise Europe browser-only ADR-024 nodata control",
  sourceUrl: "https://github.com/artemsemdev/SeaRise-Europe",
  sourceSha256: sha256(nodataControlBytes),
  attributionText:
    "Synthetic browser-only DataUnavailable control; not production or public scientific evidence.",
  licence: {
    spdxId: "CC-BY-4.0",
    name: "Creative Commons Attribution 4.0 International",
    url: "https://creativecommons.org/licenses/by/4.0/",
  },
  redistribution: "allowed",
  appliesToRoles: ["support-boundary", "coastal-boundary"],
});
const attributionBytes = compactJson(attribution);
writeOverlay("config/source-attribution.json", attributionBytes);
const methodologyBytes = readFileSync(resolve(payloadRoot, "config/methodology.json"));
writeOverlay("config/methodology.json", methodologyBytes);

const identity = (path, bytes) => ({ path, sha256: sha256(bytes) });
const repositoryBytes = (path) => readFileSync(resolve(repositoryRoot, path));
const v1ManifestBytes = readFileSync(resolve(payloadRoot, "manifest.json"));
const v1BuildReceiptBytes = readFileSync(resolve(payloadRoot, "receipts/build.json"));
const v1ProvenanceBytes = readFileSync(resolve(payloadRoot, "provenance.intoto.jsonl"));
// The overlay keeps byte-identical copies only so the assembled fixture cannot
// shadow the sealed base evidence with modified claims.
writeOverlay("receipts/build.json", v1BuildReceiptBytes);
writeOverlay("provenance.intoto.jsonl", v1ProvenanceBytes);
const nonClaims = [
  "No build run, workflow, platform, timestamp, or code revision is asserted for this deterministic browser derivation.",
  "This receipt is not the authoritative build receipt for the sealed v1 release.",
  "This synthetic fixture is not approved real-source public-release evidence.",
];
const overlayInputs = [
  identity("analysis/source-grid.json.gz", sourceGridBytes),
  identity("analysis/cog-range-integrity.json", rangeIntegrityBytes),
  ...cogArtifacts
    .filter((artifact) => existsSync(resolve(overlayRoot, artifact.path)))
    .map((artifact) => identity(artifact.path, cogBodies.get(artifact.path))),
  ...boundaries.map((boundary) => identity(boundary.path, boundary.bytes)),
].sort((left, right) => left.path.localeCompare(right.path));
const derivationMaterials = [
  identity(
    `contracts/release/v1/fixtures/release/${RELEASE_ID}/manifest.json`,
    v1ManifestBytes,
  ),
  identity(
    `contracts/release/v1/fixtures/release/${RELEASE_ID}/receipts/build.json`,
    v1BuildReceiptBytes,
  ),
  identity(
    `contracts/release/v1/fixtures/release/${RELEASE_ID}/provenance.intoto.jsonl`,
    v1ProvenanceBytes,
  ),
  identity(
    `contracts/release/v1/fixtures/release/${RELEASE_ID}/config/methodology.json`,
    methodologyBytes,
  ),
  identity(
    "src/web/scripts/generate-scientific-fixture-contracts.mjs",
    repositoryBytes("src/web/scripts/generate-scientific-fixture-contracts.mjs"),
  ),
  identity(
    "src/web/scripts/checksum-inventory.mjs",
    repositoryBytes("src/web/scripts/checksum-inventory.mjs"),
  ),
  identity(nodataControlPath, nodataControlBytes),
  identity(boundaryArrowSchemasPath, boundaryArrowSchemasBytes),
  identity(
    "scripts/release/build-browser-integrity-fixture.py",
    repositoryBytes("scripts/release/build-browser-integrity-fixture.py"),
  ),
  identity(
    "src/pipeline/searise_pipeline/release/boundary_geoparquet.py",
    repositoryBytes("src/pipeline/searise_pipeline/release/boundary_geoparquet.py"),
  ),
  ...overlayInputs,
].sort((left, right) => left.path.localeCompare(right.path));
const derivedOutputs = [
  identity("sbom/browser-integrity.cdx.json", sbomBytes),
  identity("config/methodology.json", methodologyBytes),
  identity("config/source-attribution.json", attributionBytes),
].sort((left, right) => left.path.localeCompare(right.path));
const derivationReceipt = {
  $schema:
    "https://artemsemdev.github.io/SeaRise-Europe/contracts/release/v2/browser-derivation-receipt.schema.json",
  schemaVersion: "2.0.0",
  receiptType: "browser-overlay-derivation",
  dataReleaseId: RELEASE_ID,
  dataProvenanceClass: "synthetic-fixture",
  executionIdentity: "not-recorded",
  materials: derivationMaterials,
  outputs: derivedOutputs,
  nonClaims,
};
const derivationReceiptBytes = compactJson(derivationReceipt);
writeOverlay("receipts/browser-derivation.json", derivationReceiptBytes);

const derivationProvenance = {
  $schema:
    "https://artemsemdev.github.io/SeaRise-Europe/contracts/release/v2/browser-derivation-provenance.schema.json",
  schemaVersion: "2.0.0",
  _type: "https://in-toto.io/Statement/v1",
  subject: [
    ...derivedOutputs.map(({ path: name, sha256: digest }) => ({
      name,
      digest: { sha256: digest },
    })),
    {
      name: "receipts/browser-derivation.json",
      digest: { sha256: sha256(derivationReceiptBytes) },
    },
  ].sort((left, right) => left.name.localeCompare(right.name)),
  predicateType:
    "https://artemsemdev.github.io/SeaRise-Europe/contracts/release/v2/browser-derivation-predicate/v1",
  predicate: {
    derivationType: "deterministic-browser-overlay",
    executionIdentity: "not-recorded",
    materials: derivationMaterials,
    receipt: identity("receipts/browser-derivation.json", derivationReceiptBytes),
    nonClaims,
  },
};
const derivationProvenanceBytes = compactJson(derivationProvenance);
writeOverlay("browser-derivation.intoto.json", derivationProvenanceBytes);

const manifest = clone(v1Manifest);
manifest.$schema =
  "https://artemsemdev.github.io/SeaRise-Europe/contracts/release/v2/manifest.schema.json";
manifest.schemaVersion = "2.0.0";
manifest.baseReleaseIdentity = {
  identityScope: "sealed-release-v1",
  schemaVersion: "1.0.0",
  manifestSha256: sha256(v1ManifestBytes),
  createdAt: v1Manifest.createdAt,
  codeRevision: v1Manifest.codeRevision,
};
manifest.browserDerivationIdentity = {
  identityScope: "browser-overlay-derivation",
  executionIdentity: "not-recorded",
  receiptArtifactId: "browser-derivation-receipt",
  provenanceArtifactId: "browser-derivation-provenance",
};
delete manifest.createdAt;
delete manifest.codeRevision;
for (const artifact of manifest.artifacts) {
  artifact.$schema =
    "https://artemsemdev.github.io/SeaRise-Europe/contracts/release/v2/artifact.schema.json";
  artifact.schemaVersion = "2.0.0";
  const replacement = cogArtifacts.find((candidate) => candidate.artifactId === artifact.artifactId);
  if (replacement) {
    artifact.byteSize = replacement.byteSize;
    artifact.sha256 = replacement.sha256;
  }
}
const baseBuildArtifact = manifest.artifacts.find(
  (artifact) => artifact.artifactId === manifest.contractArtifacts.buildReceipt,
);
const baseProvenanceArtifact = manifest.artifacts.find(
  (artifact) => artifact.artifactId === manifest.contractArtifacts.provenance,
);
const baseSignatureArtifact = manifest.artifacts.find(
  (artifact) => artifact.artifactId === manifest.contractArtifacts.signature,
);
baseBuildArtifact.role = "base-release-build-receipt";
baseProvenanceArtifact.role = "base-release-provenance";
baseSignatureArtifact.role = "base-release-signature";
const derivationLineage = [
  identity("receipts/browser-derivation.json", derivationReceiptBytes),
];
const scriptIdentity = (path) => identity(path, repositoryBytes(path));
const sourceGridLineage = [
  scriptIdentity("scripts/release/build-browser-integrity-fixture.py"),
  scriptIdentity("src/pipeline/searise_pipeline/release/model.py"),
  scriptIdentity("src/pipeline/searise_pipeline/release/source_grid.py"),
  scriptIdentity("src/pipeline/fixtures/ar6-regional-release/source-fixture-receipt.json"),
  scriptIdentity("src/pipeline/fixtures/ar6-regional-release/source-fixture.json.gz"),
  scriptIdentity("src/pipeline/science/ar6-regional-release.json"),
].sort((left, right) => left.path.localeCompare(right.path));
const rangeIntegrityLineage = [
  scriptIdentity("scripts/release/build-browser-integrity-fixture.py"),
  scriptIdentity("src/pipeline/searise_pipeline/release/range_integrity.py"),
  identity(
    `contracts/release/v1/fixtures/release/${RELEASE_ID}/manifest.json`,
    v1ManifestBytes,
  ),
].sort((left, right) => left.path.localeCompare(right.path));
const projectionLineageByArtifactId = new Map(
  cogArtifacts
    .filter((artifact) => existsSync(resolve(overlayRoot, artifact.path)))
    .map((artifact) => {
      const baseArtifact = v1Manifest.artifacts.find(
        (candidate) => candidate.artifactId === artifact.artifactId,
      );
      return [
        artifact.artifactId,
        [
          scriptIdentity("scripts/release/build-browser-integrity-fixture.py"),
          identity(
            `contracts/release/v1/fixtures/release/${RELEASE_ID}/${baseArtifact.path}`,
            readFileSync(resolve(payloadRoot, baseArtifact.path)),
          ),
        ].sort((left, right) => left.path.localeCompare(right.path)),
      ];
    }),
);
for (const artifact of manifest.artifacts) {
  const projectionLineage = projectionLineageByArtifactId.get(artifact.artifactId);
  if (projectionLineage) artifact.lineage = projectionLineage;
}
const boundaryLineage = [
  scriptIdentity("scripts/release/build-browser-integrity-fixture.py"),
  scriptIdentity("src/pipeline/searise_pipeline/release/boundary_geoparquet.py"),
  identity(nodataControlPath, nodataControlBytes),
  identity(boundaryArrowSchemasPath, boundaryArrowSchemasBytes),
  scriptIdentity("src/pipeline/sources/source-lock.phase-1-settlement-coastline.json"),
].sort((left, right) => left.path.localeCompare(right.path));
const common = {
  $schema: "https://artemsemdev.github.io/SeaRise-Europe/contracts/release/v2/artifact.schema.json",
  schemaVersion: "2.0.0",
  dataReleaseId: RELEASE_ID,
  dataProvenanceClass: "synthetic-fixture",
  immutable: true,
  lineage: derivationLineage,
  spatialBounds: null,
};
const additions = [
  { ...common, artifactId: "source-grid-identity", path: "analysis/source-grid.json.gz", role: "source-grid-identity", mediaType: "application/gzip", scientificUse: "exact-lookup-support", byteSize: sourceGridBytes.length, sha256: sha256(sourceGridBytes), lineage: sourceGridLineage, rights: { attributionIds: ["ipcc-ar6-sl-projections-20210809"], redistribution: "allowed" } },
  { ...common, artifactId: "cog-range-integrity", path: "analysis/cog-range-integrity.json", role: "range-integrity-index", mediaType: "application/json", scientificUse: "exact-lookup-support", byteSize: rangeIntegrityBytes.length, sha256: sha256(rangeIntegrityBytes), lineage: rangeIntegrityLineage, rights: { attributionIds: ["ipcc-ar6-sl-projections-20210809"], redistribution: "allowed" } },
  { ...common, artifactId: "browser-integrity-sbom", path: "sbom/browser-integrity.cdx.json", role: "sbom", mediaType: "application/json", scientificUse: "not-applicable", byteSize: sbomBytes.length, sha256: sha256(sbomBytes), rights: { attributionIds: ["geonames-fixture"], redistribution: "allowed" } },
  ...boundaries.map((boundary) => ({
    ...common,
    artifactId: boundary.artifactId,
    path: boundary.path,
    role: boundary.role,
    mediaType: "application/vnd.apache.parquet",
    scientificUse: "not-applicable",
    byteSize: boundary.bytes.length,
    sha256: sha256(boundary.bytes),
    spatialBounds: boundary.spatialBounds,
    lineage: boundaryLineage,
    rights: {
      attributionIds: ["browser-nodata-control-fixture", "natural-earth-boundaries"],
      redistribution: "allowed",
    },
  })),
  {
    ...common,
    artifactId: "browser-derivation-receipt",
    path: "receipts/browser-derivation.json",
    role: "browser-derivation-receipt",
    mediaType: "application/json",
    scientificUse: "not-applicable",
    byteSize: derivationReceiptBytes.length,
    sha256: sha256(derivationReceiptBytes),
    lineage: derivationMaterials,
    rights: { attributionIds: ["geonames-fixture"], redistribution: "allowed" },
  },
  {
    ...common,
    artifactId: "browser-derivation-provenance",
    path: "browser-derivation.intoto.json",
    role: "browser-derivation-provenance",
    mediaType: "application/vnd.in-toto+json",
    scientificUse: "not-applicable",
    byteSize: derivationProvenanceBytes.length,
    sha256: sha256(derivationProvenanceBytes),
    rights: { attributionIds: ["geonames-fixture"], redistribution: "allowed" },
  },
];
const firstProjection = manifest.artifacts.findIndex(
  (artifact) => artifact.role === "projection-analysis-cog",
);
manifest.artifacts.splice(firstProjection, 0, ...additions);
manifest.contractArtifacts.sourceGridIdentity = "source-grid-identity";
manifest.contractArtifacts.rangeIntegrityIndex = "cog-range-integrity";
manifest.contractArtifacts.sbom = "browser-integrity-sbom";
manifest.contractArtifacts.baseReleaseBuildReceipt = manifest.contractArtifacts.buildReceipt;
manifest.contractArtifacts.browserDerivationReceipt = "browser-derivation-receipt";
manifest.contractArtifacts.baseReleaseProvenance = manifest.contractArtifacts.provenance;
manifest.contractArtifacts.browserDerivationProvenance = "browser-derivation-provenance";
manifest.contractArtifacts.baseReleaseSignature = manifest.contractArtifacts.signature;
delete manifest.contractArtifacts.buildReceipt;
delete manifest.contractArtifacts.provenance;
delete manifest.contractArtifacts.signature;

const replaceArtifact = (artifactId, bytes) => {
  const artifact = manifest.artifacts.find((candidate) => candidate.artifactId === artifactId);
  artifact.byteSize = bytes.length;
  artifact.sha256 = sha256(bytes);
};
replaceArtifact("attribution", attributionBytes);
manifest.artifacts.find((artifact) => artifact.artifactId === "attribution").lineage =
  derivationLineage;
replaceArtifact("methodology", methodologyBytes);
manifest.artifacts.find((artifact) => artifact.artifactId === "methodology").lineage =
  derivationLineage;

// Render from the complete final manifest inventory, not a partial inherited
// list. manifest.json and checksums.txt are the only exclusions because their
// inclusion would create a mutual/direct self-reference cycle.
const checksumsBytes = Buffer.from(canonicalChecksumText(manifest), "utf8");
assertChecksumInventory(manifest, checksumsBytes.toString("utf8"));
writeOverlay("checksums.txt", checksumsBytes);
replaceArtifact("checksums", checksumsBytes);
manifest.artifacts.find((artifact) => artifact.artifactId === "checksums").lineage =
  derivationLineage;

writeOverlay("manifest.json", compactJson(manifest));

for (const artifact of manifest.artifacts) {
  const overlayPath = resolve(overlayRoot, artifact.path);
  const body = readFileSync(existsSync(overlayPath) ? overlayPath : resolve(payloadRoot, artifact.path));
  if (body.length !== artifact.byteSize || sha256(body) !== artifact.sha256) {
    throw new Error(`The assembled v2 body differs from manifest identity: ${artifact.path}`);
  }
}
if (treeDigest(sealedFixtureRoot) !== sealedFixtureDigest) {
  throw new Error("The v2 overlay generator modified the byte-sealed v1 fixture subtree");
}
