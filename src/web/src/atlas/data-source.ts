import type {
  AtlasCatalogV1,
  AtlasEdition,
  AtlasInspectionV1,
  AtlasPlaceSearchV1,
  AtlasPlaceV1,
  AtlasPoint,
  AtlasProtection,
  AtlasYear,
} from "./browser-data-contract";

export type AtlasDataSourceErrorCode = "invalid-request" | "unavailable" | "invalid-response";

export class AtlasDataSourceError extends Error {
  readonly code: AtlasDataSourceErrorCode;

  constructor(code: AtlasDataSourceErrorCode, message: string, options?: ErrorOptions) {
    super(message, options);
    this.name = "AtlasDataSourceError";
    this.code = code;
  }
}

export interface AtlasRequestOptions {
  readonly signal?: AbortSignal;
}

export interface AtlasInspectionRequest extends AtlasRequestOptions {
  readonly coordinates: AtlasPoint;
  readonly protection: AtlasProtection;
}

export interface AtlasTileRequest extends AtlasRequestOptions {
  readonly year: AtlasYear;
  readonly protection: AtlasProtection;
  readonly z: number;
  readonly x: number;
  readonly y: number;
}

export interface AtlasTileResponse {
  readonly data: ArrayBuffer;
  readonly validPixels: number;
  readonly floodPixels: number;
}

export interface AtlasDataSource {
  readonly edition: AtlasEdition;
  getCatalog(options?: AtlasRequestOptions): Promise<AtlasCatalogV1>;
  search(query: string, options?: AtlasRequestOptions): Promise<AtlasPlaceSearchV1>;
  getPlace(id: string, options?: AtlasRequestOptions): Promise<AtlasPlaceV1 | null>;
  inspect(request: AtlasInspectionRequest): Promise<AtlasInspectionV1>;
  getTile(request: AtlasTileRequest): Promise<AtlasTileResponse>;
}

export function throwIfAborted(signal?: AbortSignal): void {
  signal?.throwIfAborted();
}

export function assertInspectionRequest(request: AtlasInspectionRequest): void {
  throwIfAborted(request.signal);
  if (!Array.isArray(request.coordinates) || request.coordinates.length !== 2
      || request.coordinates.some((coordinate) => !Number.isFinite(coordinate))
      || request.coordinates[0] < -180 || request.coordinates[0] > 180
      || request.coordinates[1] < -85 || request.coordinates[1] > 85
      || (request.protection !== "unprotected" && request.protection !== "protected")) {
    throw new AtlasDataSourceError("invalid-request", "Atlas inspection request is outside the supported geography or defense settings.");
  }
}

export function assertTileRequest(request: AtlasTileRequest): void {
  throwIfAborted(request.signal);
  const limit = Number.isSafeInteger(request.z) && request.z >= 0 && request.z <= 18 ? 2 ** request.z : 0;
  if (!limit || !Number.isSafeInteger(request.x) || !Number.isSafeInteger(request.y)
      || request.x < 0 || request.y < 0 || request.x >= limit || request.y >= limit
      || ![2030, 2050, 2100].includes(request.year)
      || (request.protection !== "unprotected" && request.protection !== "protected")) {
    throw new AtlasDataSourceError("invalid-request", "Atlas tile request has an unsupported layer or Web Mercator coordinate.");
  }
}

export function isAbortError(error: unknown, signal?: AbortSignal): boolean {
  return signal?.aborted === true || (error instanceof DOMException && error.name === "AbortError");
}
