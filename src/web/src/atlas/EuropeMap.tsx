import { Crosshair, Minus, Plus, GlobeHemisphereEast, Link, Check, NavigationArrow } from "@phosphor-icons/react";
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { maplibregl } from "./map-runtime";
import type { Map as MapLibreMap } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import {
  createEuropeStyle, FLOOD_BEFORE_LAYER, FLOOD_MAX_ZOOM, floodTileZoom,
  FIXTURE_ORIENTATION_PLACES, MAP_MAX_ZOOM,
} from "./basemap-style";

export interface EuropeMapCity {
  readonly id: string;
  readonly name: string;
  readonly countryName: string;
  readonly countryCode: string;
  readonly coordinates: readonly [number, number];
}

export interface EuropeMapStatus {
  readonly loading: boolean;
  readonly error: string | null;
  readonly validPixels: number | null;
  readonly floodPixels: number | null;
}

export interface EuropeMapCamera {
  readonly lng: number;
  readonly lat: number;
  readonly zoom: number;
}

export interface EuropeMapDataSource {
  readonly edition: "real-local" | "synthetic-fixture";
  readonly getTile: (request: {
    readonly year: 2030 | 2050 | 2100;
    readonly protection: "unprotected" | "protected";
    readonly z: number;
    readonly x: number;
    readonly y: number;
    readonly signal?: AbortSignal;
  }) => Promise<{ readonly data: ArrayBuffer; readonly validPixels: number; readonly floodPixels: number }>;
}

type FloodTileRequest = Parameters<EuropeMapDataSource["getTile"]>[0];
type FloodTileResult = Awaited<ReturnType<EuropeMapDataSource["getTile"]>>;

// Exported for the provider boundary tests kept beside this component.
// eslint-disable-next-line react-refresh/only-export-components
export async function loadFloodTile(
  dataSource: EuropeMapDataSource,
  request: FloodTileRequest,
): Promise<FloodTileResult> {
  const tile = await dataSource.getTile(request);
  if (!(tile.data instanceof ArrayBuffer) || !Number.isSafeInteger(tile.validPixels) || tile.validPixels < 0 ||
    !Number.isSafeInteger(tile.floodPixels) || tile.floodPixels < 0) {
    throw new TypeError("A flood tile provider returned an invalid tile result.");
  }
  if (tile.floodPixels > tile.validPixels) {
    throw new TypeError("A local flood tile has inconsistent pixel counts.");
  }
  return tile;
}

export interface EuropeMapProps {
  readonly qaMapEnabled?: boolean;
  readonly dataSource: EuropeMapDataSource;
  onOverview?: () => void;
  onShare?: () => void;
  onRefocus?: () => void;
  onPlace?: (id: string) => void;
  shared?: boolean;
  readonly city: EuropeMapCity | null;
  readonly year: 2030 | 2050 | 2100;
  readonly protection: "unprotected" | "protected";
  readonly visible: boolean;
  readonly onStatus: (status: EuropeMapStatus) => void;
  readonly initialCamera?: EuropeMapCamera | null;
  readonly onCameraChange?: (camera: EuropeMapCamera) => void;
  readonly inspectionPoint?: readonly [number, number] | null;
  readonly onInspect?: (point: [number, number]) => void;
  readonly focusRequest?: number;
  /** True only while resolving the city saved with initialCamera. */
  readonly restoreCity?: boolean;
}

interface TileCounts {
  readonly z: number;
  readonly x: number;
  readonly y: number;
  readonly validPixels: number;
  readonly floodPixels: number;
}

interface ActiveLayer {
  readonly generation: number;
  readonly key: string;
  readonly tiles: Map<string, TileCounts>;
  visible: boolean;
}

