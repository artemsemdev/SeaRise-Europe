import {
  lazy,
  Suspense,
  useCallback,
  useEffect,
  useRef,
  useState,
  type RefObject,
} from "react";
import { AirplaneTilt } from "@phosphor-icons/react";
import { useAssessmentRuntime } from "./application/use-assessment-runtime";
import { useProjectionUrl } from "./application/use-projection-url";
import type { BrowserRuntimeFactory } from "./application/browser-runtime";
import type {
  ProjectionUrlEnvironment,
  ProjectionUrlEvent,
} from "./application/projection-url-controller";
import { MethodologyDialog } from "./components/MethodologyDialog";
import { ProjectionPanel } from "./components/ProjectionPanel";
import { SettlementSearch } from "./components/SettlementSearch";
import { releaseLabel, runtimeConfig } from "./config";
import { technicalErrorFrom } from "./data/manifest-repository";
import {
  selectionKey,
  visibleAcceptedProjection,
  type ProjectionState,
} from "./domain/projection-state";
import {
  technicalErrorPresentation,
  validateCoordinates,
  type ReleaseContext,
  type Selection,
  type TechnicalError,
} from "./domain/release";
import type { SearchWorkerFactory } from "./search/client";
import type { SettlementSearchRecord } from "./search/types";
import { canRetryRelease, useReleaseContext, type ReleaseBootstrapState } from "./use-release-context";
import flightOverviewUrl from "./assets/flight-overview.svg?url";

const ArchitecturePage = lazy(() => import("./routes/ArchitecturePage"));
const MapExplorer = lazy(() => import("./components/map/MapExplorer"));

function Brand() {
  return (
    <a className="brand" href="/" aria-label="SeaRise Europe home">
      <span>SeaRise</span> <em>Europe</em>
    </a>
  );
}

function Header({ light = false }: { light?: boolean }) {
  return (
    <header className={`site-header${light ? " light" : ""}`}>
      <Brand />
      <nav aria-label="Primary navigation">
        <a href="/about/architecture/">Architecture</a>
        <a href="https://github.com/artemsemdev/SeaRise-Europe">Source</a>
      </nav>
      <span className="release-pill">{releaseLabel()}</span>
    </header>
  );
}

function FlightHeader({
  methodologyAvailable,
  onOpenMethodology,
  methodologyTriggerRef,
}: {
  readonly methodologyAvailable: boolean;
  readonly onOpenMethodology: () => void;
  readonly methodologyTriggerRef: RefObject<HTMLButtonElement | null>;
}) {
  return (
    <header className="flight-header">
      <Brand />
      <div className="flight-header__actions">
        <span className="release-pill">{releaseLabel()}</span>
        <button
          ref={methodologyTriggerRef}
          type="button"
          aria-label="Methodology and sources"
          disabled={!methodologyAvailable}
          onClick={onOpenMethodology}
        >
          Methodology
        </button>
      </div>
    </header>
  );
}

function ReleaseStartup({ state, retry }: { state: ReleaseBootstrapState; retry: () => void }) {
  if (state.phase === "loading") return <p className="release-startup">Validating pinned release…</p>;
  if (state.phase === "ready") {
    return (
      <p className="release-startup ready">
        Release contract ready · {state.context.manifest.datasets.length} exact combinations
      </p>
    );
  }
  const presentation = technicalErrorPresentation(state.error);
  return (
    <div className="release-startup error" role="alert">
      <strong>{presentation.title}.</strong> {state.error.message} {presentation.guidance}
      {canRetryRelease(state) ? (
        <button type="button" onClick={retry}>Retry pinned release</button>
      ) : (
        <span> Retry limit reached; reload after checking the connection.</span>
      )}
    </div>
  );
}

function projectionScopeReady(state: ProjectionState | null, context: ReleaseContext): boolean {
  if (!state || state.phase === "booting") return false;
  return state.release?.dataReleaseId === context.dataReleaseId &&
    state.release.methodologyVersion === context.methodologyVersion;
}

