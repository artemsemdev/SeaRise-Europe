import {
  ATLAS_PROTECTIONS,
  ATLAS_YEARS,
  type AtlasBounds,
  type AtlasCatalogV1,
  type AtlasInspectionV1,
  type AtlasPlaceSearchV1,
  type AtlasPlaceV1,
  type AtlasPointResultV1,
  type AtlasProtection,
  type AtlasTileCountsV1,
  type AtlasYear,
  validateAtlasCatalog,
  validateAtlasInspection,
  validateAtlasPlace,
  validateAtlasPlaceSearch,
  validateAtlasTileCounts,
} from "./browser-data-contract";

export const SYNTHETIC_ATLAS_CATALOG: AtlasCatalogV1 = validateAtlasCatalog({
  schemaVersion: "coastal-atlas-browser-v1",
  edition: "synthetic-fixture",
  bounds: [-30.5, 29.5, 45.5, 75.5],
  scenario: "ssp585",
  condition: "spring-high-tide",
  cellSizeMeters: 25,
  source: {
    name: "SeaRise Europe illustrative synthetic coastal fixture",
    url: "https://github.com/artemsemdev/SeaRise-Europe",
    methodologyUrl: "https://github.com/artemsemdev/SeaRise-Europe/issues/495",
    license: "MIT",
    notes: [
      "Authored deterministic values for software tests; this is not CoCliCo data or scientific evidence.",
      "The fixture makes no publication, flood-risk, safety, or real-world accuracy claim.",
    ],
  },
  layers: ATLAS_YEARS.flatMap((year) => ATLAS_PROTECTIONS.map((protection) => ({
    id: `ssp585-${year}-${protection}`,
    scenario: "ssp585",
    year,
    protection,
    status: "available",
  }))),
});

export const SYNTHETIC_ATLAS_PLACES: readonly AtlasPlaceV1[] = Object.freeze([
  validateAtlasPlace({
    id: "fixture:venice", name: "Venice", countryCode: "IT", countryName: "Italy",
    coordinates: [12.3155, 45.4408],
  }),
  validateAtlasPlace({
    id: "fixture:rotterdam", name: "Rotterdam", countryCode: "NL", countryName: "Netherlands",
    coordinates: [4.4777, 51.9244],
  }),
  validateAtlasPlace({
    id: "fixture:hamburg", name: "Hamburg", countryCode: "DE", countryName: "Germany",
    coordinates: [9.9937, 53.5511],
  }),
  validateAtlasPlace({
    id: "fixture:bordeaux", name: "Bordeaux", countryCode: "FR", countryName: "France",
    coordinates: [-0.5792, 44.8378],
  }),
]);

function normalizeSearchText(value: string): string {
  return value.normalize("NFKD").replace(/\p{M}+/gu, "").toLowerCase().trim().replace(/\s+/gu, " ");
}

export function searchSyntheticAtlasPlaces(query: string): AtlasPlaceSearchV1 {
  const normalized = normalizeSearchText(query);
  const results = normalized.length === 0 ? [] : SYNTHETIC_ATLAS_PLACES.filter((place) =>
    normalizeSearchText(`${place.name} ${place.countryName} ${place.countryCode}`).includes(normalized));
  return validateAtlasPlaceSearch({ results, totalPlaces: SYNTHETIC_ATLAS_PLACES.length });
}

function pointResult(year: AtlasYear, depthMeters: number | null): AtlasPointResultV1 {
  return Object.freeze({
    year,
    status: depthMeters === null ? "unknown" : depthMeters === 0 ? "zero" : "flooded",
    depthMeters,
  });
}

function inspection(
  place: AtlasPlaceV1,
  protection: AtlasProtection,
  depths: readonly [number | null, number | null, number | null],
): AtlasInspectionV1 {
  return validateAtlasInspection({
    coordinates: place.coordinates,
    protection,
    cellSizeMeters: 25,
    results: ATLAS_YEARS.map((year, index) => pointResult(year, depths[index])),
  });
}

