import {
  BaseClient,
  BaseResponse,
  fromCustomClient,
  type GeoTIFF,
  type GeoTIFFImage,
} from "geotiff";
import type { HorizonYear, ProjectionContextV2, ScenarioId } from "../contracts/generated/release-contract";
import {
  ReleaseContext,
  TechnicalFailure,
  type Coordinates,
  type ResolvedArtifact,
} from "../domain/release";
import {
  MAXIMUM_SOURCE_DISTANCE_KILOMETRES,
  selectNearestSourceGridLocation,
  type AnalysisArtifactReader,
  type AnalysisReadResult,
} from "../domain/scientific-lookup";
import {
  artifactCacheIdentity,
  createSharedArtifactResource,
  sha256Hex,
  verifiedArtifactBytes,
  waitForCaller,
  waitForSharedArtifact,
  type ArtifactTransport,
  type SharedArtifactResource,
} from "./artifact-integrity";

interface NativeLocation {
  readonly locationId: number;
  readonly latitude: number;
  readonly longitude: number;
  readonly row: number;
  readonly column: number;
}

interface CachedCog {
  readonly artifact: ResolvedArtifact & { readonly role: "projection-analysis-cog" };
  readonly image: GeoTIFFImage;
  readonly locations: readonly NativeLocation[];
}

interface SourceGridDocument {
  readonly schemaVersion: 1;
  readonly releaseContractId: "ar6-europe-regional-release-v1";
  readonly sourceArchiveSha256: string;
  readonly width: 76;
  readonly height: 46;
  readonly storageOrder: "south-to-north-row-major";
  readonly cogCellMapping: Readonly<{
    sourceRow: "height - 1 - cogRow";
    sourceColumn: "cogColumn";
  }>;
  readonly locationIds: readonly number[];
}

interface RangeChunkIdentity {
  readonly start: number;
  readonly endExclusive: number;
  readonly sha256: string;
}

interface RangeArtifactIdentity {
  readonly artifactId: string;
  readonly path: string;
  readonly byteSize: number;
  readonly sha256: string;
  readonly chunks: readonly RangeChunkIdentity[];
}

interface RangeIntegrityIndex {
  readonly schemaVersion: 1;
  readonly dataReleaseId: string;
  readonly algorithm: "sha256";
  readonly chunkSize: 65_536;
  readonly artifacts: readonly RangeArtifactIdentity[];
}

interface ScientificMetadata {
  readonly sourceGrid: SourceGridDocument;
  readonly rangeIntegrity: RangeIntegrityIndex;
}

function technical(
  code: "SchemaInvalid" | "FetchFailed" | "RangeUnsupported" | "DecodeFailed" | "IntegrityFailed" | "UnsupportedBrowser" | "Aborted",
  message: string,
  recoverable = false,
): TechnicalFailure {
  return new TechnicalFailure({ kind: "technical-error", code, message, recoverable });
}

function equalNumbers(actual: readonly number[], expected: readonly number[]): boolean {
  return actual.length === expected.length && actual.every((value, index) => value === expected[index]);
}

class BrowserResponse extends BaseResponse {
  readonly #response: Response;

  constructor(response: Response) {
    super();
    this.#response = response;
  }

  override get status(): number {
    return this.#response.status;
  }

  override getHeader(name: string): string | undefined {
    return this.#response.headers.get(name) ?? undefined;
  }

  override getData(): Promise<ArrayBuffer> {
    return this.#response.arrayBuffer();
  }
}

class StrictRangeClient extends BaseClient {
  readonly #artifact: ResolvedArtifact;
  readonly #identity: RangeArtifactIdentity;
  readonly #fetch: typeof fetch;
  readonly #signal: AbortSignal;
  #etag: string | undefined;
  failure: TechnicalFailure | undefined;

