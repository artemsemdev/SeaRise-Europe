import { describe, expect, it } from "vitest";
import {
  ATLAS_PROTECTIONS,
  ATLAS_YEARS,
  AtlasContractError,
  validateAtlasCatalog,
  validateAtlasInspection,
  validateAtlasPlace,
  validateAtlasPlaceSearch,
  validateAtlasTileCounts,
} from "./browser-data-contract";

function catalog() {
  return {
    schemaVersion: "coastal-atlas-browser-v1",
    edition: "real-local",
    bounds: [-30.5, 29.5, 45.5, 75.5],
    scenario: "ssp585",
    condition: "spring-high-tide",
    cellSizeMeters: 25,
    source: {
      name: "Example real local coastal source",
      url: "https://example.test/source",
      methodologyUrl: "https://example.test/methodology",
      license: "CC-BY-4.0",
      notes: ["Local-only source used by the real-data adapter."],
    },
    layers: ATLAS_YEARS.flatMap((year) => ATLAS_PROTECTIONS.map((protection) => ({
      id: `ssp585-${year}-${protection}`,
      scenario: "ssp585",
      year,
      protection,
      status: "available",
    }))),
  };
}

function inspection() {
  return {
    coordinates: [12.3155, 45.4408],
    protection: "unprotected",
    cellSizeMeters: 25,
    results: [
      { year: 2030, status: "unknown", depthMeters: null },
      { year: 2050, status: "zero", depthMeters: 0 },
      { year: 2100, status: "flooded", depthMeters: 0.75 },
    ],
  };
}

describe("coastal atlas browser catalog contract", () => {
  it("accepts the exact six supported combinations without exposing disk authority", () => {
    const validated = validateAtlasCatalog(catalog());

    expect(validated.layers).toHaveLength(6);
    expect(new Set(validated.layers.map(({ year, protection }) => `${year}/${protection}`)).size).toBe(6);
    expect(JSON.stringify(validated)).not.toMatch(/sha256|byteSize|inputs|\.tif|raw\//u);
    expect(Object.isFrozen(validated)).toBe(true);
    expect(Object.isFrozen(validated.layers)).toBe(true);
  });

  it.each([
    ["unsupported edition", (value: ReturnType<typeof catalog>) => { value.edition = "production"; }],
    ["unordered bounds", (value: ReturnType<typeof catalog>) => { value.bounds = [20, 30, 10, 40]; }],
    ["non-HTTP source", (value: ReturnType<typeof catalog>) => { value.source.url = "file:///private/source.tif"; }],
    ["empty source notes", (value: ReturnType<typeof catalog>) => { value.source.notes = []; }],
    ["wrong layer id", (value: ReturnType<typeof catalog>) => { value.layers[0].id = "wrong"; }],
    ["unsupported year", (value: ReturnType<typeof catalog>) => { (value.layers[0] as { year: number }).year = 2040; }],
    ["unsupported defense", (value: ReturnType<typeof catalog>) => { (value.layers[0] as { protection: string }).protection = "partial"; }],
  ])("rejects malformed catalog metadata: %s", (_name, mutate) => {
    const value = catalog();
    mutate(value);
    expect(() => validateAtlasCatalog(value)).toThrow(AtlasContractError);
  });

  it("rejects duplicate or missing combinations", () => {
    const duplicate = catalog();
    duplicate.layers[5] = { ...duplicate.layers[0] };
    expect(() => validateAtlasCatalog(duplicate)).toThrow(/duplicate or missing/u);

    const missing = catalog();
    missing.layers.pop();
    expect(() => validateAtlasCatalog(missing)).toThrow(/all six/u);
  });

  it("rejects private disk and provenance properties at every public boundary", () => {
    const withInput = catalog();
    Object.assign(withInput.layers[0], { inputs: [{ file: "raw/private.tif", sha256: "a".repeat(64) }] });
    expect(() => validateAtlasCatalog(withInput)).toThrow(/additional properties/u);

    const withSourceHash = catalog();
    Object.assign(withSourceHash.source, { sha256: "a".repeat(64) });
    expect(() => validateAtlasCatalog(withSourceHash)).toThrow(/additional properties/u);
  });
});

describe("coastal atlas place contracts", () => {
  const place = {
    id: "fixture:venice",
    name: "Venice",
    countryCode: "IT",
    countryName: "Italy",
    coordinates: [12.3155, 45.4408],
  };

  it("accepts a place and a unique bounded search result", () => {
    expect(validateAtlasPlace(place)).toEqual(place);
    expect(validateAtlasPlaceSearch({ results: [place], totalPlaces: 4 })).toEqual({ results: [place], totalPlaces: 4 });
  });

  it("rejects invalid geography, duplicate ids, and additional response metadata", () => {
    expect(() => validateAtlasPlace({ ...place, coordinates: [12, 90] })).toThrow(AtlasContractError);
    expect(() => validateAtlasPlaceSearch({ results: [place, place], totalPlaces: 4 })).toThrow(/duplicate/u);
    expect(() => validateAtlasPlaceSearch({ results: [place], totalPlaces: 0 })).toThrow(/totalPlaces/u);
    expect(() => validateAtlasPlaceSearch({ results: [place], totalPlaces: 4, sha256: "private" })).toThrow(/additional/u);
  });
});

describe("coastal atlas point and tile contracts", () => {
  it("preserves flooded, valid zero, and unknown as three distinct point values", () => {
    const validated = validateAtlasInspection(inspection());
    expect(validated.results).toEqual([
      { year: 2030, status: "unknown", depthMeters: null },
      { year: 2050, status: "zero", depthMeters: 0 },
      { year: 2100, status: "flooded", depthMeters: 0.75 },
    ]);
  });

  it.each([
    ["unknown with zero", "unknown", 0],
    ["zero with null", "zero", null],
    ["zero with positive depth", "zero", 0.1],
    ["flooded with zero", "flooded", 0],
    ["flooded with infinity", "flooded", Number.POSITIVE_INFINITY],
    ["transport error as data status", "error", null],
  ])("rejects %s", (_name, status, depthMeters) => {
    const value = inspection();
    value.results[0] = { year: 2030, status, depthMeters };
    expect(() => validateAtlasInspection(value)).toThrow(/status|depth/u);
  });

  it("rejects duplicate years and malformed inspection metadata", () => {
    const duplicate = inspection();
    duplicate.results[2] = { year: 2050, status: "zero", depthMeters: 0 };
    expect(() => validateAtlasInspection(duplicate)).toThrow(/duplicate or missing/u);
    expect(() => validateAtlasInspection({ ...inspection(), cellSizeMeters: 50 })).toThrow(/25 meter/u);
  });

  it("accepts consistent tile counts including no-data and all-zero tiles", () => {
    expect(validateAtlasTileCounts({ validPixels: 0, floodPixels: 0 })).toEqual({ validPixels: 0, floodPixels: 0 });
    expect(validateAtlasTileCounts({ validPixels: 16, floodPixels: 0 })).toEqual({ validPixels: 16, floodPixels: 0 });
    expect(validateAtlasTileCounts({ validPixels: 16, floodPixels: 5 })).toEqual({ validPixels: 16, floodPixels: 5 });
  });

  it.each([
    { validPixels: -1, floodPixels: 0 },
    { validPixels: 4, floodPixels: 5 },
    { validPixels: 65_537, floodPixels: 0 },
    { validPixels: 4.5, floodPixels: 1 },
    { validPixels: 4, floodPixels: 1, sha256: "private" },
  ])("rejects inconsistent tile counts %#", (counts) => {
    expect(() => validateAtlasTileCounts(counts)).toThrow(AtlasContractError);
  });
});
