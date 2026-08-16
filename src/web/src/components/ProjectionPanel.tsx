import {
  HORIZON_YEARS,
  SCENARIO_IDS,
  type HorizonYear,
  type ScenarioId,
} from "../contracts/generated/release-contract";
import {
  visibleAcceptedProjection,
  type AcceptedProjection,
  type ProjectionState,
} from "../domain/projection-state";
import {
  technicalErrorPresentation,
  type Selection,
  type TechnicalError,
} from "../domain/release";
import type { AssessmentResult } from "../domain/scientific-lookup";
import type { ReleaseMethodology } from "../data/methodology-repository";
import "./ProjectionPanel.css";

const SCENARIO_LABELS: Readonly<Record<ScenarioId, string>> = Object.freeze({
  "ssp1-26": "Lower-emissions scenario (SSP1-2.6)",
  "ssp2-45": "Intermediate-emissions scenario (SSP2-4.5)",
  "ssp5-85": "Higher-emissions scenario (SSP5-8.5)",
});

const REQUIRED_DISCLAIMER =
  "This regional sea-level projection is for informational and educational use. " +
  "It does not determine flooding, inundation, terrain exposure, or property risk. " +
  "It is not an engineering assessment, structural survey, legal determination, " +
  "insurance evaluation, mortgage guidance, or financial advice. Do not use it as " +
  "a substitute for appropriate professional or local evidence.";

export interface ProjectionPanelProps {
  readonly state: ProjectionState;
  readonly methodology: ReleaseMethodology | null;
  readonly onSelectionChange: (selection: Selection) => void;
  readonly onRetry: () => void;
  readonly onReset: () => void;
  readonly onShare: () => void;
  readonly onOpenMethodology: () => void;
}

function assertNever(value: never): never {
  throw new Error(`Unhandled projection panel value: ${JSON.stringify(value)}`);
}

function selectedLocation(selection: Selection): React.ReactNode {
  const { latitude, longitude } = selection.location.coordinates;
  return (
    <p className="projection-panel__location">
      <strong>
        {selection.location.kind === "settlement"
          ? `Selected settlement: ${selection.location.placeId}`
          : "Selected point"}
      </strong>
      <span>{latitude.toFixed(5)}°, {longitude.toFixed(5)}° (WGS84)</span>
    </p>
  );
}

function currentSelection(state: ProjectionState): Selection | null {
  switch (state.phase) {
    case "searching":
      return state.previous?.selection ?? null;
    case "evaluating":
    case "updating":
      return state.operation.selection;
    case "result":
      return state.accepted.selection;
    case "offline":
    case "connection-required":
    case "unsupported-browser":
    case "integrity-error":
    case "technical-error":
      return state.operation?.kind === "search"
        ? state.previous?.selection ?? null
        : state.operation?.selection ?? state.previous?.selection ?? null;
    case "booting":
    case "ready":
      return null;
    default:
      return assertNever(state);
  }
}

function phaseIsBusy(state: ProjectionState): boolean {
  return state.phase === "booting" || state.phase === "searching" ||
    state.phase === "evaluating" || state.phase === "updating";
}

function methodologyMatches(
  accepted: AcceptedProjection,
  methodology: ReleaseMethodology,
): boolean {
  return methodology.dataReleaseId === accepted.release.dataReleaseId &&
    methodology.methodologyVersion === accepted.release.methodologyVersion &&
    methodology.resultStates.join("\0") ===
      "ProjectionAvailable\0DataUnavailable\0OutOfScope\0UnsupportedGeography";
}