  #record(error: TechnicalFailure): TechnicalFailure {
    this.failure = error;
    return error;
  }

  constructor(
    url: string,
    artifact: ResolvedArtifact,
    identity: RangeArtifactIdentity,
    fetcher: typeof fetch,
    signal: AbortSignal,
  ) {
    super(url);
    this.#artifact = artifact;
    this.#identity = identity;
    this.#fetch = fetcher;
    this.#signal = signal;
  }

  async validateDelivery(): Promise<void> {
    let response: Response;
    try {
      response = await this.#fetch(this.url, {
        method: "HEAD",
        signal: this.#signal,
        credentials: "omit",
        referrerPolicy: "no-referrer",
      });
    } catch (error) {
      if (this.#signal.aborted || (error instanceof DOMException && error.name === "AbortError")) {
        throw technical("Aborted", `Delivery metadata for ${this.#artifact.artifactId} was cancelled.`, true);
      }
      throw technical("FetchFailed", `Delivery metadata for ${this.#artifact.artifactId} is unavailable.`, true);
    }
    if (!response.ok) {
      throw technical("FetchFailed", `Delivery metadata for ${this.#artifact.artifactId} returned HTTP ${response.status}.`, true);
    }
    const etag = response.headers.get("etag");
    if (
      response.headers.get("accept-ranges") !== "bytes" ||
      response.headers.get("content-length") !== String(this.#artifact.byteSize) ||
      !etag
    ) {
      throw technical("RangeUnsupported", `Host delivery for ${this.#artifact.artifactId} lacks exact HEAD range identity.`, true);
    }
    const expectedEtag = `"sha256-${this.#artifact.sha256}"`;
    if (etag !== expectedEtag) {
      throw technical("IntegrityFailed", `Host delivery for ${this.#artifact.artifactId} does not match its manifest ETag.`);
    }
    this.#etag = etag;
  }

  override async request(options: RequestInit = {}): Promise<BaseResponse> {
    const requested = /^bytes=(\d+)-(\d+)$/.exec(new Headers(options.headers).get("range") ?? "");
    if (!requested) {
      throw this.#record(technical("RangeUnsupported", `A bounded byte range is required for ${this.#artifact.artifactId}.`, true));
    }
    const requestedStart = Number(requested[1]);
    const requestedEnd = Math.min(Number(requested[2]), this.#artifact.byteSize - 1);
    if (requestedStart > requestedEnd || requestedStart < 0) {
      throw this.#record(technical("RangeUnsupported", `An invalid byte range was requested for ${this.#artifact.artifactId}.`, true));
    }
    const firstChunk = Math.floor(requestedStart / 65_536);
    const lastChunk = Math.floor(requestedEnd / 65_536);
    const chunks = this.#identity.chunks.slice(firstChunk, lastChunk + 1);
    if (
      chunks.length !== lastChunk - firstChunk + 1 ||
      chunks[0]?.start !== firstChunk * 65_536 ||
      chunks.at(-1)?.endExclusive !== Math.min((lastChunk + 1) * 65_536, this.#artifact.byteSize)
    ) {
      throw this.#record(technical("IntegrityFailed", `Range identity coverage is incomplete for ${this.#artifact.artifactId}.`));
    }
    const expandedStart = chunks[0].start;
    const expandedEnd = chunks.at(-1)!.endExclusive - 1;
    const headers = new Headers(options.headers);
    headers.set("Range", `bytes=${expandedStart}-${expandedEnd}`);
    if (!this.#etag) {
      throw this.#record(technical("RangeUnsupported", `HEAD identity is required before reading ${this.#artifact.artifactId}.`, true));
    }
    headers.set("If-Match", this.#etag);
    let response: Response;
    try {
      response = await this.#fetch(this.url, {
        ...options,
        signal: this.#signal,
        headers,
        credentials: "omit",
        referrerPolicy: "no-referrer",
      });
    } catch (error) {
      if (this.#signal.aborted || (error instanceof DOMException && error.name === "AbortError")) {
        throw this.#record(technical("Aborted", `A byte range for ${this.#artifact.artifactId} was cancelled.`, true));
      }
      throw this.#record(technical("FetchFailed", `A required byte range for ${this.#artifact.artifactId} is unavailable.`, true));
    }
    const expectedLength = expandedEnd - expandedStart + 1;
    if (response.status !== 200 && !response.ok) {
      throw this.#record(technical("FetchFailed", `A required byte range for ${this.#artifact.artifactId} returned HTTP ${response.status}.`, true));
    }
    if (
      response.status !== 206 ||
      response.headers.get("accept-ranges") !== "bytes" ||
      response.headers.get("content-length") !== String(expectedLength) ||
      response.headers.get("content-range") !== `bytes ${expandedStart}-${expandedEnd}/${this.#artifact.byteSize}` ||
      !response.headers.get("etag")
    ) {
      throw this.#record(technical("RangeUnsupported", `Host delivery for ${this.#artifact.artifactId} returned an inexact byte range.`, true));
    }
    if (response.headers.get("etag") !== this.#etag) {
      throw this.#record(technical("IntegrityFailed", `Host delivery for ${this.#artifact.artifactId} changed ETag during a range read.`));
    }
    let expanded: ArrayBuffer;
    try {
      expanded = await response.arrayBuffer();
    } catch (error) {
      if (this.#signal.aborted || (error instanceof DOMException && error.name === "AbortError")) {
        throw this.#record(technical("Aborted", `A byte range for ${this.#artifact.artifactId} was cancelled.`, true));
      }
      throw this.#record(technical("FetchFailed", `A byte-range body for ${this.#artifact.artifactId} is unavailable.`, true));
    }
    if (expanded.byteLength !== expectedLength) {
      throw this.#record(technical("IntegrityFailed", `A byte range for ${this.#artifact.artifactId} has the wrong size.`));
    }
    for (const chunk of chunks) {
      const relativeStart = chunk.start - expandedStart;
      const bytes = expanded.slice(relativeStart, relativeStart + chunk.endExclusive - chunk.start);
      if ((await sha256Hex(bytes)) !== chunk.sha256) {
        throw this.#record(technical("IntegrityFailed", `A byte range for ${this.#artifact.artifactId} failed SHA-256 verification.`));
      }
    }
    const selected = expanded.slice(requestedStart - expandedStart, requestedEnd - expandedStart + 1);
    return new BrowserResponse(new Response(selected, {
      status: 206,
      headers: {
        "accept-ranges": "bytes",
        "content-length": String(selected.byteLength),
        "content-range": `bytes ${requestedStart}-${requestedEnd}/${this.#artifact.byteSize}`,
        "content-type": this.#artifact.mediaType,
      },
    }));
  }
}

