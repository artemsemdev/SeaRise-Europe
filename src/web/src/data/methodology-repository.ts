import {
  ReleaseContext,
  TechnicalFailure,
  type ReleaseDisposition,
  type ResolvedArtifact,
} from "../domain/release";
import {
  artifactCacheIdentity,
  createSharedArtifactResource,
  defaultArtifactTransport,
  verifiedArtifactBytes,
  waitForSharedArtifact,
  type ArtifactTransport,
  type SharedArtifactResource,
} from "./artifact-integrity";

const METHODOLOGY_SCHEMA =
  "https://artemsemdev.github.io/SeaRise-Europe/contracts/release/v1/methodology.schema.json";
const ATTRIBUTION_SCHEMA_V1 =
  "https://artemsemdev.github.io/SeaRise-Europe/contracts/release/v1/attribution.schema.json";
const ATTRIBUTION_SCHEMA_V2 =
  "https://artemsemdev.github.io/SeaRise-Europe/contracts/release/v2/attribution.schema.json";
const ADR_DECISION_PATH = "docs/architecture/adr/ADR-024-ar6-regional-projection-contract.md";
const APPROVED_BASELINE_LIMITATIONS = [
  "Reports regional relative sea-level projection, not an absolute water level.",
  "Does not model flooding, terrain exposure, probability, or property risk.",
] as const;
const RESULT_STATES = [
  "ProjectionAvailable",
  "DataUnavailable",
  "OutOfScope",
  "UnsupportedGeography",
] as const;
const PROHIBITED_CLAIMS = [
  "flooding",
  "inundation",
  "terrain-exposure",
  "flood-probability",
  "property-risk",
] as const;
const ATTRIBUTION_ROLES_V1 = new Set([
  "release-manifest", "contract-schema", "scenario-config", "methodology", "source-attribution",
  "source-receipt", "build-receipt", "support-boundary", "coastal-boundary",
  "settlement-search-index", "settlement-geoparquet", "projection-analysis-cog",
  "projection-visual-pmtiles", "projection-geoparquet", "quality-summary", "release-gate-report",
  "architecture-evidence", "stac-catalog", "stac-collection", "stac-item", "checksums",
  "provenance", "signature",
]);
const ATTRIBUTION_ROLES_V2 = new Set([
  ...ATTRIBUTION_ROLES_V1,
  "base-release-build-receipt", "browser-derivation-receipt", "settlement-search-receipt",
  "source-grid-identity", "range-integrity-index", "sbom", "base-release-provenance",
  "browser-derivation-provenance", "base-release-signature",
]);
const SCIENTIFIC_ATTRIBUTION_ROLES = [
  "projection-analysis-cog",
  "projection-geoparquet",
  "projection-visual-pmtiles",
] as const;

export interface MethodologySource {
  readonly title: string;
  readonly attributionText: string;
  readonly sourceUrl: string;
  readonly licence: Readonly<{ readonly spdxId: string; readonly name: string; readonly url: string }>;
}

export interface ReleaseMethodology {
  readonly dataReleaseId: string;
  readonly disposition: ReleaseDisposition;
  readonly methodologyVersion: "ar6-regional-projection-v1";
  readonly baseline: "1995-2014 mean";
  readonly likelyRange: Readonly<{
    readonly confidence: "medium";
    readonly lowerQuantile: 0.167;
    readonly medianQuantile: 0.5;
    readonly upperQuantile: 0.833;
  }>;
  readonly lookup: Readonly<{
    readonly operator: "nearest-source-grid-location";
    readonly nativeResolutionDegrees: 1;
    readonly maximumDistanceKilometres: 100;
    readonly distanceLimitInclusive: true;
    readonly interpolation: "prohibited";
    readonly extrapolation: "prohibited";
    readonly nodataSubstitution: "prohibited";
    readonly tideGaugeFallback: "prohibited";
  }>;
  readonly resultStates: typeof RESULT_STATES;
  readonly limitations: readonly string[];
  readonly prohibitedClaims: typeof PROHIBITED_CLAIMS;
  readonly decision: Readonly<{ readonly id: "ADR-024"; readonly href: string }>;
  readonly source: MethodologySource;
}

