import { lazy, Suspense, useId, useState } from "react";
import { releaseLabel, runtimeConfig } from "./config";

const ArchitecturePage = lazy(() => import("./routes/ArchitecturePage"));

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

function LandingPage() {
  const hintId = useId();
  const [place, setPlace] = useState("");
  const [status, setStatus] = useState("Place search loads locally in the next Phase 2 slice.");

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
          <form
            className="search-shell"
            role="search"
            onSubmit={(event) => {
              event.preventDefault();
              setStatus(
                place.trim()
                  ? `“${place.trim()}” stayed in this browser. The local search index is not enabled in this shell yet.`
                  : "Enter a European city, town, or village.",
              );
            }}
          >
            <label htmlFor="place-search">Find a city, town, or village</label>
            <div className="search-control">
              <span className="search-icon" aria-hidden="true" />
              <input
                id="place-search"
                value={place}
                onChange={(event) => setPlace(event.target.value)}
                aria-describedby={hintId}
                autoComplete="off"
                placeholder="Try Rotterdam, Porto, or Galway"
              />
              <button type="submit">Explore</button>
            </div>
            <p id={hintId} className="search-hint">
              Settlements only. Your text stays in this browser.
            </p>
            <p className="status" role="status" aria-live="polite">
              {status}
            </p>
          </form>
        </div>
        <aside className="scope-card" aria-label="Current data status">
          <span className="scope-number">3 × 3</span>
          <span>scenario and horizon combinations</span>
          <span className="scope-rule" />
          <strong>Fixture mode</strong>
          <span>No public scientific release is claimed.</span>
        </aside>
      </section>
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

  return (
    <div className="app-shell">
      <a className="skip-link" href="#main">Skip to content</a>
      <Header light={architecture} />
      {architecture ? (
        <Suspense fallback={<main id="main" className="route-loading">Loading architecture evidence…</main>}>
          <ArchitecturePage />
        </Suspense>
      ) : (
        <LandingPage />
      )}
      <footer>
        <span>SeaRise Europe</span>
        <code>{runtimeConfig.dataReleaseId}</code>
        <span>Informational and educational use only.</span>
      </footer>
    </div>
  );
}