function nativeLocations(
  context: ProjectionContextV2,
  sourceGrid: SourceGridDocument,
): readonly NativeLocation[] {
  const { grid } = context;
  const [xScale, xSkew, xOrigin, ySkew, yScale, yOrigin] = grid.transform;
  if (
    xScale !== 1 ||
    xSkew !== 0 ||
    ySkew !== 0 ||
    yScale !== -1 ||
    xOrigin !== -30.5 ||
    yOrigin !== 75.5
  ) {
    throw technical("SchemaInvalid", "The release changed the approved source-native grid transform.");
  }
  const locations: NativeLocation[] = [];
  for (let row = 0; row < grid.height; row += 1) {
    const latitude = yOrigin + (row + 0.5) * yScale;
    for (let column = 0; column < grid.width; column += 1) {
      const longitude = xOrigin + (column + 0.5) * xScale;
      const sourceRow = grid.height - 1 - row;
      const locationId = sourceGrid.locationIds[sourceRow * grid.width + column];
      if (!Number.isSafeInteger(locationId)) {
        throw technical("IntegrityFailed", "The release source-grid identity does not cover the analysis COG.");
      }
      locations.push(
        Object.freeze({
          locationId,
          latitude,
          longitude,
          row,
          column,
        }),
      );
    }
  }
  return Object.freeze(locations);
}

