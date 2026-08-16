import { Buffer } from "node:buffer";
import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import {
  chmodSync,
  closeSync,
  constants,
  existsSync,
  fstatSync,
  lstatSync,
  mkdirSync,
  mkdtempSync,
  openSync,
  readFileSync,
  readdirSync,
  realpathSync,
  rmSync,
  statSync,
  writeFileSync,
} from "node:fs";
import { createServer as createHttpServer } from "node:http";
import { tmpdir } from "node:os";
import { dirname, extname, isAbsolute, join, relative, resolve, sep } from "node:path";
import { privateCandidateBuildIdentity } from "./build-identity.mjs";

const ARTIFACT_SCHEMA =
  "https://artemsemdev.github.io/SeaRise-Europe/contracts/release/v2/artifact.schema.json";
const PRIVATE_MANIFEST_SCHEMA =
  "https://artemsemdev.github.io/SeaRise-Europe/contracts/release/v2/private-binding-manifest.schema.json";
const PRIVATE_RELEASE_SCHEMA =
  "https://artemsemdev.github.io/SeaRise-Europe/contracts/release/v2/private-release-manifest.schema.json";
const BROWSER_DERIVATION_RECEIPT_SCHEMA =
  "https://artemsemdev.github.io/SeaRise-Europe/contracts/release/v2/browser-derivation-receipt.schema.json";
const BROWSER_DERIVATION_PROVENANCE_SCHEMA =
  "https://artemsemdev.github.io/SeaRise-Europe/contracts/release/v2/browser-derivation-provenance.schema.json";
const RELEASE_ID = /^searise-europe-v\d+\.\d+\.\d+-\d{8}-[a-f0-9]{12}$/;
const SHA256 = /^[a-f0-9]{64}$/;
const SCENARIOS = ["ssp1-26", "ssp2-45", "ssp5-85"];
const HORIZONS = [2030, 2050, 2100];
const CHUNK_SIZE = 65_536;
const repositoryRoot = resolve(import.meta.dirname, "../../..");
const fixtureReleaseId = "searise-europe-v1.0.0-20260810-c096aeab4e09";
const fixtureRoot = resolve(
  repositoryRoot,
  "contracts/release/v2/fixtures/browser-release",
  fixtureReleaseId,
);
const fixtureManifest = JSON.parse(readFileSync(resolve(fixtureRoot, "manifest.json"), "utf8"));

const mediaTypes = {
  ".br": "application/vnd.searise.search-index+json",
  ".css": "text/css",
  ".gz": "application/gzip",
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript",
  ".json": "application/json",
  ".jsonl": "application/x-ndjson",
  ".md": "text/markdown",
  ".parquet": "application/vnd.apache.parquet",
  ".pmtiles": "application/vnd.pmtiles",
  ".tif": "image/tiff; application=geotiff; profile=cloud-optimized",
  ".txt": "text/plain",
  ".wasm": "application/wasm",
  ".webmanifest": "application/manifest+json",
  ".woff2": "font/woff2",
};

function sha256(bytes) {
  return createHash("sha256").update(bytes).digest("hex");
}

function fileSha256(path) {
  return sha256(readFileSync(path));
}

function compactJson(value) {
  return Buffer.from(`${JSON.stringify(value)}\n`, "utf8");
}

function safeRelativePath(value) {
  if (
    typeof value !== "string" ||
    value === "" ||
    value.includes("\\") ||
    value.startsWith("/") ||
    value.split("/").some((part) => part === "" || part === "." || part === "..")
  ) {
    throw new Error(`Unsafe release-relative path: ${value}`);
  }
  return value;
}

function explicitDirectory(value, label) {
  if (!value || !isAbsolute(value)) throw new Error(`${label} must be an explicit absolute path`);
  const requested = resolve(value);
  const info = lstatSync(requested);
  if (info.isSymbolicLink() || !info.isDirectory() || realpathSync(requested) !== requested) {
    throw new Error(`${label} must be one real, non-symlink directory`);
  }
  return requested;
}

function explicitFile(value, label) {
  if (!value || !isAbsolute(value)) throw new Error(`${label} must be an explicit absolute path`);
  const requested = resolve(value);
  const info = lstatSync(requested);
  if (info.isSymbolicLink() || !info.isFile() || realpathSync(requested) !== requested) {
    throw new Error(`${label} must be one real, non-symlink regular file`);
  }
  return requested;
}

function readOnlyFileSnapshot(path, label) {
  const requested = explicitFile(path, label);
  const info = lstatSync(requested);
  if ((info.mode & 0o222) !== 0) throw new Error(`${label} must not have write bits`);
  const bytes = readFileSync(requested);
  const after = lstatSync(requested);
  if (
    after.isSymbolicLink() ||
    !after.isFile() ||
    after.dev !== info.dev ||
    after.ino !== info.ino ||
    after.size !== bytes.length
  ) {
    throw new Error(`${label} changed while its identity was read`);
  }
  return Object.freeze({
    path: requested,
    realpath: realpathSync(requested),
    byteSize: bytes.length,
    sha256: sha256(bytes),
    dev: after.dev,
    ino: after.ino,
    bytes,
  });
}

function fileBeneath(root, logicalPath) {
  const safe = safeRelativePath(logicalPath);
  let cursor = root;
  for (const part of safe.split("/")) {
    cursor = join(cursor, part);
    if (lstatSync(cursor).isSymbolicLink()) throw new Error(`Symlink is forbidden: ${safe}`);
  }
  const real = realpathSync(cursor);
  if (!real.startsWith(`${root}${sep}`) || !statSync(real).isFile()) {
    throw new Error(`Release artifact escapes its explicit root: ${safe}`);
  }
  return real;
}

