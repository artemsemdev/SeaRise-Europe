import { layers, LIGHT, type Flavor } from "@protomaps/basemaps";
import type { ExpressionSpecification, LayerSpecification, StyleSpecification } from "maplibre-gl";
import europeOverviewJson from "../../../../data/cartography/europe-display.geojson?raw";
import ukraineJson from "../../../../data/cartography/ukraine.geojson?raw";

export const MAP_MAX_ZOOM = 16;
// CoCliCo's native cells are 25 m. Higher map zooms enlarge those cells.
export const FLOOD_MAX_ZOOM = 13;
export const FLOOD_BEFORE_LAYER = "atlas-basemap-building-outlines";

const DETAIL_MIN_ZOOM = 6;

// Use the explicit display footprint: coarse PMTiles tiles can also contain
// neighboring continents. Country label anchors sometimes sit offshore (e.g.
// Denmark), so use the geography-rules.json country scope for those instead.
const EUROPE_OVERVIEW = JSON.parse(europeOverviewJson);
const EUROPE_SUPPORT = EUROPE_OVERVIEW.features[0].geometry;
const UKRAINE_DISPLAY = JSON.parse(ukraineJson).features[0].geometry;
const OVERVIEW_COUNTRIES = [
  "Albania", "Åland", "Åland Islands", "Andorra", "Austria", "Belgium", "Bulgaria",
  "Bosnia and Herzegovina", "Belarus", "Switzerland", "Czechia", "Czech Republic",
  "Germany", "Denmark", "Spain", "Estonia", "Finland", "France", "Faroe Islands",
  "United Kingdom", "Guernsey", "Gibraltar", "Greece", "Croatia", "Hungary", "Isle of Man",
  "Ireland", "Iceland", "Italy", "Jersey", "Kosovo", "Liechtenstein", "Lithuania",
  "Luxembourg", "Latvia", "Monaco", "Moldova", "North Macedonia", "Malta", "Montenegro",
  "Netherlands", "Norway", "Poland", "Portugal", "Romania", "San Marino", "Serbia",
  "Slovakia", "Slovenia", "Sweden", "Ukraine", "Vatican City",
];
const EUROPE_CONTEXT_BOUNDS = {
  type: "Polygon" as const, coordinates: [[[-30, 30], [45, 30], [45, 75], [-30, 75], [-30, 30]]],
};

// A deliberately small orientation set, copied from the verified local Europe
// city catalogue (`atlas/europe/context/cities.json.br`). The source records
// are GeoNames 2747891, 3164603, 2911298, and 3031582 respectively. Keeping
// these in the style avoids a remote request and keeps the low-zoom support
// mask readable without pretending it covers countries outside the atlas.
export const OVERVIEW_ORIENTATION_PLACES = {
  type: "FeatureCollection" as const,
  features: [
    { type: "Feature" as const, properties: { name: "Rotterdam", sourceId: "geonames:2747891" }, geometry: { type: "Point" as const, coordinates: [4.47917, 51.9225] } },
    { type: "Feature" as const, properties: { name: "Venice", sourceId: "geonames:3164603" }, geometry: { type: "Point" as const, coordinates: [12.33265, 45.43713] } },
    { type: "Feature" as const, properties: { name: "Hamburg", sourceId: "geonames:2911298" }, geometry: { type: "Point" as const, coordinates: [9.99302, 53.55073] } },
    { type: "Feature" as const, properties: { name: "Bordeaux", sourceId: "geonames:3031582" }, geometry: { type: "Point" as const, coordinates: [-0.58046, 44.84124] } },
  ],
};

export const FIXTURE_ORIENTATION_PLACES = {
  type: "FeatureCollection" as const,
  features: [
    { type: "Feature" as const, properties: { name: "Venice", sourceId: "fixture:venice" }, geometry: { type: "Point" as const, coordinates: [12.3155, 45.4408] } },
    { type: "Feature" as const, properties: { name: "Rotterdam", sourceId: "fixture:rotterdam" }, geometry: { type: "Point" as const, coordinates: [4.4777, 51.9244] } },
    { type: "Feature" as const, properties: { name: "Hamburg", sourceId: "fixture:hamburg" }, geometry: { type: "Point" as const, coordinates: [9.9937, 53.5511] } },
    { type: "Feature" as const, properties: { name: "Bordeaux", sourceId: "fixture:bordeaux" }, geometry: { type: "Point" as const, coordinates: [-0.5792, 44.8378] } },
  ],
};

