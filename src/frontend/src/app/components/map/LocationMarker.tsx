// LocationMarker is managed imperatively by MapSurface via maplibre-gl Marker API.
// This type alias exists so MapSurface can reference it for the marker ref.
// A declarative React wrapper is unnecessary since MapLibre markers are DOM-based,
// and the marker lifecycle is tightly coupled to the map instance.

import type maplibregl from "maplibre-gl";

type LocationMarker = maplibregl.Marker;
export default LocationMarker;