function candidateSnapshot(candidateRoot) {
  if ((lstatSync(candidateRoot).mode & 0o222) !== 0) {
    throw new Error("Candidate root directory is writable");
  }
  const records = [];
  function walk(directory) {
    for (const entry of readdirSync(directory, { withFileTypes: true })) {
      const path = join(directory, entry.name);
      const logicalPath = relative(candidateRoot, path).split(sep).join("/");
      const info = lstatSync(path);
      if (entry.isSymbolicLink()) throw new Error(`Candidate contains a symlink: ${logicalPath}`);
      if (entry.isDirectory()) {
        if ((info.mode & 0o222) !== 0) throw new Error(`Candidate directory is writable: ${logicalPath}`);
        walk(path);
      } else if (entry.isFile()) {
        if ((info.mode & 0o222) !== 0) throw new Error(`Candidate file is writable: ${logicalPath}`);
        records.push({ path: logicalPath, byteSize: info.size, sha256: fileSha256(path) });
      } else {
        throw new Error(`Candidate contains a non-regular entry: ${logicalPath}`);
      }
    }
  }
  walk(candidateRoot);
  records.sort((left, right) => left.path.localeCompare(right.path));
  return Object.freeze({
    records: Object.freeze(records),
    digest: sha256(compactJson(records)),
  });
}

function writePrivateFile(overlayRoot, logicalPath, bytes) {
  const destination = resolve(overlayRoot, safeRelativePath(logicalPath));
  if (!destination.startsWith(`${overlayRoot}${sep}`)) throw new Error("Overlay path escaped");
  mkdirSync(dirname(destination), { mode: 0o700, recursive: true });
  writeFileSync(destination, bytes, { flag: "wx", mode: 0o600 });
  chmodSync(destination, 0o600);
  return destination;
}

function artifactCommon(artifact, releaseId, lineage) {
  const stacIdentity = /^stac\/items\/(ssp1-26|ssp2-45|ssp5-85)-(2030|2050|2100)\.json$/.exec(
    artifact.path,
  );
  return {
    $schema: ARTIFACT_SCHEMA,
    schemaVersion: "2.0.0",
    dataReleaseId: releaseId,
    dataProvenanceClass: "real-source",
    immutable: true,
    lineage: [lineage],
    artifactId: stacIdentity ? `stac-${stacIdentity[1]}-${stacIdentity[2]}` : artifact.artifactId,
    path: artifact.path,
    role: artifact.role,
    mediaType: artifact.mediaType,
    scientificUse: "not-applicable",
    byteSize: artifact.byteSize,
    sha256: artifact.sha256,
    spatialBounds: null,
    rights: artifact.rights,
  };
}

function enrichCandidateArtifact(artifact, releaseId, lineage, candidateArtifacts, candidateRoot) {
  const result = artifactCommon(artifact, releaseId, lineage);
  if (artifact.role === "build-receipt") result.role = "base-release-build-receipt";
  const template = fixtureManifest.artifacts.find(
    (candidate) => candidate.path === artifact.path && candidate.role === artifact.role,
  );
  if (["support-boundary", "coastal-boundary"].includes(artifact.role)) {
    const boundaryTemplate = fixtureManifest.artifacts.find(
      (candidate) =>
        candidate.role === artifact.role &&
        candidate.mediaType === "application/vnd.apache.parquet",
    );
    const boundaryAuthority = candidateArtifacts.find(
      (candidate) =>
        candidate.role === artifact.role &&
        candidate.mediaType === "application/vnd.apache.parquet",
    );
    if (
      boundaryTemplate?.sha256 !== boundaryAuthority?.sha256 ||
      boundaryTemplate.byteSize !== boundaryAuthority.byteSize
    ) {
      throw new Error(`No byte-identical reviewed browser boundary for ${artifact.path}`);
    }
    result.spatialBounds = boundaryTemplate.spatialBounds;
  } else if (["projection-analysis-cog", "projection-visual-pmtiles"].includes(artifact.role)) {
    const match = /^(?:analysis|layers)\/(ssp1-26|ssp2-45|ssp5-85)\/(2030|2050|2100)\.(?:tif|pmtiles)$/.exec(
      artifact.path,
    );
    if (!match) throw new Error(`Projection path has no canonical scenario/horizon: ${artifact.path}`);
    const [, scenario, horizonText] = match;
    const horizon = Number(horizonText);
    const stac = JSON.parse(
      readFileSync(fileBeneath(candidateRoot, `stac/items/${scenario}-${horizon}.json`), "utf8"),
    );
    const asset = artifact.role === "projection-analysis-cog" ? stac.assets?.analysis : stac.assets?.visual;
    if (
      stac.properties?.["searise:scenario"] !== scenario ||
      stac.properties?.["searise:horizon"] !== horizon ||
      asset?.["searise:artifact_id"] !== artifact.artifactId ||
      asset?.["file:size"] !== artifact.byteSize ||
      asset?.["checksum:multihash"] !== `1220${artifact.sha256}`
    ) {
      throw new Error(`Candidate STAC identity disagrees with ${artifact.path}`);
    }
    result.scientificUse =
      artifact.role === "projection-analysis-cog" ? "exact-lookup" : "visual-only";
    result.spatialBounds = stac.bbox;
    result.projectionContext = {
      scenario,
      horizon,
      source: {
        sourceRelease: stac.properties["searise:source_release"],
        archiveSha256: stac.properties["searise:source_archive_sha256"],
        memberSha256: stac.properties["searise:source_member_sha256"],
        methodologyVersion: stac.properties["searise:method_version"],
      },
      grid: {
        crs: "EPSG:4326",
        bounds: stac.bbox,
        transform: [1, 0, -30.5, 0, -1, 75.5],
        width: 76,
        height: 46,
        nativeResolutionDegrees: 1,
        nodata: -32768,
      },
      values: {
        storedUnits: stac.properties["searise:stored_units"],
        scaleToMetres: stac.properties["searise:scale_to_metres"],
        baseline: stac.properties["searise:baseline"],
        quantiles: stac.properties["searise:quantiles"],
      },
    };
  } else if (artifact.role === "projection-geoparquet") {
    if (template?.sha256 !== artifact.sha256 || template.byteSize !== artifact.byteSize) {
      throw new Error(`No byte-identical reviewed browser metadata for ${artifact.path}`);
    }
    result.scientificUse = template.scientificUse;
    result.spatialBounds = template.spatialBounds;
    if (template.projectionContext) result.projectionContext = template.projectionContext;
    if (template.projectionMatrixContext) {
      result.projectionMatrixContext = template.projectionMatrixContext;
    }
  }
  return result;
}

