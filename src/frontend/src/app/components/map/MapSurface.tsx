"use client";

import { useEffect, useRef, useCallback } from "react";
import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { useMapStore, useSelectedLocation } from "@/lib/store/mapStore";
import { useAppStore, useAppPhase } from "@/lib/store/appStore";
import { strings } from "@/lib/i18n/en";
import LocationMarker from "./LocationMarker";

const DEFAULT_CENTER: [number, number] = [10, 54];
const DEFAULT_ZOOM = 4;
const EXPOSURE_SOURCE = "exposure-tiles";
const EXPOSURE_LAYER = "exposure-layer";

const FALLBACK_STYLE: maplibregl.StyleSpecification = {
  version: 8,
  sources: {
    carto: {
      type: "raster",
      tiles: [
        "https://a.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png",
        "https://b.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png",
        "https://c.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png",
        "https://d.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png",
      ],
      tileSize: 256,
      attribution: "&copy; OpenStreetMap contributors, &copy; CARTO",
    },
  },
  layers: [
    {
      id: "carto-dark",
      type: "raster",
      source: "carto",
      minzoom: 0,
      maxzoom: 19,
    },
  ],
};

export default function MapSurface() {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const markerRef = useRef<LocationMarker | null>(null);
  const selectedLocation = useSelectedLocation();
  const setViewport = useMapStore((s) => s.setViewport);
  const startAssessing = useAppStore((s) => s.startAssessing);
  const setSelectedLocation = useMapStore((s) => s.setSelectedLocation);
  const phase = useAppPhase();

  const handleMapClick = useCallback(
    (e: maplibregl.MapMouseEvent) => {
      const currentLocation = useMapStore.getState().selectedLocation;
      if (!currentLocation) return;

      const newLocation = {
        label: `${e.lngLat.lat.toFixed(4)}, ${e.lngLat.lng.toFixed(4)}`,
        latitude: e.lngLat.lat,
        longitude: e.lngLat.lng,
      };
      setSelectedLocation(newLocation);
      startAssessing(newLocation);
    },
    [startAssessing, setSelectedLocation]
  );

  // Initialize map
  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;

    const styleUrl = process.env.NEXT_PUBLIC_BASEMAP_STYLE_URL;
    const style: string | maplibregl.StyleSpecification = styleUrl || FALLBACK_STYLE;

    const map = new maplibregl.Map({
      container: containerRef.current,
      style,
      center: DEFAULT_CENTER,
      zoom: DEFAULT_ZOOM,
      attributionControl: {},
    });

    map.getContainer().setAttribute("role", "img");
    map.getContainer().setAttribute(
      "aria-label",
      strings.accessibility.mapLabel
    );

    map.on("moveend", () => {
      const center = map.getCenter();
      setViewport({
        center: [center.lng, center.lat],
        zoom: map.getZoom(),
      });
    });

    map.on("click", (e) => handleMapClick(e));

    mapRef.current = map;

    return () => {
      map.remove();
      mapRef.current = null;
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Update aria-label when phase changes
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;

    if (phase.phase === "result" && selectedLocation) {
      const label = strings.accessibility.mapWithResult(
        selectedLocation.label,
        phase.result.scenario.displayName,
        phase.result.horizon.year
      );
      map.getContainer().setAttribute("aria-label", label);
    } else if (selectedLocation) {
      map.getContainer().setAttribute(
        "aria-label",
        strings.accessibility.mapWithLocation(selectedLocation.label)
      );
    } else {
      map.getContainer().setAttribute("aria-label", strings.accessibility.mapLabel);
    }
  }, [selectedLocation, phase]);

  // Fly to selected location and manage marker
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;

    if (selectedLocation) {
      map.flyTo({
        center: [selectedLocation.longitude, selectedLocation.latitude],
        zoom: Math.max(map.getZoom(), 10),
        duration: 1500,
      });

      // Determine marker color based on result state
      const isWarn =
        phase.phase === "result" &&
        phase.result.resultState === "ModeledExposureDetected";

      if (markerRef.current) {
        (markerRef.current as unknown as maplibregl.Marker).setLngLat([
          selectedLocation.longitude,
          selectedLocation.latitude,
        ]);
        // Update marker color
        const el = (markerRef.current as unknown as maplibregl.Marker).getElement();
        el.style.background = isWarn ? "rgba(255,186,56,.3)" : "rgba(157, 202, 255, 0.3)";
        const inner = el.querySelector("div") as HTMLElement | null;
        if (inner) inner.style.background = isWarn ? "#ffba38" : "#9dcaff";
      } else {
        const el = document.createElement("div");
        el.style.width = "28px";
        el.style.height = "28px";
        el.style.borderRadius = "50%";
        el.style.background = isWarn ? "rgba(255,186,56,.3)" : "rgba(157, 202, 255, 0.3)";
        el.style.display = "flex";
        el.style.alignItems = "center";
        el.style.justifyContent = "center";
        el.style.animation = "marker-pulse 2s ease-in-out infinite";
        const inner = document.createElement("div");
        inner.style.width = "10px";
        inner.style.height = "10px";
        inner.style.borderRadius = "50%";
        inner.style.background = isWarn ? "#ffba38" : "#9dcaff";
        el.appendChild(inner);

        const marker = new maplibregl.Marker({ element: el })
          .setLngLat([
            selectedLocation.longitude,
            selectedLocation.latitude,
          ])
          .addTo(map);

        markerRef.current = marker as unknown as LocationMarker;
      }
    } else if (markerRef.current) {
      (markerRef.current as unknown as maplibregl.Marker).remove();
      markerRef.current = null;
    }
  }, [selectedLocation, phase]);

  // Manage exposure tile layer
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;

    const setupLayer = () => {
      const tileUrl =
        phase.phase === "result" &&
        phase.result.resultState === "ModeledExposureDetected" &&
        phase.result.layerTileUrlTemplate
          ? phase.result.layerTileUrlTemplate
          : null;

      // Remove existing exposure layer/source if present
      if (map.getLayer(EXPOSURE_LAYER)) {
        map.removeLayer(EXPOSURE_LAYER);
      }
      if (map.getSource(EXPOSURE_SOURCE)) {
        map.removeSource(EXPOSURE_SOURCE);
      }

      // Add new exposure layer if there's a tile URL
      if (tileUrl) {
        map.addSource(EXPOSURE_SOURCE, {
          type: "raster",
          tiles: [tileUrl],
          tileSize: 256,
        });
        map.addLayer({
          id: EXPOSURE_LAYER,
          type: "raster",
          source: EXPOSURE_SOURCE,
          paint: {
            "raster-opacity": 0.7,
          },
        });
      }
    };

    if (map.isStyleLoaded()) {
      setupLayer();
    } else {
      map.on("load", setupLayer);
    }
  }, [phase]);

  return (
    <div
      ref={containerRef}
      className="h-full w-full"
      data-testid="map-container"
    />
  );
}