function technical(
  code: "SchemaInvalid" | "ReleaseIdentityMismatch" | "DecodeFailed" | "Aborted",
  message: string,
  recoverable = false,
): TechnicalFailure {
  return new TechnicalFailure({ kind: "technical-error", code, message, recoverable });
}

function record(value: unknown, name: string): Record<string, unknown> {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw technical("SchemaInvalid", `${name} must be a JSON object.`);
  }
  return value as Record<string, unknown>;
}

function exactKeys(value: Record<string, unknown>, expected: readonly string[], name: string): void {
  if (Object.keys(value).sort().join("\0") !== [...expected].sort().join("\0")) {
    throw technical("SchemaInvalid", `${name} has an invalid field set.`);
  }
}

function exactArray(value: unknown, expected: readonly unknown[], name: string): void {
  if (!Array.isArray(value) || value.length !== expected.length || value.some((item, index) => item !== expected[index])) {
    throw technical("SchemaInvalid", `${name} does not match the approved ADR-024 sequence.`);
  }
}

function nonEmptyString(value: unknown, name: string): string {
  if (typeof value !== "string" || value.length === 0) {
    throw technical("SchemaInvalid", `${name} must be a non-empty string.`);
  }
  return value;
}

function httpsUrl(value: unknown, name: string): string {
  const text = nonEmptyString(value, name);
  try {
    if (new URL(text).protocol !== "https:") throw new Error("not HTTPS");
  } catch {
    throw technical("SchemaInvalid", `${name} must be an absolute HTTPS URL.`);
  }
  return text;
}

function decodeJson(bytes: ArrayBuffer, artifactId: string): unknown {
  try {
    return JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes));
  } catch {
    throw technical("DecodeFailed", `Artifact ${artifactId} is not valid UTF-8 JSON.`);
  }
}

function deepFreeze<T>(value: T): T {
  if (value !== null && typeof value === "object" && !Object.isFrozen(value)) {
    Object.values(value).forEach((child) => deepFreeze(child));
    Object.freeze(value);
  }
  return value;
}

function validateReleaseIdentity(
  document: Record<string, unknown>,
  context: ReleaseContext,
  name: string,
): void {
  if (
    document.dataReleaseId !== context.dataReleaseId ||
    document.dataProvenanceClass !== context.manifest.dataProvenanceClass
  ) {
    throw technical("ReleaseIdentityMismatch", `${name} belongs to a different release.`);
  }
}

function decisionUrl(context: ReleaseContext): string {
  const revision = context.manifest.baseReleaseIdentity.codeRevision;
  if (!/^[a-f0-9]{40}$/.test(revision)) {
    throw technical("ReleaseIdentityMismatch", "The release code revision is not an exact Git commit identity.");
  }
  return `https://github.com/artemsemdev/SeaRise-Europe/blob/${revision}/${ADR_DECISION_PATH}`;
}