async function validateImage(
  image: GeoTIFFImage,
  projection: ProjectionContextV2,
  artifact: ResolvedArtifact,
): Promise<void> {
  const geoKeys = image.getGeoKeys();
  const bounds = image.getBoundingBox();
  const resolution = image.getResolution();
  if (
    image.getWidth() !== projection.grid.width ||
    image.getHeight() !== projection.grid.height ||
    image.getSamplesPerPixel() !== 3 ||
    ![0, 1, 2].every(
      (sample) => image.getBitsPerSample(sample) === 16 && image.getSampleFormat(sample) === 2,
    ) ||
    geoKeys?.GeographicTypeGeoKey !== 4326 ||
    !equalNumbers(bounds, projection.grid.bounds) ||
    !equalNumbers(resolution, [1, -1, 0]) ||
    image.getGDALNoData() !== projection.grid.nodata
  ) {
    throw technical("IntegrityFailed", `Analysis COG ${artifact.artifactId} metadata violates ADR-024.`);
  }
  const metadata = await image.getGDALMetadata();
  const bandDescriptions = await Promise.all(
    [0, 1, 2].map(async (sample) => {
      const description = (await image.getGDALMetadata(sample))?.DESCRIPTION;
      return typeof description === "string" ? description : undefined;
    }),
  );
  const expectedMetadata: Readonly<Record<string, string>> = Object.freeze({
    BASELINE: projection.values.baseline,
    CONFIDENCE: "medium",
    HORIZON: String(projection.horizon),
    METHOD_VERSION: projection.source.methodologyVersion,
    NATIVE_RESOLUTION_DEGREES: String(projection.grid.nativeResolutionDegrees),
    SCALE_TO_METRES: String(projection.values.scaleToMetres),
    SCENARIO: projection.scenario,
    SCIENTIFIC_DISPOSITION: "projection-only",
    SOURCE_ARCHIVE_SHA256: projection.source.archiveSha256,
    SOURCE_MEMBER_SHA256: projection.source.memberSha256,
    SOURCE_RELEASE: projection.source.sourceRelease,
    UNITS: projection.values.storedUnits,
  });
  if (
    !metadata ||
    Object.keys(expectedMetadata).some((key) => metadata[key] !== expectedMetadata[key]) ||
    !equalNumbers(
      bandDescriptions.map((description) => Number(description?.replace(/^q/, ""))),
      projection.values.quantiles,
    )
  ) {
    throw technical(
      "IntegrityFailed",
      `Analysis COG ${artifact.artifactId} does not match its scenario, horizon, source, and quantile identity.`,
    );
  }
}

function exactKeys(value: Record<string, unknown>, expected: readonly string[]): boolean {
  return Object.keys(value).sort().join("\0") === [...expected].sort().join("\0");
}

function decodeJson(bytes: ArrayBuffer, artifactId: string): unknown {
  try {
    return JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes));
  } catch {
    throw technical("DecodeFailed", `Artifact ${artifactId} is not valid UTF-8 JSON.`);
  }
}

async function decodeGzipJson(bytes: ArrayBuffer, artifactId: string): Promise<unknown> {
  if (typeof DecompressionStream === "undefined") {
    throw technical("UnsupportedBrowser", "Gzip decoding is unavailable in this browser.");
  }
  try {
    const stream = new Blob([bytes]).stream().pipeThrough(new DecompressionStream("gzip"));
    return decodeJson(await new Response(stream).arrayBuffer(), artifactId);
  } catch (error) {
    if (error instanceof TechnicalFailure) throw error;
    throw technical("DecodeFailed", `Artifact ${artifactId} is not valid deterministic gzip JSON.`);
  }
}