function overlayArtifact({ id, path, role, mediaType, scientificUse, bytes, releaseId, lineage, rights }) {
  return {
    $schema: ARTIFACT_SCHEMA,
    schemaVersion: "2.0.0",
    dataReleaseId: releaseId,
    dataProvenanceClass: "real-source",
    immutable: true,
    lineage: [lineage],
    artifactId: id,
    path,
    role,
    mediaType,
    scientificUse,
    byteSize: bytes.length,
    sha256: sha256(bytes),
    spatialBounds: null,
    rights,
  };
}

function parsePort(value) {
  const port = Number(value ?? "4173");
  if (!Number.isSafeInteger(port) || port < 1024 || port > 65_535) {
    throw new Error("SEARISE_LOCAL_PORT must be an unprivileged TCP port");
  }
  return port;
}

function rangeFor(header, size) {
  if (header == null) return null;
  if (typeof header !== "string" || header.includes(",")) return false;
  const match = /^bytes=(0|[1-9]\d*)-(0|[1-9]\d*)?$/.exec(header);
  if (!match) return false;
  const start = Number(match[1]);
  const end = match[2] === undefined ? size - 1 : Number(match[2]);
  if (!Number.isSafeInteger(start) || !Number.isSafeInteger(end) || start > end || end >= size) {
    return false;
  }
  return { start, end };
}

export function verifiedPinnedBytes(record) {
  const info = lstatSync(record.path);
  if (info.isSymbolicLink() || !info.isFile() || info.size !== record.byteSize) {
    throw new Error("Allowlisted artifact identity changed");
  }
  if (realpathSync(record.path) !== record.realpath) {
    throw new Error("Allowlisted artifact target changed");
  }
  const descriptor = openSync(record.path, constants.O_RDONLY | constants.O_NOFOLLOW);
  try {
    const opened = fstatSync(descriptor);
    if (opened.size !== record.byteSize || opened.dev !== record.dev || opened.ino !== record.ino) {
      throw new Error("Allowlisted artifact changed while opening");
    }
    const bytes = readFileSync(descriptor);
    if (bytes.length !== record.byteSize || sha256(bytes) !== record.sha256) {
      throw new Error("Allowlisted artifact content changed");
    }
    return bytes;
  } finally {
    closeSync(descriptor);
  }
}

export function allowlistedRecord(path, identity, source) {
  const info = statSync(path);
  if (!info.isFile() || info.size !== identity.byteSize || fileSha256(path) !== identity.sha256) {
    throw new Error(`Allowlisted bytes differ: ${identity.path}`);
  }
  return Object.freeze({
    source,
    path,
    realpath: realpathSync(path),
    byteSize: info.size,
    sha256: identity.sha256,
    dev: info.dev,
    ino: info.ino,
    mediaType: mediaTypes[extname(path)] ?? identity.mediaType ?? "application/octet-stream",
  });
}

export function overlayIdentity(path) {
  const descriptor = openSync(path, constants.O_RDONLY | (constants.O_DIRECTORY ?? 0));
  try {
    const pathInfo = lstatSync(path);
    const descriptorInfo = fstatSync(descriptor);
    if (
      pathInfo.isSymbolicLink() ||
      !pathInfo.isDirectory() ||
      !descriptorInfo.isDirectory() ||
      pathInfo.dev !== descriptorInfo.dev ||
      pathInfo.ino !== descriptorInfo.ino
    ) {
      throw new Error("Private overlay identity changed while it was pinned");
    }
    return Object.freeze({
      path,
      realpath: realpathSync(path),
      dev: descriptorInfo.dev,
      ino: descriptorInfo.ino,
      descriptor,
      lifecycle: { closed: false },
    });
  } catch (error) {
    closeSync(descriptor);
    throw error;
  }
}

export function removePrivateOverlay(identity) {
  try {
    if (!existsSync(identity.path)) return;
    if (identity.lifecycle.closed) {
      throw new Error("Refusing to remove with a released private overlay identity");
    }
    const temporaryRoot = realpathSync(tmpdir());
    const info = lstatSync(identity.path);
    const pinnedInfo = fstatSync(identity.descriptor);
    if (
      info.isSymbolicLink() ||
      !info.isDirectory() ||
      !pinnedInfo.isDirectory() ||
      identity.path !== identity.realpath ||
      realpathSync(identity.path) !== identity.realpath ||
      pinnedInfo.dev !== identity.dev ||
      pinnedInfo.ino !== identity.ino ||
      info.dev !== pinnedInfo.dev ||
      info.ino !== pinnedInfo.ino ||
      !identity.path.startsWith(`${temporaryRoot}${sep}searise-private-binding-`)
    ) {
      throw new Error("Refusing to remove a replaced private overlay directory");
    }
    rmSync(identity.path, { recursive: true });
  } finally {
    if (!identity.lifecycle.closed) {
      closeSync(identity.descriptor);
      identity.lifecycle.closed = true;
    }
  }
}

