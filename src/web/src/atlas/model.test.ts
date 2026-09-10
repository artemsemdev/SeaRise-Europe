import { describe, expect, it } from "vitest";
import { parseCity, parseInspection, parseCatalog, readSelection, selectionUrl } from "./model";

import { SYNTHETIC_ATLAS_CATALOG as catalog } from "./synthetic-fixture";

describe("European inundation selection", () => {
  it("opens Europe without a hardcoded country or place", () => {
    expect(readSelection("")).toEqual({ cityId: null, year: 2050, protection: "unprotected", visible: true, compare: false, camera: null, point: null });
    expect(readSelection(selectionUrl(null, 2030, "unprotected", true).slice(1)).cityId).toBeNull();
  });
  it("round-trips a real GeoNames identity and all shared controls", () => {
    const url = selectionUrl("geonames:3164603", 2100, "protected", false);
    expect(readSelection(url.slice(1))).toEqual({ cityId: "geonames:3164603", year: 2100, protection: "protected", visible: false, compare: false, camera: null, point: null });
  });
  it("keeps place lookup separate from year fallback and preserves legacy links", () => {
    expect(readSelection("?city=rotterdam&year=2040&defenses=unknown")).toEqual({ cityId: "rotterdam", year: 2050, protection: "unprotected", visible: true, compare: false, camera: null, point: null });
    expect(readSelection("?city=" + "x".repeat(129)).cityId).toBeNull();
  });
  it("accepts only the public six-layer catalog, without disk metadata", () => {
    expect(parseCatalog(catalog).layers).toHaveLength(6);
    const validLayer = catalog.layers[0];
    expect(() => parseCatalog({ ...catalog, layers: [validLayer, validLayer] })).toThrow();
    for (const changed of [{ scenario: "ssp245" }, { status: undefined }, { inputs: [{ file: "raw/private.tif" }] }]) {
      expect(() => parseCatalog({ ...catalog, layers: [{ ...validLayer, ...changed }, ...catalog.layers.slice(1)] })).toThrow();
    }
  });
  it("validates searched geography instead of trusting shared URL coordinates", () => {
    const city = { id: "geonames:3164603", name: "Venice", countryCode: "IT", countryName: "Italy", coordinates: [12.3388, 45.4343] };
    expect(parseCity(city)).toEqual(city);
    expect(() => parseCity({ ...city, coordinates: [400, 95] })).toThrow();
    expect(() => parseCity({ ...city, countryName: "" })).toThrow();
  });
});


describe("exact map views and native point results", () => {
  it("round-trips camera, point and comparison while rejecting invalid geography", () => {
    const options = { camera: { lng: 12.3388, lat: 45.4343, zoom: 12.3 }, point: [12.35, 45.44] as [number, number], compare: true };
    const restored = readSelection(selectionUrl("geonames:3164603", 2100, "protected", true, options).slice(1));
    expect(restored).toMatchObject(options);
    const boundaryPoint: [number, number] = [0.000000123456789, 45.12345678901234];
    expect(readSelection(selectionUrl(null, 2100, "unprotected", true, { point: boundaryPoint }).slice(1)).point).toEqual(boundaryPoint);
    for (const view of ["180,0,8", "12,45,17", "12,45,Infinity", "12,45,", "12,45,8,9"]) expect(readSelection(`?view=${view}`).camera).toBeNull();
    for (const point of ["180,0", "12,NaN", "12,45,8", ","]) expect(readSelection(`?point=${point}`).point).toBeNull();
    expect(readSelection("?compare=on&year=2050").year).toBe(2100);
  });
  it("never turns unknown or invalid native data into a dry result", () => {
    const valid = { coordinates: [12,45], protection: "unprotected", cellSizeMeters: 25,
      results: [{ year: 2030, status: "zero", depthMeters: 0 }, { year: 2050, status: "unknown", depthMeters: null }, { year: 2100, status: "flooded", depthMeters: 1.2 }] };
    expect(parseInspection(valid)).toEqual(valid);
    for (const result of [{ year: 2030, status: "zero", depthMeters: null }, { year: 2030, status: "unknown", depthMeters: 0 }, { year: 2030, status: "flooded", depthMeters: 0 }, { year: 2030, status: "flooded", depthMeters: Infinity }]) {
      expect(() => parseInspection({ ...valid, results: [result, ...valid.results.slice(1)] })).toThrow();
    }
    expect(() => parseInspection({ ...valid, results: [...valid.results.slice(1), valid.results[1]] })).toThrow();
  });
});


describe("retired calculation links", () => {
  it.each(["additional", "total", "baseline"])("opens %s links in the coastal atlas with independent controls preserved", (viewMode) => {
    const selection = readSelection(`?model=searise&viewMode=${viewMode}&city=geonames:3164603&year=2050&defenses=protected&flooding=off&compare=on&view=12.25,45.43,10&point=12.2486111,45.4511111`);
    expect(selection).toEqual({ cityId: "geonames:3164603", year: 2100, protection: "protected", visible: false, compare: true,
      camera: { lng: 12.25, lat: 45.43, zoom: 10 }, point: [12.2486111, 45.4511111] });
    const url = selectionUrl(selection.cityId, selection.year, selection.protection, selection.visible, selection);
    expect(new URLSearchParams(url.slice(2)).has("model")).toBe(false);
    expect(new URLSearchParams(url.slice(2)).has("viewMode")).toBe(false);
    expect(readSelection(url.slice(1))).toEqual(selection);
  });
  it("does not accept experimental catalogs or terrain cells as CoCliCo results", () => {
    expect(() => parseCatalog({ ...catalog, version: 1, model: "searise-coastal-screening-v1" })).toThrow();
    expect(() => parseInspection({ coordinates: [12,45], protection: "unprotected", cellSizeMeters: 30,
      results: [2030, 2050, 2100].map((year) => ({ year, status: "flooded", depthMeters: 1 })) })).toThrow();
  });
});