const palette: Flavor = {
  ...LIGHT,
  // The base palette intentionally leaves visual priority to the cyan flood
  // layer: cool water, near-white land, and only subdued contextual detail.
  background: "#D0DBD1", earth: "#F7F7F0", water: "#D0DBD1",
  park_a: "#E3EBE0", park_b: "#D6E5D2", wood_a: "#DCE8D8", wood_b: "#CFE0CC",
  scrub_a: "#E7ECDD", scrub_b: "#DDE7D5", sand: "#F2EFE5", beach: "#F5F1E7",
  industrial: "#ECEFF1", hospital: "#F2EDEE", school: "#F0F2EC", pedestrian: "#F2F3F1",
  aerodrome: "#EEF0F1", runway: "#E7EBED", pier: "#E8EDF0", buildings: "#E2E7E9",
  minor_service: "#F7F8F8", minor_a: "#F3F5F5", minor_b: "#FFFFFF", link: "#FFFFFF",
  major: "#FFFFFF", highway: "#FFFCF6", railway: "#B8C1C6", boundaries: "#B5C0C7",
  roads_label_minor: "#5B6570", roads_label_minor_halo: "#F7F7F0",
  roads_label_major: "#44505C", roads_label_major_halo: "#F7F7F0",
  ocean_label: "#527083", subplace_label: "#5D6872", subplace_label_halo: "#F7F7F0",
  city_label: "#1B1F26", city_label_halo: "#F7F7F0",
  state_label: "#68737D", state_label_halo: "#F7F7F0", country_label: "#4D5964",
  landcover: {
    barren: "#EEEADD", farmland: "#E5EDDC", forest: "#D8E6D5", glacier: "#F4F6F6",
    grassland: "#E0EADC", scrub: "#E5EBD9", urban_area: "#EEF0F1",
  },
};

export function floodTileZoom(mapZoom: number): number {
  // MapLibre's 256px raster tiles use one more level than its 512px map tiles.
  return Math.max(0, Math.min(FLOOD_MAX_ZOOM, Math.round(mapZoom + 1)));
}

