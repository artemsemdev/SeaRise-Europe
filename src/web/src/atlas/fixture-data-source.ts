import { zlibSync } from "fflate";
import {
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
  throwIfAborted,
} from "./data-source";
import {
  SYNTHETIC_ATLAS_CATALOG,
  SYNTHETIC_ATLAS_GRIDS,
  SYNTHETIC_ATLAS_PLACES,
  searchSyntheticAtlasPlaces,
  syntheticAtlasDepthAt,
  syntheticAtlasInspectionAt,
} from "./synthetic-fixture";

const TILE_SIZE = 256;
const PNG_SIGNATURE = new Uint8Array([137, 80, 78, 71, 13, 10, 26, 10]);
const DEPTH_COLORS = Object.freeze([
  [123, 220, 241, 195],
  [82, 198, 231, 205],
  [45, 167, 219, 215],
  [29, 128, 198, 225],
  [31, 91, 170, 235],
  [40, 60, 127, 245],
] as const);

function writeUint32(target: Uint8Array, offset: number, value: number): void {
  new DataView(target.buffer, target.byteOffset, target.byteLength).setUint32(offset, value, false);
}

function crc32(bytes: Uint8Array): number {
  let crc = 0xffffffff;
  for (const byte of bytes) {
    crc ^= byte;
    for (let bit = 0; bit < 8; bit += 1) crc = (crc >>> 1) ^ (0xedb88320 & -(crc & 1));
  }
  return (crc ^ 0xffffffff) >>> 0;
}

function pngChunk(name: string, payload: Uint8Array): Uint8Array {
  const type = new TextEncoder().encode(name);
  const chunk = new Uint8Array(12 + payload.length);
  writeUint32(chunk, 0, payload.length);
  chunk.set(type, 4);
  chunk.set(payload, 8);
  writeUint32(chunk, 8 + payload.length, crc32(chunk.subarray(4, 8 + payload.length)));
  return chunk;
}

function concatBytes(parts: readonly Uint8Array[]): Uint8Array {
  const output = new Uint8Array(parts.reduce((total, part) => total + part.length, 0));
  let offset = 0;
  for (const part of parts) {
    output.set(part, offset);
    offset += part.length;
  }
  return output;
}

function encodePng(rgba: Uint8Array): ArrayBuffer {
  const header = new Uint8Array(13);
  writeUint32(header, 0, TILE_SIZE);
  writeUint32(header, 4, TILE_SIZE);
  header.set([8, 6, 0, 0, 0], 8);
  const scanlines = new Uint8Array(TILE_SIZE * (1 + TILE_SIZE * 4));
  for (let row = 0; row < TILE_SIZE; row += 1) {
    scanlines.set(rgba.subarray(row * TILE_SIZE * 4, (row + 1) * TILE_SIZE * 4), row * (1 + TILE_SIZE * 4) + 1);
  }
  const bytes = concatBytes([
    PNG_SIGNATURE,
    pngChunk("IHDR", header),
    pngChunk("IDAT", zlibSync(scanlines, { level: 6 })),
    pngChunk("IEND", new Uint8Array()),
  ]);
  return bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength) as ArrayBuffer;
}

function longitudeAt(x: number, z: number, pixel: number): number {
  return ((x + (pixel + 0.5) / TILE_SIZE) / 2 ** z) * 360 - 180;
}

function latitudeAt(y: number, z: number, pixel: number): number {
  const normalized = 1 - 2 * (y + (pixel + 0.5) / TILE_SIZE) / 2 ** z;
  return Math.atan(Math.sinh(Math.PI * normalized)) * 180 / Math.PI;
}

function colorForDepth(depth: number): readonly [number, number, number, number] {
  const thresholds = [0.25, 0.5, 1, 2, 5];
  let index = 0;
  while (index < thresholds.length && depth > thresholds[index]) index += 1;
  return DEPTH_COLORS[index];
}

let unknownTilePng: ArrayBuffer | undefined;

function renderTile(request: AtlasTileRequest): AtlasTileResponse {
  const grid = SYNTHETIC_ATLAS_GRIDS.find(({ year, protection }) =>
    year === request.year && protection === request.protection)!;
  const [west, south, east, north] = grid.extent.bounds;
  // Monotonic pixel-center bounds prove every sample is unknown outside the
  // authored grid; avoid scanning 65,536 empty pixels for each overview tile.
  if (longitudeAt(request.x, request.z, TILE_SIZE - 1) < west
      || longitudeAt(request.x, request.z, 0) > east
      || latitudeAt(request.y, request.z, 0) < south
      || latitudeAt(request.y, request.z, TILE_SIZE - 1) > north) {
    unknownTilePng ??= encodePng(new Uint8Array(TILE_SIZE * TILE_SIZE * 4));
    // Callers can transfer the buffer to a worker without detaching the cache.
    return Object.freeze({ data: unknownTilePng.slice(0), validPixels: 0, floodPixels: 0 });
  }
  const rgba = new Uint8Array(TILE_SIZE * TILE_SIZE * 4);
  let validPixels = 0;
  let floodPixels = 0;
  for (let row = 0; row < TILE_SIZE; row += 1) {
    const latitude = latitudeAt(request.y, request.z, row);
    for (let column = 0; column < TILE_SIZE; column += 1) {
      const longitude = longitudeAt(request.x, request.z, column);
      const depth = syntheticAtlasDepthAt([longitude, latitude], request.year, request.protection);
      if (depth === null) continue;
      validPixels += 1;
      if (depth === 0) continue;
      floodPixels += 1;
      rgba.set(colorForDepth(depth), (row * TILE_SIZE + column) * 4);
    }
  }
  const counts = validateAtlasTileCounts({ validPixels, floodPixels });
  return Object.freeze({ data: encodePng(rgba), ...counts });
}

export class FixtureAtlasDataSource implements AtlasDataSource {
  readonly edition = "synthetic-fixture" as const;

  async getCatalog(options: AtlasRequestOptions = {}) {
    throwIfAborted(options.signal);
    return SYNTHETIC_ATLAS_CATALOG;
  }

  async search(query: string, options: AtlasRequestOptions = {}) {
    throwIfAborted(options.signal);
    if (typeof query !== "string" || query.length > 160) {
      throw new AtlasDataSourceError("invalid-request", "Fixture atlas search query is invalid.");
    }
    return searchSyntheticAtlasPlaces(query);
  }

  async getPlace(id: string, options: AtlasRequestOptions = {}) {
    throwIfAborted(options.signal);
    if (typeof id !== "string" || !id || id.length > 128) {
      throw new AtlasDataSourceError("invalid-request", "Fixture atlas place id is invalid.");
    }
    return SYNTHETIC_ATLAS_PLACES.find((place) => place.id === id) ?? null;
  }

  async inspect(request: AtlasInspectionRequest) {
    assertInspectionRequest(request);
    return syntheticAtlasInspectionAt(request.coordinates, request.protection);
  }

  async getTile(request: AtlasTileRequest): Promise<AtlasTileResponse> {
    assertTileRequest(request);
    const response = renderTile(request);
    throwIfAborted(request.signal);
    return response;
  }
}

export function createFixtureAtlasDataSource(): AtlasDataSource {
  return new FixtureAtlasDataSource();
}