const EUROPE_CENTER: [number, number] = [9, 51];
const EUROPE_BOUNDS: [[number, number], [number, number]] = [[-31, 28], [46, 77]];
// Frame the main European coast on entry. The wider navigation envelope still
// includes the prepared Atlantic islands and northern European coverage. Fit
// all of Ukraine, whose eastern border extends beyond 40° E.
const EUROPE_OVERVIEW_BOUNDS: [[number, number], [number, number]] = [[-12, 35], [41, 71.5]];
const EUROPE_ZOOM = 3.3;
const CITY_ZOOM = 8.2;
const FLOOD_SOURCE = "atlas-europe-flood-source";
const FLOOD_LAYER = "atlas-europe-flood";
const PROTOCOL_PREFIX = "searise-europe-flood";
const PLAIN_MAP_ERROR = "The map could not load its local geographic data.";

let protocolSequence = 0;

function layerKey(year: EuropeMapProps["year"], protection: EuropeMapProps["protection"]): string {
  return `ssp585-${year}-${protection}`;
}

function tileIntersectsView(tile: TileCounts, map: MapLibreMap): boolean {
  const scale = 2 ** tile.z;
  const west = tile.x / scale * 360 - 180;
  const east = (tile.x + 1) / scale * 360 - 180;
  const north = Math.atan(Math.sinh(Math.PI * (1 - 2 * tile.y / scale))) * 180 / Math.PI;
  const south = Math.atan(Math.sinh(Math.PI * (1 - 2 * (tile.y + 1) / scale))) * 180 / Math.PI;
  const bounds = map.getBounds();
  return east >= bounds.getWest() && west <= bounds.getEast() &&
    north >= bounds.getSouth() && south <= bounds.getNorth();
}

function currentViewCounts(active: ActiveLayer, map: MapLibreMap): Pick<EuropeMapStatus, "validPixels" | "floodPixels"> | null {
  const candidates = [...active.tiles.values()].filter((tile) => tileIntersectsView(tile, map));
  if (!candidates.length) return null;
  const desiredZoom = floodTileZoom(map.getZoom());
  const targetZoom = [...new Set(candidates.map((tile) => tile.z))]
    .sort((left, right) => Math.abs(left - desiredZoom) - Math.abs(right - desiredZoom))[0];
  let validPixels = 0;
  let floodPixels = 0;
  for (const tile of candidates) {
    if (tile.z !== targetZoom) continue;
    validPixels += tile.validPixels;
    floodPixels += tile.floodPixels;
  }
  return { validPixels, floodPixels };
}

function markerElement(color = "#f4ad3d", size = 15): HTMLDivElement {
  const marker = document.createElement("div");
  marker.setAttribute("aria-hidden", "true");
  Object.assign(marker.style, {
    width: `${size}px`,
    height: `${size}px`,
    borderRadius: "50%",
    background: color,
    border: "2px solid #fff1d4",
    boxShadow: `0 0 0 5px color-mix(in srgb, ${color} 20%, transparent), 0 5px 16px rgba(2,17,31,.52)`,
  });
  return marker;
}

function fixturePlaceLabel(name: string, onActivate: () => void): HTMLButtonElement {
  const label = document.createElement("button");
  label.type = "button";
  label.textContent = name;
  label.setAttribute("aria-label", `Open ${name}`);
  Object.assign(label.style, {
    border: "0", background: "rgba(247,247,240,.9)", color: "#1B1F26",
    borderRadius: "4px", padding: "2px 5px", font: "600 12px system-ui, sans-serif",
    boxShadow: "0 1px 4px rgba(2,17,31,.18)", cursor: "pointer",
  });
  label.addEventListener("click", (event) => { event.stopPropagation(); onActivate(); });
  return label;
}

function cityCoordinates(city: EuropeMapCity): [number, number] {
  return [city.coordinates[0], city.coordinates[1]];
}

