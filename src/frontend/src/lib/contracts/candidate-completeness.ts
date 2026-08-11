export interface CandidateArtifact {
  artifactId: string;
  path: string;
  role: string;
  mediaType: string;
  contentEncoding: string;
  dataReleaseId: string;
  immutable: boolean;
  byteSize: number;
  observedByteSize: number;
  sha256: string;
  observedSha256: string;
  writeSequence: number;
  rights: { attributionIds: string[]; redistribution: string };
}

interface ProjectionGrid {
  crs: string;
  bounds: number[];
  transform: number[];
  width: number;
  height: number;
  nativeResolutionDegrees: number;
  nodata: number;
}

interface StacItem {
  path: string;
  dataReleaseId: string;
  scenario: string;
  horizon: number;
  analysisHref: string;
  visualHref: string;
  tableHref: string;
}

interface ParityEvidence {
  rowColumnSha256: string;
  storedClassSha256: string;
  nodataSha256: string;
  finalStateSha256: string;
}

export interface CandidateDocument {
  contractId: string;
  candidateId: string;
  dataReleaseId: string;
  publicationClaim: boolean;
  manifest: { path: string; artifactCount: number; writeSequence: number };
  attributionRegistry: string[];
  geometryPolicy: {
    status: string;
    purpose: string;
    canonical: boolean;
    production: boolean;
    publicationEligible: boolean;
    hazardExtentClaim: boolean;
  };
  projectionGrid: ProjectionGrid;
  artifacts: CandidateArtifact[];
  checksumInventory: {
    path: string;
    algorithm: string;
    subjects: Array<{ path: string; sha256: string }>;
  };
  gateReportSemantics: {
    candidateState: string;
    validatedScope: string;
    validatedArtifactCount: number;
    excludedPaths: string[];
    manifestHashReferenced: boolean;
  };
  stac: {
    catalog: { path: string; collectionHref: string };
    collection: { path: string; itemHrefs: string[] };
    items: StacItem[];
  };
  parity: {
    status: string;
    python: ParityEvidence;
    typescript: ParityEvidence;
  };
}

interface RequiredArtifact {
  artifactId: string;
  path: string;
  role: string;
  mediaType: string;
  contentEncoding: string;
  attributionId: string;
}

export interface RequiredArtifactContract {
  contractId: string;
  artifactCount: number;
  scenarios: string[];
  horizons: number[];
  attributionRegistry: string[];
  forbiddenDeferredRoles: string[];
  projectionGrid: ProjectionGrid;
  requiredArtifacts: RequiredArtifact[];
}

export interface CandidateCompletenessSummary {
  artifactCount: number;
  datasetCount: number;
  manifestWrittenLast: true;
}

export class CandidateCompletenessError extends TypeError {
  constructor(public readonly code: string, message: string) {
    super(message);
    this.name = "CandidateCompletenessError";
  }
}

function fail(code: string, message: string): never {
  throw new CandidateCompletenessError(code, message);
}