function parseMethodology(value: unknown, context: ReleaseContext): Omit<ReleaseMethodology, "source"> {
  const document = record(value, "Methodology artifact");
  exactKeys(document, [
    "$schema", "schemaVersion", "dataReleaseId", "dataProvenanceClass", "methodologyVersion",
    "decision", "configuration", "modeledQuantity", "publishedUnits", "baseline", "likelyRange",
    "lookup", "resultStates", "prohibitedClaims", "limitations",
  ], "Methodology artifact");
  validateReleaseIdentity(document, context, "Methodology artifact");

  const decision = record(document.decision, "Methodology decision");
  exactKeys(decision, ["id", "status", "href"], "Methodology decision");
  const configuration = record(document.configuration, "Methodology configuration");
  exactKeys(configuration, ["path", "sha256"], "Methodology configuration");
  const scenarioArtifact = context.artifact(context.manifest.contractArtifacts.scenarioConfig);
  const likelyRange = record(document.likelyRange, "Methodology likely range");
  exactKeys(likelyRange, ["confidence", "lowerQuantile", "medianQuantile", "upperQuantile"], "Methodology likely range");
  const lookup = record(document.lookup, "Methodology lookup");
  exactKeys(lookup, [
    "sourceLocationFamily", "operator", "maximumDistanceKilometres", "distanceLimitInclusive",
    "nativeResolutionDegrees", "interpolation", "extrapolation", "tideGaugeFallback",
    "nodataSubstitution", "scientificArtifactRole",
  ], "Methodology lookup");
  exactArray(document.resultStates, RESULT_STATES, "Methodology result states");
  exactArray(document.prohibitedClaims, PROHIBITED_CLAIMS, "Methodology prohibited claims");
  const expectedDecisionUrl = decisionUrl(context);
  const limitations = document.limitations;
  if (!Array.isArray(limitations) || limitations.length === 0 ||
      limitations.some((item) => typeof item !== "string" || item.length === 0) ||
      new Set(limitations).size !== limitations.length ||
      APPROVED_BASELINE_LIMITATIONS.some((limitation) => !limitations.includes(limitation))) {
    throw technical("SchemaInvalid", "Methodology limitations must retain the approved projection-only baseline.");
  }

  if (
    document.$schema !== METHODOLOGY_SCHEMA || document.schemaVersion !== "1.0.0" ||
    document.methodologyVersion !== context.methodologyVersion ||
    document.modeledQuantity !== "regional-relative-sea-level-change" || document.publishedUnits !== "m" ||
    document.baseline !== "1995-2014 mean" ||
    decision.id !== "ADR-024" || decision.status !== "accepted" || decision.href !== expectedDecisionUrl ||
    configuration.path !== scenarioArtifact.path || configuration.sha256 !== scenarioArtifact.sha256 ||
    likelyRange.confidence !== "medium" || likelyRange.lowerQuantile !== 0.167 ||
    likelyRange.medianQuantile !== 0.5 || likelyRange.upperQuantile !== 0.833 ||
    lookup.sourceLocationFamily !== "grid" || lookup.operator !== "nearest-source-grid-location" ||
    lookup.maximumDistanceKilometres !== 100 || lookup.distanceLimitInclusive !== true ||
    lookup.nativeResolutionDegrees !== 1 || lookup.interpolation !== "prohibited" ||
    lookup.extrapolation !== "prohibited" || lookup.tideGaugeFallback !== "prohibited" ||
    lookup.nodataSubstitution !== "prohibited" || lookup.scientificArtifactRole !== "projection-analysis-cog"
  ) {
    throw technical("SchemaInvalid", "Methodology artifact changes the approved ADR-024 semantics.");
  }

  return deepFreeze({
    dataReleaseId: context.dataReleaseId,
    disposition: context.disposition,
    methodologyVersion: "ar6-regional-projection-v1" as const,
    baseline: "1995-2014 mean" as const,
    likelyRange: {
      confidence: "medium" as const,
      lowerQuantile: 0.167 as const,
      medianQuantile: 0.5 as const,
      upperQuantile: 0.833 as const,
    },
    lookup: {
      operator: "nearest-source-grid-location" as const,
      nativeResolutionDegrees: 1 as const,
      maximumDistanceKilometres: 100 as const,
      distanceLimitInclusive: true as const,
      interpolation: "prohibited" as const,
      extrapolation: "prohibited" as const,
      nodataSubstitution: "prohibited" as const,
      tideGaugeFallback: "prohibited" as const,
    },
    resultStates: RESULT_STATES,
    limitations: [...limitations] as string[],
    prohibitedClaims: PROHIBITED_CLAIMS,
    decision: { id: "ADR-024" as const, href: expectedDecisionUrl },
  });
}

