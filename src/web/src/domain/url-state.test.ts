import fc from "fast-check";
import { describe, expect, it } from "vitest";
import { HORIZON_YEARS, SCENARIO_IDS } from "../contracts/generated/release-contract";
import { TechnicalFailure, type Selection } from "./release";
import { parseUrlSelection, writeUrlSelection } from "./url-state";

const releaseId = "searise-europe-v1.0.0-20260810-c096aeab4e09";
const defaults = { scenario: "ssp2-45", horizon: 2050 } as const;

describe("strict release URL state", () => {
  it("round-trips release, selection, coordinate, and stable place identity", () => {
    fc.assert(
      fc.property(
        fc.constantFrom(...SCENARIO_IDS),
        fc.constantFrom(...HORIZON_YEARS),
        fc.double({ min: -90, max: 90, noNaN: true, noDefaultInfinity: true }),
        fc.double({ min: -180, max: 180, noNaN: true, noDefaultInfinity: true }),
        fc.option(fc.stringMatching(/^[a-z][a-z0-9.-]{0,20}$/), { nil: undefined }),
        (scenario, horizon, latitude, longitude, placeId) => {
          const location: Selection["location"] = placeId
            ? { kind: "settlement", placeId, coordinates: { latitude, longitude } }
            : { kind: "coordinate", coordinates: { latitude, longitude } };
          const selection: Selection = { dataReleaseId: releaseId, scenario, horizon, location };
          const written = writeUrlSelection(new URL("https://app.example/"), selection);
          expect(parseUrlSelection(written, releaseId, defaults)).toEqual(selection);
        },
      ),
      { numRuns: 200 },
    );
  });

  it("rejects release isolation, invalid coordinates, and unsupported selections", () => {
    expect(() =>
      parseUrlSelection(
        new URL("https://app.example/?release=searise-europe-v1.0.0-20260810-aaaaaaaaaaaa&lat=1&lon=2"),
        releaseId,
        defaults,
      ),
    ).toThrowError(TechnicalFailure);
    expect(() =>
      parseUrlSelection(new URL("https://app.example/?lat=Infinity&lon=2"), releaseId, defaults),
    ).toThrowError(TechnicalFailure);
    expect(() =>
      parseUrlSelection(new URL("https://app.example/?scenario=ssp9-99&lat=1&lon=2"), releaseId, defaults),
    ).toThrowError(TechnicalFailure);
    expect(() =>
      parseUrlSelection(new URL("https://app.example/?horizon=2051&lat=1&lon=2"), releaseId, defaults),
    ).toThrowError(TechnicalFailure);
  });

  it("returns no selection when the URL has no location", () => {
    expect(parseUrlSelection(new URL("https://app.example/"), releaseId, defaults)).toBeUndefined();
  });
});
