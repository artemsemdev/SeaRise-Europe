import { describe, expect, it, vi } from "vitest";
import { loadFloodTile, type EuropeMapDataSource } from "./EuropeMap";

const request = {
  year: 2050 as const,
  protection: "protected" as const,
  z: 7,
  x: 63,
  y: 42,
};

describe("Europe map tile provider", () => {
  it("forwards the selected layer, tile coordinate, and abort signal", async () => {
    const controller = new AbortController();
    const getTile = vi.fn(async () => ({ data: new ArrayBuffer(8), validPixels: 64, floodPixels: 12 }));
    const source: EuropeMapDataSource = { edition: "synthetic-fixture", getTile };

    await expect(loadFloodTile(source, { ...request, signal: controller.signal })).resolves.toMatchObject({
      validPixels: 64,
      floodPixels: 12,
    });
    expect(getTile).toHaveBeenCalledWith({ ...request, signal: controller.signal });
  });

  it.each([
    { data: new Uint8Array(1), validPixels: 1, floodPixels: 0 },
    { data: new ArrayBuffer(1), validPixels: -1, floodPixels: 0 },
    { data: new ArrayBuffer(1), validPixels: 1, floodPixels: 2 },
  ])("rejects invalid provider results", async (result) => {
    const source = {
      edition: "real-local" as const,
      getTile: vi.fn(async () => result),
    } as unknown as EuropeMapDataSource;
    await expect(loadFloodTile(source, request)).rejects.toThrow(/invalid|inconsistent/u);
  });
});