function parseSource(value: unknown, context: ReleaseContext): MethodologySource {
  const document = record(value, "Attribution artifact");
  exactKeys(document, ["$schema", "schemaVersion", "dataReleaseId", "dataProvenanceClass", "records"], "Attribution artifact");
  validateReleaseIdentity(document, context, "Attribution artifact");
  const allowedRoles = document.$schema === ATTRIBUTION_SCHEMA_V1 && document.schemaVersion === "1.0.0"
    ? ATTRIBUTION_ROLES_V1
    : document.$schema === ATTRIBUTION_SCHEMA_V2 && document.schemaVersion === "2.0.0"
      ? ATTRIBUTION_ROLES_V2
      : undefined;
  if (!allowedRoles || !Array.isArray(document.records) || document.records.length === 0) {
    throw technical("SchemaInvalid", "Attribution artifact does not match its strict public contract.");
  }
  if (context.manifest.sources.length !== 1) {
    throw technical("SchemaInvalid", "The projection methodology must declare exactly one scientific source.");
  }
  const releaseSource = context.manifest.sources[0];
  let selected: MethodologySource | undefined;
  const seenIds = new Set<string>();
  for (const candidate of document.records) {
    const entry = record(candidate, "Attribution record");
    const keys = [
      "attributionId", "sourceId", "title", "sourceUrl", "licence", "attributionText",
      "redistribution", "sourceSha256", "appliesToRoles",
      ...(Object.hasOwn(entry, "derivativeNotice") ? ["derivativeNotice"] : []),
    ];
    exactKeys(entry, keys, "Attribution record");
    const attributionId = nonEmptyString(entry.attributionId, "Attribution ID");
    if (!/^[a-z0-9][a-z0-9.-]+$/.test(attributionId) || seenIds.has(attributionId)) {
      throw technical("SchemaInvalid", "Attribution IDs must be unique contract identifiers.");
    }
    seenIds.add(attributionId);
    const sourceId = nonEmptyString(entry.sourceId, "Attribution source ID");
    const sourceSha256 = nonEmptyString(entry.sourceSha256, "Attribution source SHA-256");
    const licence = record(entry.licence, "Attribution licence");
    exactKeys(licence, ["spdxId", "name", "url"], "Attribution licence");
    const appliesToRoles = entry.appliesToRoles;
    const title = nonEmptyString(entry.title, "Attribution title");
    const attributionText = nonEmptyString(entry.attributionText, "Attribution text");
    const sourceUrl = httpsUrl(entry.sourceUrl, "Attribution source URL");
    const spdxId = nonEmptyString(licence.spdxId, "Licence SPDX ID");
    const licenceName = nonEmptyString(licence.name, "Licence name");
    const licenceUrl = httpsUrl(licence.url, "Licence URL");
    if (!/^[a-z0-9][a-z0-9./_-]+$/.test(sourceId) || !/^[a-f0-9]{64}$/.test(sourceSha256) ||
        !/^[A-Za-z0-9.+-]+$/.test(spdxId) ||
        !Array.isArray(appliesToRoles) || appliesToRoles.length === 0 ||
        appliesToRoles.some((role) => typeof role !== "string" || !allowedRoles.has(role)) ||
        new Set(appliesToRoles).size !== appliesToRoles.length ||
        !["allowed", "conditional", "prohibited"].includes(String(entry.redistribution)) ||
        (entry.redistribution === "conditional" && !Object.hasOwn(entry, "derivativeNotice")) ||
        (Object.hasOwn(entry, "derivativeNotice") &&
          (typeof entry.derivativeNotice !== "string" || entry.derivativeNotice.length === 0))) {
      throw technical("SchemaInvalid", "Attribution record fields violate the strict public contract.");
    }
    if (attributionId === releaseSource.attributionId) {
      if (
        selected || sourceId !== releaseSource.sourceId || sourceSha256 !== releaseSource.archiveSha256 ||
        entry.redistribution !== "allowed" ||
        SCIENTIFIC_ATTRIBUTION_ROLES.some((role) => !appliesToRoles.includes(role))
      ) {
        throw technical("ReleaseIdentityMismatch", "Scientific attribution does not match the manifest source identity.");
      }
      selected = deepFreeze({
        title,
        attributionText,
        sourceUrl,
        licence: {
          spdxId,
          name: licenceName,
          url: licenceUrl,
        },
      });
    }
  }
  if (!selected) {
    throw technical("ReleaseIdentityMismatch", "Scientific attribution is missing for the manifest source.");
  }
  return selected;
}