function canonicalJson(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(",")}]`;
  if (value !== null && typeof value === "object") {
    const record = value as Record<string, unknown>;
    return `{${Object.keys(record)
      .sort()
      .map((key) => `${JSON.stringify(key)}:${canonicalJson(record[key])}`)
      .join(",")}}`;
  }
  return JSON.stringify(value);
}

function safePath(value: string): boolean {
  return (
    value.length > 0 &&
    !value.startsWith("/") &&
    !value.includes("\\") &&
    !value.includes("//") &&
    value.split("/").every((part) => part !== "" && part !== "." && part !== "..")
  );
}

function resolveHref(sourcePath: string, href: string): string {
  if (
    !href ||
    href.startsWith("/") ||
    href.includes("\\") ||
    href.split("/", 1)[0].includes(":") ||
    href.split("/").some((part) => part === "" || part === ".")
  ) {
    return fail("unsafe-reference", `unsafe STAC href: ${href}`);
  }
  const parts = sourcePath.split("/").slice(0, -1);
  for (const part of href.split("/")) {
    if (part === "..") {
      if (parts.length === 0) {
        return fail("unsafe-reference", `STAC href escapes the release: ${href}`);
      }
      parts.pop();
    } else {
      parts.push(part);
    }
  }
  if (parts.includes("releases")) {
    return fail("unsafe-reference", `STAC href crosses a release: ${href}`);
  }
  return parts.join("/");
}

function validateGeometryPolicy(candidate: CandidateDocument): void {
  const expected = {
    status: "selected-scope-approximation",
    purpose: "product-eligibility-only",
    canonical: false,
    production: false,
    publicationEligible: false,
    hazardExtentClaim: false,
  };
  if (
    canonicalJson(candidate.geometryPolicy) !== canonicalJson(expected) ||
    candidate.publicationClaim !== false
  ) {
    fail("geometry-policy", "non-canonical geometry cannot carry a publication claim");
  }
}

function validateArtifacts(
  candidate: CandidateDocument,
  contract: RequiredArtifactContract,
): CandidateArtifact[] {
  const artifacts = candidate.artifacts;
  const forbidden = new Set(contract.forbiddenDeferredRoles);
  if (artifacts.some((artifact) => forbidden.has(artifact.role))) {
    fail("premature-supply-chain", "signing, provenance, and SBOM belong to issue #53");
  }
  for (const artifact of artifacts) {
    if (!safePath(artifact.path)) {
      fail("unsafe-reference", `unsafe artifact path: ${artifact.path}`);
    }
    if (artifact.dataReleaseId !== candidate.dataReleaseId) {
      fail("cross-release-reference", "artifact release ID differs from candidate");
    }
    if (artifact.immutable !== true) {
      fail("artifact-immutable", `artifact is mutable: ${artifact.artifactId}`);
    }
    if (
      artifact.sha256 !== artifact.observedSha256 ||
      artifact.byteSize !== artifact.observedByteSize
    ) {
      fail("artifact-integrity", `artifact bytes differ: ${artifact.artifactId}`);
    }
  }

  const ids = artifacts.map((artifact) => artifact.artifactId);
  const paths = artifacts.map((artifact) => artifact.path);
  if (new Set(ids).size !== ids.length || new Set(paths).size !== paths.length) {
    fail("artifact-duplicate", "artifact IDs and paths must be unique");
  }

  const expectedById = new Map(
    contract.requiredArtifacts.map((artifact) => [artifact.artifactId, artifact]),
  );
  const actualById = new Map(
    artifacts.map((artifact) => [artifact.artifactId, artifact]),
  );
  const extra = ids.filter((id) => !expectedById.has(id));
  if (extra.length) fail("artifact-extra", `unexpected artifacts: ${extra.sort().join(", ")}`);
  const missing = Array.from(expectedById.keys()).filter((id) => !actualById.has(id));
  if (missing.length || artifacts.length !== contract.artifactCount) {
    fail("artifact-inventory", `missing artifacts: ${missing.sort().join(", ")}`);
  }

  if (
    canonicalJson(candidate.attributionRegistry) !==
    canonicalJson(contract.attributionRegistry)
  ) {
    fail("artifact-rights", "attribution registry differs from the exact contract");
  }
  const registry = new Set(candidate.attributionRegistry);
  for (const [artifactId, expected] of Array.from(expectedById.entries())) {
    const actual = actualById.get(artifactId) as CandidateArtifact;
    if (
      actual.path !== expected.path ||
      actual.role !== expected.role ||
      actual.mediaType !== expected.mediaType ||
      actual.contentEncoding !== expected.contentEncoding
    ) {
      fail("artifact-inventory", `artifact contract differs: ${artifactId}`);
    }
    if (
      canonicalJson(actual.rights.attributionIds) !==
        canonicalJson([expected.attributionId]) ||
      actual.rights.attributionIds.some((id) => !registry.has(id)) ||
      actual.rights.redistribution !== "allowed"
    ) {
      fail("artifact-rights", `artifact rights are incomplete: ${artifactId}`);
    }
  }
  return artifacts;
}

function validateStac(
  candidate: CandidateDocument,
  contract: RequiredArtifactContract,
): number {
  const { catalog, collection, items } = candidate.stac;
  if (
    catalog.path !== "stac/catalog.json" ||
    resolveHref(catalog.path, catalog.collectionHref) !== "stac/collection.json"
  ) {
    fail("stac-reference", "STAC catalog does not resolve to its collection");
  }

  const expectedPairs = contract.scenarios.flatMap((scenario) =>
    contract.horizons.map((horizon) => ({ scenario, horizon })),
  );
  const expectedPaths = new Set(
    expectedPairs.map(({ scenario, horizon }) => `stac/items/${scenario}-${horizon}.json`),
  );
  const resolvedItems = collection.itemHrefs.map((href) =>
    resolveHref(collection.path, href),
  );
  if (
    collection.path !== "stac/collection.json" ||
    new Set(resolvedItems).size !== resolvedItems.length ||
    resolvedItems.some((path) => !expectedPaths.has(path)) ||
    resolvedItems.length !== expectedPaths.size
  ) {
    fail("stac-reference", "STAC collection item links differ from the 3 x 3 matrix");
  }

  const expectedPairKeys = new Set(
    expectedPairs.map(({ scenario, horizon }) => `${scenario}:${horizon}`),
  );
  const actualPairKeys = items.map((item) => `${item.scenario}:${item.horizon}`);
  if (
    items.length !== expectedPairKeys.size ||
    new Set(actualPairKeys).size !== actualPairKeys.length ||
    actualPairKeys.some((pair) => !expectedPairKeys.has(pair))
  ) {
    fail("stac-reference", "STAC item matrix is incomplete or duplicated");
  }
  for (const item of items) {
    if (item.dataReleaseId !== candidate.dataReleaseId) {
      fail("cross-release-reference", "STAC item release ID differs from candidate");
    }
    const itemPath = `stac/items/${item.scenario}-${item.horizon}.json`;
    const targets: Array<[keyof Pick<StacItem, "analysisHref" | "visualHref" | "tableHref">, string]> = [
      ["analysisHref", `analysis/${item.scenario}/${item.horizon}.tif`],
      ["visualHref", `layers/${item.scenario}/${item.horizon}.pmtiles`],
      ["tableHref", "analysis/projections.parquet"],
    ];
    if (
      item.path !== itemPath ||
      targets.some(([field, target]) => resolveHref(itemPath, item[field]) !== target)
    ) {
      fail("stac-reference", `STAC item links differ: ${item.scenario}-${item.horizon}`);
    }
  }
  return expectedPairs.length;
}

function validateSealing(
  candidate: CandidateDocument,
  artifacts: CandidateArtifact[],
): void {
  const byPath = new Map(artifacts.map((artifact) => [artifact.path, artifact]));
  const { checksumInventory: checksum } = candidate;
  const expectedSubjects = Array.from(byPath.keys())
    .filter((path) => path !== "checksums.txt")
    .sort();
  if (
    checksum.path !== "checksums.txt" ||
    checksum.algorithm !== "sha256" ||
    new Set(checksum.subjects.map((subject) => subject.path)).size !==
      checksum.subjects.length ||
    canonicalJson(checksum.subjects.map((subject) => subject.path)) !==
      canonicalJson(expectedSubjects)
  ) {
    fail("checksum-coverage", "checksums must cover the exact sorted non-self inventory");
  }
  if (
    checksum.subjects.some(
      (subject) => subject.sha256 !== (byPath.get(subject.path) as CandidateArtifact).sha256,
    )
  ) {
    fail("checksum-integrity", "checksum entries must match the sealed artifact hashes");
  }

  const gatePaths = ["evidence/gate-report.json", "evidence/gate-report.md"];
  const gateSubjects = artifacts.filter(
    (artifact) => artifact.path !== "checksums.txt" && !gatePaths.includes(artifact.path),
  );
  const gate = candidate.gateReportSemantics;
  if (
    gate.candidateState !== "pre-manifest-snapshot" ||
    gate.validatedScope !==
      "required-artifacts-except-gate-reports-checksums-and-manifest" ||
    gate.validatedArtifactCount !== gateSubjects.length ||
    canonicalJson(gate.excludedPaths) !==
      canonicalJson(["checksums.txt", ...gatePaths, "manifest.json"]) ||
    gate.manifestHashReferenced !== false
  ) {
    fail("gate-report-scope", "gate reports must validate an acyclic pre-manifest snapshot");
  }
  const firstGateSequence = Math.min(
    ...gatePaths.map((path) => (byPath.get(path) as CandidateArtifact).writeSequence),
  );
  if (firstGateSequence <= Math.max(...gateSubjects.map((artifact) => artifact.writeSequence))) {
    fail("gate-report-scope", "gate reports must follow every artifact they validate");
  }
  const checksumSequence = (byPath.get("checksums.txt") as CandidateArtifact).writeSequence;
  const lastSubjectSequence = Math.max(
    ...artifacts
      .filter((artifact) => artifact.path !== "checksums.txt")
      .map((artifact) => artifact.writeSequence),
  );
  if (checksumSequence <= lastSubjectSequence) {
    fail("checksum-order", "checksums must be written after every declared subject");
  }
}

export function validateCandidateCompleteness(
  candidate: CandidateDocument,
  contract: RequiredArtifactContract,
): CandidateCompletenessSummary {
  if (candidate.contractId !== contract.contractId) {
    fail("candidate-schema", "candidate and required-artifact contract IDs differ");
  }
  validateGeometryPolicy(candidate);
  if (canonicalJson(candidate.projectionGrid) !== canonicalJson(contract.projectionGrid)) {
    fail("projection-grid", "projection grid differs from the public v1 grid");
  }
  const artifacts = validateArtifacts(candidate, contract);
  const datasetCount = validateStac(candidate, contract);
  validateSealing(candidate, artifacts);
  if (
    candidate.parity.status !== "passed" ||
    canonicalJson(candidate.parity.python) !== canonicalJson(candidate.parity.typescript)
  ) {
    fail("cross-runtime-parity", "Python and TypeScript lookup evidence differs");
  }

  const sequences = artifacts.map((artifact) => artifact.writeSequence);
  const expectedSequences = Array.from(
    { length: artifacts.length },
    (_, index) => index + 1,
  );
  if (
    canonicalJson([...sequences].sort((left, right) => left - right)) !==
      canonicalJson(expectedSequences) ||
    candidate.manifest.path !== "manifest.json" ||
    candidate.manifest.artifactCount !== artifacts.length ||
    candidate.manifest.writeSequence !== artifacts.length + 1
  ) {
    fail("manifest-order", "artifact writes must be contiguous and manifest exactly last");
  }
  return {
    artifactCount: artifacts.length,
    datasetCount,
    manifestWrittenLast: true,
  };
}