export function createPrivateCandidateBinding(options) {
  const candidateRoot = explicitDirectory(options.candidateRoot, "Candidate root");
  const initialSourceGrid = readOnlyFileSnapshot(options.sourceGrid, "Source-grid input");
  const sourceGridPath = initialSourceGrid.path;
  const port = parsePort(options.port);
  const origin = `http://127.0.0.1:${port}`;
  const initialSnapshot = candidateSnapshot(candidateRoot);
  const snapshotByPath = new Map(initialSnapshot.records.map((record) => [record.path, record]));
  const candidateManifestPath = fileBeneath(candidateRoot, "manifest.json");
  const candidateManifest = JSON.parse(readFileSync(candidateManifestPath, "utf8"));
  const releaseId = candidateManifest.dataReleaseId;
  if (
    !RELEASE_ID.test(releaseId) ||
    candidateManifest.schemaVersion !== "2.0.0" ||
    candidateManifest.dataProvenanceClass !== "real-source" ||
    candidateManifest.publicationClaim !== false ||
    !Array.isArray(candidateManifest.artifacts)
  ) {
    throw new Error("Explicit candidate is not the expected private real-source v2 candidate");
  }
  for (const artifact of candidateManifest.artifacts) {
    const observed = snapshotByPath.get(safeRelativePath(artifact.path));
    if (
      !observed ||
      observed.byteSize !== artifact.byteSize ||
      observed.sha256 !== artifact.sha256 ||
      artifact.dataReleaseId !== releaseId ||
      artifact.dataProvenanceClass !== "real-source" ||
      artifact.immutable !== true ||
      !SHA256.test(artifact.sha256)
    ) {
      throw new Error(`Candidate manifest identity failed: ${artifact.path}`);
    }
  }
  const baseBuildArtifact = candidateManifest.artifacts.find(
    (artifact) => artifact.role === "build-receipt",
  );
  if (!baseBuildArtifact) throw new Error("Candidate has no base build receipt");
  const baseBuildReceipt = JSON.parse(
    readFileSync(fileBeneath(candidateRoot, baseBuildArtifact.path), "utf8"),
  );
  const adapterCodeRevision = execFileSync("git", ["rev-parse", "HEAD"], {
    cwd: repositoryRoot,
    encoding: "utf8",
  }).trim();
  if (!/^[a-f0-9]{40}$/.test(adapterCodeRevision)) {
    throw new Error("The local adapter Git revision is unavailable");
  }
  const adapterCreatedAt = new Date().toISOString();

  const sourceGridTemplate = fixtureManifest.artifacts.find(
    (artifact) => artifact.role === "source-grid-identity",
  );
  const sourceGridBytes = initialSourceGrid.bytes;
  const sourceGridInfo = statSync(sourceGridPath);
  const sourceGridHash = initialSourceGrid.sha256;
  if (
    sourceGridInfo.size !== sourceGridBytes.length ||
    sourceGridInfo.size !== sourceGridTemplate.byteSize ||
    sourceGridHash !== sourceGridTemplate.sha256
  ) {
    throw new Error("Explicit source-grid input differs from the reviewed AR6 identity");
  }

  const overlayRoot = mkdtempSync(join(realpathSync(tmpdir()), "searise-private-binding-"));
  let pinnedOverlay;
  try {
    chmodSync(overlayRoot, 0o700);
  pinnedOverlay = overlayIdentity(overlayRoot);
  const candidateManifestIdentity = snapshotByPath.get("manifest.json");
  const privateBinding = {
    adapter: { createdAt: adapterCreatedAt, codeRevision: adapterCodeRevision },
    baseCandidate: {
      candidateId: candidateManifest.candidateId,
      dataReleaseId: releaseId,
      manifestSha256: candidateManifestIdentity.sha256,
      snapshotSha256: initialSnapshot.digest,
      createdAt: baseBuildReceipt.completedAt,
      codeRevision: baseBuildReceipt.codeRevision,
    },
    sourceGrid: { byteSize: sourceGridInfo.size, sha256: sourceGridHash },
  };
  const bindingDocument = {
    schemaVersion: "1.0.0",
    privateEngineeringOnly: true,
    verified: false,
    publicPromotionAuthorized: false,
    signatureAvailable: false,
    binding: privateBinding,
    nonclaims: [
      "No public signature is created or claimed.",
      "No publication, upload, promotion, or scientific approval is performed.",
      "The v2 overlay is ephemeral local metadata and is not a release candidate.",
    ],
  };
  const bindingBytes = compactJson(bindingDocument);
  const bindingPath = writePrivateFile(
    overlayRoot,
    "local-binding/private-binding.json",
    bindingBytes,
  );
  const lineage = {
    path: "local-binding/private-binding.json",
    sha256: sha256(bindingBytes),
  };
  const ipccRights = {
    attributionIds: ["ipcc-ar6-sl-projections-20210809"],
    redistribution: "allowed",
  };
  const localRights = {
    attributionIds: ["searise-europe-candidate-completeness-v1"],
    redistribution: "allowed",
  };

  const cogArtifacts = candidateManifest.artifacts.filter(
    (artifact) => artifact.role === "projection-analysis-cog",
  );
  const rangeDocument = {
    algorithm: "sha256",
    artifacts: cogArtifacts.map((artifact) => {
      const path = fileBeneath(candidateRoot, artifact.path);
      const body = readFileSync(path);
      const chunks = [];
      for (let start = 0; start < body.length; start += CHUNK_SIZE) {
        const endExclusive = Math.min(start + CHUNK_SIZE, body.length);
        chunks.push({ start, endExclusive, sha256: sha256(body.subarray(start, endExclusive)) });
      }
      return {
        artifactId: artifact.artifactId,
        byteSize: artifact.byteSize,
        chunks,
        path: artifact.path,
        sha256: artifact.sha256,
      };
    }),
    chunkSize: CHUNK_SIZE,
    dataReleaseId: releaseId,
    schemaVersion: 1,
  };
  const rangeBytes = compactJson(rangeDocument);
  const rangePath = writePrivateFile(
    overlayRoot,
    "analysis/cog-range-integrity.json",
    rangeBytes,
  );
  const sbomBytes = compactJson({
    bomFormat: "CycloneDX",
    specVersion: "1.6",
    version: 1,
    metadata: {
      component: {
        type: "data",
        name: "SeaRise private local browser binding metadata",
        version: releaseId,
        properties: [
          { name: "org.searise.privateEngineeringOnly", value: "true" },
          { name: "org.searise.verified", value: "false" },
        ],
      },
    },
    components: [
      {
        type: "data",
        name: "candidate-manifest",
        version: candidateManifest.candidateId,
        hashes: [{ alg: "SHA-256", content: candidateManifestIdentity.sha256 }],
      },
      {
        type: "data",
        name: "source-grid-identity",
        version: "20210809",
        hashes: [{ alg: "SHA-256", content: sourceGridHash }],
      },
    ],
  });
  const sbomPath = writePrivateFile(overlayRoot, "sbom/private-binding.cdx.json", sbomBytes);
  const derivationMaterials = [
    ...initialSnapshot.records.map((record) => ({
      path: `candidate/${record.path}`,
      sha256: record.sha256,
    })),
    { path: "source-grid/source-grid.json.gz", sha256: sourceGridHash },
  ].sort((left, right) => left.path.localeCompare(right.path));
  const derivedOutputs = [
    { path: "analysis/cog-range-integrity.json", sha256: sha256(rangeBytes) },
    { path: "local-binding/private-binding.json", sha256: sha256(bindingBytes) },
    { path: "sbom/private-binding.cdx.json", sha256: sha256(sbomBytes) },
  ].sort((left, right) => left.path.localeCompare(right.path));
  const derivationNonClaims = [
    "No build run, workflow, platform, timestamp, or code revision is asserted for this deterministic browser derivation.",
    "This receipt is not the authoritative build receipt for the private Phase 1 candidate.",
    "This private real-source binding is not approved public-release evidence.",
  ];
  const derivationReceiptBytes = compactJson({
    $schema: BROWSER_DERIVATION_RECEIPT_SCHEMA,
    schemaVersion: "2.0.0",
    receiptType: "browser-overlay-derivation",
    dataReleaseId: releaseId,
    dataProvenanceClass: "real-source",
    executionIdentity: "not-recorded",
    materials: derivationMaterials,
    outputs: derivedOutputs,
    nonClaims: derivationNonClaims,
  });
  const derivationReceiptPath = writePrivateFile(
    overlayRoot,
    "receipts/browser-derivation.json",
    derivationReceiptBytes,
  );
  const derivationReceiptIdentity = {
    path: "receipts/browser-derivation.json",
    sha256: sha256(derivationReceiptBytes),
  };
  const derivationProvenanceBytes = compactJson({
    $schema: BROWSER_DERIVATION_PROVENANCE_SCHEMA,
    schemaVersion: "2.0.0",
    _type: "https://in-toto.io/Statement/v1",
    subject: [
      ...derivedOutputs.map(({ path: name, sha256: digest }) => ({
        name,
        digest: { sha256: digest },
      })),
      {
        name: derivationReceiptIdentity.path,
        digest: { sha256: derivationReceiptIdentity.sha256 },
      },
    ].sort((left, right) => left.name.localeCompare(right.name)),
    predicateType:
      "https://artemsemdev.github.io/SeaRise-Europe/contracts/release/v2/browser-derivation-predicate/v1",
    predicate: {
      derivationType: "deterministic-browser-overlay",
      executionIdentity: "not-recorded",
      materials: derivationMaterials,
      receipt: derivationReceiptIdentity,
      nonClaims: derivationNonClaims,
    },
  });
  const derivationProvenancePath = writePrivateFile(
    overlayRoot,
    "browser-derivation.intoto.json",
    derivationProvenanceBytes,
  );
  const artifacts = candidateManifest.artifacts
    .filter((artifact) => artifact.role !== "checksums")
    .map((artifact) =>
      enrichCandidateArtifact(
        artifact,
        releaseId,
        lineage,
        candidateManifest.artifacts,
        candidateRoot,
      ),
    );
  artifacts.push(
    overlayArtifact({
      id: "source-grid-identity",
      path: "analysis/source-grid.json.gz",
      role: "source-grid-identity",
      mediaType: "application/gzip",
      scientificUse: "exact-lookup-support",
      bytes: sourceGridBytes,
      releaseId,
      lineage,
      rights: ipccRights,
    }),
    overlayArtifact({
      id: "cog-range-integrity",
      path: "analysis/cog-range-integrity.json",
      role: "range-integrity-index",
      mediaType: "application/json",
      scientificUse: "exact-lookup-support",
      bytes: rangeBytes,
      releaseId,
      lineage,
      rights: ipccRights,
    }),
    overlayArtifact({
      id: "private-binding-sbom",
      path: "sbom/private-binding.cdx.json",
      role: "sbom",
      mediaType: "application/json",
      scientificUse: "not-applicable",
      bytes: sbomBytes,
      releaseId,
      lineage,
      rights: localRights,
    }),
    overlayArtifact({
      id: "browser-derivation-receipt",
      path: "receipts/browser-derivation.json",
      role: "browser-derivation-receipt",
      mediaType: "application/json",
      scientificUse: "not-applicable",
      bytes: derivationReceiptBytes,
      releaseId,
      lineage: { path: "local-binding/private-binding.json", sha256: sha256(bindingBytes) },
      rights: localRights,
    }),
    overlayArtifact({
      id: "browser-derivation-provenance",
      path: "browser-derivation.intoto.json",
      role: "browser-derivation-provenance",
      mediaType: "application/vnd.in-toto+json",
      scientificUse: "not-applicable",
      bytes: derivationProvenanceBytes,
      releaseId,
      lineage: derivationReceiptIdentity,
      rights: localRights,
    }),
  );
  artifacts.sort((left, right) => left.path.localeCompare(right.path));
  const checksumsBytes = Buffer.from(
    `${artifacts.map((artifact) => `${artifact.sha256}  ${artifact.path}`).join("\n")}\n`,
    "utf8",
  );
  const checksumsPath = writePrivateFile(overlayRoot, "checksums.txt", checksumsBytes);
  artifacts.push(
    overlayArtifact({
      id: "private-binding-checksums",
      path: "checksums.txt",
      role: "checksums",
      mediaType: "text/plain",
      scientificUse: "not-applicable",
      bytes: checksumsBytes,
      releaseId,
      lineage,
      rights: localRights,
    }),
  );
  artifacts.sort((left, right) => left.path.localeCompare(right.path));

  const artifactByRole = (role) => artifacts.find((artifact) => artifact.role === role);
  const artifactByPath = (path) => artifacts.find((artifact) => artifact.path === path);
  const ipccReceipt = JSON.parse(
    readFileSync(fileBeneath(candidateRoot, "receipts/sources/ipcc-ar6.json"), "utf8"),
  );
  const datasets = SCENARIOS.flatMap((scenario) =>
    HORIZONS.map((horizon) => ({
      scenario,
      horizon,
      analysisArtifactId: artifactByPath(`analysis/${scenario}/${horizon}.tif`).artifactId,
      analyticalArtifactId: artifactByRole("projection-geoparquet").artifactId,
      visualArtifactId: artifactByPath(`layers/${scenario}/${horizon}.pmtiles`).artifactId,
      stacItemArtifactId: artifactByPath(`stac/items/${scenario}-${horizon}.json`).artifactId,
    })),
  );
  const sourceReceipts = artifacts
    .filter((artifact) => artifact.role === "source-receipt")
    .map((artifact) => artifact.artifactId);
  const stacItems = artifacts
    .filter((artifact) => artifact.role === "stac-item")
    .sort((left, right) => left.path.localeCompare(right.path))
    .map((artifact) => artifact.artifactId);
  const releaseManifest = {
    $schema: PRIVATE_RELEASE_SCHEMA,
    schemaVersion: "2.0.0",
    dataReleaseId: releaseId,
    dataProvenanceClass: "real-source",
    baseReleaseIdentity: {
      identityScope: "private-phase-1-candidate",
      schemaVersion: "2.0.0",
      manifestSha256: candidateManifestIdentity.sha256,
      createdAt: baseBuildReceipt.completedAt,
      codeRevision: baseBuildReceipt.codeRevision,
    },
    browserDerivationIdentity: {
      identityScope: "browser-overlay-derivation",
      executionIdentity: "not-recorded",
      receiptArtifactId: "browser-derivation-receipt",
      provenanceArtifactId: "browser-derivation-provenance",
    },
    previousReleaseId: null,
    methodologyVersion: "ar6-regional-projection-v1",
    defaults: { scenario: "ssp2-45", horizon: 2050 },
    publication: {
      appendOnly: true,
      cacheControl: "private, no-store",
      releasePath: `releases/${releaseId}`,
    },
    releaseAuthority: {
      automatedValidation: "pending",
      releaseDisposition: "pending-owner",
      dataProvenanceClass: "real-source",
      statusDisclosureRequired: true,
    },
    sources: [
      {
        sourceId: ipccReceipt.sourceId,
        sourceRelease: ipccReceipt.sourceVersion,
        archiveSha256: ipccReceipt.sha256,
        attributionId: ipccReceipt.attributionId,
        receiptArtifactId: artifactByPath("receipts/sources/ipcc-ar6.json").artifactId,
      },
    ],
    contractArtifacts: {
      scenarioConfig: artifactByRole("scenario-config").artifactId,
      methodology: artifactByRole("methodology").artifactId,
      attribution: artifactByRole("source-attribution").artifactId,
      sourceReceipts,
      baseReleaseBuildReceipt: artifactByRole("base-release-build-receipt").artifactId,
      browserDerivationReceipt: "browser-derivation-receipt",
      sourceGridIdentity: "source-grid-identity",
      rangeIntegrityIndex: "cog-range-integrity",
      sbom: "private-binding-sbom",
      searchRecords: artifactByPath("search/europe-core.codepoint-trie.json.br").artifactId,
      qualitySummary: artifactByRole("quality-summary").artifactId,
      architectureEvidence: artifactByRole("architecture-evidence").artifactId,
      stacCatalog: artifactByRole("stac-catalog").artifactId,
      stacCollection: artifactByRole("stac-collection").artifactId,
      stacItems,
      checksums: "private-binding-checksums",
      baseReleaseProvenance: null,
      browserDerivationProvenance: "browser-derivation-provenance",
      baseReleaseSignature: null,
    },
    datasets,
    artifacts,
  };
  const manifest = {
    $schema: PRIVATE_MANIFEST_SCHEMA,
    schemaVersion: "1.0.0",
    dataReleaseId: releaseId,
    privateEngineeringOnly: true,
    verified: false,
    publicPromotionAuthorized: false,
    binding: privateBinding,
    releaseManifest,
  };
  const manifestBytes = compactJson(manifest);
  const manifestPath = writePrivateFile(overlayRoot, "manifest.json", manifestBytes);

  const allowlist = new Map();
  for (const artifact of artifacts) {
    let path;
    let source;
    if (artifact.path === "analysis/source-grid.json.gz") {
      path = sourceGridPath;
      source = "explicit-source-grid";
    } else if (
      [
        "analysis/cog-range-integrity.json",
        "browser-derivation.intoto.json",
        "receipts/browser-derivation.json",
        "sbom/private-binding.cdx.json",
        "checksums.txt",
      ].includes(artifact.path)
    ) {
      path = resolve(overlayRoot, artifact.path);
      source = "private-overlay";
    } else {
      path = fileBeneath(candidateRoot, artifact.path);
      source = "candidate-in-place";
    }
    allowlist.set(artifact.path, allowlistedRecord(path, artifact, source));
  }
  allowlist.set(
    "manifest.json",
    allowlistedRecord(
      manifestPath,
      { path: "manifest.json", byteSize: manifestBytes.length, sha256: sha256(manifestBytes) },
      "private-overlay",
    ),
  );
  allowlist.set(
    "local-binding/private-binding.json",
    allowlistedRecord(
      bindingPath,
      {
        path: "local-binding/private-binding.json",
        byteSize: bindingBytes.length,
        sha256: sha256(bindingBytes),
      },
      "private-overlay",
    ),
  );

  const overlayFiles = [
    bindingPath,
    derivationProvenancePath,
    derivationReceiptPath,
    rangePath,
    sbomPath,
    checksumsPath,
    manifestPath,
  ];
  const overlayDirectories = [];
  function collectOverlayDirectories(directory) {
    overlayDirectories.push(directory);
    for (const entry of readdirSync(directory, { withFileTypes: true })) {
      if (entry.isDirectory()) collectOverlayDirectories(join(directory, entry.name));
    }
  }
  collectOverlayDirectories(overlayRoot);
  if (overlayDirectories.some((path) => (lstatSync(path).mode & 0o777) !== 0o700)) {
    throw new Error("Overlay directory mode is not 0700");
  }
  if (overlayFiles.some((path) => (lstatSync(path).mode & 0o777) !== 0o600)) {
    throw new Error("Overlay file mode is not 0600");
  }

  return Object.freeze({
    candidateRoot,
    releaseId,
    origin,
    port,
    overlayRoot,
    manifest,
    allowlist,
    initialSnapshot,
    initialSourceGrid,
    snapshot() {
      return Object.freeze({
        candidate: candidateSnapshot(candidateRoot),
        sourceGrid: readOnlyFileSnapshot(sourceGridPath, "Source-grid input"),
      });
    },
    cleanup() {
      removePrivateOverlay(pinnedOverlay);
    },
  });
  } catch (error) {
    if (pinnedOverlay) removePrivateOverlay(pinnedOverlay);
    throw error;
  }
}