function resolveArtifacts(context: ReleaseContext): readonly [ResolvedArtifact, ResolvedArtifact] {
  const methodology = context.artifact(context.manifest.contractArtifacts.methodology);
  const attribution = context.artifact(context.manifest.contractArtifacts.attribution);
  if (
    methodology.role !== "methodology" || methodology.mediaType !== "application/json" ||
    methodology.scientificUse !== "not-applicable" ||
    attribution.role !== "source-attribution" || attribution.mediaType !== "application/json" ||
    attribution.scientificUse !== "not-applicable"
  ) {
    throw technical("SchemaInvalid", "Methodology contract artifacts have invalid release roles or media types.");
  }
  const source = context.manifest.sources[0];
  if (
    context.manifest.sources.length !== 1 ||
    Object.values(context.datasets).some((dataset) =>
      [dataset.analysisArtifactId, dataset.analyticalArtifactId, dataset.visualArtifactId].some(
        (artifactId) => !context.artifact(artifactId).rights.attributionIds.includes(source.attributionId),
      ),
    )
  ) {
    throw technical("ReleaseIdentityMismatch", "Projection artifacts do not share one manifest-bound scientific attribution.");
  }
  return [methodology, attribution];
}

export class MethodologyRepository {
  readonly #transport: ArtifactTransport;
  readonly #cache = new Map<string, SharedArtifactResource<ReleaseMethodology>>();

  constructor(options: { readonly transport?: ArtifactTransport } = {}) {
    this.#transport = options.transport ?? defaultArtifactTransport;
  }

  async load(context: ReleaseContext, signal: AbortSignal): Promise<ReleaseMethodology> {
    if (signal.aborted) throw technical("Aborted", "Methodology loading was cancelled.", true);
    const artifacts = resolveArtifacts(context);
    const cacheKey = JSON.stringify([
      artifactCacheIdentity(context, artifacts),
      context.disposition,
      context.methodologyVersion,
      context.manifest.sources,
    ]);
    let resource = this.#cache.get(cacheKey);
    if (!resource) {
      resource = createSharedArtifactResource(async (resourceSignal) => {
        const [methodologyBytes, attributionBytes] = await Promise.all(
          artifacts.map((artifact) => verifiedArtifactBytes(artifact, resourceSignal, this.#transport)),
        );
        const methodology = parseMethodology(decodeJson(methodologyBytes, artifacts[0].artifactId), context);
        const source = parseSource(decodeJson(attributionBytes, artifacts[1].artifactId), context);
        return deepFreeze({ ...methodology, source });
      });
      this.#cache.set(cacheKey, resource);
      while (this.#cache.size > 2) this.#cache.delete(this.#cache.keys().next().value as string);
      resource.pending.catch(() => {
        if (this.#cache.get(cacheKey) === resource) this.#cache.delete(cacheKey);
      });
    }
    return waitForSharedArtifact(resource, signal, "Methodology loading was cancelled.", () => {
      if (this.#cache.get(cacheKey) === resource) this.#cache.delete(cacheKey);
    });
  }
}