function projectionSelectionStatus(
  scopeReady: boolean,
  state: ProjectionState | null,
  hasAcceptedProjection: boolean,
): string {
  if (!scopeReady) return "Waiting for the exact release runtime.";
  if (!state || state.phase === "ready") return "Choose a settlement to continue.";
  switch (state.phase) {
    case "searching":
      // Search owns its result-count announcement. Keep the assessment region
      // stable until a settlement becomes an assessment command.
      return "Choose a settlement to continue.";
    case "evaluating":
      return "Checking the selected place against the exact nearest native source-grid location.";
    case "updating":
      return "Checking a scenario or horizon update. The previous accepted projection remains visible until the update completes.";
    case "result":
      return `Scientific outcome updated: ${state.accepted.result.resultState}. The accepted projection is shown in the result panel.`;
    case "offline":
    case "connection-required":
    case "unsupported-browser":
    case "integrity-error":
    case "technical-error":
      return hasAcceptedProjection
        ? "The previous accepted projection remains in the result panel; the latest operation ended in a technical failure."
        : "The selected operation ended in a technical failure. No scientific outcome was produced.";
    case "booting":
      return "Loading and verifying the pinned data release.";
  }
}

function projectionPanelVisible(state: ProjectionState | null, hasAcceptedProjection: boolean): boolean {
  if (!state) return false;
  if (hasAcceptedProjection) return true;
  return state.phase === "result" || state.phase === "offline" || state.phase === "connection-required" ||
    state.phase === "unsupported-browser" || state.phase === "integrity-error" ||
    state.phase === "technical-error";
}

function sameLocation(left: Selection["location"], right: Selection["location"]): boolean {
  if (left.kind !== right.kind) return false;
  if (left.kind === "settlement" && right.kind === "settlement" && left.placeId !== right.placeId) return false;
  return left.coordinates.latitude === right.coordinates.latitude &&
    left.coordinates.longitude === right.coordinates.longitude;
}

function projectionJourneySelection(state: ProjectionState | null): Selection | null {
  if (!state) return null;
  if (state.phase === "evaluating") return state.operation.selection;
  if (state.phase === "updating" && !sameLocation(
    state.previous.selection.location,
    state.operation.selection.location,
  )) return state.operation.selection;
  return null;
}

function flightPhase(
  state: ProjectionState | null,
  journeyActive: boolean,
  panelVisible: boolean,
  externalFailure: boolean,
): "idle" | "transition" | "result" | "failure" {
  if (externalFailure) return "failure";
  if (state && (state.phase === "offline" || state.phase === "connection-required" ||
    state.phase === "unsupported-browser" || state.phase === "integrity-error" ||
    state.phase === "technical-error")) return "failure";
  if (journeyActive) return "transition";
  return panelVisible ? "result" : "idle";
}

function settlementSelection(
  context: ReleaseContext,
  projection: ProjectionState | null,
  record: SettlementSearchRecord,
): Selection {
  const accepted = projection ? visibleAcceptedProjection(projection) : null;
  return Object.freeze({
    dataReleaseId: context.dataReleaseId,
    scenario: accepted?.selection.scenario ?? context.defaults.scenario,
    horizon: accepted?.selection.horizon ?? context.defaults.horizon,
    location: Object.freeze({
      kind: "settlement" as const,
      placeId: record.placeId,
      coordinates: validateCoordinates({
        latitude: record.latitude,
        longitude: record.longitude,
      }),
    }),
  });
}

function TechnicalAlert({
  error,
  prefix,
  focusRef,
}: {
  error: TechnicalError;
  prefix: string;
  focusRef?: RefObject<HTMLDivElement | null>;
}) {
  const presentation = technicalErrorPresentation(error);
  return (
    <div
      ref={focusRef}
      className="application-technical-alert"
      role="alert"
      tabIndex={focusRef ? -1 : undefined}
      data-technical-error={error.code}
    >
      <strong>{prefix}: {presentation.title}.</strong>{" "}
      {error.message} {presentation.guidance} This is a technical failure, not a scientific outcome.
    </div>
  );
}

interface NavigationIntent {
  readonly serial: number;
  readonly selection: Selection;
}

function useReducedMotionPreference(): boolean {
  const query = "(prefers-reduced-motion: reduce)";
  const [reduced, setReduced] = useState(() =>
    typeof window !== "undefined" && typeof window.matchMedia === "function"
      ? window.matchMedia(query).matches
      : false,
  );

  useEffect(() => {
    if (typeof window.matchMedia !== "function") return;
    const media = window.matchMedia(query);
    const update = (event: MediaQueryListEvent): void => setReduced(event.matches);
    media.addEventListener?.("change", update);
    return () => media.removeEventListener?.("change", update);
  }, []);

  return reduced;
}

export interface LandingPageProps {
  readonly release: ReleaseBootstrapState;
  readonly retry: () => void;
  readonly runtimeFactory?: BrowserRuntimeFactory;
  readonly urlEnvironment?: ProjectionUrlEnvironment;
  readonly searchWorkerFactory?: SearchWorkerFactory;
}

