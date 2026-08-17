import type { ErrorObject } from "ajv";
import {
  HORIZON_YEARS,
  SCENARIO_IDS,
  type BrowserReleaseManifestV2,
  type HorizonYear,
  type PrivateBindingManifestV1,
  type ReleaseArtifactV2,
  type ReleaseDatasetV2,
  type PrivateReleaseManifestV1,
  type ScenarioId,
} from "../contracts/generated/release-contract";
import validateManifest from "../contracts/generated/manifest-validator.mjs";
import validatePrivateManifest from "../contracts/generated/private-binding-validator.mjs";
import {
  ReleaseContext,
  TechnicalFailure,
  datasetIdentity,
  type ReleaseDisposition,
  type ResolvedArtifact,
  type TechnicalError,
} from "../domain/release";
export { technicalErrorFrom } from "./technical-error";

export type ManifestTransport = (
  input: URL,
  init: Readonly<{ signal: AbortSignal; headers: Readonly<Record<string, string>> }>,
) => Promise<Response>;

interface ManifestRepositoryOptions {
  readonly manifestUrl: string;
  readonly allowedOrigins: readonly string[];
  readonly expectedDisposition: ReleaseDisposition;
  readonly transport?: ManifestTransport;
}

function technical(
  code: TechnicalError["code"],
  message: string,
  recoverable = false,
): TechnicalFailure {
  return new TechnicalFailure({ kind: "technical-error", code, message, recoverable });
}

function validationSummary(errors: ErrorObject[] | null | undefined): string {
  const first = errors?.[0];
  return first ? `${first.instancePath || "/"} ${first.message ?? "is invalid"}` : "unknown contract error";
}

function deepFreeze<T>(value: T): T {
  if (value !== null && typeof value === "object" && !Object.isFrozen(value)) {
    for (const child of Object.values(value)) deepFreeze(child);
    Object.freeze(value);
  }
  return value;
}

function expectedDisposition(manifest: BrowserReleaseManifestV2, expected: ReleaseDisposition): void {
  const authority = manifest.releaseAuthority;
  if (expected === "synthetic-fixture" && manifest.dataProvenanceClass !== "synthetic-fixture") {
    throw technical("ReleaseIdentityMismatch", "A synthetic build must load a synthetic fixture release.");
  }
  if (expected === "public-promoted") {
    if (
      manifest.dataProvenanceClass !== "real-source" ||
      authority.automatedValidation !== "passed" ||
      authority.releaseDisposition !== "approved"
    ) {
      throw technical("ReleaseIdentityMismatch", "The public build requires an approved real-source release.");
    }
  }
  if (expected === "private-engineering" && manifest.dataProvenanceClass !== "real-source") {
    throw technical("ReleaseIdentityMismatch", "A private engineering binding must identify real-source data.");
  }
  if (
    expected === "private-engineering" &&
    (authority.automatedValidation !== "pending" ||
      authority.releaseDisposition !== "pending-owner" ||
      authority.statusDisclosureRequired !== true ||
      manifest.publication.cacheControl !== "private, no-store" ||
      manifest.contractArtifacts.baseReleaseSignature !== null)
  ) {
    throw technical(
      "ReleaseIdentityMismatch",
      "A private engineering binding must remain pending, unsigned, disclosed, and non-cacheable.",
    );
  }
}

function privateReleaseManifest(value: PrivateBindingManifestV1, pinnedReleaseId: string): PrivateReleaseManifestV1 {
  if (
    value.dataReleaseId !== pinnedReleaseId ||
    value.releaseManifest.dataReleaseId !== pinnedReleaseId ||
    value.binding.baseCandidate.dataReleaseId !== pinnedReleaseId ||
    value.releaseManifest.baseReleaseIdentity.manifestSha256 !==
      value.binding.baseCandidate.manifestSha256 ||
    value.releaseManifest.baseReleaseIdentity.createdAt !== value.binding.baseCandidate.createdAt ||
    value.releaseManifest.baseReleaseIdentity.codeRevision !==
      value.binding.baseCandidate.codeRevision ||
    value.releaseManifest.browserDerivationIdentity.receiptArtifactId !==
      value.releaseManifest.contractArtifacts.browserDerivationReceipt ||
    value.releaseManifest.browserDerivationIdentity.provenanceArtifactId !==
      value.releaseManifest.contractArtifacts.browserDerivationProvenance ||
    value.privateEngineeringOnly !== true ||
    value.verified !== false ||
    value.publicPromotionAuthorized !== false
  ) {
    throw technical("ReleaseIdentityMismatch", "Private binding identities or fail-closed flags disagree.");
  }
  return value.releaseManifest;
}

