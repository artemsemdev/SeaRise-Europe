import {
  BaseClient,
  BaseResponse,
  fromCustomClient,
  type GeoTIFF,
  type GeoTIFFImage,
} from "geotiff";
import type { HorizonYear, ProjectionContextV1, ScenarioId } from "../contracts/generated/release-contract";
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

function technical(
  code: "SchemaInvalid" | "FetchFailed" | "RangeUnsupported" | "DecodeFailed" | "IntegrityFailed" | "Aborted",
  message: string,
  recoverable = false,
): TechnicalFailure {
  return new TechnicalFailure({ kind: "technical-error", code, message, recoverable });
}

function equalNumbers(actual: readonly number[], expected: readonly number[]): boolean {
  return actual.length === expected.length && actual.every((value, index) => value === expected[index]);
}

function sourceLocationId(latitude: number, longitude: number): number {
  const latitudeIndex = 90 - latitude;
  const longitudeIndex = ((longitude % 360) + 360) % 360;
  if (!Number.isInteger(latitudeIndex) || !Number.isInteger(longitudeIndex)) {
    throw technical("DecodeFailed", "The analysis grid is not aligned to native AR6 source locations.");
  }
  return 1_000_000_000 + latitudeIndex * 100_000 + longitudeIndex * 10;
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
  failure: "range-unsupported" | "fetch-failed" | undefined;

  override async request(options: RequestInit = {}): Promise<BaseResponse> {
    let response: Response;
    try {
      response = await fetch(this.url, { ...options, credentials: "omit" });
    } catch (error) {
      if (!options.signal?.aborted) this.failure = "fetch-failed";
      throw error;
    }
    if (new Headers(options.headers).has("range") && response.status === 200) {
      this.failure = "range-unsupported";
    } else if (!response.ok) {
      this.failure = "fetch-failed";
    }
    return new BrowserResponse(response);
  }
}

function nativeLocations(context: ProjectionContextV1): readonly NativeLocation[] {
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
      locations.push(
        Object.freeze({
          locationId: sourceLocationId(latitude, longitude),
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

function validateImage(
  image: GeoTIFFImage,
  projection: ProjectionContextV1,
  artifact: ResolvedArtifact,
): void {
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
  projection: ProjectionContextV1,
): string {
  return JSON.stringify([
    context.dataReleaseId,
    artifact.artifactId,
    artifact.sha256,
    artifact.url,
    projection.scenario,
    projection.horizon,
  ]);
}

export class CogAnalysisArtifactReader implements AnalysisArtifactReader {
  readonly #cache = new Map<string, Promise<CachedCog>>();

  async #open(
    context: ReleaseContext,
    artifact: ResolvedArtifact,
    projection: ProjectionContextV1,
    signal: AbortSignal,
  ): Promise<CachedCog> {
    if (artifact.role !== "projection-analysis-cog") {
      throw technical("SchemaInvalid", `${artifact.artifactId} is not a scientific analysis COG.`);
    }
    const cacheIdentity = cogCacheIdentity(context, artifact, projection);
    let pending = this.#cache.get(cacheIdentity);
    if (!pending) {
      pending = (async () => {
        const client = new StrictRangeClient(artifact.url);
        try {
          const sourceOptions = {
            allowFullFile: false,
            blockSize: 65_536,
            cacheSize: 8,
            headers: Object.freeze({ Accept: artifact.mediaType }),
          } as Parameters<typeof fromCustomClient>[1] & {
            readonly blockSize: number;
            readonly cacheSize: number;
          };
          const tiff: GeoTIFF = await fromCustomClient(client, sourceOptions, signal);
          const image = await tiff.getImage(0);
          validateImage(image, projection, artifact);
          return Object.freeze({
            artifact,
            image,
            locations: nativeLocations(projection),
          }) as CachedCog;
        } catch (error) {
          if (error instanceof TechnicalFailure) throw error;
          if (client.failure === "range-unsupported") {
            throw technical(
              "RangeUnsupported",
              `Host delivery for ${artifact.artifactId} does not preserve byte ranges.`,
              true,
            );
          }
          if (client.failure === "fetch-failed") {
            throw technical(
              "FetchFailed",
              `A required byte range for ${artifact.artifactId} is unavailable.`,
              true,
            );
          }
          throw classifyReadError(error, artifact.artifactId, signal);
        }
      })();
      this.#cache.set(cacheIdentity, pending);
      while (this.#cache.size > 4) this.#cache.delete(this.#cache.keys().next().value as string);
      pending.catch(() => {
        if (this.#cache.get(cacheIdentity) === pending) this.#cache.delete(cacheIdentity);
      });
    }
    return pending;
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
    const cached = await this.#open(context, artifact, artifact.projectionContext, signal);
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
      rasters = await cached.image.readRasters({
        window: [
          selected.candidate.column,
          selected.candidate.row,
          selected.candidate.column + 1,
          selected.candidate.row + 1,
        ],
        samples: [0, 1, 2],
        interleave: false,
        signal,
      });
    } catch (error) {
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