function LandingPageSession({
  release,
  retry,
  runtimeFactory,
  urlEnvironment,
  searchWorkerFactory,
}: LandingPageProps) {
  const context = release.phase === "ready" ? release.context : null;
  const runtime = useAssessmentRuntime(context, runtimeFactory);
  const [methodologyOpen, setMethodologyOpen] = useState(false);
  const [clearSearchToken, setClearSearchToken] = useState(0);
  const [commandError, setCommandError] = useState<TechnicalError | null>(null);
  const [urlError, setUrlError] = useState<TechnicalError | null>(null);
  const [shareStatus, setShareStatus] = useState("");
  const [navigationIntent, setNavigationIntent] = useState<NavigationIntent | null>(null);
  const [journeyMotionSkipToken, setJourneyMotionSkipToken] = useState(0);
  const [skippedJourneyKey, setSkippedJourneyKey] = useState<string | null>(null);
  const navigationSerial = useRef(0);
  const handledNavigationSerial = useRef(0);
  const pendingInitialSelection = useRef<string | null>(null);
  const methodologyTriggerRef = useRef<HTMLButtonElement>(null);
  const searchInputRef = useRef<HTMLInputElement>(null);
  const transitionStatusRef = useRef<HTMLParagraphElement>(null);
  const resultHeadingRef = useRef<HTMLHeadingElement>(null);
  const projectionFailureRef = useRef<HTMLDivElement>(null);
  const commandFailureRef = useRef<HTMLDivElement>(null);
  const pendingSelectionFocus = useRef(false);
  const pendingSearchFocus = useRef(false);
  const sessionActive = useRef(false);

  useEffect(() => {
    sessionActive.current = true;
    return () => {
      sessionActive.current = false;
    };
  }, []);

  const submitSelection = useCallback((selection: Selection): void => {
    if (!sessionActive.current || context?.dataReleaseId !== selection.dataReleaseId) return;
    setCommandError(null);
    setShareStatus("");
    void runtime.select(selection).catch((error: unknown) => {
      if (!sessionActive.current || context.dataReleaseId !== selection.dataReleaseId) return;
      setCommandError(technicalErrorFrom(error));
    });
  }, [context, runtime]);

  const clearApplicationSelection = useCallback((): void => {
    if (!context || !sessionActive.current) return;
    setCommandError(null);
    if (projectionScopeReady(runtime.projection, context)) {
      runtime.cancelSearch();
      try {
        runtime.reset();
      } catch (error: unknown) {
        setCommandError(technicalErrorFrom(error));
      }
    }
    setClearSearchToken((token) => token + 1);
    setMethodologyOpen(false);
    setUrlError(null);
    setShareStatus("");
  }, [context, runtime]);

  const observeUrl = useCallback((event: ProjectionUrlEvent): void => {
    if (!context || !sessionActive.current) return;
    if (event.type === "selection") {
      if (event.selection.dataReleaseId !== context.dataReleaseId) return;
      const key = `${context.dataReleaseId}:${selectionKey(event.selection)}`;
      if (event.source === "initial") {
        if (pendingInitialSelection.current === key) return;
        pendingInitialSelection.current = key;
      }
      setUrlError(null);
      const serial = ++navigationSerial.current;
      setNavigationIntent(Object.freeze({ serial, selection: event.selection }));
      return;
    }
    if (event.type === "technical-error") {
      navigationSerial.current += 1;
      pendingInitialSelection.current = null;
      setNavigationIntent(null);
      setUrlError(event.error);
      setShareStatus("");
      return;
    }
    navigationSerial.current += 1;
    pendingInitialSelection.current = null;
    setNavigationIntent(null);
    if (event.source === "popstate") clearApplicationSelection();
  }, [clearApplicationSelection, context]);

  const projectionUrl = useProjectionUrl(context, observeUrl, urlEnvironment);
  const scopeReady = context !== null && projectionScopeReady(runtime.projection, context);

  useEffect(() => {
    if (!scopeReady || !navigationIntent ||
        navigationIntent.serial <= handledNavigationSerial.current) return;
    handledNavigationSerial.current = navigationIntent.serial;
    pendingInitialSelection.current = null;
    submitSelection(navigationIntent.selection);
  }, [navigationIntent, scopeReady, submitSelection]);

  const accepted = runtime.projection ? visibleAcceptedProjection(runtime.projection) : null;
  const panelVisible = projectionPanelVisible(runtime.projection, accepted !== null);
  const journeySelection = projectionJourneySelection(runtime.projection);
  const externalFailure = commandError !== null || urlError !== null ||
    runtime.methodology.phase === "technical-error";
  const journeyActive = journeySelection !== null && !externalFailure;
  const journeyKey = journeySelection && runtime.projection
    ? `${runtime.projection.operationToken}:${selectionKey(journeySelection)}`
    : null;
  const reducedMotion = useReducedMotionPreference();
  const journeyMotionComplete = reducedMotion || (journeyKey !== null && journeyKey === skippedJourneyKey);
  const currentFlightPhase = flightPhase(runtime.projection, journeyActive, panelVisible, externalFailure);
  const verifiedMethodology = runtime.methodology.phase === "ready" && context &&
      runtime.methodology.dataReleaseId === context.dataReleaseId
    ? runtime.methodology.methodology
    : null;

  useEffect(() => {
    if (!pendingSelectionFocus.current || !runtime.projection) return;
    if ((runtime.projection.phase === "evaluating" || runtime.projection.phase === "updating") && journeyActive) {
      transitionStatusRef.current?.focus();
      return;
    }
    if (runtime.projection.phase === "result" && verifiedMethodology && resultHeadingRef.current) {
      resultHeadingRef.current.focus();
      pendingSelectionFocus.current = false;
      return;
    }
    if (["offline", "connection-required", "unsupported-browser", "integrity-error", "technical-error"]
      .includes(runtime.projection.phase) && projectionFailureRef.current) {
      projectionFailureRef.current.focus();
      pendingSelectionFocus.current = false;
    }
  }, [journeyActive, runtime.projection, verifiedMethodology]);

  useEffect(() => {
    if (!pendingSelectionFocus.current || !commandError || !commandFailureRef.current) return;
    commandFailureRef.current.focus();
    pendingSelectionFocus.current = false;
  }, [commandError]);

  useEffect(() => {
    if (!pendingSearchFocus.current || !scopeReady || panelVisible || journeyActive) return;
    searchInputRef.current?.focus();
    pendingSearchFocus.current = false;
  }, [journeyActive, panelVisible, scopeReady]);

  const reset = (): void => {
    if (!context) return;
    pendingInitialSelection.current = null;
    pendingSelectionFocus.current = false;
    pendingSearchFocus.current = true;
    setNavigationIntent(null);
    clearApplicationSelection();
    projectionUrl.reset();
  };

  const share = (): void => {
    if (!accepted) return;
    setUrlError(null);
    const published = projectionUrl.share(accepted);
    setShareStatus(published
      ? "Share link is ready in the browser address bar."
      : "The accepted result could not be added to the browser address bar.");
  };

  return (
    <main
      id="main"
      className={`landing flight-app${panelVisible ? " has-projection" : ""}${journeyActive ? " is-journey" : ""}`}
      data-flight-phase={currentFlightPhase}
    >
      <FlightHeader
        methodologyAvailable={verifiedMethodology !== null}
        onOpenMethodology={() => setMethodologyOpen(true)}
        methodologyTriggerRef={methodologyTriggerRef}
      />

      <div className="flight-map-layer flight-scene" aria-hidden={!context || !scopeReady}>
        {context && scopeReady ? (
          <Suspense fallback={<p className="map-module-loading">Loading map module…</p>}>
            <MapExplorer
              context={context}
              selection={accepted?.selection}
              journeyTarget={journeySelection?.location.coordinates}
              journeyActive={journeyActive}
              journeyMotionSkipToken={journeyMotionSkipToken}
              onSelection={(selection) => {
                runtime.cancelSearch();
                setClearSearchToken((token) => token + 1);
                submitSelection(selection);
              }}
            />
          </Suspense>
        ) : (
          <div className="flight-map-fallback" aria-hidden="true" />
        )}
      </div>

      <div className="flight-overview" aria-hidden="true">
        <img src={flightOverviewUrl} alt="" />
      </div>

      <section
        className="flight-command flight-search"
        aria-labelledby="hero-title"
        hidden={panelVisible || journeyActive}
      >
          <div className="flight-command__content">
            <h1 id="hero-title">Take me <em>there</em>.</h1>
            <p className="hero-copy">
              Name a European coastal settlement. You will fly to it and watch the modelled
              scenario play out — computed in your browser, in about fifteen seconds.
            </p>
            <ReleaseStartup state={release} retry={retry} />
            <SettlementSearch
              release={scopeReady ? context : null}
              inputRef={searchInputRef}
              clearToken={clearSearchToken}
              workerFactory={searchWorkerFactory}
              onSearchLifecycle={runtime.handleSearchLifecycle}
              onSelect={(record) => {
                if (!context || !scopeReady) return;
                pendingSelectionFocus.current = true;
                submitSelection(settlementSelection(context, runtime.projection, record));
              }}
            />
          </div>
      </section>

      <p className="selection-status" role="status" aria-live="polite" aria-atomic="true">
        {shareStatus || projectionSelectionStatus(scopeReady, runtime.projection, accepted !== null)}
      </p>

      {journeyActive ? (
        <div className="flight-progress">
          <AirplaneTilt size={19} weight="fill" aria-hidden="true" />
          <span>
            <strong>{journeyMotionComplete ? "Checking the selected point" : "Flying to the selected point"}</strong>
            {reducedMotion
              ? "Camera motion reduced. Checking its exact nearest native source-grid location in this browser…"
              : journeyMotionComplete
                ? "Camera motion skipped. Checking its exact nearest native source-grid location in this browser…"
                : "Checking its exact nearest native source-grid location in this browser…"}
          </span>
          {!journeyMotionComplete ? (
            <button
              type="button"
              onClick={() => {
                if (!journeyKey) return;
                setSkippedJourneyKey(journeyKey);
                setJourneyMotionSkipToken((token) => token + 1);
              }}
            >
              Skip motion
            </button>
          ) : null}
          <p ref={transitionStatusRef} className="flight-progress__focus-target" tabIndex={-1}>
            Selected place accepted. Exact browser lookup is in progress.
          </p>
        </div>
      ) : null}

      <div className="flight-alerts">
        {commandError ? (
          <TechnicalAlert error={commandError} prefix="Selection command failed" focusRef={commandFailureRef} />
        ) : null}
        {urlError ? <TechnicalAlert error={urlError} prefix="Share or navigation failed" /> : null}
        {runtime.methodology.phase === "technical-error" ? (
          <TechnicalAlert error={runtime.methodology.error} prefix="Methodology verification failed" />
        ) : null}
      </div>

      {runtime.projection ? (
        <ProjectionPanel
          state={runtime.projection}
          methodology={verifiedMethodology}
          resultHeadingRef={resultHeadingRef}
          failureAlertRef={projectionFailureRef}
          onSelectionChange={submitSelection}
          onRetry={() => {
            setCommandError(null);
            const releaseId = context?.dataReleaseId;
            void runtime.retry().catch((error: unknown) => {
              if (sessionActive.current && context?.dataReleaseId === releaseId) {
                setCommandError(technicalErrorFrom(error));
              }
            });
          }}
          onReset={reset}
          onShare={share}
          onOpenMethodology={() => setMethodologyOpen(true)}
          showMethodologyAction={false}
        />
      ) : null}

      {context ? (
        <MethodologyDialog
          methodology={verifiedMethodology}
          release={context}
          open={methodologyOpen}
          onClose={() => setMethodologyOpen(false)}
          triggerRef={methodologyTriggerRef}
        />
      ) : null}

    </main>
  );
}

