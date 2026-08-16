import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import fixture from "../../../../../contracts/release/v1/fixtures/release/searise-europe-v1.0.0-20260810-c096aeab4e09/manifest.json";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ManifestRepository } from "../../data/manifest-repository";
import type { Coordinates } from "../../domain/release";
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
  it("updates overlay, legend, and text alternative atomically", async () => {
    render(<MapExplorer context={await context()} onSelection={vi.fn()} />);
    fireEvent.change(screen.getByLabelText("Scenario"), { target: { value: "ssp5-85" } });
    fireEvent.change(screen.getByLabelText("Horizon"), { target: { value: "2100" } });
    fireEvent.click(screen.getByLabelText(/Upper · q0.833/));

    expect(screen.getByTestId("map-adapter")).toHaveAttribute(
      "data-artifact",
      "projection-ssp5-85-2100-pmtiles",
    );
    expect(screen.getByTestId("map-adapter")).toHaveAttribute("data-band", "upper");
    expect(screen.getByLabelText("Map text alternative")).toHaveTextContent(
      "ssp5-85 · 2100 · Upper · q0.833",
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
    render(<MapExplorer context={await context()} onSelection={vi.fn()} />);
    expect(screen.getByRole("link", { name: /IPCC AR6 Sea Level Projections/i })).toBeVisible();
    expect(screen.getByRole("link", { name: /release attribution record/i })).toHaveAttribute(
      "href",
      expect.stringMatching(new RegExp(`/releases/${fixture.dataReleaseId}/.+/source-attribution.json$`)),
    );
    expect(screen.getByRole("link", { name: "OpenFreeMap" })).toBeVisible();
    expect(screen.getByRole("link", { name: /OpenStreetMap contributors/i })).toBeVisible();
  });
});
