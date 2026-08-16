import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import fixture from "../../../../../contracts/release/v2/fixtures/browser-release/searise-europe-v1.0.0-20260810-c096aeab4e09/manifest.json";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ManifestRepository } from "../../data/manifest-repository";
import type { Coordinates, Selection } from "../../domain/release";
import MapExplorer from "./MapExplorer";

vi.mock("./MapSurface", () => ({
  MapSurface: ({ layers, band, journeyTarget, journeyMotionSkipToken, interactionEnabled, onCoordinate }: {
    layers: { projection: { artifactId: string } };
    band: string;
    journeyTarget?: Coordinates;
    journeyMotionSkipToken?: number;
    interactionEnabled?: boolean;
    onCoordinate: (coordinates: Coordinates) => void;
  }) => (
    <div
      data-testid="map-adapter"
      data-artifact={layers.projection.artifactId}
      data-band={band}
      data-journey={journeyTarget ? `${journeyTarget.latitude}/${journeyTarget.longitude}` : "idle"}
      data-motion-skip-token={journeyMotionSkipToken ?? 0}
      data-interaction-enabled={interactionEnabled ? "true" : "false"}
    >
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
  it("keeps preview non-result while the result panel owns scenario and horizon selection", async () => {
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
    expect(screen.queryByLabelText("Scenario")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Horizon")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Map text alternative")).toHaveTextContent(/default non-result preview/i);
    expect(screen.getByTestId("map-adapter")).toHaveAttribute("data-interaction-enabled", "false");

    rerender(<MapExplorer context={release} selection={initial} onSelection={command} />);
    expect(screen.getByTestId("map-adapter")).toHaveAttribute("data-interaction-enabled", "true");
    expect(screen.getByLabelText("Map text alternative")).toHaveTextContent(
      "Selected coordinate: 51.5000, -0.1000",
    );
    expect(screen.getByTestId("map-adapter")).toHaveAttribute("data-artifact", "projection-ssp2-45-2050-pmtiles");

    const future = Object.freeze({ ...initial, scenario: "ssp5-85" as const, horizon: 2100 as const });
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

  it("passes a deterministic journey target to the map without presenting it as accepted", async () => {
    const release = await context();
    render(
      <MapExplorer
        context={release}
        journeyActive
        journeyTarget={{ latitude: 59.9139, longitude: 10.7522 }}
        journeyMotionSkipToken={3}
        onSelection={vi.fn()}
      />,
    );
    expect(screen.getByRole("region", { name: /release-scoped source-grid visualization/i })).toHaveAttribute(
      "data-journey-active",
      "true",
    );
    expect(screen.getByTestId("map-adapter")).toHaveAttribute("data-journey", "59.9139/10.7522");
    expect(screen.getByTestId("map-adapter")).toHaveAttribute("data-motion-skip-token", "3");
    expect(screen.getByLabelText("Map text alternative")).toHaveTextContent(/default non-result preview/i);
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