function canonicalCombinations(): readonly (readonly [ScenarioId, HorizonYear])[] {
  return SCENARIO_IDS.flatMap((scenario) =>
    HORIZON_YEARS.map((horizon) => [scenario, horizon] as const),
  );
}

function referencedArtifactIds(manifest: BrowserReleaseManifestV2): readonly string[] {
  const contracts = manifest.contractArtifacts;
  const identities = [
    contracts.scenarioConfig,
    contracts.methodology,
    contracts.attribution,
    ...contracts.sourceReceipts,
    contracts.baseReleaseBuildReceipt,
    contracts.browserDerivationReceipt,
    contracts.sourceGridIdentity,
    contracts.rangeIntegrityIndex,
    contracts.sbom,
    contracts.searchRecords,
    contracts.qualitySummary,
    contracts.architectureEvidence,
    contracts.stacCatalog,
    contracts.stacCollection,
    ...contracts.stacItems,
    contracts.checksums,
    contracts.baseReleaseProvenance,
    contracts.browserDerivationProvenance,
    contracts.baseReleaseSignature,
    ...manifest.sources.map((source) => source.receiptArtifactId),
  ];
  return identities.filter((identity): identity is string => identity !== null);
}

function requireRole(
  artifacts: Readonly<Record<string, ResolvedArtifact>>,
  artifactId: string,
  roles: readonly ReleaseArtifactV2["role"][],
): void {
  if (!roles.includes(artifacts[artifactId]?.role)) {
    throw technical("SchemaInvalid", `Artifact ${artifactId} does not have its required release role.`);
  }
}

function resolveArtifactUrl(
  artifact: ReleaseArtifactV2,
  releaseRoot: URL,
  allowedOrigins: ReadonlySet<string>,
): string {
  const url = new URL(artifact.path, releaseRoot);
  if (
    !allowedOrigins.has(url.origin) ||
    !["http:", "https:"].includes(url.protocol) ||
    url.username !== "" ||
    url.password !== "" ||
    url.search !== "" ||
    url.hash !== "" ||
    !url.pathname.startsWith(releaseRoot.pathname)
  ) {
    throw technical("IntegrityFailed", `Artifact ${artifact.artifactId} resolves outside the pinned release.`);
  }
  return url.href;
}