function PhaseMessage({ state }: { readonly state: ProjectionState }): React.ReactNode {
  switch (state.phase) {
    case "booting":
      return <p role="status">Loading and verifying the pinned data release…</p>;
    case "ready":
      return <p role="status">Choose a settlement or point to check the selected data.</p>;
    case "searching":
      return <p role="status">Searching places locally…</p>;
    case "evaluating":
      return <p role="status">Checking the selected point against the selected data…</p>;
    case "updating":
      return (
        <div className="projection-panel__update" role="status">
          <strong>Checking a new selection</strong>
          {selectedLocation(state.operation.selection)}
          <span>{SCENARIO_LABELS[state.operation.selection.scenario]} · exact ID {state.operation.selection.scenario} · {state.operation.selection.horizon}</span>
          <span>The result below is the previous accepted result until this check completes.</span>
        </div>
      );
    case "result":
      return null;
    case "offline":
      return <FailureMessage error={state.error} title="Selected data not available offline" body="Reconnect to load the uncached artifacts for this exact selection. No scientific outcome was produced for the failed operation." />;
    case "connection-required":
      return <FailureMessage error={state.error} title="Connection required for selected data" body="The required immutable data is not cached. Reconnect and retry this exact selection; no substitute was used." />;
    case "unsupported-browser":
    case "integrity-error":
    case "technical-error":
      return <FailureMessage error={state.error} />;
    default:
      return assertNever(state);
  }
}

function FailureMessage({
  error,
  title,
  body,
}: {
  readonly error: TechnicalError;
  readonly title?: string;
  readonly body?: string;
}): React.ReactNode {
  const presentation = technicalErrorPresentation(error);
  return (
    <div className="projection-panel__failure" role="alert" data-technical-error={error.code}>
      <strong>{title ?? presentation.title}</strong>
      <span>{body ?? `${error.message} ${presentation.guidance}`}</span>
      <span>Technical failure — not a DataUnavailable scientific outcome.</span>
    </div>
  );
}

function SelectionControls({
  selection,
  disabled,
  onChange,
}: {
  readonly selection: Selection;
  readonly disabled: boolean;
  readonly onChange: (selection: Selection) => void;
}): React.ReactNode {
  const changeScenario = (scenario: ScenarioId): void => onChange(Object.freeze({ ...selection, scenario }));
  const changeHorizon = (horizon: HorizonYear): void => onChange(Object.freeze({ ...selection, horizon }));
  return (
    <div className="projection-panel__controls" aria-label="Projection selection">
      <fieldset disabled={disabled}>
        <legend>Emissions scenario</legend>
        {SCENARIO_IDS.map((scenario) => (
          <label key={scenario}>
            <input
              type="radio"
              name="projection-scenario"
              value={scenario}
              checked={selection.scenario === scenario}
              onChange={() => changeScenario(scenario)}
            />
            <span>{SCENARIO_LABELS[scenario]} <code>{scenario}</code></span>
          </label>
        ))}
      </fieldset>
      <fieldset disabled={disabled}>
        <legend>Absolute horizon</legend>
        {HORIZON_YEARS.map((horizon) => (
          <label key={horizon}>
            <input
              type="radio"
              name="projection-horizon"
              value={horizon}
              checked={selection.horizon === horizon}
              onChange={() => changeHorizon(horizon)}
            />
            <span>{horizon}</span>
          </label>
        ))}
      </fieldset>
    </div>
  );
}

function dispositionCopy(methodology: ReleaseMethodology): string {
  switch (methodology.disposition) {
    case "synthetic-fixture":
      return "Synthetic fixture — demonstration only. Values are synthetic and are not a public scientific release.";
    case "private-engineering":
      return "Private engineering candidate — local validation only. It is not verified, public, signed, or approved for publication.";
    case "public-promoted":
      return "Public promoted release — approved immutable release artifacts passed the required release validation.";
    default:
      return assertNever(methodology.disposition);
  }
}

function mapMeaning(result: AssessmentResult): string {
  switch (result.resultState) {
    case "ProjectionAvailable":
      return "The marker identifies the selected point. The map layer provides regional visual context; the numeric result below comes only from the exact nearest native source-grid lookup, not from map colour.";
    case "DataUnavailable":
      return "The marker identifies the selected point. A neutral unavailable map state means the selected source data cannot provide all required values; it does not mean zero change.";
    case "OutOfScope":
      return "The marker is inside the supported Europe geometry but outside the versioned coastal analysis area. The boundary describes product scope, not hazard reach.";
    case "UnsupportedGeography":
      return "The marker is outside the current release's supported Europe geometry. Map position or colour does not create a scientific result.";
    default:
      return assertNever(result);
  }
}

