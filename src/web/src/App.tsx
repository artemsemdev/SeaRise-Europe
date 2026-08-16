import {
  lazy,
  Suspense,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
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
import { releaseScopeStatus } from "./release-copy";
import { canRetryRelease, useReleaseContext, type ReleaseBootstrapState } from "./use-release-context";

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
    case "offline":
    case "connection-required":
    case "unsupported-browser":
    case "integrity-error":
    case "technical-error":
      return hasAcceptedProjection
        ? "The previous accepted projection remains shown below; the latest operation ended in a technical failure."
        : "The selected operation ended in a technical failure. No scientific outcome was produced.";
    default:
      return hasAcceptedProjection
        ? "The accepted projection is shown below."
        : "The selected point is being checked below.";
  }
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

function TechnicalAlert({ error, prefix }: { error: TechnicalError; prefix: string }) {
  const presentation = technicalErrorPresentation(error);
  return (
    <div className="application-technical-alert" role="alert" data-technical-error={error.code}>
      <strong>{prefix}: {presentation.title}.</strong>{" "}
      {error.message} {presentation.guidance} This is a technical failure, not a scientific outcome.
    </div>
  );
}

interface NavigationIntent {
  readonly serial: number;
  readonly selection: Selection;
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
  const [mapOpen, setMapOpen] = useState(false);
  const [methodologyOpen, setMethodologyOpen] = useState(false);
  const [clearSearchToken, setClearSearchToken] = useState(0);
  const [commandError, setCommandError] = useState<TechnicalError | null>(null);
  const [urlError, setUrlError] = useState<TechnicalError | null>(null);
  const [shareStatus, setShareStatus] = useState("");
  const [navigationIntent, setNavigationIntent] = useState<NavigationIntent | null>(null);
  const navigationSerial = useRef(0);
  const handledNavigationSerial = useRef(0);
  const pendingInitialSelection = useRef<string | null>(null);
  const methodologyTriggerRef = useRef<HTMLButtonElement>(null);
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
  const scopeStatus = releaseScopeStatus(release);
  const verifiedMethodology = runtime.methodology.phase === "ready" && context &&
      runtime.methodology.dataReleaseId === context.dataReleaseId
    ? runtime.methodology.methodology
    : null;

  const reset = (): void => {
    if (!context) return;
    pendingInitialSelection.current = null;
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
    <main id="main" className="landing">
      <section className="hero" aria-labelledby="hero-title">
        <div className="graticule" aria-hidden="true" />
        <div className="continent continent-one" aria-hidden="true" />
        <div className="continent continent-two" aria-hidden="true" />
        <div className="hero-content">
          <p className="eyebrow">Regional projections · three scenarios · three horizons</p>
          <h1 id="hero-title">
            Explore regional sea-level projections <em>across Europe</em>.
          </h1>
          <p className="hero-copy">
            Explore IPCC AR6 regional relative sea-level projections for European
            settlements. Values are regional—not predictions of flooding or property risk.
          </p>
          <ReleaseStartup state={release} retry={retry} />
          <SettlementSearch
            release={scopeReady ? context : null}
            clearToken={clearSearchToken}
            workerFactory={searchWorkerFactory}
            onSearchLifecycle={runtime.handleSearchLifecycle}
            onSelect={(record) => {
              if (!context || !scopeReady) return;
              submitSelection(settlementSelection(context, runtime.projection, record));
            }}
          />
          <p className="selection-status" aria-live="polite">
            {projectionSelectionStatus(scopeReady, runtime.projection, accepted !== null)}
          </p>
        </div>
        <aside className="scope-card" aria-label="Current data status">
          <span className="scope-number">3 × 3</span>
          <span>scenario and horizon combinations</span>
          <span className="scope-rule" />
          <strong>{scopeStatus.title}</strong>
          <span>{scopeStatus.detail}</span>
        </aside>
      </section>

      {commandError ? <TechnicalAlert error={commandError} prefix="Selection command failed" /> : null}
      {urlError ? <TechnicalAlert error={urlError} prefix="Share or navigation failed" /> : null}
      {runtime.methodology.phase === "technical-error" ? (
        <TechnicalAlert error={runtime.methodology.error} prefix="Methodology verification failed" />
      ) : null}
      <p className="share-status" role="status" aria-live="polite">{shareStatus}</p>

      {runtime.projection ? (
        <ProjectionPanel
          state={runtime.projection}
          methodology={verifiedMethodology}
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
          methodologyTriggerRef={methodologyTriggerRef}
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

      {context && scopeReady ? (
        <section className="map-launcher" aria-label="Release visualization">
          {!mapOpen ? (
            <>
              <p className="eyebrow dark">Optional visualization</p>
              <h2>The map stays out of the initial application bundle.</h2>
              <p>Open it when useful. Search, release validation, and textual information do not depend on it.</p>
              <button type="button" onClick={() => setMapOpen(true)}>Open static visualization</button>
            </>
          ) : (
            <Suspense fallback={<p className="map-module-loading" role="status">Loading map module…</p>}>
              <MapExplorer
                context={context}
                selection={accepted?.selection}
                onSelection={(selection) => {
                  runtime.cancelSearch();
                  setClearSearchToken((token) => token + 1);
                  submitSelection(selection);
                }}
              />
            </Suspense>
          )}
        </section>
      ) : null}
      <section className="principles" aria-labelledby="principles-title">
        <p className="eyebrow dark">What this explorer reports</p>
        <h2 id="principles-title">A source-bound regional projection, with its limits beside it.</h2>
        <div className="principle-grid">
          <article>
            <span>01</span>
            <h3>Exact source lookup</h3>
            <p>The browser reads one nearest native AR6 grid location. It does not infer values from map colour.</p>
          </article>
          <article>
            <span>02</span>
            <h3>Private by design</h3>
            <p>Settlement search and point selection stay in the browser; no application API receives them.</p>
          </article>
          <article>
            <span>03</span>
            <h3>Honest outcomes</h3>
            <p>Unavailable data and unsupported geography remain explicit, separate outcomes.</p>
          </article>
        </div>
      </section>
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
    <div className="app-shell">
      <a className="skip-link" href="#main">Skip to content</a>
      <Header light={architecture} />
      {architecture ? (
        <Suspense fallback={<main id="main" className="route-loading">Loading architecture evidence…</main>}>
          <ArchitecturePage />
        </Suspense>
      ) : (
        <LandingPage
          release={release}
          retry={retryRelease}
          runtimeFactory={runtimeFactory}
          urlEnvironment={urlEnvironment}
          searchWorkerFactory={searchWorkerFactory}
        />
      )}
      <footer>
        <span>SeaRise Europe</span>
        <code>{runtimeConfig.dataReleaseId}</code>
        <span>Informational and educational use only.</span>
      </footer>
    </div>
  );
}
