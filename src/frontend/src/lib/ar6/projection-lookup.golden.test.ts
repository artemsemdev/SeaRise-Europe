// @vitest-environment node

import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

import {
  Ar6GridInterval,
  Ar6GridLocation,
  Ar6LookupContract,
  Ar6ScopeState,
  lookupAr6Projection,
} from "./projection-lookup";

interface GoldenProjection {
  scenario: Ar6GridInterval["scenario"];
  horizon: Ar6GridInterval["horizon"];
  lowerMillimetres: number;
  centralMillimetres: number;
  upperMillimetres: number;
  lowerMetres: number;
  centralMetres: number;
  upperMetres: number;
}

interface GoldenResult {
  id: string;
  coordinates: { latitude: number; longitude: number };
  state: string;
  reasonCode: string;
  source?: {
    locationId: number;
    latitude: number;
    longitude: number;
    family: "grid";
    distanceKilometres: number;
  };
  projections?: GoldenProjection[];
}

interface GoldenDocument {
  provenance: { memberSha256: Record<string, string> };
  publicationMetadata: Record<string, unknown>;
  results: GoldenResult[];
}

const scienceDirectory = resolve(process.cwd(), "../pipeline/science");
const contract = JSON.parse(
  readFileSync(resolve(scienceDirectory, "ar6-lookup-validation.json"), "utf8"),
) as Ar6LookupContract;
const goldens = JSON.parse(
  readFileSync(resolve(scienceDirectory, "evidence/ar6-lookup-goldens.json"), "utf8"),
) as GoldenDocument;

function upstreamScenario(scenario: Ar6GridInterval["scenario"]): string {
  return scenario.replace("ssp1-26", "ssp126").replace("ssp2-45", "ssp245").replace(
    "ssp5-85",
    "ssp585",
  );
}

function scopeFor(result: GoldenResult): Ar6ScopeState {
  if (result.state === "UnsupportedGeography") return "unsupported-geography";
  if (result.state === "OutOfScope") return "out-of-scope";
  return "in-scope";
}

describe("Python and TypeScript AR6 golden parity", () => {
  it("matches every source identity and integer-millimetre projection bit-exactly", () => {
    expect(goldens.publicationMetadata).toEqual(contract.publicationMetadata);
    const available = goldens.results.filter(
      (result) => result.state === "ProjectionAvailable",
    );

    for (const golden of goldens.results) {
      const projections = golden.projections ?? [
        {
          scenario: "ssp2-45" as const,
          horizon: 2050 as const,
          lowerMillimetres: 0,
          centralMillimetres: 0,
          upperMillimetres: 0,
          lowerMetres: 0,
          centralMetres: 0,
          upperMetres: 0,
        },
      ];
      for (const projection of projections) {
        const locations: Ar6GridLocation[] = available.map((candidate) => {
          const source = candidate.source!;
          const values = candidate.projections!.find(
            (item) =>
              item.scenario === projection.scenario && item.horizon === projection.horizon,
          )!;
          return {
            locationId: source.locationId,
            latitude: source.latitude,
            longitude: source.longitude,
            lowerMillimetres: values.lowerMillimetres,
            centralMillimetres: values.centralMillimetres,
            upperMillimetres: values.upperMillimetres,
          };
        });
        const interval: Ar6GridInterval = {
          scenario: projection.scenario,
          horizon: projection.horizon,
          baseline: "1995-2014 mean",
          sourceRelease: "20210809",
          memberSha256:
            goldens.provenance.memberSha256[upstreamScenario(projection.scenario)],
          locations,
        };
        const actual = lookupAr6Projection(
          interval,
          golden.coordinates.latitude,
          golden.coordinates.longitude,
          scopeFor(golden),
          contract,
        );

        expect([actual.state, actual.reasonCode], golden.id).toEqual([
          golden.state,
          golden.reasonCode,
        ]);
        if (actual.state !== "ProjectionAvailable" || !golden.source) continue;
        expect(actual.source, golden.id).toEqual(golden.source);
        expect(
          {
            lowerMillimetres: actual.lowerMillimetres,
            centralMillimetres: actual.centralMillimetres,
            upperMillimetres: actual.upperMillimetres,
            lowerMetres: actual.lowerMetres,
            centralMetres: actual.centralMetres,
            upperMetres: actual.upperMetres,
          },
          golden.id,
        ).toEqual({
          lowerMillimetres: projection.lowerMillimetres,
          centralMillimetres: projection.centralMillimetres,
          upperMillimetres: projection.upperMillimetres,
          lowerMetres: projection.lowerMetres,
          centralMetres: projection.centralMetres,
          upperMetres: projection.upperMetres,
        });
      }
    }
  });
});
