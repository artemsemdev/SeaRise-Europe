import { describe, expect, it } from "vitest";
import { ATLAS_PROTECTIONS, ATLAS_YEARS, validateAtlasCatalog, validateAtlasInspection, validateAtlasPlaceSearch, validateAtlasTileCounts } from "./browser-data-contract";
import {
  SYNTHETIC_ATLAS_CATALOG,
  SYNTHETIC_ATLAS_GRIDS,
  SYNTHETIC_ATLAS_INSPECTIONS,
  SYNTHETIC_ATLAS_PLACES,
  searchSyntheticAtlasPlaces,
  syntheticAtlasInspection,
} from "./synthetic-fixture";

describe("coastal atlas synthetic fixture", () => {
  it("is explicitly illustrative and complete without private data authority", () => {
    expect(validateAtlasCatalog(SYNTHETIC_ATLAS_CATALOG).edition).toBe("synthetic-fixture");
    expect(SYNTHETIC_ATLAS_CATALOG.source.name).toMatch(/illustrative synthetic/u);
    expect(SYNTHETIC_ATLAS_CATALOG.source.name).not.toMatch(/coclico/iu);
    expect(SYNTHETIC_ATLAS_CATALOG.layers).toHaveLength(6);
    expect(JSON.stringify(SYNTHETIC_ATLAS_CATALOG)).not.toMatch(/sha256|byteSize|inputs|filePath|\.tif|raw\//u);
  });

  it("provides four stable coastal places and deterministic search", () => {
    expect(SYNTHETIC_ATLAS_PLACES.map(({ id }) => id)).toEqual([
      "fixture:venice",
      "fixture:rotterdam",
      "fixture:hamburg",
      "fixture:bordeaux",
    ]);
    expect(validateAtlasPlaceSearch({ results: SYNTHETIC_ATLAS_PLACES, totalPlaces: 4 }).results).toHaveLength(4);
    expect(searchSyntheticAtlasPlaces("rot").totalPlaces).toBe(4);
    expect(searchSyntheticAtlasPlaces("rot").results.map(({ name }) => name)).toEqual(["Rotterdam"]);
    expect(searchSyntheticAtlasPlaces("  FRANCE ").results.map(({ name }) => name)).toEqual(["Bordeaux"]);
    expect(searchSyntheticAtlasPlaces("missing").results).toEqual([]);
    expect(searchSyntheticAtlasPlaces("rot")).toEqual(searchSyntheticAtlasPlaces("rot"));
  });

  it("provides both defenses at every place with all three point meanings", () => {
    expect(SYNTHETIC_ATLAS_INSPECTIONS).toHaveLength(SYNTHETIC_ATLAS_PLACES.length * ATLAS_PROTECTIONS.length);
    SYNTHETIC_ATLAS_INSPECTIONS.forEach((inspection) => expect(validateAtlasInspection(inspection)).toEqual(inspection));

    const meanings = new Set(SYNTHETIC_ATLAS_INSPECTIONS.flatMap((inspection) =>
      inspection.results.map(({ status }) => status)));
    expect(meanings).toEqual(new Set(["unknown", "zero", "flooded"]));

    expect(syntheticAtlasInspection("fixture:venice", "unprotected")?.results).toEqual([
      { year: 2030, status: "zero", depthMeters: 0 },
      { year: 2050, status: "flooded", depthMeters: 0.4 },
      { year: 2100, status: "flooded", depthMeters: 1.2 },
    ]);
    expect(syntheticAtlasInspection("fixture:venice", "protected")?.results).toEqual([
      { year: 2030, status: "unknown", depthMeters: null },
      { year: 2050, status: "zero", depthMeters: 0 },
      { year: 2100, status: "flooded", depthMeters: 0.6 },
    ]);
    expect(syntheticAtlasInspection("missing", "protected")).toBeNull();
  });

  it("has one bounded Venice source grid for every layer combination", () => {
    expect(SYNTHETIC_ATLAS_GRIDS).toHaveLength(6);
    const combinations = SYNTHETIC_ATLAS_GRIDS.map(({ year, protection }) => `${year}/${protection}`);
    expect(new Set(combinations)).toEqual(new Set(ATLAS_YEARS.flatMap((year) =>
      ATLAS_PROTECTIONS.map((protection) => `${year}/${protection}`))));

    for (const fixture of SYNTHETIC_ATLAS_GRIDS) {
      expect(fixture.extent).toMatchObject({
        crs: "EPSG:4326", width: 4, height: 4, rowOrder: "north-to-south", nominalCellSizeMeters: 25,
      });
      expect(fixture.extent.bounds[2] - fixture.extent.bounds[0]).toBeLessThan(0.002);
      expect(fixture.extent.bounds[3] - fixture.extent.bounds[1]).toBeLessThan(0.002);
      expect(fixture.depthsMeters).toHaveLength(16);
      expect(fixture.displayAlpha).toEqual(fixture.depthsMeters.map((depth) =>
        depth !== null && depth > 0 ? 255 : 0));

      const actual = {
        validPixels: fixture.depthsMeters.filter((depth) => depth !== null).length,
        floodPixels: fixture.depthsMeters.filter((depth) => depth !== null && depth > 0).length,
      };
      expect(validateAtlasTileCounts(fixture.expectedTileCounts)).toEqual(actual);
    }
  });

  it("keeps transparent valid zero distinct from transparent unknown", () => {
    const allZero = SYNTHETIC_ATLAS_GRIDS.find(({ year, protection }) =>
      year === 2030 && protection === "protected");
    expect(allZero).toBeDefined();
    expect(allZero?.expectedTileCounts).toEqual({ validPixels: 1, floodPixels: 0 });
    expect(allZero?.depthsMeters.filter((depth) => depth === 0)).toHaveLength(1);
    expect(allZero?.depthsMeters.filter((depth) => depth === null)).toHaveLength(15);
    expect(new Set(allZero?.displayAlpha)).toEqual(new Set([0]));
  });
});