function parseSourceGrid(value: unknown, context: ReleaseContext): SourceGridDocument {
  const source = context.manifest.sources[0];
  if (!value || typeof value !== "object") {
    throw technical("SchemaInvalid", "The source-grid identity artifact is not an object.");
  }
  const document = value as Record<string, unknown>;
  const mapping = document.cogCellMapping;
  const locationIds = document.locationIds;
  if (
    !exactKeys(document, [
      "schemaVersion", "releaseContractId", "sourceArchiveSha256", "width", "height",
      "storageOrder", "cogCellMapping", "locationIds",
    ]) ||
    document.schemaVersion !== 1 ||
    document.releaseContractId !== "ar6-europe-regional-release-v1" ||
    document.sourceArchiveSha256 !== source?.archiveSha256 ||
    document.width !== 76 ||
    document.height !== 46 ||
    document.storageOrder !== "south-to-north-row-major" ||
    !mapping ||
    typeof mapping !== "object" ||
    !exactKeys(mapping as Record<string, unknown>, ["sourceRow", "sourceColumn"]) ||
    (mapping as Record<string, unknown>).sourceRow !== "height - 1 - cogRow" ||
    (mapping as Record<string, unknown>).sourceColumn !== "cogColumn" ||
    !Array.isArray(locationIds) ||
    locationIds.length !== 76 * 46 ||
    locationIds.some((locationId) => !Number.isSafeInteger(locationId) || locationId < 1_000_000_000) ||
    new Set(locationIds).size !== locationIds.length
  ) {
    throw technical("IntegrityFailed", "The source-grid identity artifact violates ADR-024.");
  }
  return Object.freeze({
    ...(document as unknown as SourceGridDocument),
    cogCellMapping: Object.freeze({ ...(mapping as SourceGridDocument["cogCellMapping"]) }),
    locationIds: Object.freeze([...locationIds]),
  });
}

function sha256String(value: unknown): value is string {
  return typeof value === "string" && /^[a-f0-9]{64}$/.test(value);
}

function parseRangeIntegrity(value: unknown, context: ReleaseContext): RangeIntegrityIndex {
  if (!value || typeof value !== "object") {
    throw technical("SchemaInvalid", "The COG range-integrity artifact is not an object.");
  }
  const document = value as Record<string, unknown>;
  if (
    !exactKeys(document, ["schemaVersion", "dataReleaseId", "algorithm", "chunkSize", "artifacts"]) ||
    document.schemaVersion !== 1 ||
    document.dataReleaseId !== context.dataReleaseId ||
    document.algorithm !== "sha256" ||
    document.chunkSize !== 65_536 ||
    !Array.isArray(document.artifacts)
  ) {
    throw technical("IntegrityFailed", "The COG range-integrity header is invalid.");
  }
  const artifacts = document.artifacts as unknown[];
  const byId = new Map<string, RangeArtifactIdentity>();
  for (const rawArtifact of artifacts) {
    if (!rawArtifact || typeof rawArtifact !== "object") {
      throw technical("IntegrityFailed", "The COG range-integrity index contains an invalid artifact.");
    }
    const record = rawArtifact as Record<string, unknown>;
    const releaseArtifact = typeof record.artifactId === "string" ? context.artifacts[record.artifactId] : undefined;
    if (
      !exactKeys(record, ["artifactId", "path", "byteSize", "sha256", "chunks"]) ||
      releaseArtifact?.role !== "projection-analysis-cog" ||
      record.path !== releaseArtifact.path ||
      record.byteSize !== releaseArtifact.byteSize ||
      record.sha256 !== releaseArtifact.sha256 ||
      !Array.isArray(record.chunks) ||
      byId.has(releaseArtifact.artifactId)
    ) {
      throw technical("IntegrityFailed", "The COG range-integrity index does not match the release manifest.");
    }
    const chunks = (record.chunks as unknown[]).map((rawChunk, index) => {
      if (!rawChunk || typeof rawChunk !== "object") {
        throw technical("IntegrityFailed", "The COG range-integrity index contains an invalid chunk.");
      }
      const chunk = rawChunk as Record<string, unknown>;
      const expectedStart = index * 65_536;
      const expectedEnd = Math.min(expectedStart + 65_536, releaseArtifact.byteSize);
      if (
        !exactKeys(chunk, ["start", "endExclusive", "sha256"]) ||
        chunk.start !== expectedStart ||
        chunk.endExclusive !== expectedEnd ||
        !sha256String(chunk.sha256)
      ) {
        throw technical("IntegrityFailed", "The COG range-integrity index has non-canonical chunk coverage.");
      }
      return Object.freeze(chunk as unknown as RangeChunkIdentity);
    });
    if (chunks.length !== Math.ceil(releaseArtifact.byteSize / 65_536)) {
      throw technical("IntegrityFailed", "The COG range-integrity index has incomplete object coverage.");
    }
    byId.set(releaseArtifact.artifactId, Object.freeze({
      ...(record as unknown as RangeArtifactIdentity),
      chunks: Object.freeze(chunks),
    }));
  }
  const expectedIds = Object.values(context.artifacts)
    .filter((artifact) => artifact.role === "projection-analysis-cog")
    .map((artifact) => artifact.artifactId)
    .sort();
  if ([...byId.keys()].sort().join("\0") !== expectedIds.join("\0")) {
    throw technical("IntegrityFailed", "The COG range-integrity index does not cover the exact release COG set.");
  }
  return Object.freeze({
    schemaVersion: 1,
    dataReleaseId: context.dataReleaseId,
    algorithm: "sha256",
    chunkSize: 65_536,
    artifacts: Object.freeze([...byId.values()]),
  });
}