function validateSemantics(
  manifest: BrowserReleaseManifestV2,
  manifestUrl: URL,
  allowedOrigins: ReadonlySet<string>,
): { artifacts: Record<string, ResolvedArtifact>; datasets: Record<string, ReleaseDatasetV2> } {
  const expectedPath = `releases/${manifest.dataReleaseId}`;
  if (manifest.publication.releasePath !== expectedPath) {
    throw technical("ReleaseIdentityMismatch", "Manifest release path does not match its immutable release ID.");
  }
  const expectedManifestSuffix = `/${expectedPath}/manifest.json`;
  if (!manifestUrl.pathname.endsWith(expectedManifestSuffix)) {
    throw technical("ReleaseIdentityMismatch", "Manifest URL path does not match the pinned release ID.");
  }
  const releaseRoot = new URL(`./`, manifestUrl);
  const artifacts: Record<string, ResolvedArtifact> = Object.create(null);
  for (const artifact of manifest.artifacts) {
    if (artifact.dataReleaseId !== manifest.dataReleaseId) {
      throw technical("ReleaseIdentityMismatch", `Artifact ${artifact.artifactId} belongs to another release.`);
    }
    if (artifact.dataProvenanceClass !== manifest.dataProvenanceClass) {
      throw technical("ReleaseIdentityMismatch", `Artifact ${artifact.artifactId} has a different provenance class.`);
    }
    if (artifacts[artifact.artifactId]) {
      throw technical("SchemaInvalid", `Artifact ID ${artifact.artifactId} is duplicated.`);
    }
    artifacts[artifact.artifactId] = deepFreeze({
      ...artifact,
      url: resolveArtifactUrl(artifact, releaseRoot, allowedOrigins),
    });
  }
  for (const artifactId of referencedArtifactIds(manifest)) {
    if (!artifacts[artifactId]) {
      throw technical("SchemaInvalid", `Required artifact ${artifactId} is missing.`);
    }
  }
  const contracts = manifest.contractArtifacts;
  requireRole(artifacts, contracts.scenarioConfig, ["scenario-config"]);
  requireRole(artifacts, contracts.methodology, ["methodology"]);
  requireRole(artifacts, contracts.attribution, ["source-attribution"]);
  for (const artifactId of contracts.sourceReceipts) requireRole(artifacts, artifactId, ["source-receipt"]);
  requireRole(artifacts, contracts.baseReleaseBuildReceipt, ["base-release-build-receipt"]);
  requireRole(artifacts, contracts.browserDerivationReceipt, ["browser-derivation-receipt"]);
  requireRole(artifacts, contracts.sourceGridIdentity, ["source-grid-identity"]);
  requireRole(artifacts, contracts.rangeIntegrityIndex, ["range-integrity-index"]);
  requireRole(artifacts, contracts.sbom, ["sbom"]);
  requireRole(artifacts, contracts.searchRecords, ["settlement-search-index", "settlement-geoparquet"]);
  requireRole(artifacts, contracts.qualitySummary, ["quality-summary"]);
  requireRole(artifacts, contracts.architectureEvidence, ["architecture-evidence"]);
  requireRole(artifacts, contracts.stacCatalog, ["stac-catalog"]);
  requireRole(artifacts, contracts.stacCollection, ["stac-collection"]);
  for (const artifactId of contracts.stacItems) requireRole(artifacts, artifactId, ["stac-item"]);
  requireRole(artifacts, contracts.checksums, ["checksums"]);
  if (contracts.baseReleaseProvenance != null) {
    requireRole(artifacts, contracts.baseReleaseProvenance, ["base-release-provenance"]);
  }
  requireRole(artifacts, contracts.browserDerivationProvenance, ["browser-derivation-provenance"]);
  if (contracts.baseReleaseSignature != null) {
    requireRole(artifacts, contracts.baseReleaseSignature, ["base-release-signature"]);
  }
  for (const source of manifest.sources) requireRole(artifacts, source.receiptArtifactId, ["source-receipt"]);

  for (const role of ["support-boundary", "coastal-boundary"] as const) {
    const candidates = Object.values(artifacts).filter(
      (artifact) =>
        artifact.role === role &&
        ["application/vnd.apache.parquet", "application/geo+json"].includes(artifact.mediaType),
    );
    if (candidates.length !== 1) {
      throw technical(
        "SchemaInvalid",
        `The release must declare exactly one browser-decodable ${role} artifact.`,
      );
    }
    const boundary = candidates[0];
    if (boundary.scientificUse !== "not-applicable" || boundary.spatialBounds == null) {
      throw technical("SchemaInvalid", `${role} must be a scoped non-scientific geometry artifact.`);
    }
  }

  const datasets: Record<string, ReleaseDatasetV2> = Object.create(null);
  const combinations = canonicalCombinations();
  for (const [index, [scenario, horizon]] of combinations.entries()) {
    const dataset = manifest.datasets[index];
    if (dataset.scenario !== scenario || dataset.horizon !== horizon) {
      throw technical("SchemaInvalid", "The release must contain the canonical nine scenario/horizon combinations.");
    }
    const analysis = artifacts[dataset.analysisArtifactId];
    const visual = artifacts[dataset.visualArtifactId];
    const stac = artifacts[dataset.stacItemArtifactId];
    const analytical = artifacts[dataset.analyticalArtifactId];
    if (
      analysis?.role !== "projection-analysis-cog" ||
      visual?.role !== "projection-visual-pmtiles" ||
      stac?.role !== "stac-item" ||
      analytical?.role !== "projection-geoparquet" ||
      analysis.projectionContext?.scenario !== scenario ||
      analysis.projectionContext.horizon !== horizon ||
      visual.projectionContext?.scenario !== scenario ||
      visual.projectionContext.horizon !== horizon
    ) {
      throw technical("SchemaInvalid", `Dataset ${scenario}/${horizon} has inconsistent artifact roles or context.`);
    }
    datasets[datasetIdentity(scenario, horizon)] = deepFreeze(dataset);
  }
  return { artifacts, datasets };
}

