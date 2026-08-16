import { useMemo, useState } from "react";
import {
  HORIZON_YEARS,
  SCENARIO_IDS,
  type HorizonYear,
  type ScenarioId,
} from "../../contracts/generated/release-contract";
import {
  VISUAL_BANDS,
  resolveMapLayers,
  type VisualBand,
} from "../../data/map-layer-resolver";
import { createCoordinateSelection, type SelectionCommand } from "../../domain/selection";
import type { ReleaseContext, Selection } from "../../domain/release";
import { MapSurface } from "./MapSurface";

const BAND_LABELS: Readonly<Record<VisualBand, string>> = Object.freeze({
  lower: "Lower · q0.167",
  central: "Central · q0.5",
  upper: "Upper · q0.833",
});

interface MapExplorerProps {
  readonly context: ReleaseContext;
  readonly selection?: Selection;
  readonly onSelection: SelectionCommand;
}

export default function MapExplorer({ context, selection, onSelection }: MapExplorerProps) {
  const [band, setBand] = useState<VisualBand>("central");
  const scenario = selection?.scenario ?? context.defaults.scenario;
  const horizon = selection?.horizon ?? context.defaults.horizon;
  const layers = useMemo(
    () => resolveMapLayers(context, scenario, horizon),
    [context, scenario, horizon],
  );
  const selectScenario = (nextScenario: ScenarioId) => {
    if (selection) onSelection(Object.freeze({ ...selection, scenario: nextScenario }));
  };
  const selectHorizon = (nextHorizon: HorizonYear) => {
    if (selection) onSelection(Object.freeze({ ...selection, horizon: nextHorizon }));
  };

  return (
    <section className="map-explorer" aria-labelledby="map-title">
      <div className="map-copy">
        <p className="eyebrow dark">Visual release layer</p>
        <h2 id="map-title">Explore the source grid, without reading science from pixels.</h2>
        <p>
          This map shows the selected release’s source-native cells. It is a visual aid only:
          exact values come from the analysis artifact, never from colour or rendered pixels.
        </p>
        {!selection ? (
          <p className="map-preview-status" role="status">
            Default release preview — not an accepted scientific result. Select a point before using scenario or horizon controls.
          </p>
        ) : null}
        <div className="map-controls" aria-label="Visual layer selection">
          <label>
            Scenario
            <select disabled={!selection} value={scenario} onChange={(event) => selectScenario(event.target.value as ScenarioId)}>
              {SCENARIO_IDS.map((value) => <option key={value}>{value}</option>)}
            </select>
          </label>
          <label>
            Horizon
            <select disabled={!selection} value={horizon} onChange={(event) => selectHorizon(Number(event.target.value) as HorizonYear)}>
              {HORIZON_YEARS.map((value) => <option key={value}>{value}</option>)}
            </select>
          </label>
        </div>
        <fieldset className="band-controls">
          <legend>Projection quantile shown visually</legend>
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
          <strong>{selection ? "Accepted result visualization" : "Default non-result preview"} · {scenario} · {horizon} · {BAND_LABELS[band]}</strong>
          <span>Artifact: {layers.projection.artifactId}</span>
          <span>Source grid: outlined 1° cells; darker colour represents a larger visual value.</span>
          <span>{selection ? "All three quantile labels remain available in text; colour is not the only key." : "No result marker or result legend is shown for this preview."}</span>
          {selection?.location.kind === "coordinate" ? (
            <span>
              Selected coordinate: {selection.location.coordinates.latitude.toFixed(4)}, {selection.location.coordinates.longitude.toFixed(4)}.
            </span>
          ) : selection?.location.kind === "settlement" ? (
            <span>
              Selected settlement {selection.location.placeId}: {selection.location.coordinates.latitude.toFixed(4)}, {selection.location.coordinates.longitude.toFixed(4)}.
            </span>
          ) : (
            <span>Select a coordinate on the map or continue without the map.</span>
          )}
        </div>
        <p className="map-attribution">
          Projection source: <a href="https://doi.org/10.5281/zenodo.6382554">IPCC AR6 Sea Level Projections</a>
          {" · "}<a href={layers.attributionArtifactUrl}>release attribution record</a>.
          The optional basemap is © <a href="https://openfreemap.org/">OpenFreeMap</a> and
          {" "}<a href="https://www.openstreetmap.org/copyright">OpenStreetMap contributors</a>.
        </p>
      </div>
      <MapSurface
        layers={layers}
        band={band}
        marker={selection?.location.coordinates}
        onCoordinate={(coordinates) => {
          onSelection(createCoordinateSelection(context, scenario, horizon, coordinates));
        }}
      />
    </section>
  );
}