function classifyReadError(error: unknown, artifactId: string, signal: AbortSignal): TechnicalFailure {
  if (signal.aborted || (error instanceof DOMException && error.name === "AbortError")) {
    return technical("Aborted", `Analysis read for ${artifactId} was cancelled.`, true);
  }
  const message = error instanceof Error ? error.message : "";
  if (/full file|range/i.test(message)) {
    return technical("RangeUnsupported", `Host delivery for ${artifactId} does not preserve byte ranges.`, true);
  }
  if (/fetch|network|HTTP|Error fetching data/i.test(message)) {
    return technical("FetchFailed", `A required byte range for ${artifactId} is unavailable.`, true);
  }
  return technical("DecodeFailed", `A required byte range for ${artifactId} could not be decoded.`, true);
}

function cogCacheIdentity(
  context: ReleaseContext,
  artifact: ResolvedArtifact,
  projection: ProjectionContextV2,
  metadataArtifacts: readonly ResolvedArtifact[],
): string {
  return JSON.stringify([
    artifactCacheIdentity(context, [artifact, ...metadataArtifacts]),
    projection.scenario,
    projection.horizon,
  ]);
}

export class CogAnalysisArtifactReader implements AnalysisArtifactReader {
  readonly #cache = new Map<string, SharedArtifactResource<CachedCog>>();
  readonly #metadataCache = new Map<string, SharedArtifactResource<ScientificMetadata>>();
  readonly #fetch: typeof fetch;
  readonly #artifactTransport: ArtifactTransport;