const INSPECTION_DEPTHS: Readonly<Record<string, readonly [number | null, number | null, number | null]>> = Object.freeze({
  "fixture:venice/unprotected": [0, 0.4, 1.2],
  "fixture:venice/protected": [null, 0, 0.6],
  "fixture:rotterdam/unprotected": [null, 0, 0.35],
  "fixture:rotterdam/protected": [null, null, 0],
  "fixture:hamburg/unprotected": [0, 0, 0.2],
  "fixture:hamburg/protected": [null, null, null],
  "fixture:bordeaux/unprotected": [null, 0.15, 0.5],
  "fixture:bordeaux/protected": [null, 0, 0.2],
});

export const SYNTHETIC_ATLAS_INSPECTIONS: readonly AtlasInspectionV1[] = Object.freeze(
  SYNTHETIC_ATLAS_PLACES.flatMap((place) => ATLAS_PROTECTIONS.map((protection) =>
    inspection(place, protection, INSPECTION_DEPTHS[`${place.id}/${protection}`]))),
);

export function syntheticAtlasInspection(placeId: string, protection: AtlasProtection): AtlasInspectionV1 | null {
  const place = SYNTHETIC_ATLAS_PLACES.find((candidate) => candidate.id === placeId);
  if (!place) return null;
  return SYNTHETIC_ATLAS_INSPECTIONS.find((candidate) =>
    candidate.coordinates[0] === place.coordinates[0]
    && candidate.coordinates[1] === place.coordinates[1]
    && candidate.protection === protection) ?? null;
}

export interface SyntheticAtlasGridV1 {
  readonly year: AtlasYear;
  readonly protection: AtlasProtection;
  readonly extent: Readonly<{
    readonly crs: "EPSG:4326";
    readonly bounds: AtlasBounds;
    readonly width: 4;
    readonly height: 4;
    readonly rowOrder: "north-to-south";
    readonly nominalCellSizeMeters: 25;
  }>;
  /** Row-major values: null is unknown, 0 is valid zero, and positive is flooded. */
  readonly depthsMeters: readonly (number | null)[];
  /** Display alpha only; both unknown and valid zero intentionally remain transparent. */
  readonly displayAlpha: readonly number[];
  readonly expectedTileCounts: AtlasTileCountsV1;
}

const VENICE_GRID_EXTENT = Object.freeze({
  crs: "EPSG:4326",
  bounds: Object.freeze([12.31486, 45.44035, 12.31614, 45.44125]) as AtlasBounds,
  width: 4,
  height: 4,
  rowOrder: "north-to-south",
  nominalCellSizeMeters: 25,
} as const);

function grid(
  year: AtlasYear,
  protection: AtlasProtection,
  depthsMeters: readonly (number | null)[],
  validPixels: number,
  floodPixels: number,
): SyntheticAtlasGridV1 {
  if (depthsMeters.length !== VENICE_GRID_EXTENT.width * VENICE_GRID_EXTENT.height
      || depthsMeters.some((depth) => depth !== null && (!Number.isFinite(depth) || depth < 0))) {
    throw new TypeError("Synthetic atlas grid must contain sixteen null or non-negative finite depth cells.");
  }
  return Object.freeze({
    year,
    protection,
    extent: VENICE_GRID_EXTENT,
    depthsMeters: Object.freeze([...depthsMeters]),
    displayAlpha: Object.freeze(depthsMeters.map((depth) => depth !== null && depth > 0 ? 255 : 0)),
    expectedTileCounts: validateAtlasTileCounts({ validPixels, floodPixels }),
  });
}

const N = null;
export const SYNTHETIC_ATLAS_GRIDS: readonly SyntheticAtlasGridV1[] = Object.freeze([
  grid(2030, "unprotected", [N, N, N, N, N, 0, 0, N, N, 0, 0.1, N, N, N, N, N], 4, 1),
  grid(2050, "unprotected", [N, N, N, N, N, 0, 0.15, N, N, 0, 0.4, 0.3, N, N, N, N], 5, 3),
  grid(2100, "unprotected", [N, N, N, N, 0, 0.2, 0.4, N, 0.1, 0, 1.2, 0.8, N, N, N, N], 7, 5),
  grid(2030, "protected", [N, N, N, N, N, 0, N, N, N, N, N, N, N, N, N, N], 1, 0),
  grid(2050, "protected", [N, N, N, N, N, 0, 0.1, N, N, 0, 0, N, N, N, N, N], 4, 1),
  grid(2100, "protected", [N, N, N, N, 0, 0.1, 0.2, N, N, 0, 0.6, 0.3, N, N, N, N], 6, 4),
]);