function defaultTransport(input: URL, init: Parameters<ManifestTransport>[1]): Promise<Response> {
  return fetch(input, { signal: init.signal, headers: init.headers, credentials: "omit" });
}

export class ManifestRepository {
  readonly #manifestUrl: URL;
  readonly #allowedOrigins: ReadonlySet<string>;
  readonly #expectedDisposition: ReleaseDisposition;
  readonly #transport: ManifestTransport;

  constructor(options: ManifestRepositoryOptions) {
    this.#manifestUrl = new URL(options.manifestUrl);
    this.#allowedOrigins = new Set(options.allowedOrigins.map((origin) => new URL(origin).origin));
    this.#expectedDisposition = options.expectedDisposition;
    this.#transport = options.transport ?? defaultTransport;
    if (
      !this.#allowedOrigins.has(this.#manifestUrl.origin) ||
      !["http:", "https:"].includes(this.#manifestUrl.protocol) ||
      this.#manifestUrl.username !== "" ||
      this.#manifestUrl.password !== "" ||
      this.#manifestUrl.search !== "" ||
      this.#manifestUrl.hash !== ""
    ) {
      throw technical("IntegrityFailed", "Manifest URL is outside the explicit origin allowlist.");
    }
  }

  async load(pinnedReleaseId: string, signal: AbortSignal): Promise<ReleaseContext> {
    if (!this.#manifestUrl.pathname.endsWith(`/releases/${pinnedReleaseId}/manifest.json`)) {
      throw technical("ReleaseIdentityMismatch", "Application and manifest URL release pins disagree.");
    }
    let response: Response;
    try {
      response = await this.#transport(this.#manifestUrl, {
        signal,
        headers: Object.freeze({ Accept: "application/json" }),
      });
    } catch (error) {
      if (signal.aborted || (error instanceof DOMException && error.name === "AbortError")) {
        throw technical("Aborted", "Manifest loading was cancelled.");
      }
      throw technical("FetchFailed", "The pinned release manifest could not be loaded.", true);
    }
    if (!response.ok) {
      throw technical("FetchFailed", `The pinned release manifest returned HTTP ${response.status}.`, true);
    }
    const contentType = response.headers.get("content-type")?.split(";", 1)[0].trim();
    if (contentType !== "application/json") {
      throw technical("DecodeFailed", "The pinned manifest response is not JSON.", true);
    }
    let value: unknown;
    try {
      value = await response.json();
    } catch {
      throw technical("DecodeFailed", "The pinned release manifest contains invalid JSON.", true);
    }
    let manifest: BrowserReleaseManifestV2;
    if (this.#expectedDisposition === "private-engineering") {
      if (!validatePrivateManifest(value)) {
        throw technical(
          "SchemaInvalid",
          `Private binding contract rejected: ${validationSummary(validatePrivateManifest.errors)}.`,
        );
      }
      manifest = privateReleaseManifest(value, pinnedReleaseId);
    } else {
      if (!validateManifest(value)) {
        throw technical("SchemaInvalid", `Manifest contract rejected: ${validationSummary(validateManifest.errors)}.`);
      }
      manifest = value;
    }
    manifest = deepFreeze(manifest);
    if (manifest.dataReleaseId !== pinnedReleaseId) {
      throw technical("ReleaseIdentityMismatch", "Application and manifest release IDs disagree.");
    }
    expectedDisposition(manifest, this.#expectedDisposition);
    const resolved = validateSemantics(manifest, this.#manifestUrl, this.#allowedOrigins);
    return new ReleaseContext({
      manifest,
      manifestUrl: this.#manifestUrl.href,
      disposition: this.#expectedDisposition,
      ...resolved,
    });
  }
}