  constructor(options: {
    readonly fetch?: typeof fetch;
    readonly artifactTransport?: ArtifactTransport;
  } = {}) {
    this.#fetch = options.fetch ?? globalThis.fetch.bind(globalThis);
    this.#artifactTransport = options.artifactTransport ?? ((input, init) =>
      this.#fetch(input, {
        signal: init.signal,
        headers: init.headers,
        credentials: "omit",
        referrerPolicy: "no-referrer",
      }));
  }

  async #metadata(context: ReleaseContext, signal: AbortSignal): Promise<ScientificMetadata> {
    const sourceGridArtifact = context.artifact(context.manifest.contractArtifacts.sourceGridIdentity);
    const rangeIntegrityArtifact = context.artifact(context.manifest.contractArtifacts.rangeIntegrityIndex);
    if (
      sourceGridArtifact.role !== "source-grid-identity" ||
      sourceGridArtifact.mediaType !== "application/gzip" ||
      rangeIntegrityArtifact.role !== "range-integrity-index" ||
      rangeIntegrityArtifact.mediaType !== "application/json"
    ) {
      throw technical("SchemaInvalid", "Scientific browser metadata artifacts have invalid release roles.");
    }
    const cacheKey = artifactCacheIdentity(context, [sourceGridArtifact, rangeIntegrityArtifact]);
    let resource = this.#metadataCache.get(cacheKey);
    if (!resource) {
      resource = createSharedArtifactResource((resourceSignal) =>
        Promise.all([
          verifiedArtifactBytes(sourceGridArtifact, resourceSignal, this.#artifactTransport),
          verifiedArtifactBytes(rangeIntegrityArtifact, resourceSignal, this.#artifactTransport),
        ]).then(async ([sourceGridBytes, rangeIntegrityBytes]) => {
          let rangeValue: unknown;
          try {
            rangeValue = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(rangeIntegrityBytes));
          } catch {
            throw technical("DecodeFailed", "The COG range-integrity artifact is invalid JSON.");
          }
          return Object.freeze({
            sourceGrid: parseSourceGrid(
              await decodeGzipJson(sourceGridBytes, sourceGridArtifact.artifactId),
              context,
            ),
            rangeIntegrity: parseRangeIntegrity(rangeValue, context),
          });
        }),
      );
      this.#metadataCache.set(cacheKey, resource);
      while (this.#metadataCache.size > 2) {
        this.#metadataCache.delete(this.#metadataCache.keys().next().value as string);
      }
      resource.pending.catch(() => {
        if (this.#metadataCache.get(cacheKey) === resource) this.#metadataCache.delete(cacheKey);
      });
    }
    return waitForSharedArtifact(
      resource,
      signal,
      "Scientific metadata loading was cancelled.",
      () => {
        if (this.#metadataCache.get(cacheKey) === resource) this.#metadataCache.delete(cacheKey);
      },
    );
  }

  async #open(
    context: ReleaseContext,
    artifact: ResolvedArtifact,
    projection: ProjectionContextV2,
    metadata: ScientificMetadata,
    signal: AbortSignal,
  ): Promise<CachedCog> {
    if (artifact.role !== "projection-analysis-cog") {
      throw technical("SchemaInvalid", `${artifact.artifactId} is not a scientific analysis COG.`);
    }
    const metadataArtifacts = [
      context.artifact(context.manifest.contractArtifacts.sourceGridIdentity),
      context.artifact(context.manifest.contractArtifacts.rangeIntegrityIndex),
    ];
    const cacheIdentity = cogCacheIdentity(context, artifact, projection, metadataArtifacts);
    let resource = this.#cache.get(cacheIdentity);
    if (!resource) {
      resource = createSharedArtifactResource(async (resourceSignal) => {
        const rangeIdentity = metadata.rangeIntegrity.artifacts.find(
          (candidate) => candidate.artifactId === artifact.artifactId,
        );
        if (!rangeIdentity) {
          throw technical("IntegrityFailed", `No range-integrity identity exists for ${artifact.artifactId}.`);
        }
        const client = new StrictRangeClient(
          artifact.url,
          artifact,
          rangeIdentity,
          this.#fetch,
          resourceSignal,
        );
        try {
          await client.validateDelivery();
          const sourceOptions = {
            allowFullFile: false,
            blockSize: 65_536,
            cacheSize: 8,
            headers: Object.freeze({ Accept: artifact.mediaType }),
          } as Parameters<typeof fromCustomClient>[1] & {
            readonly blockSize: number;
            readonly cacheSize: number;
          };
          const tiff: GeoTIFF = await fromCustomClient(client, sourceOptions);
          const image = await tiff.getImage(0);
          await validateImage(image, projection, artifact);
          return Object.freeze({
            artifact,
            image,
            locations: nativeLocations(projection, metadata.sourceGrid),
          }) as CachedCog;
        } catch (error) {
          if (error instanceof TechnicalFailure) throw error;
          if (client.failure) throw client.failure;
          throw classifyReadError(error, artifact.artifactId, resourceSignal);
        }
      });
      this.#cache.set(cacheIdentity, resource);
      while (this.#cache.size > 4) this.#cache.delete(this.#cache.keys().next().value as string);
      resource.pending.catch(() => {
        if (this.#cache.get(cacheIdentity) === resource) this.#cache.delete(cacheIdentity);
      });
    }
    return waitForSharedArtifact(
      resource,
      signal,
      `Analysis read for ${artifact.artifactId} was cancelled.`,
      () => {
        if (this.#cache.get(cacheIdentity) === resource) this.#cache.delete(cacheIdentity);
      },
    );
  }

  async lookup(
    context: ReleaseContext,
    scenario: ScenarioId,
    horizon: HorizonYear,
    coordinates: Coordinates,
    signal: AbortSignal,
  ): Promise<AnalysisReadResult> {
    if (signal.aborted) throw technical("Aborted", "Analysis lookup was cancelled.", true);
    const dataset = context.dataset(scenario, horizon);
    const artifact = context.artifact(dataset.analysisArtifactId);
    if (
      artifact.role !== "projection-analysis-cog" ||
      artifact.scientificUse !== "exact-lookup" ||
      artifact.projectionContext.scenario !== scenario ||
      artifact.projectionContext.horizon !== horizon ||
      artifact.projectionContext.values.quantiles.join(",") !== "0.167,0.5,0.833" ||
      artifact.projectionContext.values.storedUnits !== "mm" ||
      artifact.projectionContext.values.scaleToMetres !== 0.001 ||
      artifact.projectionContext.values.baseline !== "1995-2014 mean" ||
      artifact.projectionContext.grid.nativeResolutionDegrees !== 1
    ) {
      throw technical("SchemaInvalid", "The selected analysis artifact violates the exact AR6 release contract.");
    }
    const metadata = await this.#metadata(context, signal);
    const cached = await this.#open(context, artifact, artifact.projectionContext, metadata, signal);
    const selected = selectNearestSourceGridLocation(cached.locations, coordinates);
    if (selected.unroundedDistanceKilometres > MAXIMUM_SOURCE_DISTANCE_KILOMETRES) {
      return Object.freeze({
        kind: "unavailable",
        reason: "source-location-too-distant",
        source: selected.source,
      });
    }
    let rasters: Awaited<ReturnType<GeoTIFFImage["readRasters"]>>;
    try {
      rasters = await waitForCaller(cached.image.readRasters({
        window: [
          selected.candidate.column,
          selected.candidate.row,
          selected.candidate.column + 1,
          selected.candidate.row + 1,
        ],
        samples: [0, 1, 2],
        interleave: false,
      }), signal, `Analysis read for ${artifact.artifactId} was cancelled.`);
    } catch (error) {
      if (error instanceof TechnicalFailure) throw error;
      throw classifyReadError(error, artifact.artifactId, signal);
    }
    if (
      rasters.length !== 3 ||
      !rasters.every((band) => band instanceof Int16Array && band.length === 1)
    ) {
      throw technical("DecodeFailed", "The analysis COG did not return three Int16 quantile samples.");
    }
    const [lowerMillimetres, medianMillimetres, upperMillimetres] = rasters.map(
      (band) => band[0],
    );
    if (
      lowerMillimetres === artifact.projectionContext.grid.nodata ||
      medianMillimetres === artifact.projectionContext.grid.nodata ||
      upperMillimetres === artifact.projectionContext.grid.nodata
    ) {
      return Object.freeze({
        kind: "unavailable",
        reason: "source-value-nodata",
        source: selected.source,
      });
    }
    return Object.freeze({
      kind: "projection",
      source: selected.source,
      lowerMillimetres,
      medianMillimetres,
      upperMillimetres,
      baseline: artifact.projectionContext.values.baseline,
      sourceRelease: artifact.projectionContext.source.sourceRelease,
      sourceMemberSha256: artifact.projectionContext.source.memberSha256,
      nativeResolutionDegrees: artifact.projectionContext.grid.nativeResolutionDegrees,
    });
  }
}
