import maplibregl, {
  type GeoJSONSourceSpecification,
  type Map as MapLibreMap,
  type StyleSpecification,
} from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { Protocol, ResolvedValueCache, type Cache } from "pmtiles";
import type { Coordinates } from "../../domain/release";
import type {
  BoundaryVisualLayer,
  ResolvedMapLayers,
  VisualBand,
} from "../../data/map-layer-resolver";
import { RenderToken } from "./render-token";
import { registerNetworkOnlyPmtiles } from "./pmtiles-network-source";

const SOURCE_ID = "searise-projection";
const FILL_LAYER_ID = "searise-projection-fill";
const OUTLINE_LAYER_ID = "searise-projection-outline";
const BASEMAP_STYLE_URL = "https://tiles.openfreemap.org/styles/positron";
const IPCC_ATTRIBUTION =
  'Garner et al. (2021), <a href="https://doi.org/10.5281/zenodo.6382554">IPCC AR6 Sea Level Projections</a>, version 20210809, CC BY 4.0.';

const EMPTY_STYLE: StyleSpecification = {
  version: 8,
  name: "SeaRise release-only canvas",
  sources: {},
  layers: [{ id: "searise-background", type: "background", paint: { "background-color": "#0b3f4d" } }],
};

let sharedProtocol: Protocol | undefined;
let sharedMetadataCache: Cache | undefined;
let protocolUsers = 0;

interface ProtocolLease {
  readonly register: (layers: ResolvedMapLayers) => void;
  readonly release: () => void;
}

function acquireProtocol(initialLayers: ResolvedMapLayers): ProtocolLease {
  if (!sharedProtocol) {
    sharedProtocol = new Protocol({ metadata: true, errorOnMissingTile: false });
    // Bounded, ephemeral decoded headers/directories only; never tile ranges.
    sharedMetadataCache = new ResolvedValueCache(64);
    maplibregl.addProtocol("pmtiles", sharedProtocol.tile);
  }
  const protocol = sharedProtocol;
  const cache = sharedMetadataCache!;
  const register = (layers: ResolvedMapLayers) => {
    registerNetworkOnlyPmtiles(protocol, cache, layers.projection);
    for (const boundary of layers.boundaries) {
      if (boundary.mediaType === "application/vnd.pmtiles") {
        registerNetworkOnlyPmtiles(protocol, cache, boundary);
      }
    }
  };
  register(initialLayers);
  protocolUsers += 1;
  let released = false;
  return Object.freeze({ register, release: () => {
    if (released) return;
    released = true;
    protocolUsers -= 1;
    if (protocolUsers === 0) {
      maplibregl.removeProtocol("pmtiles");
      sharedProtocol = undefined;
      sharedMetadataCache = undefined;
    }
  } });
}

export type MapRuntimeStatus =
  | { readonly kind: "loading"; readonly message: string }
  | { readonly kind: "ready"; readonly message: string }
  | { readonly kind: "degraded"; readonly message: string }
  | { readonly kind: "unavailable"; readonly message: string };

export interface MapControllerOptions {
  readonly container: HTMLElement;
  readonly initialLayers: ResolvedMapLayers;
  readonly initialBand: VisualBand;
  readonly onCoordinate: (coordinates: Coordinates) => void;
  readonly onStatus: (status: MapRuntimeStatus) => void;
}

function isStyleSpecification(value: unknown): value is StyleSpecification {
  if (!value || typeof value !== "object") return false;
  const candidate = value as { version?: unknown; sources?: unknown; layers?: unknown };
  return candidate.version === 8 && Boolean(candidate.sources) && Array.isArray(candidate.layers);
}

function pmtilesUrl(url: string): string {
  return `pmtiles://${url}`;
}

function boundarySource(boundary: BoundaryVisualLayer): GeoJSONSourceSpecification | {
  type: "vector";
  url: string;
} {
  if (boundary.mediaType === "application/geo+json") {
    return { type: "geojson", data: boundary.url };
  }
  return { type: "vector", url: pmtilesUrl(boundary.url) };
}

function addBoundary(map: MapLibreMap, boundary: BoundaryVisualLayer): void {
  const sourceId = `searise-${boundary.kind}`;
  const layerId = `${sourceId}-line`;
  if (!map.getSource(sourceId)) map.addSource(sourceId, boundarySource(boundary));
  if (map.getLayer(layerId)) return;
  map.addLayer({
    id: layerId,
    type: "line",
    source: sourceId,
    ...(boundary.mediaType === "application/vnd.pmtiles"
      ? { "source-layer": boundary.sourceLayer }
      : {}),
    paint: {
      "line-color": boundary.kind === "coastal-boundary" ? "#075d68" : "#344f55",
      "line-width": boundary.kind === "coastal-boundary" ? 2.5 : 1.5,
      "line-dasharray": boundary.kind === "coastal-boundary" ? [1, 1.5] : [3, 2],
    },
  });
}

