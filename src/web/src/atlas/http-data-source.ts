import {
  type AtlasCatalogV1,
  type AtlasInspectionV1,
  type AtlasPlaceSearchV1,
  type AtlasPlaceV1,
  validateAtlasCatalog,
  validateAtlasInspection,
  validateAtlasPlace,
  validateAtlasPlaceSearch,
  validateAtlasTileCounts,
} from "./browser-data-contract";
import {
  AtlasDataSourceError,
  type AtlasDataSource,
  type AtlasInspectionRequest,
  type AtlasRequestOptions,
  type AtlasTileRequest,
  type AtlasTileResponse,
  assertInspectionRequest,
  assertTileRequest,
  isAbortError,
  throwIfAborted,
} from "./data-source";

export interface HttpAtlasDataSourceOptions {
  readonly baseUrl?: string;
  readonly fetch?: typeof globalThis.fetch;
}

function normalizedBaseUrl(value: string): string {
  if (typeof value !== "string" || !value || value.includes("?") || value.includes("#")) {
    throw new AtlasDataSourceError("invalid-request", "Real-local atlas base URL is invalid.");
  }
  return value.replace(/\/+$/u, "");
}

function contentType(response: Response): string {
  return response.headers.get("content-type")?.split(";", 1)[0].trim().toLowerCase() ?? "";
}

function parseCount(response: Response, name: string): number {
  const value = response.headers.get(name);
  if (value === null || !/^(0|[1-9][0-9]*)$/u.test(value)) {
    throw new AtlasDataSourceError("invalid-response", `Real-local atlas tile is missing ${name}.`);
  }
  return Number(value);
}

function pngBytes(data: ArrayBuffer): boolean {
  const signature = [137, 80, 78, 71, 13, 10, 26, 10];
  const bytes = new Uint8Array(data);
  return bytes.length > signature.length && signature.every((value, index) => bytes[index] === value);
}

export class HttpAtlasDataSource implements AtlasDataSource {
  readonly edition = "real-local" as const;
  readonly #baseUrl: string;
  readonly #fetch: typeof globalThis.fetch;

  constructor(options: HttpAtlasDataSourceOptions = {}) {
    this.#baseUrl = normalizedBaseUrl(options.baseUrl ?? "/atlas-data");
    this.#fetch = options.fetch ?? globalThis.fetch.bind(globalThis);
  }

  async #response(path: string, signal?: AbortSignal): Promise<Response> {
    throwIfAborted(signal);
    try {
      return await this.#fetch(`${this.#baseUrl}${path}`, { method: "GET", signal });
    } catch (error) {
      if (isAbortError(error, signal)) throw error;
      throw new AtlasDataSourceError("unavailable", "The real-local atlas service is unavailable.", { cause: error });
    }
  }

  async #json(path: string, signal?: AbortSignal): Promise<unknown> {
    const response = await this.#response(path, signal);
    if (!response.ok) throw new AtlasDataSourceError("unavailable", `The real-local atlas request failed with HTTP ${response.status}.`);
    if (contentType(response) !== "application/json") {
      throw new AtlasDataSourceError("invalid-response", "The real-local atlas returned a non-JSON response.");
    }
    try {
      return await response.json();
    } catch (error) {
      if (isAbortError(error, signal)) throw error;
      throw new AtlasDataSourceError("invalid-response", "The real-local atlas returned malformed JSON.", { cause: error });
    }
  }

  #validated<T>(read: () => T, message: string): T {
    try {
      return read();
    } catch (error) {
      if (error instanceof AtlasDataSourceError) throw error;
      throw new AtlasDataSourceError("invalid-response", message, { cause: error });
    }
  }

  async getCatalog(options: AtlasRequestOptions = {}): Promise<AtlasCatalogV1> {
    const value = await this.#json("/manifest.json", options.signal);
    const catalog = this.#validated(() => validateAtlasCatalog(value), "The real-local atlas catalog is invalid.");
    if (catalog.edition !== this.edition) {
      throw new AtlasDataSourceError("invalid-response", "The real-local atlas catalog has the wrong edition.");
    }
    return catalog;
  }

  async search(query: string, options: AtlasRequestOptions = {}): Promise<AtlasPlaceSearchV1> {
    if (typeof query !== "string" || query.length > 160) {
      throw new AtlasDataSourceError("invalid-request", "Atlas search query must contain at most 160 characters.");
    }
    const value = await this.#json(`/europe/search?q=${encodeURIComponent(query)}`, options.signal);
    return this.#validated(() => validateAtlasPlaceSearch(value), "The real-local atlas search response is invalid.");
  }

  async getPlace(id: string, options: AtlasRequestOptions = {}): Promise<AtlasPlaceV1 | null> {
    if (typeof id !== "string" || !id || id.length > 128) {
      throw new AtlasDataSourceError("invalid-request", "Atlas place id must contain between 1 and 128 characters.");
    }
    const response = await this.#response(`/europe/place?id=${encodeURIComponent(id)}`, options.signal);
    if (response.status === 404) return null;
    if (!response.ok) throw new AtlasDataSourceError("unavailable", `The real-local place request failed with HTTP ${response.status}.`);
    if (contentType(response) !== "application/json") {
      throw new AtlasDataSourceError("invalid-response", "The real-local place response is not JSON.");
    }
    try {
      return validateAtlasPlace(await response.json());
    } catch (error) {
      if (isAbortError(error, options.signal)) throw error;
      if (error instanceof AtlasDataSourceError) throw error;
      throw new AtlasDataSourceError("invalid-response", "The real-local place response is invalid.", { cause: error });
    }
  }

  async inspect(request: AtlasInspectionRequest): Promise<AtlasInspectionV1> {
    assertInspectionRequest(request);
    const query = new URLSearchParams({
      lon: String(request.coordinates[0]),
      lat: String(request.coordinates[1]),
      defenses: request.protection,
    });
    const value = await this.#json(`/inspect?${query}`, request.signal);
    const result = this.#validated(() => validateAtlasInspection(value), "The real-local atlas inspection response is invalid.");
    if (result.protection !== request.protection
        || result.coordinates[0] !== request.coordinates[0]
        || result.coordinates[1] !== request.coordinates[1]) {
      throw new AtlasDataSourceError("invalid-response", "The real-local inspection response does not match its request.");
    }
    return result;
  }

  async getTile(request: AtlasTileRequest): Promise<AtlasTileResponse> {
    assertTileRequest(request);
    const response = await this.#response(
      `/tiles/${request.year}/${request.protection}/${request.z}/${request.x}/${request.y}.png`,
      request.signal,
    );
    if (!response.ok) throw new AtlasDataSourceError("unavailable", `The real-local tile request failed with HTTP ${response.status}.`);
    if (contentType(response) !== "image/png") {
      throw new AtlasDataSourceError("invalid-response", "The real-local tile response is not a PNG.");
    }
    const counts = this.#validated(() => validateAtlasTileCounts({
      validPixels: parseCount(response, "x-valid-pixels"),
      floodPixels: parseCount(response, "x-flood-pixels"),
    }), "The real-local atlas tile counts are invalid.");
    const data = await response.arrayBuffer();
    throwIfAborted(request.signal);
    if (!pngBytes(data)) throw new AtlasDataSourceError("invalid-response", "The real-local tile has an invalid PNG signature.");
    return Object.freeze({ data, ...counts });
  }
}

export function createRealLocalAtlasDataSource(options: HttpAtlasDataSourceOptions = {}): AtlasDataSource {
  return new HttpAtlasDataSource(options);
}
