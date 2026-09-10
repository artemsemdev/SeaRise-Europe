export const ATLAS_YEARS = [2030, 2050, 2100] as const;
export const ATLAS_PROTECTIONS = ["unprotected", "protected"] as const;

export type AtlasYear = (typeof ATLAS_YEARS)[number];
export type AtlasProtection = (typeof ATLAS_PROTECTIONS)[number];
export type AtlasEdition = "real-local" | "synthetic-fixture";
export type AtlasLayerStatus = "available" | "no-valid-data";
export type AtlasPointStatus = "flooded" | "zero" | "unknown";
export type AtlasPoint = readonly [longitude: number, latitude: number];
export type AtlasBounds = readonly [west: number, south: number, east: number, north: number];

export interface AtlasCatalogSourceV1 {
  readonly name: string;
  readonly url: string;
  readonly methodologyUrl: string;
  readonly license: string;
  readonly notes: readonly string[];
}

export interface AtlasLayerV1 {
  readonly id: string;
  readonly scenario: "ssp585";
  readonly year: AtlasYear;
  readonly protection: AtlasProtection;
  readonly status: AtlasLayerStatus;
}

/**
 * Browser-safe catalog. Storage locations, byte sizes, checksums, and private
 * provenance receipts belong to the server-side disk manifest, never here.
 */
export interface AtlasCatalogV1 {
  readonly schemaVersion: "coastal-atlas-browser-v1";
  readonly edition: AtlasEdition;
  readonly bounds: AtlasBounds;
  readonly scenario: "ssp585";
  readonly condition: "spring-high-tide";
  readonly cellSizeMeters: 25;
  readonly source: AtlasCatalogSourceV1;
  readonly layers: readonly AtlasLayerV1[];
}

export interface AtlasPlaceV1 {
  readonly id: string;
  readonly name: string;
  readonly countryCode: string;
  readonly countryName: string;
  readonly coordinates: AtlasPoint;
}

export interface AtlasPlaceSearchV1 {
  readonly results: readonly AtlasPlaceV1[];
  readonly totalPlaces: number;
}

export interface AtlasPointResultV1 {
  readonly year: AtlasYear;
  readonly status: AtlasPointStatus;
  readonly depthMeters: number | null;
}

export interface AtlasInspectionV1 {
  readonly coordinates: AtlasPoint;
  readonly protection: AtlasProtection;
  readonly cellSizeMeters: 25;
  readonly results: readonly AtlasPointResultV1[];
}

/** Counts carried by tile response headers. Valid zero cells count as valid. */
export interface AtlasTileCountsV1 {
  readonly validPixels: number;
  readonly floodPixels: number;
}

export class AtlasContractError extends TypeError {
  constructor(message: string) {
    super(message);
    this.name = "AtlasContractError";
  }
}

function fail(message: string): never {
  throw new AtlasContractError(message);
}

function exactRecord(value: unknown, keys: readonly string[], name: string): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return fail(`${name} must be an object.`);
  }
  const record = value as Record<string, unknown>;
  const expected = new Set(keys);
  if (Object.keys(record).length !== expected.size || Object.keys(record).some((key) => !expected.has(key))) {
    fail(`${name} contains missing or additional properties.`);
  }
  return record;
}

function textValue(value: unknown, name: string, maximum = 512): string {
  if (typeof value !== "string" || value.trim() !== value || value.length === 0 || value.length > maximum) {
    fail(`${name} must be a non-empty trimmed string of at most ${maximum} characters.`);
  }
  return value;
}

function httpUrl(value: unknown, name: string): string {
  const text = textValue(value, name, 2048);
  let url: URL;
  try {
    url = new URL(text);
  } catch {
    return fail(`${name} must be an absolute HTTP(S) URL.`);
  }
  if (!new Set(["http:", "https:"]).has(url.protocol) || url.username || url.password) {
    fail(`${name} must be an absolute HTTP(S) URL without credentials.`);
  }
  return url.href;
}

function point(value: unknown, name: string): AtlasPoint {
  if (!Array.isArray(value) || value.length !== 2
      || value.some((coordinate) => typeof coordinate !== "number" || !Number.isFinite(coordinate))
      || value[0] < -180 || value[0] > 180 || value[1] < -85 || value[1] > 85) {
    return fail(`${name} must contain finite Web Mercator longitude and latitude.`);
  }
  return Object.freeze([value[0], value[1]]) as AtlasPoint;
}