function valueColour(property: string): maplibregl.ExpressionSpecification {
  return [
    "interpolate",
    ["linear"],
    ["get", property],
    -100,
    "#e6f2ef",
    0,
    "#b9ddd7",
    250,
    "#65b5ad",
    500,
    "#267d83",
    1000,
    "#173f56",
    2000,
    "#2f183f",
  ];
}

export class MapController {
  readonly #map: MapLibreMap;
  readonly #protocol: ProtocolLease;
  readonly #renderToken = new RenderToken();
  readonly #onCoordinate: (coordinates: Coordinates) => void;
  readonly #onStatus: (status: MapRuntimeStatus) => void;
  #layers: ResolvedMapLayers;
  #band: VisualBand;
  #marker: maplibregl.Marker | undefined;
  #basemapAbort: AbortController | undefined;
  #basemapActive = false;
  #basemapUnavailable = false;
  #styleReady = false;
  #destroyed = false;

  constructor(options: MapControllerOptions) {
    this.#layers = options.initialLayers;
    this.#band = options.initialBand;
    this.#onCoordinate = options.onCoordinate;
    this.#onStatus = options.onStatus;
    this.#protocol = acquireProtocol(this.#layers);
    this.#map = new maplibregl.Map({
      container: options.container,
      style: EMPTY_STYLE,
      center: [10, 53],
      zoom: 3,
      minZoom: 1,
      maxZoom: 8,
      attributionControl: false,
      cooperativeGestures: true,
      interactive: false,
    });
    this.#map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
    this.#map.addControl(new maplibregl.AttributionControl({ compact: true }), "bottom-right");
    this.#map.on("error", (event) => {
      if (this.#destroyed) return;
      const sourceId = "sourceId" in event ? event.sourceId : undefined;
      if (sourceId === SOURCE_ID || !this.#basemapActive) {
        this.#onStatus({
          kind: "unavailable",
          message: "The visual overlay could not be rendered. The textual selection remains available.",
        });
      } else {
        this.#onStatus({
          kind: "degraded",
          message: "Some optional basemap detail is unavailable. Release data and text remain usable.",
        });
      }
    });
    this.#applyWhenReady(this.#renderToken.next(), true);
  }

  selectScreenPoint(clientX: number, clientY: number): void {
    const bounds = this.#map.getCanvas().getBoundingClientRect();
    const point = [clientX - bounds.left, clientY - bounds.top] as [number, number];
    const location = this.#map.unproject(point);
    const coordinates = Object.freeze({ latitude: location.lat, longitude: location.lng });
    this.setMarker(coordinates);
    this.#onCoordinate(coordinates);
  }

  #removeReleaseLayers(): void {
    for (const id of [OUTLINE_LAYER_ID, FILL_LAYER_ID]) {
      if (this.#map.getLayer(id)) this.#map.removeLayer(id);
    }
    if (this.#map.getSource(SOURCE_ID)) this.#map.removeSource(SOURCE_ID);
    for (const boundary of this.#layers.boundaries) {
      const sourceId = `searise-${boundary.kind}`;
      const layerId = `${sourceId}-line`;
      if (this.#map.getLayer(layerId)) this.#map.removeLayer(layerId);
      if (this.#map.getSource(sourceId)) this.#map.removeSource(sourceId);
    }
  }

  #applyWhenReady(token: number, fit: boolean): void {
    const apply = () => {
      if (this.#destroyed || !this.#renderToken.isCurrent(token)) return;
      this.#removeReleaseLayers();
      const projection = this.#layers.projection;
      this.#protocol.register(this.#layers);
      this.#map.addSource(SOURCE_ID, {
        type: "vector",
        url: pmtilesUrl(projection.url),
        attribution: IPCC_ATTRIBUTION,
      });
      const valueProperty = projection.valueProperties[this.#band];
      this.#map.addLayer({
        id: FILL_LAYER_ID,
        type: "fill",
        source: SOURCE_ID,
        "source-layer": projection.sourceLayer,
        filter: ["has", valueProperty],
        paint: {
          "fill-color": valueColour(valueProperty),
          "fill-opacity": 0.68,
        },
      });
      this.#map.addLayer({
        id: OUTLINE_LAYER_ID,
        type: "line",
        source: SOURCE_ID,
        "source-layer": projection.sourceLayer,
        paint: { "line-color": "#10272d", "line-opacity": 0.48, "line-width": 0.7 },
      });
      for (const boundary of this.#layers.boundaries) addBoundary(this.#map, boundary);
      if (fit) this.#map.fitBounds([...projection.bounds], { padding: 32, duration: 0 });
      this.#onStatus(this.#basemapUnavailable
        ? {
            kind: "degraded",
            message: `Optional basemap unavailable. ${projection.scenario} · ${projection.horizon} · ${this.#band} release overlay ready.`,
          }
        : {
            kind: "ready",
            message: `${projection.scenario} · ${projection.horizon} · ${this.#band} visual band ready.`,
          });
    };
    if (this.#styleReady || this.#map.isStyleLoaded()) {
      this.#styleReady = true;
      apply();
    } else {
      this.#map.once("style.load", () => {
        this.#styleReady = true;
        apply();
      });
    }
  }

  update(layers: ResolvedMapLayers, band: VisualBand): void {
    this.#layers = layers;
    this.#band = band;
    this.#onStatus({ kind: "loading", message: "Updating the release-scoped visual overlay…" });
    this.#applyWhenReady(this.#renderToken.next(), false);
  }

  setMarker(coordinates: Coordinates | undefined): void {
    if (!coordinates) {
      this.#marker?.remove();
      this.#marker = undefined;
      return;
    }
    if (!this.#marker) {
      this.#marker = new maplibregl.Marker({ color: "#b23b2e" })
        .setLngLat([coordinates.longitude, coordinates.latitude])
        .addTo(this.#map);
    } else {
      this.#marker.setLngLat([coordinates.longitude, coordinates.latitude]);
    }
  }

  travelTo(coordinates: Coordinates, animated: boolean): void {
    if (this.#destroyed) return;
    this.#map.easeTo({
      center: [coordinates.longitude, coordinates.latitude],
      zoom: Math.max(this.#map.getZoom(), 5),
      duration: animated ? 900 : 0,
      essential: false,
    });
  }

  setInteractionEnabled(enabled: boolean): void {
    if (this.#destroyed) return;
    const handlers = [
      this.#map.boxZoom,
      this.#map.doubleClickZoom,
      this.#map.dragPan,
      this.#map.dragRotate,
      this.#map.keyboard,
      this.#map.scrollZoom,
      this.#map.touchZoomRotate,
    ];
    for (const handler of handlers) {
      if (enabled) handler.enable();
      else handler.disable();
    }
    this.#map.getCanvas().tabIndex = enabled ? 0 : -1;
    const controls = this.#map.getContainer().querySelector<HTMLElement>(".maplibregl-control-container");
    if (controls) {
      controls.inert = !enabled;
      if (enabled) controls.removeAttribute("aria-hidden");
      else controls.setAttribute("aria-hidden", "true");
    }
    for (const control of this.#map.getContainer().querySelectorAll<HTMLButtonElement>(".maplibregl-ctrl button")) {
      control.disabled = !enabled;
      control.tabIndex = enabled ? 0 : -1;
    }
  }

  finishTravel(coordinates: Coordinates): void {
    if (this.#destroyed) return;
    this.#map.stop();
    this.#map.jumpTo({
      center: [coordinates.longitude, coordinates.latitude],
      zoom: Math.max(this.#map.getZoom(), 5),
    });
  }

  async loadOptionalBasemap(): Promise<void> {
    this.#basemapAbort?.abort();
    const controller = new AbortController();
    this.#basemapAbort = controller;
    this.#basemapUnavailable = false;
    this.#onStatus({ kind: "loading", message: "Loading optional OpenFreeMap context…" });
    try {
      const response = await fetch(BASEMAP_STYLE_URL, {
        signal: controller.signal,
        credentials: "omit",
        headers: { Accept: "application/json" },
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const style: unknown = await response.json();
      if (!isStyleSpecification(style)) throw new Error("invalid style contract");
      if (controller.signal.aborted || this.#destroyed) return;
      this.#basemapActive = true;
      this.#basemapUnavailable = false;
      const token = this.#renderToken.next();
      this.#styleReady = false;
      this.#map.setStyle(style);
      this.#applyWhenReady(token, false);
    } catch (error) {
      if (controller.signal.aborted || this.#destroyed) return;
      this.#basemapActive = false;
      this.#basemapUnavailable = true;
      this.#onStatus({
        kind: "degraded",
        message: `Optional basemap unavailable${error instanceof Error ? ` (${error.message})` : ""}. Release overlay and text remain usable.`,
      });
    }
  }

  destroy(): void {
    if (this.#destroyed) return;
    this.#destroyed = true;
    this.#renderToken.invalidate();
    this.#basemapAbort?.abort();
    this.#marker?.remove();
    this.#map.remove();
    this.#protocol.release();
  }
}

export function createMapController(options: MapControllerOptions): MapController {
  return new MapController(options);
}