function focusCity(map: MapLibreMap, city: EuropeMapCity): void {
  const reduced = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
  const mobile = window.matchMedia?.("(max-width: 760px)").matches;
  const camera = {
    center: cityCoordinates(city), zoom: CITY_ZOOM, pitch: 0, bearing: 0, padding: 0,
    offset: (mobile ? [0, 0] : [120, 0]) as [number, number],
    duration: reduced ? 0 : 850, essential: false,
  };
  // flyTo's reduced-motion shortcut drops offset. easeTo preserves the
  // selected city's visible anchor while still moving without animation.
  if (reduced) map.easeTo(camera);
  else map.flyTo(camera);
}

export function EuropeMap({
  dataSource, qaMapEnabled = false,
  city, year, protection, visible, onStatus, initialCamera = null, onCameraChange,
  inspectionPoint = null, onInspect, focusRequest, restoreCity = false, onOverview, onShare, onRefocus, onPlace, shared = false,
}: EuropeMapProps) {
  const rootRef = useRef<HTMLDivElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MapLibreMap | null>(null);
  const markerRef = useRef<maplibregl.Marker | null>(null);
  const inspectionMarkerRef = useRef<maplibregl.Marker | null>(null);
  const fixturePlaceMarkersRef = useRef<maplibregl.Marker[]>([]);
  const onStatusRef = useRef(onStatus);
  const onCameraChangeRef = useRef(onCameraChange);
  const onInspectRef = useRef(onInspect);
  const onPlaceRef = useRef(onPlace);
  const dataSourceRef = useRef(dataSource);
  const editionRef = useRef(dataSource.edition);
  const activeLayerRef = useRef<ActiveLayer | null>(null);
  const generationRef = useRef(0);
  const destroyedRef = useRef(false);
  const fatalErrorRef = useRef(false);
  const initialCityRef = useRef(city);
  const initialCameraRef = useRef(initialCamera);
  const skipInitialNavigationRef = useRef(initialCamera !== null);
  const preserveInitialCameraRef = useRef(initialCamera !== null && restoreCity);
  const focusRequestRef = useRef<number | undefined>(focusRequest);
  const overviewRef = useRef<{ center: maplibregl.LngLat; zoom: number } | null>(null);
  const [mapReady, setMapReady] = useState(false);
  const [zoomState, setZoomState] = useState({ zoom: EUROPE_ZOOM, min: 0, max: MAP_MAX_ZOOM });
  const [protocolName] = useState(() => `${PROTOCOL_PREFIX}-${++protocolSequence}`);

  useEffect(() => { onStatusRef.current = onStatus; }, [onStatus]);
  useEffect(() => { onCameraChangeRef.current = onCameraChange; }, [onCameraChange]);
  useEffect(() => { onInspectRef.current = onInspect; }, [onInspect]);
  useEffect(() => { onPlaceRef.current = onPlace; }, [onPlace]);
  useEffect(() => { dataSourceRef.current = dataSource; }, [dataSource]);

  const publish = useCallback((status: EuropeMapStatus) => {
    const root = rootRef.current;
    if (root) {
      root.dataset.validPixels = status.validPixels === null ? "" : String(status.validPixels);
      root.dataset.floodPixels = status.floodPixels === null ? "" : String(status.floodPixels);
    }
    onStatusRef.current(status);
  }, []);

  const publishError = useCallback(() => {
    fatalErrorRef.current = true;
    publish({ loading: false, error: PLAIN_MAP_ERROR, validPixels: null, floodPixels: null });
  }, [publish]);

  useEffect(() => {
    if (!containerRef.current) return;
    destroyedRef.current = false;
    fatalErrorRef.current = false;
    publish({ loading: true, error: null, validPixels: null, floodPixels: null });

    maplibregl.addProtocol(protocolName, async (request, abortController) => {
      const pattern = new RegExp(`^${protocolName}://coclico/total/g([0-9]+)/((?:2030|2050|2100))/(unprotected|protected)/([0-9]+)/([0-9]+)/([0-9]+)\\.png$`, "u");
      const match = pattern.exec(request.url);
      if (!match) throw new TypeError("A local flood tile URL is invalid.");
      const [, generationRaw, yearRaw, protectionRaw, zRaw, xRaw, yRaw] = match;
      const generation = Number(generationRaw);
      const tileYear = Number(yearRaw) as EuropeMapProps["year"];
      const tileProtection = protectionRaw as EuropeMapProps["protection"];
      const z = Number(zRaw);
      const x = Number(xRaw);
      const y = Number(yRaw);
      const scale = 2 ** z;
      if (!Number.isSafeInteger(generation) || generation < 1 || z < 0 || z > FLOOD_MAX_ZOOM ||
        !Number.isSafeInteger(x) || !Number.isSafeInteger(y) || x < 0 || y < 0 || x >= scale || y >= scale) {
        throw new TypeError("A local flood tile coordinate is invalid.");
      }
      try {
        const tile = await loadFloodTile(dataSourceRef.current, {
          year: tileYear, protection: tileProtection, z, x, y,
          signal: abortController.signal,
        });
        const { data, validPixels, floodPixels } = tile;
        const active = activeLayerRef.current;
        if (active?.generation === generation && active.key === layerKey(tileYear, tileProtection)) {
          active.tiles.set(`${z}/${x}/${y}`, { z, x, y, validPixels, floodPixels });
        }
        return { data };
      } catch (error) {
        if (!abortController.signal.aborted && activeLayerRef.current?.generation === generation) publishError();
        throw error;
      }
    });

    const initialCity = initialCityRef.current;
    const initialCamera = initialCameraRef.current;
    const map = new maplibregl.Map({
      container: containerRef.current,
      style: createEuropeStyle(window.location.origin, editionRef.current),
      center: initialCamera ? [initialCamera.lng, initialCamera.lat] : initialCity ? cityCoordinates(initialCity) : EUROPE_CENTER,
      zoom: initialCamera?.zoom ?? (initialCity ? CITY_ZOOM : EUROPE_ZOOM),
      pitch: 0,
      bearing: 0,
      minZoom: 0,
      maxZoom: MAP_MAX_ZOOM,
      // Preserve discrete scientific cells without making the data look smoother.
      anisotropicFilterPitch: 180,
      renderWorldCopies: false,
      attributionControl: false,
      dragRotate: false,
      pitchWithRotate: false,
      touchPitch: false,
    });
    mapRef.current = map;
    if (editionRef.current === "synthetic-fixture") {
      fixturePlaceMarkersRef.current = FIXTURE_ORIENTATION_PLACES.features.map((place) =>
        new maplibregl.Marker({
          element: fixturePlaceLabel(place.properties.name, () => onPlaceRef.current?.(place.properties.sourceId)),
          anchor: "left", offset: [8, 0],
        }).setLngLat(place.geometry.coordinates as [number, number]).addTo(map));
    }
    map.dragRotate.disable();
    map.touchZoomRotate.disableRotation();
    let resizeFrame: number | null = null;
    const resizeObserver = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(() => {
      if (resizeFrame !== null) cancelAnimationFrame(resizeFrame);
      resizeFrame = requestAnimationFrame(() => {
        resizeFrame = null;
        if (!destroyedRef.current) map.resize();
      });
    });
    resizeObserver?.observe(containerRef.current);
    const updateOverview = () => {
      const previous = overviewRef.current;
      const mobile = window.matchMedia?.("(max-width: 760px)").matches;
      const camera = map.cameraForBounds(EUROPE_OVERVIEW_BOUNDS, {
        padding: { top: mobile ? 12 : 24, bottom: mobile ? 12 : 120, left: mobile ? 12 : 350, right: mobile ? 12 : 54 },
        bearing: 0, maxZoom: 5,
      });
      if (!camera?.center || typeof camera.zoom !== "number") return;
      const atOverview = previous && map.getZoom() <= previous.zoom + 0.01;
      overviewRef.current = { center: maplibregl.LngLat.convert(camera.center), zoom: Math.max(0, camera.zoom) };
      map.setMinZoom(overviewRef.current.zoom);
      setZoomState({ zoom: map.getZoom(), min: overviewRef.current.zoom, max: MAP_MAX_ZOOM });
      if (atOverview) map.jumpTo({ ...overviewRef.current, pitch: 0, bearing: 0, padding: { top: 0, right: 0, bottom: 0, left: 0 } });
    };
    map.setTransformConstrain((center, requestedZoom) => {
      const overview = overviewRef.current;
      if (!overview) return { center, zoom: requestedZoom ?? EUROPE_ZOOM };
      const zoom = Math.max(overview.zoom, Math.min(MAP_MAX_ZOOM, requestedZoom ?? map.getZoom()));
      // At the broadest view keep the fitted European composition in place.
      // Permit progressively more panning as the user explores European detail.
      const freedom = Math.min(1, (zoom - overview.zoom) / 2);
      const west = overview.center.lng + (EUROPE_BOUNDS[0][0] - overview.center.lng) * freedom;
      const east = overview.center.lng + (EUROPE_BOUNDS[1][0] - overview.center.lng) * freedom;
      const south = overview.center.lat + (EUROPE_BOUNDS[0][1] - overview.center.lat) * freedom;
      const north = overview.center.lat + (EUROPE_BOUNDS[1][1] - overview.center.lat) * freedom;
      return { center: new maplibregl.LngLat(Math.max(west, Math.min(east, center.lng)), Math.max(south, Math.min(north, center.lat))), zoom };
    });
    updateOverview();
    map.on("resize", updateOverview);
    const updateDragPan = () => {
      const canPan = map.getZoom() > map.getMinZoom() + 0.000001;
      if (canPan !== map.dragPan.isEnabled()) {
        if (canPan) map.dragPan.enable();
        else map.dragPan.disable();
      }
    };
    const updateZoomState = () => setZoomState({ zoom: map.getZoom(), min: map.getMinZoom(), max: MAP_MAX_ZOOM });
    map.on("zoom", updateDragPan);
    map.on("zoom", updateZoomState);
    map.on("resize", updateDragPan);
    updateDragPan();
    updateZoomState();
    map.on("moveend", () => {
      const overview = overviewRef.current;
      if (overview && map.getZoom() <= overview.zoom + 0.01 && (map.getPitch() !== 0 || map.getBearing() !== 0)) {
        map.jumpTo({ ...overview, pitch: 0, bearing: 0, padding: { top: 0, right: 0, bottom: 0, left: 0 } });
      }
      onCameraChangeRef.current?.({ lng: map.getCenter().lng, lat: map.getCenter().lat, zoom: map.getZoom() });
    });
    map.on("click", (event) => {
      const placeLayers = editionRef.current === "real-local"
        ? ["atlas-europe-overview-place-dot", "atlas-europe-overview-place-label"]
        : ["atlas-europe-overview-place-dot"];
      const place = map.queryRenderedFeatures(event.point, { layers: placeLayers })[0];
      if (typeof place?.properties.sourceId === "string" && onPlaceRef.current) {
        onPlaceRef.current(place.properties.sourceId);
        return;
      }
      const point: [number, number] = [event.lngLat.lng, event.lngLat.lat];
      if (point[0] < EUROPE_BOUNDS[0][0] || point[0] > EUROPE_BOUNDS[1][0] ||
        point[1] < EUROPE_BOUNDS[0][1] || point[1] > EUROPE_BOUNDS[1][1]) return;
      onInspectRef.current?.(point);
    });
    map.addControl(new maplibregl.ScaleControl({ maxWidth: 110, unit: "metric" }), "bottom-right");
    const qaWindow = window as Window & { __SEARISE_ATLAS_MAP__?: MapLibreMap };
    if (qaMapEnabled) qaWindow.__SEARISE_ATLAS_MAP__ = map;
    map.on("error", (event) => {
      if (destroyedRef.current || (event.error instanceof Error && event.error.name === "AbortError")) return;
      publishError();
    });
    map.on("movestart", () => {
      const active = activeLayerRef.current;
      if (active?.visible && !fatalErrorRef.current) {
        publish({ loading: true, error: null, validPixels: null, floodPixels: null });
      }
    });
    const publishLoadedView = () => {
      const active = activeLayerRef.current;
      if (!active || !active.visible || fatalErrorRef.current || !map.areTilesLoaded()) return;
      const counts = currentViewCounts(active, map);
      if (!counts) return;
      publish({ loading: false, error: null, ...counts });
    };
    map.on("idle", publishLoadedView);
    map.on("moveend", publishLoadedView);
    map.once("load", () => setMapReady(true));

    return () => {
      destroyedRef.current = true;
      activeLayerRef.current = null;
      markerRef.current?.remove();
      markerRef.current = null;
      inspectionMarkerRef.current?.remove();
      inspectionMarkerRef.current = null;
      fixturePlaceMarkersRef.current.forEach((marker) => marker.remove());
      fixturePlaceMarkersRef.current = [];
      if (qaWindow.__SEARISE_ATLAS_MAP__ === map) delete qaWindow.__SEARISE_ATLAS_MAP__;
      map.remove();
      mapRef.current = null;
      overviewRef.current = null;
      resizeObserver?.disconnect();
      if (resizeFrame !== null) cancelAnimationFrame(resizeFrame);
      maplibregl.removeProtocol(protocolName);
      setMapReady(false);
    };
  }, [protocolName, publish, publishError, qaMapEnabled]);

  useLayoutEffect(() => {
    const map = mapRef.current;
    if (!map || !mapReady) return;
    const generation = ++generationRef.current;
    const key = layerKey(year, protection);
    activeLayerRef.current = { generation, key, tiles: new Map(), visible };
    if (rootRef.current) {
      rootRef.current.dataset.layer = key;
      rootRef.current.dataset.validPixels = "";
      rootRef.current.dataset.floodPixels = "";
    }
    publish({ loading: visible, error: null, validPixels: null, floodPixels: null });
    if (map.getLayer(FLOOD_LAYER)) {
      map.setLayoutProperty(FLOOD_LAYER, "visibility", "none");
      map.removeLayer(FLOOD_LAYER);
    }
    if (map.getSource(FLOOD_SOURCE)) map.removeSource(FLOOD_SOURCE);
    if (fatalErrorRef.current) {
      publishError();
      return;
    }
    map.addSource(FLOOD_SOURCE, {
      type: "raster",
      tiles: [`${protocolName}://coclico/total/g${generation}/${year}/${protection}/{z}/{x}/{y}.png`],
      tileSize: 256,
      minzoom: 0,
      maxzoom: FLOOD_MAX_ZOOM,
    });
    map.addLayer({
      id: FLOOD_LAYER,
      type: "raster",
      source: FLOOD_SOURCE,
      layout: { visibility: visible ? "visible" : "none" },
      paint: { "raster-opacity": 1, "raster-fade-duration": 0, "raster-resampling": "nearest" },
    }, FLOOD_BEFORE_LAYER);
  }, [mapReady, protection, protocolName, publish, publishError, visible, year]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapReady) return;
    markerRef.current?.remove();
    markerRef.current = null;
    if (city) {
      markerRef.current = new maplibregl.Marker({ element: markerElement() }).setLngLat(cityCoordinates(city)).addTo(map);
    }
    if (skipInitialNavigationRef.current) {
      skipInitialNavigationRef.current = false;
      if (city) preserveInitialCameraRef.current = false;
      return;
    }
    if (preserveInitialCameraRef.current) {
      if (city) preserveInitialCameraRef.current = false;
      return;
    }
    const reduced = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    if (city) {
      focusCity(map, city);
    } else {
      const overview = overviewRef.current;
      if (overview) map.easeTo({ ...overview, pitch: 0, bearing: 0, padding: 0, duration: reduced ? 0 : 850 });
    }
  }, [city, mapReady]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapReady) return;
    inspectionMarkerRef.current?.remove();
    inspectionMarkerRef.current = null;
    // The point result has one matching marker; the city remains a navigation target.
    if (markerRef.current) markerRef.current.getElement().hidden = !!inspectionPoint;
    if (inspectionPoint) {
      inspectionMarkerRef.current = new maplibregl.Marker({ element: markerElement("#82d7e4", 11) })
        .setLngLat([inspectionPoint[0], inspectionPoint[1]])
        .addTo(map);
    }
  }, [city, inspectionPoint, mapReady]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapReady || focusRequest === undefined || focusRequest === focusRequestRef.current || !city) return;
    focusRequestRef.current = focusRequest;
    focusCity(map, city);
  }, [city, focusRequest, mapReady]);

  const zoomBy = (delta: number) => {
    const map = mapRef.current;
    if (!map) return;
    const mobile = window.matchMedia?.("(max-width: 760px)").matches;
    const canvas = map.getCanvas();
    const nextZoom = Math.max(map.getMinZoom(), Math.min(MAP_MAX_ZOOM, map.getZoom() + delta));
    if (overviewRef.current && nextZoom === map.getMinZoom()) {
      if (map.getZoom() <= map.getMinZoom() + 0.000001 && map.getPitch() === 0 && map.getBearing() === 0) return;
      map.easeTo({ ...overviewRef.current, pitch: 0, bearing: 0, padding: 0,
        duration: window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ? 0 : 300 });
      return;
    }
    // Match the visible map focus used when placing a city beside the story.
    // Zooming around the canvas center would move that city out of the view.
    const around = map.unproject([canvas.clientWidth / 2 + (mobile ? 0 : 120), canvas.clientHeight / 2]);
    map.easeTo({
      zoom: nextZoom,
      around,
      duration: window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ? 0 : 300,
    });
  };

  const canZoomIn = mapReady && zoomState.zoom < zoomState.max - 0.000001;
  const canZoomOut = mapReady && zoomState.zoom > zoomState.min + 0.000001;

  return (
    <div
      ref={rootRef}
      className="atlas-map"
      aria-label="Interactive Europe inundation atlas"
      data-layer={layerKey(year, protection)}
      data-valid-pixels=""
      data-flood-pixels=""
      style={{ position: "relative", width: "100%", height: "100%" }}
    >
      <div ref={containerRef} className="atlas-map__canvas" style={{ position: "absolute", inset: 0 }} />
      <div className="atlas-map__controls" aria-label="Map controls">
        <button type="button" aria-label="Zoom in" title="Zoom in" disabled={!canZoomIn} onClick={() => zoomBy(1)}><Plus size={18} weight="bold" /></button>
        <button type="button" aria-label="Zoom out" title="Zoom out" disabled={!canZoomOut} onClick={() => zoomBy(-1)}><Minus size={18} weight="bold" /></button>
        <button type="button" aria-label="Inspect map center" title="Inspect map center" disabled={!mapReady} onClick={() => {
          const center = mapRef.current?.getCenter();
          if (center) onInspectRef.current?.([center.lng, center.lat]);
        }}><Crosshair size={19} /></button>
        {onRefocus && <button className="refocus-control" type="button" aria-label="Return to selected place" title="Return to selected place" disabled={!city || !mapReady} onClick={onRefocus}><NavigationArrow size={18} /></button>}
        {onOverview && <button type="button" aria-label="European overview" title="European overview" onClick={onOverview}><GlobeHemisphereEast size={19} /></button>}
        {onShare && <button type="button" aria-label={shared ? "Link copied" : "Copy link to this view"} title="Copy link to this view" onClick={onShare}>{shared ? <Check size={19} /> : <Link size={19} />}</button>}
      </div>

    </div>
  );
}