function OutcomeContent({
  accepted,
  methodology,
  contextLabel,
}: {
  readonly accepted: AcceptedProjection;
  readonly methodology: ReleaseMethodology;
  readonly contextLabel: string | null;
}): React.ReactNode {
  const { result, selection } = accepted;
  const scenarioLabel = SCENARIO_LABELS[result.scenario];
  let content: React.ReactNode;
  switch (result.resultState) {
    case "ProjectionAvailable":
      content = (
        <>
          <h3>Projected regional sea-level change available</h3>
          <p>
            Near this point, IPCC AR6 projects a median regional relative sea-level change of
            {` ${result.medianMetres.toFixed(3)} m`} by <strong>{result.horizon}</strong> under
            {` ${scenarioLabel}`} (exact ID <code>{result.scenario}</code>). Its medium-confidence
            likely range (q0.167–q0.833) is <strong>{result.lowerMetres.toFixed(3)}–{result.upperMetres.toFixed(3)} m</strong>,
            relative to the <strong>{result.baseline}</strong>.
          </p>
          <dl className="projection-panel__metadata">
            <div><dt>Source-grid location</dt><dd>{result.source.latitude.toFixed(4)}°, {result.source.longitude.toFixed(4)}°</dd></div>
            <div><dt>Source-grid distance</dt><dd>{result.source.distanceKilometres.toFixed(3)} km</dd></div>
            <div><dt>Native resolution</dt><dd>{result.nativeResolutionDegrees}°</dd></div>
            <div><dt>Methodology version</dt><dd><code>{result.methodologyVersion}</code></dd></div>
            <div><dt>Data release</dt><dd><code>{result.dataReleaseId}</code></dd></div>
            <div><dt>AR6 source release</dt><dd><code>{result.sourceRelease}</code></dd></div>
          </dl>
          <section aria-labelledby="projection-source-title">
            <h4 id="projection-source-title">Source and licence</h4>
            <p>{methodology.source.attributionText}</p>
            <p>
              <a href={methodology.source.sourceUrl} rel="noreferrer">{methodology.source.title}</a>
              {" · "}
              <a href={methodology.source.licence.url} rel="noreferrer">
                {methodology.source.licence.name} ({methodology.source.licence.spdxId})
              </a>
            </p>
          </section>
          <section aria-labelledby="projection-limitations-title">
            <h4 id="projection-limitations-title">Limitations</h4>
            <ul>{methodology.limitations.map((limitation) => <li key={limitation}>{limitation}</li>)}</ul>
          </section>
        </>
      );
      break;
    case "DataUnavailable":
      content = (
        <>
          <h3>Model data unavailable for this point</h3>
          <p>
            The active dataset has no usable value for this point under {scenarioLabel} (exact ID <code>{result.scenario}</code>) in {result.horizon}.
            No other scenario, year, dataset, source-grid location, or value was substituted. This is not a zero-change or no-risk result.
          </p>
          <p>
            {result.reason === "source-location-too-distant"
              ? `The nearest native source-grid location is ${result.source.distanceKilometres.toFixed(3)} km away, beyond the inclusive 100 km limit.`
              : "At least one required source quantile (q0.167, q0.5, or q0.833) is nodata at the selected native source-grid location."}
          </p>
        </>
      );
      break;
    case "OutOfScope":
      content = (
        <>
          <h3>Outside the coastal analysis area</h3>
          <p>
            This point is inside the supported Europe geometry but outside the versioned coastal analysis area.
            SeaRise Europe does not assess inland hazards. Search another settlement or choose a point closer to the coast.
            The scope result does not imply absence of coastal or climate hazards.
          </p>
        </>
      );
      break;
    case "UnsupportedGeography":
      content = (
        <>
          <h3>Outside the supported Europe area</h3>
          <p>
            This point is outside the geography supported by the current SeaRise Europe release.
            Search a supported European settlement or choose another point. This is a normal domain outcome, not an application error.
          </p>
        </>
      );
      break;
    default:
      return assertNever(result);
  }

  return (
    <article className="projection-panel__outcome" data-outcome={result.resultState} aria-labelledby="projection-outcome-title">
      {contextLabel === null ? (
        <p className="projection-panel__sr-only" role="status">Scientific outcome updated: {result.resultState}.</p>
      ) : null}
      {contextLabel ? <p className="projection-panel__context-label">{contextLabel}</p> : null}
      <div id="projection-outcome-title">{content}</div>
      {selectedLocation(selection)}
      <p><strong>Release status:</strong> {dispositionCopy(methodology)}</p>
      <p><strong>Map meaning:</strong> {mapMeaning(result)}</p>
      <p className="projection-panel__disclaimer">{REQUIRED_DISCLAIMER}</p>
    </article>
  );
}

