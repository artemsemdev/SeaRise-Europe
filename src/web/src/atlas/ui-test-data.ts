import { vi } from "vitest";
import { ATLAS_YEARS } from "./browser-data-contract";
import type { AtlasDataSource } from "./data-source";
import {
  SYNTHETIC_ATLAS_CATALOG,
  SYNTHETIC_ATLAS_PLACES,
  searchSyntheticAtlasPlaces,
  syntheticAtlasInspection,
} from "./synthetic-fixture";

/** Component tests inject a provider; they never contact the local adapter. */
export function fakeDataSource(edition: AtlasDataSource["edition"] = "synthetic-fixture") {
  return {
    edition,
    getCatalog: vi.fn<AtlasDataSource["getCatalog"]>().mockResolvedValue({ ...SYNTHETIC_ATLAS_CATALOG, edition }),
    search: vi.fn<AtlasDataSource["search"]>().mockImplementation(async (query) => searchSyntheticAtlasPlaces(query)),
    getPlace: vi.fn<AtlasDataSource["getPlace"]>().mockImplementation(async (id) =>
      SYNTHETIC_ATLAS_PLACES.find((place) => place.id === id) ?? null),
    inspect: vi.fn<AtlasDataSource["inspect"]>().mockImplementation(async ({ coordinates, protection }) => {
      const place = SYNTHETIC_ATLAS_PLACES.find((entry) => entry.coordinates.every((value, index) => value === coordinates[index]));
      return place ? syntheticAtlasInspection(place.id, protection)! : {
        coordinates, protection, cellSizeMeters: 25,
        results: ATLAS_YEARS.map((year) => ({ year, status: "unknown", depthMeters: null })),
      };
    }),
    getTile: vi.fn<AtlasDataSource["getTile"]>().mockRejectedValue(new Error("Map rendering is tested separately.")),
  } satisfies AtlasDataSource;
}