function bounds(value: unknown): AtlasBounds {
  if (!Array.isArray(value) || value.length !== 4
      || value.some((coordinate) => typeof coordinate !== "number" || !Number.isFinite(coordinate))) {
    return fail("catalog.bounds must contain four finite coordinates.");
  }
  const [west, south, east, north] = value;
  if (west < -180 || east > 180 || south < -85 || north > 85 || west >= east || south >= north) {
    fail("catalog.bounds must be an ordered Web Mercator geographic extent.");
  }
  return Object.freeze([west, south, east, north]) as AtlasBounds;
}

function supportedYear(value: unknown, name: string): AtlasYear {
  if (!ATLAS_YEARS.includes(value as AtlasYear)) fail(`${name} is unsupported.`);
  return value as AtlasYear;
}

function supportedProtection(value: unknown, name: string): AtlasProtection {
  if (!ATLAS_PROTECTIONS.includes(value as AtlasProtection)) fail(`${name} is unsupported.`);
  return value as AtlasProtection;
}

function validateSource(value: unknown): AtlasCatalogSourceV1 {
  const source = exactRecord(value, ["name", "url", "methodologyUrl", "license", "notes"], "catalog.source");
  if (!Array.isArray(source.notes) || source.notes.length === 0 || source.notes.length > 16) {
    fail("catalog.source.notes must contain between one and sixteen notes.");
  }
  return Object.freeze({
    name: textValue(source.name, "catalog.source.name"),
    url: httpUrl(source.url, "catalog.source.url"),
    methodologyUrl: httpUrl(source.methodologyUrl, "catalog.source.methodologyUrl"),
    license: textValue(source.license, "catalog.source.license", 128),
    notes: Object.freeze(source.notes.map((note, index) => textValue(note, `catalog.source.notes[${index}]`, 2048))),
  });
}

function validateLayer(value: unknown): AtlasLayerV1 {
  const layer = exactRecord(value, ["id", "scenario", "year", "protection", "status"], "catalog layer");
  const year = supportedYear(layer.year, "catalog layer year");
  const protection = supportedProtection(layer.protection, "catalog layer protection");
  if (layer.scenario !== "ssp585") fail("catalog layer scenario is unsupported.");
  if (layer.status !== "available" && layer.status !== "no-valid-data") {
    fail("catalog layer status is unsupported.");
  }
  if (layer.id !== `ssp585-${year}-${protection}`) fail("catalog layer id does not match its identity.");
  return Object.freeze({
    id: layer.id,
    scenario: "ssp585",
    year,
    protection,
    status: layer.status,
  });
}

export function validateAtlasCatalog(value: unknown): AtlasCatalogV1 {
  const catalog = exactRecord(value, [
    "schemaVersion", "edition", "bounds", "scenario", "condition",
    "cellSizeMeters", "source", "layers",
  ], "atlas catalog");
  if (catalog.schemaVersion !== "coastal-atlas-browser-v1") fail("atlas catalog schema version is unsupported.");
  if (catalog.edition !== "real-local" && catalog.edition !== "synthetic-fixture") {
    fail("atlas catalog edition is unsupported.");
  }
  if (catalog.scenario !== "ssp585" || catalog.condition !== "spring-high-tide" || catalog.cellSizeMeters !== 25) {
    fail("atlas catalog scenario, condition, or cell size is unsupported.");
  }
  if (!Array.isArray(catalog.layers) || catalog.layers.length !== ATLAS_YEARS.length * ATLAS_PROTECTIONS.length) {
    fail("atlas catalog must contain all six year and defense combinations.");
  }
  const layers = catalog.layers.map(validateLayer);
  const identities = new Set(layers.map((layer) => `${layer.year}/${layer.protection}`));
  for (const year of ATLAS_YEARS) {
    for (const protection of ATLAS_PROTECTIONS) {
      if (!identities.has(`${year}/${protection}`)) {
        fail("atlas catalog has a duplicate or missing year and defense combination.");
      }
    }
  }
  return Object.freeze({
    schemaVersion: "coastal-atlas-browser-v1",
    edition: catalog.edition,
    bounds: bounds(catalog.bounds),
    scenario: "ssp585",
    condition: "spring-high-tide",
    cellSizeMeters: 25,
    source: validateSource(catalog.source),
    layers: Object.freeze(layers),
  });
}

