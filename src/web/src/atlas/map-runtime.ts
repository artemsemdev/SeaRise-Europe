import * as maplibregl from "maplibre-gl";
import mapWorkerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url";
import { Protocol } from "pmtiles";

// Vite bundles the worker and its shared module into a same-origin asset.
maplibregl.setWorkerUrl(mapWorkerUrl);
maplibregl.addProtocol("pmtiles", new Protocol().tile);
export { maplibregl };