function responseHeaders(binding, record) {
  return {
    "Accept-Ranges": "bytes",
    "Access-Control-Allow-Origin": binding.origin,
    "Access-Control-Allow-Methods": "GET, HEAD",
    "Access-Control-Expose-Headers":
      "Accept-Ranges, Content-Length, Content-Range, ETag, X-SeaRise-Private-Binding",
    "Cache-Control": "private, no-store",
    "Content-Type": record.mediaType,
    ETag: `"sha256-${record.sha256}"`,
    "X-Content-Type-Options": "nosniff",
    "X-SeaRise-Private-Binding": "true",
    Vary: "Origin",
  };
}

function sendStatus(binding, request, response) {
  if (!["GET", "HEAD"].includes(request.method ?? "")) {
    response.writeHead(405, { Allow: "GET, HEAD" }).end();
    return;
  }
  let current;
  try {
    current = binding.snapshot();
  } catch {
    const body = compactJson({
      schemaVersion: "1.0.0",
      privateEngineeringOnly: true,
      verified: false,
      candidateSnapshot: { unchanged: false },
      sourceGridSnapshot: { unchanged: false },
    });
    response.writeHead(409, {
      "Cache-Control": "no-store",
      "Content-Length": String(body.length),
      "Content-Type": "application/json",
    });
    response.end(request.method === "HEAD" ? undefined : body);
    return;
  }
  const body = compactJson({
    schemaVersion: "1.0.0",
    privateEngineeringOnly: true,
    verified: false,
    publicPromotionAuthorized: false,
    signatureAvailable: false,
    dataReleaseId: binding.releaseId,
    candidateSnapshot: {
      initialSha256: binding.initialSnapshot.digest,
      currentSha256: current.candidate.digest,
      unchanged: current.candidate.digest === binding.initialSnapshot.digest,
    },
    sourceGridSnapshot: {
      initialSha256: binding.initialSourceGrid.sha256,
      currentSha256: current.sourceGrid.sha256,
      unchanged:
        current.sourceGrid.sha256 === binding.initialSourceGrid.sha256 &&
        current.sourceGrid.dev === binding.initialSourceGrid.dev &&
        current.sourceGrid.ino === binding.initialSourceGrid.ino,
    },
    overlayPermissions: { directory: "0700", files: "0600" },
  });
  response.writeHead(200, {
    "Access-Control-Allow-Origin": binding.origin,
    "Cache-Control": "no-store",
    "Content-Length": String(body.length),
    "Content-Type": "application/json",
    "X-Content-Type-Options": "nosniff",
  });
  response.end(request.method === "HEAD" ? undefined : body);
}

