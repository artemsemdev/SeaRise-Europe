import { compressors } from "hyparquet-compressors";
import { parquetReadObjects, type AsyncBuffer } from "hyparquet";
import type { ReleaseArtifactV2 } from "../contracts/generated/release-contract";
import {
  ReleaseContext,
  TechnicalFailure,
  type Coordinates,
  type GeographyClassification,
  type ResolvedArtifact,
} from "../domain/release";
import type { GeographyClassifier } from "../domain/scientific-lookup";
import {
  artifactCacheIdentity,
  createSharedArtifactResource,
  defaultArtifactTransport,
  verifiedArtifactBytes,
  waitForSharedArtifact,
  type ArtifactTransport,
  type SharedArtifactResource,
} from "./artifact-integrity";

type Position = readonly [number, number];
type Ring = readonly Position[];
type Polygon = readonly Ring[];

interface MultiPolygonGeometry {
  readonly type: "MultiPolygon";
  readonly coordinates: readonly Polygon[];
}

interface BoundaryPair {
  readonly support: MultiPolygonGeometry;
  readonly coastal: MultiPolygonGeometry;
}

export type GeographyTransport = ArtifactTransport;

const BOUNDARY_MEDIA_TYPES = [
  "application/vnd.apache.parquet",
  "application/geo+json",
] as const;

function technical(
  code:
    | "SchemaInvalid"
    | "FetchFailed"
    | "DecodeFailed"
    | "IntegrityFailed"
    | "UnsupportedBrowser"
    | "Aborted",
  message: string,
  recoverable = false,
): TechnicalFailure {
  return new TechnicalFailure({ kind: "technical-error", code, message, recoverable });
}

function finitePosition(value: unknown): value is Position {
  return (
    Array.isArray(value) &&
    value.length === 2 &&
    value.every((coordinate) => typeof coordinate === "number" && Number.isFinite(coordinate)) &&
    value[0] >= -180 &&
    value[0] <= 180 &&
    value[1] >= -90 &&
    value[1] <= 90
  );
}

function multiPolygon(value: unknown, artifactId: string): MultiPolygonGeometry {
  if (
    !value ||
    typeof value !== "object" ||
    (value as { type?: unknown }).type !== "MultiPolygon" ||
    !Array.isArray((value as { coordinates?: unknown }).coordinates)
  ) {
    throw technical("DecodeFailed", `Boundary artifact ${artifactId} must contain one MultiPolygon.`);
  }
  const geometry = value as MultiPolygonGeometry;
  if (
    geometry.coordinates.length === 0 ||
    geometry.coordinates.some(
      (polygon) =>
        !Array.isArray(polygon) ||
        polygon.length === 0 ||
        polygon.some(
          (ring) =>
            !Array.isArray(ring) ||
            ring.length < 4 ||
            ring.some((position) => !finitePosition(position)) ||
            ring[0][0] !== ring.at(-1)?.[0] ||
            ring[0][1] !== ring.at(-1)?.[1],
        ),
    )
  ) {
    throw technical("DecodeFailed", `Boundary artifact ${artifactId} contains invalid OGC:CRS84 rings.`);
  }
  return geometry;
}

function arrayBufferFile(bytes: ArrayBuffer): AsyncBuffer {
  return {
    byteLength: bytes.byteLength,
    slice: (start, end) => bytes.slice(start, end),
  };
}

async function decodeGeoParquet(
  artifact: ResolvedArtifact,
  bytes: ArrayBuffer,
): Promise<MultiPolygonGeometry> {
  let rows: Record<string, unknown>[];
  try {
    rows = await parquetReadObjects({
      file: arrayBufferFile(bytes),
      columns: [
        "boundary_id",
        "role",
        "status",
        "purpose",
        "publication_eligible",
        "canonical",
        "production",
        "hazard_extent_claim",
        "geometry",
      ],
      compressors,
      rowFormat: "object",
    });
  } catch {
    throw technical("DecodeFailed", `Boundary GeoParquet ${artifact.artifactId} could not be decoded.`);
  }
  const row = rows[0];
  if (
    rows.length !== 1 ||
    row.role !== artifact.role ||
    row.status !== "selected-scope-approximation" ||
    row.purpose !== "product-eligibility-only" ||
    row.publication_eligible !== false ||
    row.canonical !== false ||
    row.production !== false ||
    row.hazard_extent_claim !== false
  ) {
    throw technical("IntegrityFailed", `Boundary GeoParquet ${artifact.artifactId} changed its scope semantics.`);
  }
  return multiPolygon(row.geometry, artifact.artifactId);
}

function decodeGeoJson(artifact: ResolvedArtifact, bytes: ArrayBuffer): MultiPolygonGeometry {
  let value: unknown;
  try {
    value = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes));
  } catch {
    throw technical("DecodeFailed", `Boundary GeoJSON ${artifact.artifactId} is invalid.`);
  }
  if (
    !value ||
    typeof value !== "object" ||
    (value as { type?: unknown }).type !== "FeatureCollection" ||
    !Array.isArray((value as { features?: unknown }).features) ||
    (value as { features: unknown[] }).features.length !== 1
  ) {
    throw technical("DecodeFailed", `Boundary GeoJSON ${artifact.artifactId} must contain one feature.`);
  }
  const feature = (value as { features: Array<{ geometry?: unknown; properties?: unknown }> }).features[0];
  const properties = feature.properties as Record<string, unknown> | undefined;
  if (
    properties?.status !== "selected-scope-approximation" ||
    properties.hazardExtentClaim !== false ||
    (artifact.role === "coastal-boundary" && properties.role !== "product-eligibility-only")
  ) {
    throw technical("IntegrityFailed", `Boundary GeoJSON ${artifact.artifactId} changed its scope semantics.`);
  }
  return multiPolygon(feature.geometry, artifact.artifactId);
}