function AcceptedResult({
  accepted,
  methodology,
  contextLabel,
}: {
  readonly accepted: AcceptedProjection;
  readonly methodology: ReleaseMethodology | null;
  readonly contextLabel: string | null;
}): React.ReactNode {
  if (methodology === null) {
    return (
      <div className="projection-panel__verification" role="status">
        Loading and verifying methodology before showing the accepted scientific outcome…
      </div>
    );
  }
  if (!methodologyMatches(accepted, methodology)) {
    return (
      <div className="projection-panel__failure" role="alert">
        <strong>Verified methodology does not match this result</strong>
        <span>The scientific outcome is hidden because its release identity is not verified.</span>
      </div>
    );
  }
  return <OutcomeContent accepted={accepted} methodology={methodology} contextLabel={contextLabel} />;
}

function acceptedContext(state: ProjectionState): string | null {
  switch (state.phase) {
    case "updating":
      return "Previous accepted result — a new selection is being checked";
    case "searching":
      return state.previous ? "Current accepted result — a new place search is in progress" : null;
    case "offline":
    case "connection-required":
    case "unsupported-browser":
    case "integrity-error":
    case "technical-error":
      return state.previous ? "Previous accepted result — separate from the failed operation" : null;
    case "booting":
    case "ready":
    case "evaluating":
    case "result":
      return null;
    default:
      return assertNever(state);
  }
}

export function ProjectionPanel({
  state,
  methodology,
  onSelectionChange,
  onRetry,
  onReset,
  onShare,
  onOpenMethodology,
}: ProjectionPanelProps): React.ReactNode {
  const accepted = visibleAcceptedProjection(state);
  const selection = currentSelection(state);
  const stableShare = state.phase === "result" && methodology !== null &&
    methodologyMatches(state.accepted, methodology);
  const methodologyUsable = methodology !== null &&
    (accepted === null || methodologyMatches(accepted, methodology));
  const canRetry = (state.phase === "offline" || state.phase === "connection-required" ||
    state.phase === "unsupported-browser" || state.phase === "integrity-error" || state.phase === "technical-error") &&
    state.error.recoverable && state.operation?.kind !== "search";
  const canReset = state.phase !== "booting" && state.phase !== "ready" && selection !== null;

  return (
    <section className="projection-panel" aria-labelledby="projection-panel-title" data-phase={state.phase}>
      <header>
        <p className="projection-panel__eyebrow">Static browser projection</p>
        <h2 id="projection-panel-title">Regional relative sea-level projection</h2>
      </header>
      <PhaseMessage state={state} />
      {selection ? (
        <SelectionControls
          selection={selection}
          disabled={phaseIsBusy(state) || state.phase !== "result"}
          onChange={onSelectionChange}
        />
      ) : null}
      {accepted ? (
        <AcceptedResult accepted={accepted} methodology={methodology} contextLabel={acceptedContext(state)} />
      ) : null}
      <div className="projection-panel__actions" aria-label="Projection actions">
        <button type="button" onClick={onRetry} disabled={!canRetry}>Retry exact selection</button>
        <button type="button" onClick={onReset} disabled={!canReset}>Reset selection</button>
        <button type="button" onClick={onShare} disabled={!stableShare}>Share accepted result</button>
        <button type="button" onClick={onOpenMethodology} disabled={!methodologyUsable}>Methodology and sources</button>
      </div>
    </section>
  );
}
