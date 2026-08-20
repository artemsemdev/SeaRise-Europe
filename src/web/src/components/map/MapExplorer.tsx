import { useMemo, useState } from "react";
import {
  VISUAL_BANDS,
  resolveMapLayers,
  type VisualBand,
} from "../../data/map-layer-resolver";
import { createCoordinateSelection, type SelectionCommand } from "../../domain/selection";
import type { Coordinates, ReleaseContext, Selection } from "../../domain/release";
import { MapSurface } from "./MapSurface";

const BAND_LABELS: Readonly<Record<VisualBand, string>> = Object.freeze({
  lower: "Lower · q0.167",
  central: "Central · q0.5",
  upper: "Upper · q0.833",
});

interface MapExplorerProps {
  readonly context: ReleaseContext;
  readonly selection?: Selection;
  readonly journeyTarget?: Coordinates;
  readonly journeyActive?: boolean;
  readonly journeyMotionSkipToken?: number;
  readonly onSelection: SelectionCommand;
}

export default function MapExplorer({
  context,
  selection,
  journeyTarget,
  journeyActive = false,
  journeyMotionSkipToken = 0,
  onSelection,
}: MapExplorerProps) {
  const [band, setBand] = useState<VisualBand>("central");
  const scenario = selection?.scenario ?? context.defaults.scenario;
  const horizon = selection?.horizon ?? context.defaults.horizon;
  const layers = useMemo(
    () => resolveMapLayers(context, scenario, horizon),
    [context, scenario, horizon],
  );

  return (
    <section
      className={`map-explorer${journeyActive ? " is-journey" : ""}`}
      aria-labelledby="map-title"
      data-journey-active={journeyActive}
    >
      <h2 id="map-title" className="map-title">
        Release-scoped source-grid visualization
      </h2>
      <MapSurface
        layers={layers}
        band={band}
        marker={selection?.location.coordinates}
        journeyTarget={journeyTarget}
        journeyMotionSkipToken={journeyMotionSkipToken}
        interactionEnabled={selection !== undefined}
        onCoordinate={(coordinates) => {
          onSelection(createCoordinateSelection(context, scenario, horizon, coordinates));
        }}
      />
      {selection ? (
        <aside className="map-copy flight-legend" aria-label="Visual layer legend and map text alternative">
          <p className="map-copy__label">Visual source grid</p>
          <strong>{scenario} · {horizon}</strong>
          <fieldset className="band-controls">
            <legend>Visual quantile band</legend>
            {VISUAL_BANDS.map((value) => (
              <label key={value}>
                <input
                  type="radio"
                  name="visual-band"
                  value={value}
                  checked={band === value}
                  onChange={() => setBand(value)}
                />
                {BAND_LABELS[value]}
              </label>
            ))}
          </fieldset>
          <div className="map-text-alternative" aria-label="Map text alternative">
            <span>Accepted result visualization · {scenario} · {horizon} · {BAND_LABELS[band]}</span>
            <span>Outlined 1° native cells; exact values never come from colour.</span>
            {selection.location.kind === "coordinate" ? (
              <span>
                Selected coordinate: {selection.location.coordinates.latitude.toFixed(4)}, {selection.location.coordinates.longitude.toFixed(4)}.
              </span>
            ) : (
              <span>
                Selected settlement {selection.location.placeId}: {selection.location.coordinates.latitude.toFixed(4)}, {selection.location.coordinates.longitude.toFixed(4)}.
              </span>
            )}
          </div>
          <p className="map-attribution flight-attribution">
            <a href="https://doi.org/10.5281/zenodo.6382554">IPCC AR6 Sea Level Projections</a>
            {" · "}<a href={layers.attributionArtifactUrl}>release attribution record</a>
            {" · optional basemap: "}<a href="https://openfreemap.org/">OpenFreeMap</a>
            {" / "}<a href="https://www.openstreetmap.org/copyright">OpenStreetMap contributors</a>
          </p>
        </aside>
      ) : null}
    </section>
  );
}