async function decodeBoundary(
  artifact: ResolvedArtifact,
  signal: AbortSignal,
  transport: GeographyTransport,
): Promise<MultiPolygonGeometry> {
  const bytes = await verifiedArtifactBytes(artifact, signal, transport);
  if (artifact.mediaType === "application/vnd.apache.parquet") {
    return decodeGeoParquet(artifact, bytes);
  }
  if (artifact.mediaType === "application/geo+json") {
    return decodeGeoJson(artifact, bytes);
  }
  throw technical("SchemaInvalid", `Boundary artifact ${artifact.artifactId} has no exact browser decoder.`);
}

function resolveBoundaryArtifact(
  context: ReleaseContext,
  role: "support-boundary" | "coastal-boundary",
): ResolvedArtifact {
  const candidates = Object.values(context.artifacts).filter(
    (artifact) =>
      artifact.role === role &&
      BOUNDARY_MEDIA_TYPES.includes(
        artifact.mediaType as (typeof BOUNDARY_MEDIA_TYPES)[number],
      ),
  );
  const preferred = candidates.filter(
    (artifact) => artifact.mediaType === "application/vnd.apache.parquet",
  );
  const selected = preferred.length > 0 ? preferred : candidates;
  if (selected.length !== 1) {
    throw technical(
      "SchemaInvalid",
      `The release must declare exactly one decodable ${role} artifact (GeoParquet preferred).`,
    );
  }
  return selected[0];
}

function ringLocation(point: Position, ring: Ring): -1 | 0 | 1 {
  let inside = false;
  for (let index = 0, previous = ring.length - 1; index < ring.length; previous = index++) {
    const start = ring[previous];
    const end = ring[index];
    const cross =
      (point[0] - start[0]) * (end[1] - start[1]) -
      (point[1] - start[1]) * (end[0] - start[0]);
    if (
      Math.abs(cross) <= Number.EPSILON * 64 &&
      point[0] >= Math.min(start[0], end[0]) &&
      point[0] <= Math.max(start[0], end[0]) &&
      point[1] >= Math.min(start[1], end[1]) &&
      point[1] <= Math.max(start[1], end[1])
    ) {
      return 0;
    }
    if (
      (start[1] > point[1]) !== (end[1] > point[1]) &&
      point[0] < ((end[0] - start[0]) * (point[1] - start[1])) / (end[1] - start[1]) + start[0]
    ) {
      inside = !inside;
    }
  }
  return inside ? 1 : -1;
}

function polygonCovers(point: Position, polygon: Polygon): boolean {
  const exterior = ringLocation(point, polygon[0]);
  if (exterior === -1) return false;
  if (exterior === 0) return true;
  for (const hole of polygon.slice(1)) {
    const location = ringLocation(point, hole);
    if (location === 0) return true;
    if (location === 1) return false;
  }
  return true;
}

export function geometryCovers(
  geometry: MultiPolygonGeometry,
  coordinates: Coordinates,
): boolean {
  const point: Position = [coordinates.longitude, coordinates.latitude];
  return geometry.coordinates.some((polygon) => polygonCovers(point, polygon));
}

export class StaticGeographyClassifier implements GeographyClassifier {
  readonly #transport: GeographyTransport;
  readonly #cache = new Map<string, SharedArtifactResource<BoundaryPair>>();

  constructor(options: { readonly transport?: GeographyTransport } = {}) {
    this.#transport = options.transport ?? defaultArtifactTransport;
  }

  async #boundaries(context: ReleaseContext, signal: AbortSignal): Promise<BoundaryPair> {
    const support = resolveBoundaryArtifact(context, "support-boundary");
    const coastal = resolveBoundaryArtifact(context, "coastal-boundary");
    const cacheKey = artifactCacheIdentity(context, [support, coastal]);
    let resource = this.#cache.get(cacheKey);
    if (!resource) {
      resource = createSharedArtifactResource((resourceSignal) =>
        Promise.all([
          decodeBoundary(support, resourceSignal, this.#transport),
          decodeBoundary(coastal, resourceSignal, this.#transport),
        ]).then(([supportGeometry, coastalGeometry]) =>
          Object.freeze({ support: supportGeometry, coastal: coastalGeometry }),
        ),
      );
      this.#cache.set(cacheKey, resource);
      while (this.#cache.size > 2) this.#cache.delete(this.#cache.keys().next().value as string);
      resource.pending.catch(() => {
        if (this.#cache.get(cacheKey) === resource) this.#cache.delete(cacheKey);
      });
    }
    return waitForSharedArtifact(
      resource,
      signal,
      "Geography classification was cancelled.",
      () => {
        if (this.#cache.get(cacheKey) === resource) this.#cache.delete(cacheKey);
      },
    );
  }

  async classify(
    context: ReleaseContext,
    coordinates: Coordinates,
    signal: AbortSignal,
  ): Promise<GeographyClassification> {
    if (signal.aborted) throw technical("Aborted", "Geography classification was cancelled.", true);
    const boundaries = await this.#boundaries(context, signal);
    if (signal.aborted) throw technical("Aborted", "Geography classification was cancelled.", true);
    if (!geometryCovers(boundaries.support, coordinates)) return "OutsideEurope";
    if (!geometryCovers(boundaries.coastal, coordinates)) return "InEuropeOutsideCoastalZone";
    return "InEuropeAndCoastalZone";
  }
}

export function isBoundaryArtifact(artifact: ReleaseArtifactV2): boolean {
  return artifact.role === "support-boundary" || artifact.role === "coastal-boundary";
}
