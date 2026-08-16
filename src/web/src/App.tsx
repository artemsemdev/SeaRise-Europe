import { lazy, Suspense, useState } from "react";
import { SettlementSearch } from "./components/SettlementSearch";
import { releaseLabel, runtimeConfig } from "./config";
import { technicalErrorPresentation } from "./domain/release";
import type { Selection } from "./domain/release";
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

function LandingPage({ release, retry }: { release: ReleaseBootstrapState; retry: () => void }) {
  const [mapOpen, setMapOpen] = useState(false);
  const [selection, applySelection] = useState<Selection>();
  const [selectionStatus, setSelectionStatus] = useState("Choose a settlement to continue.");

  return (
    <main id="main" className="landing">
      <section className="hero" aria-labelledby="hero-title">
        <div className="graticule" aria-hidden="true" />
        <div className="continent continent-one" aria-hidden="true" />
        <div className="continent continent-two" aria-hidden="true" />
        <div className="hero-content">
          <p className="eyebrow">Regional projections · three scenarios · three horizons</p>
          <h1 id="hero-title">
            Take me <em>there</em>.
          </h1>
          <p className="hero-copy">
            Explore IPCC AR6 regional relative sea-level projections for European
            settlements. Values are regional—not predictions of flooding or property risk.
          </p>
          <ReleaseStartup state={release} retry={retry} />
          <SettlementSearch
            release={release.phase === "ready" ? release.context : null}
            onSelect={(record) => setSelectionStatus(
              `${record.displayName}, ${record.admin1Name ?? record.countryCode} selected at ${record.latitude}, ${record.longitude}.`,
            )}
          />
          <p className="selection-status" aria-live="polite">{selectionStatus}</p>
        </div>
        <aside className="scope-card" aria-label="Current data status">
          <span className="scope-number">3 × 3</span>
          <span>scenario and horizon combinations</span>
          <span className="scope-rule" />
          <strong>Fixture mode</strong>
          <span>No public scientific release is claimed.</span>
        </aside>
      </section>
      {release.phase === "ready" ? (
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
                context={release.context}
                selection={selection}
                onSelection={applySelection}
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

export default function App() {
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
        <LandingPage release={release} retry={retryRelease} />
      )}
      <footer>
        <span>SeaRise Europe</span>
        <code>{runtimeConfig.dataReleaseId}</code>
        <span>Informational and educational use only.</span>
      </footer>
    </div>
  );
}
