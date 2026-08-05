// @vitest-environment node

import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

import {
  Ar6GridInterval,
  Ar6LookupContract,
  Ar6LookupContractError,
  lookupAr6Projection,
} from "./projection-lookup";

const scienceDirectory = resolve(process.cwd(), "../pipeline/science");
const contract = JSON.parse(
  readFileSync(resolve(scienceDirectory, "ar6-lookup-validation.json"), "utf8"),
) as Ar6LookupContract;

function interval(
  locations: Ar6GridInterval["locations"],
  scenario: Ar6GridInterval["scenario"] = "ssp2-45",
  horizon: Ar6GridInterval["horizon"] = 2050,
): Ar6GridInterval {
  return {
    scenario,
    horizon,
    baseline: "1995-2014 mean",
    sourceRelease: "20210809",
    memberSha256: "b".repeat(64),
    locations,
  };
}

describe("AR6 source-native projection lookup", () => {
  it("uses the lowest source location ID for an exact distance tie", () => {
    const result = lookupAr6Projection(
      interval([
        {
          locationId: 20,
          latitude: 0,
          longitude: -0.5,
          lowerMillimetres: 100,
          centralMillimetres: 200,
          upperMillimetres: 300,
        },
        {
          locationId: 10,
          latitude: 0,
          longitude: 0.5,
          lowerMillimetres: 400,
          centralMillimetres: 500,
          upperMillimetres: 600,
        },
      ]),
      0,
      0,
      "in-scope",
      contract,
    );

    expect(result.state).toBe("ProjectionAvailable");
    if (result.state !== "ProjectionAvailable") throw new Error("expected projection");
    expect(result.source.locationId).toBe(10);
    expect([
      result.lowerMillimetres,
      result.centralMillimetres,
      result.upperMillimetres,
    ]).toEqual([400, 500, 600]);
  });

  it("never skips a nearest nodata location", () => {
    const result = lookupAr6Projection(
      interval([
        {
          locationId: 10,
          latitude: 0,
          longitude: 0,
          lowerMillimetres: null,
          centralMillimetres: null,
          upperMillimetres: null,
        },
        {
          locationId: 20,
          latitude: 0,
          longitude: 0.5,
          lowerMillimetres: 100,
          centralMillimetres: 200,
          upperMillimetres: 300,
        },
      ]),
      0,
      0.01,
      "in-scope",
      contract,
    );

    expect(result.state).toBe("DataUnavailable");
    if (result.state !== "DataUnavailable") throw new Error("expected nodata");
    expect(result.reasonCode).toBe("source-value-nodata");
    expect(result.source.locationId).toBe(10);
  });

  it("includes the exact maximum distance then fails beyond it", () => {
    const source = {
      locationId: 1,
      latitude: 0,
      longitude: 0,
      lowerMillimetres: 100,
      centralMillimetres: 200,
      upperMillimetres: 300,
    };
    const boundaryLatitude =
      (100 / contract.lookup.distance.earthMeanRadiusKm) * (180 / Math.PI);

    expect(
      lookupAr6Projection(interval([source]), boundaryLatitude, 0, "in-scope", contract)
        .state,
    ).toBe("ProjectionAvailable");
    const beyond = lookupAr6Projection(
      interval([source]),
      (100.001 / contract.lookup.distance.earthMeanRadiusKm) * (180 / Math.PI),
      0,
      "in-scope",
      contract,
    );
    expect([beyond.state, beyond.reasonCode]).toEqual([
      "DataUnavailable",
      "source-location-too-distant",
    ]);
  });

  it("resolves scope before reading an empty grid", () => {
    expect(
      lookupAr6Projection(interval([]), 52.52, 13.405, "out-of-scope", contract).state,
    ).toBe("OutOfScope");
    expect(
      lookupAr6Projection(interval([]), 40.7128, -74.006, "unsupported-geography", contract)
        .state,
    ).toBe("UnsupportedGeography");
  });

  it.each<[string, (changed: Ar6LookupContract) => void]>([
    ["maximum distance", (changed) => (changed.lookup.maximumDistanceKm = 101)],
    [
      "Earth radius",
      (changed) => (changed.lookup.distance.earthMeanRadiusKm = 6371),
    ],
    [
      "distance decimals",
      (changed) => (changed.lookup.distance.reportedDistanceDecimalPlaces = 3),
    ],
    ["quantiles", (changed) => (changed.lookup.requiredQuantiles = [0.17, 0.5, 0.83])],
  ])("fails closed when %s changes", (_label, mutate) => {
    const changed = structuredClone(contract);
    mutate(changed);

    expect(() =>
      lookupAr6Projection(interval([]), 0, 0, "out-of-scope", changed),
    ).toThrow(Ar6LookupContractError);
  });
});