export function handlePrivateRelease(binding, request, response) {
  const url = new URL(request.url ?? "/", binding.origin);
  const isPrivatePath =
    url.pathname === "/__local-binding/status" ||
    url.pathname.startsWith(`/releases/${binding.releaseId}/`);
  if (!isPrivatePath) return false;
  if (
    request.headers.host !== new URL(binding.origin).host ||
    (request.headers.origin && request.headers.origin !== binding.origin)
  ) {
    response.writeHead(403).end();
    return true;
  }
  if (url.pathname === "/__local-binding/status") {
    sendStatus(binding, request, response);
    return true;
  }
  const prefix = `/releases/${binding.releaseId}/`;
  if (!["GET", "HEAD"].includes(request.method ?? "")) {
    response.writeHead(405, { Allow: "GET, HEAD" }).end();
    return true;
  }
  if (url.search || url.hash) {
    response.writeHead(403).end();
    return true;
  }
  let logicalPath;
  try {
    logicalPath = safeRelativePath(decodeURIComponent(url.pathname.slice(prefix.length)));
  } catch {
    response.writeHead(400).end();
    return true;
  }
  const record = binding.allowlist.get(logicalPath);
  if (!record) {
    response.writeHead(404).end();
    return true;
  }
  const headers = responseHeaders(binding, record);
  const range = rangeFor(request.headers.range, record.byteSize);
  if (range === false) {
    response.writeHead(416, { ...headers, "Content-Range": `bytes */${record.byteSize}` }).end();
    return true;
  }
  let bytes;
  try {
    bytes = verifiedPinnedBytes(record);
  } catch {
    response.writeHead(409, headers).end();
    return true;
  }
  const start = range?.start ?? 0;
  const end = range?.end ?? record.byteSize - 1;
  response.writeHead(range ? 206 : 200, {
    ...headers,
    "Content-Length": String(end - start + 1),
    ...(range ? { "Content-Range": `bytes ${start}-${end}/${record.byteSize}` } : {}),
  });
  if (request.method === "HEAD") {
    response.end();
  } else {
    response.end(bytes.subarray(start, end + 1));
  }
  return true;
}