export function validateAtlasPlace(value: unknown): AtlasPlaceV1 {
  const place = exactRecord(value, ["id", "name", "countryCode", "countryName", "coordinates"], "atlas place");
  const countryCode = textValue(place.countryCode, "atlas place countryCode", 2);
  if (!/^[A-Z]{2}$/u.test(countryCode)) fail("atlas place countryCode must be two uppercase ASCII letters.");
  return Object.freeze({
    id: textValue(place.id, "atlas place id", 128),
    name: textValue(place.name, "atlas place name", 256),
    countryCode,
    countryName: textValue(place.countryName, "atlas place countryName", 256),
    coordinates: point(place.coordinates, "atlas place coordinates"),
  });
}

export function validateAtlasPlaceSearch(value: unknown): AtlasPlaceSearchV1 {
  const search = exactRecord(value, ["results", "totalPlaces"], "atlas place search");
  if (!Array.isArray(search.results) || search.results.length > 12) {
    fail("atlas place search must contain at most twelve results.");
  }
  const results = search.results.map(validateAtlasPlace);
  if (new Set(results.map((place) => place.id)).size !== results.length) {
    fail("atlas place search contains duplicate place ids.");
  }
  if (!Number.isSafeInteger(search.totalPlaces) || Number(search.totalPlaces) < results.length
      || Number(search.totalPlaces) > 5_000_000) {
    fail("atlas place search totalPlaces must cover the results and stay within the browser limit.");
  }
  return Object.freeze({ results: Object.freeze(results), totalPlaces: Number(search.totalPlaces) });
}

function validatePointResult(value: unknown): AtlasPointResultV1 {
  const result = exactRecord(value, ["year", "status", "depthMeters"], "atlas point result");
  const year = supportedYear(result.year, "atlas point result year");
  if (result.status !== "flooded" && result.status !== "zero" && result.status !== "unknown") {
    fail("atlas point result status is unsupported.");
  }
  const validDepth = result.status === "unknown"
    ? result.depthMeters === null
    : result.status === "zero"
      ? result.depthMeters === 0
      : typeof result.depthMeters === "number" && Number.isFinite(result.depthMeters) && result.depthMeters > 0;
  if (!validDepth) fail("atlas point status and depthMeters disagree.");
  return Object.freeze({ year, status: result.status, depthMeters: result.depthMeters as number | null });
}

export function validateAtlasInspection(value: unknown): AtlasInspectionV1 {
  const inspection = exactRecord(value, ["coordinates", "protection", "cellSizeMeters", "results"], "atlas inspection");
  if (inspection.cellSizeMeters !== 25 || !Array.isArray(inspection.results) || inspection.results.length !== ATLAS_YEARS.length) {
    fail("atlas inspection must contain one result per supported year at 25 meter cell size.");
  }
  const results = inspection.results.map(validatePointResult);
  if (new Set(results.map((result) => result.year)).size !== ATLAS_YEARS.length
      || ATLAS_YEARS.some((year) => !results.some((result) => result.year === year))) {
    fail("atlas inspection has a duplicate or missing year.");
  }
  return Object.freeze({
    coordinates: point(inspection.coordinates, "atlas inspection coordinates"),
    protection: supportedProtection(inspection.protection, "atlas inspection protection"),
    cellSizeMeters: 25,
    results: Object.freeze(results),
  });
}

export function validateAtlasTileCounts(value: unknown): AtlasTileCountsV1 {
  const counts = exactRecord(value, ["validPixels", "floodPixels"], "atlas tile counts");
  if (!Number.isSafeInteger(counts.validPixels) || !Number.isSafeInteger(counts.floodPixels)
      || Number(counts.validPixels) < 0 || Number(counts.validPixels) > 65_536
      || Number(counts.floodPixels) < 0 || Number(counts.floodPixels) > Number(counts.validPixels)) {
    fail("atlas tile counts must be consistent non-negative 256 by 256 pixel counts.");
  }
  return Object.freeze({ validPixels: Number(counts.validPixels), floodPixels: Number(counts.floodPixels) });
}
