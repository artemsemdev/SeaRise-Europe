import { validateStyleMin } from "@maplibre/maplibre-gl-style-spec";
import { describe, expect, it } from "vitest";
import { createEuropeStyle, FLOOD_BEFORE_LAYER, floodTileZoom } from "./basemap-style";

describe("detailed European map", () => {
  it("keeps the committed fixture overview free of external map resources", () => {
    const style = createEuropeStyle("https://example.invalid", "synthetic-fixture");
    expect(validateStyleMin(style)).toEqual([]);
    expect(style).not.toHaveProperty("glyphs");
    expect(style).not.toHaveProperty("sprite");
    expect(style.sources).not.toHaveProperty("atlas-basemap");
    expect(JSON.stringify(style)).not.toContain("https://");
    expect(style.sources["atlas-europe-orientation"]).toMatchObject({ type: "geojson" });
    const fixturePlaces = (style.sources["atlas-europe-orientation"] as {
      data: { features: Array<{ properties: { sourceId: string } }> };
    }).data.features;
    expect(fixturePlaces.map((place) => place.properties.sourceId)).toEqual([
      "fixture:venice", "fixture:rotterdam", "fixture:hamburg", "fixture:bordeaux",
    ]);
  });

  it("builds a valid style whose tile, glyph, and sprite resources are local", () => {
    const style = createEuropeStyle("http://127.0.0.1:4174");
    expect(validateStyleMin(style)).toEqual([]);
    expect(JSON.stringify(style.layers)).not.toContain("Devanagari");
    expect(style.glyphs).toMatch(/^http:\/\/127\.0\.0\.1:4174\/atlas-data\/basemap\/fonts\//u);
    expect(style.sprite).toBe("http://127.0.0.1:4174/atlas-data/basemap/sprites/v4/light");
    expect(style.sources["atlas-basemap"]).toMatchObject({
      type: "vector", url: "pmtiles://http://127.0.0.1:4174/atlas-data/basemap/protomaps-europe.pmtiles",
      bounds: [-30.5, 29.5, 45.5, 75.5],
    });
  });

  it("shows the prepared European region at overview and preserves street detail", () => {
    const style = createEuropeStyle("http://127.0.0.1:4174");
    expect(JSON.stringify(style)).not.toContain("protomaps-world-overview");
    expect(style.sources["atlas-europe-overview"]).toMatchObject({ type: "geojson" });
    const overview = style.layers.filter((layer) => "source" in layer && layer.source === "atlas-europe-overview");
    expect(overview.some((layer) => layer.type === "fill" && layer.maxzoom === 6)).toBe(true);
    const detail = style.layers.filter((layer) => "source" in layer && layer.source === "atlas-basemap"
      && !layer.id.startsWith("atlas-europe-overview-"));
    expect(detail.every((layer) => (layer.minzoom ?? 0) >= 6)).toBe(true);
    expect(detail.some((layer) => layer.id === "roads_minor")).toBe(true);
    expect(detail.some((layer) => layer.id === "buildings")).toBe(true);
  });

  it("renders scoped country, city, and sea labels before street detail activates", () => {
    const style = createEuropeStyle("http://127.0.0.1:4174");
    for (const kind of ["country", "city", "sea"]) {
      const label = style.layers.find((layer) => layer.id === `atlas-europe-overview-${kind}`);
      expect(label).toMatchObject({ type: "symbol", source: "atlas-basemap", minzoom: 0, maxzoom: 6 });
      expect(JSON.stringify(label)).toContain('"within"');
    }
    const country = style.layers.find((layer) => layer.id === "atlas-europe-overview-country");
    expect(JSON.stringify(country)).toContain("Denmark");
    expect(JSON.stringify(country)).not.toMatch(/Russia|Turkey|Egypt/u);
    // Neighboring land from coarse source tiles must remain hidden.
    expect(style.layers.filter((layer) => "source" in layer && layer.source === "atlas-basemap"
      && (layer.minzoom ?? 0) < 6).every((layer) => layer.type === "symbol")).toBe(true);
  });

  it("uses pale sage-blue water, off-white land, restrained parks, and dark labels", () => {
    const style = createEuropeStyle("http://127.0.0.1:4174");
    expect(style.layers[0]).toMatchObject({
      id: "background", type: "background", minzoom: 0,
      paint: { "background-color": "#D0DBD1" },
    });
    expect(style.layers.find((layer) => layer.id === "atlas-europe-overview-land")).toMatchObject({
      paint: { "fill-color": "#F7F7F0" },
    });
    expect(style.layers.find((layer) => layer.id === "water")).toMatchObject({
      paint: { "fill-color": "#D0DBD1" },
    });
    const parks = style.layers.find((layer) => layer.id === "landuse_park");
    expect(parks).toMatchObject({ paint: expect.objectContaining({ "fill-color": expect.any(Array) }) });
    expect(JSON.stringify(parks?.paint)).toContain("#D6E5D2");
    expect(style.layers.find((layer) => layer.id === "places_locality")).toMatchObject({
      paint: { "text-color": "#1B1F26", "text-halo-color": "#F7F7F0" },
    });
    expect(style.layers.find((layer) => layer.id === "atlas-europe-overview-place-label")).toMatchObject({
      paint: { "text-color": "#1B1F26", "text-halo-color": "#F7F7F0" },
    });
  });

  it("adds a small, local and source-backed orientation set to the Europe-only overview", () => {
    const style = createEuropeStyle("http://127.0.0.1:4174");
    expect(style.sources["atlas-europe-orientation"]).toMatchObject({ type: "geojson", maxzoom: 6 });
    const orientation = style.layers.filter((layer) => "source" in layer && layer.source === "atlas-europe-orientation");
    expect(orientation.map((layer) => layer.id)).toEqual([
      "atlas-europe-overview-place-dot", "atlas-europe-overview-place-label",
    ]);
    expect(orientation.every((layer) => layer.minzoom === 0 && layer.maxzoom === 6)).toBe(true);
    const labels = orientation.find((layer) => layer.id === "atlas-europe-overview-place-label");
    expect(labels).toMatchObject({ type: "symbol", layout: { "text-field": ["get", "name"] } });
    expect(JSON.stringify(style.sources["atlas-europe-orientation"])).toContain("geonames:2747891");
    expect(JSON.stringify(style.sources["atlas-europe-orientation"])).not.toMatch(/Russia|Turkey/u);
  });

  it("keeps land below flooding and street/building outlines and names above it", () => {
    const style = createEuropeStyle("http://127.0.0.1:4174");
    const insertion = style.layers.findIndex((layer) => layer.id === FLOOD_BEFORE_LAYER);
    expect(insertion).toBeGreaterThan(0);
    expect(style.layers.slice(insertion).some((layer) => layer.type === "fill")).toBe(false);
    for (const id of ["roads_minor", "roads_labels_minor", "places_locality", "atlas-europe-overview-country",
      "atlas-europe-overview-city", "atlas-europe-overview-sea", "atlas-europe-overview-place-label"]) {
      expect(style.layers.findIndex((layer) => layer.id === id)).toBeGreaterThan(insertion);
    }
    expect(style.layers.findIndex((layer) => layer.id === "buildings")).toBeLessThan(insertion);
  });

  it("refines 256px flood tiles with zoom then holds native source detail", () => {
    expect([0, 8.2, 9, 11.5, 12, 15, 16].map(floodTileZoom)).toEqual([1, 9, 10, 13, 13, 13, 13]);
  });
});