export function createEuropeStyle(
  origin: string,
  edition: "real-local" | "synthetic-fixture" = "real-local",
): StyleSpecification {
  if (edition === "synthetic-fixture") {
    return {
      version: 8,
      name: "SeaRise fixture Europe atlas",
      sources: {
        "atlas-europe-overview": { type: "geojson", data: EUROPE_OVERVIEW, maxzoom: DETAIL_MIN_ZOOM },
        "atlas-europe-orientation": { type: "geojson", data: FIXTURE_ORIENTATION_PLACES, maxzoom: DETAIL_MIN_ZOOM },
      },
      layers: [
        { id: "background", type: "background", paint: { "background-color": palette.water } },
        {
          id: "atlas-europe-overview-land", type: "fill", source: "atlas-europe-overview",
          paint: { "fill-color": palette.earth, "fill-opacity": 0.98 },
        },
        {
          id: "atlas-europe-overview-coast", type: "line", source: "atlas-europe-overview",
          paint: { "line-color": "#CDD6DC", "line-width": 0.85, "line-opacity": 0.9 },
        },
        {
          id: FLOOD_BEFORE_LAYER, type: "line", source: "atlas-europe-overview",
          paint: { "line-opacity": 0 },
        },
        {
          id: "atlas-europe-overview-place-dot", type: "circle", source: "atlas-europe-orientation",
          paint: { "circle-radius": 5.5, "circle-color": "#E39B2C", "circle-stroke-width": 2, "circle-stroke-color": "#FFFFFF" },
        },
      ],
    };
  }
  const generated = layers("atlas-basemap", palette, { lang: "en" }) as LayerSpecification[];
  for (const layer of generated) {
    if (layer.type === "background") {
      // The background is water at every zoom. Keep it below the Europe mask
      // so the overview remains Europe-only without a fabricated world layer.
      layer.minzoom = 0;
    } else {
      layer.minzoom = Math.max(DETAIL_MIN_ZOOM, layer.minzoom ?? 0);
    }
    if (layer.type === "fill" && layer.id === "water") {
      layer.paint = { ...layer.paint, "fill-opacity": ["case", ["==", ["get", "kind"], "ocean"], 0, 1] };
    }
    if (layer.type === "line" && layer.id === "boundaries_country") {
      // The upstream archive includes an occupation/dispute line across Crimea.
      // It is not Ukraine's international border. Keep normal international
      // boundaries and leave disputed features outside Ukraine unaffected.
      layer.filter = ["all", ["<=", ["get", "kind_detail"], 2],
        ["!", ["all", ["==", ["get", "disputed"], true], ["within", UKRAINE_DISPLAY]]]];
    }
    if (layer.type === "fill" && layer.id === "landuse_park") {
      // Reserve and military boundaries also exist at sea. Coloring their
      // administrative extent like land invents islands in a coastal atlas.
      layer.filter = ["in", "kind", "park", "cemetery", "forest", "golf_course",
        "wood", "scrub", "grassland", "grass", "glacier", "sand", "airfield"];
    }
    if (layer.type === "symbol" && /^(places_|water_|earth_|roads_labels_|pois$)/u.test(layer.id)) {
      layer.layout = { ...layer.layout, "text-field": ["coalesce", ["get", "name:en"], ["get", "name"]] };
    }
  }
  const overviewLabels = generated.flatMap<LayerSpecification>((layer) => {
    if (layer.type !== "symbol") return [];
    const englishName: ExpressionSpecification = ["coalesce", ["get", "name:en"], ["get", "name"]];
    if (layer.id === "places_country") return [{
      ...layer, id: "atlas-europe-overview-country", minzoom: 0, maxzoom: DETAIL_MIN_ZOOM,
      layout: { ...layer.layout, "text-size": ["interpolate", ["linear"], ["zoom"], 2, 9, 4, 12, 6, 15],
        "text-variable-anchor": ["center", "top", "bottom", "left", "right"], "text-radial-offset": 0.5 },
      filter: ["all", ["==", ["get", "kind"], "country"],
        ["in", englishName, ["literal", OVERVIEW_COUNTRIES]], ["within", EUROPE_CONTEXT_BOUNDS]],
    }];
    if (layer.id === "places_locality") return [{
      ...layer, id: "atlas-europe-overview-city", minzoom: 0, maxzoom: DETAIL_MIN_ZOOM,
      filter: ["all", ["==", ["get", "kind"], "locality"], ["within", EUROPE_SUPPORT],
        ["!", ["in", englishName, ["literal", OVERVIEW_ORIENTATION_PLACES.features.map((place) => place.properties.name)]]]],
    }];
    if (layer.id === "water_label_ocean") return [{
      ...layer, id: "atlas-europe-overview-sea", minzoom: 0, maxzoom: DETAIL_MIN_ZOOM,
      filter: ["all", ["in", ["get", "kind"], ["literal", ["sea", "ocean", "bay", "strait", "fjord"]]],
        ["within", EUROPE_CONTEXT_BOUNDS]],
    }];
    return [];
  });
  // Flooding covers land/building fills; outlines, roads, and labels stay legible.
  const background = generated.filter((layer) => layer.type === "background");
  const ground = generated.filter((layer) => layer.type === "fill");
  const detail = generated.filter((layer) => layer.type !== "background" && layer.type !== "fill");
  return {
    version: 8,
    name: "SeaRise detailed local Europe atlas",
    glyphs: `${origin}/atlas-data/basemap/fonts/{fontstack}/{range}.pbf`,
    sprite: `${origin}/atlas-data/basemap/sprites/v4/light`,
    sources: {
      "atlas-europe-overview": { type: "geojson", data: EUROPE_OVERVIEW, maxzoom: DETAIL_MIN_ZOOM },
      "atlas-europe-orientation": { type: "geojson", data: OVERVIEW_ORIENTATION_PLACES, maxzoom: DETAIL_MIN_ZOOM },
      "atlas-basemap": {
        type: "vector",
        url: `pmtiles://${origin}/atlas-data/basemap/protomaps-europe.pmtiles`,
        bounds: [-30.5, 29.5, 45.5, 75.5],
        attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap contributors</a> · Protomaps · Natural Earth',
      },
    },
    layers: [
      ...background,
      {
        id: "atlas-europe-overview-land", type: "fill", source: "atlas-europe-overview", maxzoom: DETAIL_MIN_ZOOM,
        paint: { "fill-color": palette.earth, "fill-opacity": 0.98 },
      },
      {
        id: "atlas-europe-overview-coast", type: "line", source: "atlas-europe-overview", maxzoom: DETAIL_MIN_ZOOM,
        paint: { "line-color": "#CDD6DC", "line-width": 0.85, "line-opacity": 0.9 },
      },
      ...ground,
      {
        id: FLOOD_BEFORE_LAYER, type: "line", source: "atlas-basemap", "source-layer": "buildings", minzoom: 14,
        paint: { "line-color": "#C8D0D5", "line-width": 0.65, "line-opacity": 0.65 },
      },
      ...detail,
      ...overviewLabels,
      {
        id: "atlas-europe-overview-place-dot", type: "circle", source: "atlas-europe-orientation", minzoom: 0, maxzoom: DETAIL_MIN_ZOOM,
        paint: { "circle-radius": 5.5, "circle-color": "#E39B2C", "circle-stroke-width": 2, "circle-stroke-color": "#FFFFFF" },
      },
      {
        id: "atlas-europe-overview-place-label", type: "symbol", source: "atlas-europe-orientation", minzoom: 0, maxzoom: DETAIL_MIN_ZOOM,
        layout: {
          "text-field": ["get", "name"], "text-font": ["Noto Sans Regular"], "text-size": 12,
          "text-offset": [0.9, 0], "text-anchor": "left",
        },
        paint: { "text-color": "#1B1F26", "text-halo-color": palette.earth, "text-halo-width": 2 },
      },
    ],
  };
}