export function forbiddenLocalFilesystemRequest(binding, requestUrl) {
  const representations = [];
  let current = String(requestUrl ?? "/").split(/[?#]/, 1)[0].replaceAll("\\", "/");
  for (let depth = 0; depth < 4; depth += 1) {
    representations.push(current);
    try {
      const decoded = decodeURIComponent(current).replaceAll("\\", "/");
      if (decoded === current) break;
      current = decoded;
    } catch {
      return true;
    }
  }
  const localTargets = [binding.candidateRoot, binding.initialSourceGrid.path].map((path) =>
    path.replaceAll("\\", "/"),
  );
  return representations.some((value) => {
    const segments = value.toLowerCase().split("/");
    return (
      segments.includes("@fs") ||
      segments.includes("..") ||
      localTargets.some((target) => value.includes(target))
    );
  });
}

export async function servePrivateCandidate(options) {
  const binding = createPrivateCandidateBinding(options);
  const buildIdentity = privateCandidateBuildIdentity(binding.releaseId);
  const webRoot = resolve(repositoryRoot, "src/web");
  const appRoot = resolve(binding.overlayRoot, "app");
  let server;
  try {
    const [{ build }, { default: react }] = await Promise.all([
      import("vite"),
      import("@vitejs/plugin-react"),
    ]);
    await build({
      configFile: false,
      root: webRoot,
      plugins: [react()],
      define: {
        __SEARISE_BUILD_IDENTITY_JSON__: JSON.stringify(JSON.stringify(buildIdentity)),
      },
      build: {
        emptyOutDir: true,
        outDir: appRoot,
        sourcemap: false,
        target: "es2022",
      },
    });
    const appAllowlist = new Map();
    function sealAppDirectory(directory) {
      chmodSync(directory, 0o700);
      for (const entry of readdirSync(directory, { withFileTypes: true })) {
        const path = join(directory, entry.name);
        if (entry.isSymbolicLink()) throw new Error("Ephemeral app bundle contains a symlink");
        if (entry.isDirectory()) {
          sealAppDirectory(path);
          continue;
        }
        if (!entry.isFile()) throw new Error("Ephemeral app bundle contains a non-file entry");
        chmodSync(path, 0o600);
        const logicalPath = relative(appRoot, path).split(sep).join("/");
        const bytes = readFileSync(path);
        appAllowlist.set(
          logicalPath,
          allowlistedRecord(
            path,
            { path: logicalPath, byteSize: bytes.length, sha256: sha256(bytes) },
            "ephemeral-private-app",
          ),
        );
      }
    }
    sealAppDirectory(appRoot);
    server = createHttpServer((request, response) => {
      if (forbiddenLocalFilesystemRequest(binding, request.url)) {
        response.writeHead(404, { "Cache-Control": "no-store" }).end();
        return;
      }
      if (handlePrivateRelease(binding, request, response)) return;
      if (!request.method || !["GET", "HEAD"].includes(request.method)) {
        response.writeHead(405, { Allow: "GET, HEAD" }).end();
        return;
      }
      const url = new URL(request.url ?? "/", binding.origin);
      let logicalPath;
      try {
        logicalPath = url.pathname === "/" ? "index.html" : safeRelativePath(
          decodeURIComponent(url.pathname.slice(1)),
        );
      } catch {
        response.writeHead(400).end();
        return;
      }
      const record = appAllowlist.get(logicalPath);
      if (!record || url.search || url.hash) {
        response.writeHead(404, { "Cache-Control": "no-store" }).end();
        return;
      }
      let bytes;
      try {
        bytes = verifiedPinnedBytes(record);
      } catch {
        response.writeHead(409, { "Cache-Control": "no-store" }).end();
        return;
      }
      response.writeHead(200, {
        "Cache-Control": "private, no-store",
        "Content-Length": String(bytes.length),
        "Content-Type": mediaTypes[extname(logicalPath)] ?? "application/octet-stream",
        ETag: `"sha256-${record.sha256}"`,
        "X-Content-Type-Options": "nosniff",
      });
      response.end(request.method === "HEAD" ? undefined : bytes);
    });
    await new Promise((resolveListen, reject) => {
      server.once("error", reject);
      server.listen(binding.port, "127.0.0.1", resolveListen);
    });
  } catch (error) {
    if (server?.listening) server.close();
    binding.cleanup();
    throw error;
  }
  return {
    binding,
    server,
    async close() {
      await new Promise((resolveClose, reject) =>
        server.close((error) => (error ? reject(error) : resolveClose())),
      );
      binding.cleanup();
    },
  };
}