/** Remounts every local command/URL/search guard when the immutable release changes. */
export function LandingPage(props: LandingPageProps) {
  const sessionKey = props.release.phase === "ready"
    ? props.release.context.dataReleaseId
    : props.release.phase;
  return <LandingPageSession key={sessionKey} {...props} />;
}

export interface AppProps {
  readonly runtimeFactory?: BrowserRuntimeFactory;
  readonly urlEnvironment?: ProjectionUrlEnvironment;
  readonly searchWorkerFactory?: SearchWorkerFactory;
}

export default function App({ runtimeFactory, urlEnvironment, searchWorkerFactory }: AppProps = {}) {
  const architecture = window.location.pathname.replace(/\/+$/, "") === "/about/architecture";
  const [release, retryRelease] = useReleaseContext();

  return (
    <div className={`app-shell${architecture ? " architecture-shell" : " flight-shell"}`}>
      <a className="skip-link" href="#main">Skip to content</a>
      {architecture ? (
        <>
          <Header light />
          <Suspense fallback={<main id="main" className="route-loading">Loading architecture evidence…</main>}>
            <ArchitecturePage />
          </Suspense>
          <footer>
            <span>SeaRise Europe</span>
            <code>{runtimeConfig.dataReleaseId}</code>
            <span>Informational and educational use only.</span>
          </footer>
        </>
      ) : (
        <LandingPage
          release={release}
          retry={retryRelease}
          runtimeFactory={runtimeFactory}
          urlEnvironment={urlEnvironment}
          searchWorkerFactory={searchWorkerFactory}
        />
      )}
    </div>
  );
}
