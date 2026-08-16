import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import fixture from "../../../../../contracts/release/v2/fixtures/browser-release/searise-europe-v1.0.0-20260810-c096aeab4e09/manifest.json";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ManifestRepository } from "../../data/manifest-repository";
import type { Coordinates, Selection } from "../../domain/release";
import MapExplorer from "./MapExplorer";

vi.mock("./MapSurface", () => ({
  MapSurface: ({ layers, band, onCoordinate }: {
    layers: { projection: { artifactId: string } };
    band: string;
    onCoordinate: (coordinates: Coordinates) => void;
  }) => (
    <div data-testid="map-adapter" data-artifact={layers.projection.artifactId} data-band={band}>
      <button type="button" onClick={() => onCoordinate({ latitude: 51.5, longitude: -0.1 })}>
        Simulate common map selection
      </button>
    </div>
  ),
}));

afterEach(cleanup);

async function context() {
  return new ManifestRepository({
    manifestUrl: `https://fixture.example/releases/${fixture.dataReleaseId}/manifest.json`,
    allowedOrigins: ["https://fixture.example"],
    expectedDisposition: "synthetic-fixture",
    transport: async () => new Response(JSON.stringify(fixture), {
      headers: { "content-type": "application/json" },
    }),
  }).load(fixture.dataReleaseId, new AbortController().signal);
}

describe("MapExplorer", () => {
  it("keeps preview non-result and accepts overlay controls only through the common command", async () => {
    const release = await context();
    const command = vi.fn();
    const initial = Object.freeze({
      dataReleaseId: release.dataReleaseId,
      scenario: "ssp2-45",
      horizon: 2050,
      location: Object.freeze({
        kind: "coordinate" as const,
        coordinates: Object.freeze({ latitude: 51.5, longitude: -0.1 }),
      }),
    }) satisfies Selection;
    const { rerender } = render(<MapExplorer context={release} onSelection={command} />);

    expect(screen.getByRole("status")).toHaveTextContent(/default release preview.*not an accepted scientific result/i);
    expect(screen.getByLabelText("Scenario")).toBeDisabled();
    expect(screen.getByLabelText("Horizon")).toBeDisabled();
    expect(screen.getByLabelText("Map text alternative")).toHaveTextContent(/no result marker or result legend/i);

    rerender(<MapExplorer context={release} selection={initial} onSelection={command} />);
    expect(screen.getByLabelText("Map text alternative")).toHaveTextContent(
      "Selected coordinate: 51.5000, -0.1000",
    );
    fireEvent.change(screen.getByLabelText("Scenario"), { target: { value: "ssp5-85" } });
    expect(command).toHaveBeenLastCalledWith(expect.objectContaining({ scenario: "ssp5-85", horizon: 2050 }));
    expect(screen.getByTestId("map-adapter")).toHaveAttribute("data-artifact", "projection-ssp2-45-2050-pmtiles");

    const higher = command.mock.calls.at(-1)![0] as Selection;
    rerender(<MapExplorer context={release} selection={higher} onSelection={command} />);
    fireEvent.change(screen.getByLabelText("Horizon"), { target: { value: "2100" } });
    expect(command).toHaveBeenLastCalledWith(expect.objectContaining({ scenario: "ssp5-85", horizon: 2100 }));

    const future = command.mock.calls.at(-1)![0] as Selection;
    rerender(<MapExplorer context={release} selection={future} onSelection={command} />);
    fireEvent.click(screen.getByLabelText(/Upper · q0.833/));

    expect(screen.getByTestId("map-adapter")).toHaveAttribute(
      "data-artifact",
      "projection-ssp5-85-2100-pmtiles",
    );
    expect(screen.getByTestId("map-adapter")).toHaveAttribute("data-band", "upper");
    expect(screen.getByLabelText("Map text alternative")).toHaveTextContent(
      "Accepted result visualization · ssp5-85 · 2100 · Upper · q0.833",
    );
  });

  it("routes a map click through the immutable common coordinate selection", async () => {
    const commonCommand = vi.fn();
    render(<MapExplorer context={await context()} onSelection={commonCommand} />);
    fireEvent.click(screen.getByRole("button", { name: /simulate common map selection/i }));

    expect(commonCommand).toHaveBeenCalledWith(expect.objectContaining({
      dataReleaseId: fixture.dataReleaseId,
      scenario: "ssp2-45",
      horizon: 2050,
      location: { kind: "coordinate", coordinates: { latitude: 51.5, longitude: -0.1 } },
    }));
    expect(Object.isFrozen(commonCommand.mock.calls[0][0])).toBe(true);

    commonCommand({
      dataReleaseId: fixture.dataReleaseId,
      scenario: "ssp2-45",
      horizon: 2050,
      location: { kind: "settlement", placeId: "search-result", coordinates: { latitude: 51.5, longitude: -0.1 } },
    });
    expect(commonCommand).toHaveBeenCalledTimes(2);
  });

  it("keeps complete projection and optional basemap attribution visible in text", async () => {
    const release = await context();
    const settlement = Object.freeze({
      dataReleaseId: release.dataReleaseId,
      scenario: "ssp2-45",
      horizon: 2050,
      location: Object.freeze({
        kind: "settlement" as const,
        placeId: "geonames:2950159",
        coordinates: Object.freeze({ latitude: 53.55, longitude: 9.9937 }),
      }),
    }) satisfies Selection;
    render(<MapExplorer context={release} selection={settlement} onSelection={vi.fn()} />);
    expect(screen.getByLabelText("Map text alternative")).toHaveTextContent(
      "Selected settlement geonames:2950159: 53.5500, 9.9937",
    );
    expect(screen.getByRole("link", { name: /IPCC AR6 Sea Level Projections/i })).toBeVisible();
    expect(screen.getByRole("link", { name: /release attribution record/i })).toHaveAttribute(
      "href",
      expect.stringMatching(new RegExp(`/releases/${fixture.dataReleaseId}/.+/source-attribution.json$`)),
    );
    expect(screen.getByRole("link", { name: "OpenFreeMap" })).toBeVisible();
    expect(screen.getByRole("link", { name: /OpenStreetMap contributors/i })).toBeVisible();
  });
});
