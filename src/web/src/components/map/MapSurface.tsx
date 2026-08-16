import { useEffect, useRef, useState } from "react";
import type { Coordinates } from "../../domain/release";
import type { ResolvedMapLayers, VisualBand } from "../../data/map-layer-resolver";
import type { MapController, MapRuntimeStatus } from "./map-runtime";

interface MapSurfaceProps {
  readonly layers: ResolvedMapLayers;
  readonly band: VisualBand;
  readonly marker?: Coordinates;
  readonly onCoordinate: (coordinates: Coordinates) => void;
}

const INITIAL_STATUS: MapRuntimeStatus = {
  kind: "loading",
  message: "Loading the release-scoped map renderer…",
};

export function MapSurface({ layers, band, marker, onCoordinate }: MapSurfaceProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const controllerRef = useRef<MapController | undefined>(undefined);
  const currentRef = useRef({ layers, band, marker, onCoordinate });
  const [status, setStatus] = useState<MapRuntimeStatus>(INITIAL_STATUS);
  const [controllerReady, setControllerReady] = useState(false);

  useEffect(() => {
    currentRef.current = { layers, band, marker, onCoordinate };
  }, [layers, band, marker, onCoordinate]);

  useEffect(() => {
    let cancelled = false;
    void import("./map-runtime").then(({ createMapController }) => {
      if (cancelled || !containerRef.current) return;
      const current = currentRef.current;
      const controller = createMapController({
        container: containerRef.current,
        initialLayers: current.layers,
        initialBand: current.band,
        onCoordinate: (coordinates) => currentRef.current.onCoordinate(coordinates),
        onStatus: setStatus,
      });
      controller.setMarker(current.marker);
      controllerRef.current = controller;
      setControllerReady(true);
    }).catch(() => {
      if (!cancelled) {
        setStatus({
          kind: "unavailable",
          message: "The optional map renderer could not start. The text alternative remains available.",
        });
      }
    });
    return () => {
      cancelled = true;
      controllerRef.current?.destroy();
      controllerRef.current = undefined;
      setControllerReady(false);
    };
  }, []);

  useEffect(() => {
    controllerRef.current?.update(layers, band);
  }, [layers, band]);

  useEffect(() => {
    controllerRef.current?.setMarker(marker);
  }, [marker]);

  return (
    <div className="map-surface-shell">
      <div
        ref={containerRef}
        className="map-surface"
        role="region"
        aria-label={`Interactive visual map for ${layers.projection.scenario}, ${layers.projection.horizon}. Exact values are not read from this map.`}
        data-release-id={layers.projection.dataReleaseId}
        data-artifact-id={layers.projection.artifactId}
        onClickCapture={(event) => {
          const target = event.target;
          if (!(target instanceof Element) || !target.closest(".maplibregl-control-container")) {
            controllerRef.current?.selectScreenPoint(event.clientX, event.clientY);
          }
        }}
      />
      <button
        className="map-selection-pin"
        type="button"
        disabled={!controllerReady}
        aria-label="Select coordinate at source extent centre"
        onClick={() => {
          const [west, south, east, north] = layers.projection.bounds;
          onCoordinate(Object.freeze({
            latitude: (south + north) / 2,
            longitude: (west + east) / 2,
          }));
        }}
      >
        <span aria-hidden="true" />
      </button>
      <div className={`map-status ${status.kind}`} role="status" aria-live="polite">
        {status.message}
      </div>
      <button
        className="basemap-button"
        type="button"
        disabled={!controllerReady}
        onClick={() => void controllerRef.current?.loadOptionalBasemap()}
      >
        Load optional basemap
      </button>
    </div>
  );
}
