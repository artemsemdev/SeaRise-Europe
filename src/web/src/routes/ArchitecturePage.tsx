import { releaseLabel, runtimeConfig } from "../config";

const flow = [
  ["Sources", "Pinned, licensed inputs"],
  ["Build", "Deterministic offline pipeline"],
  ["Release", "Manifest, STAC, checksums"],
  ["Browser", "Local search and exact lookup"],
];

export default function ArchitecturePage() {
  return (
    <main id="main" className="architecture-page">
      <a className="back-link" href="/">← Back to explorer</a>
      <p className="eyebrow dark">Architecture evidence</p>
      <h1>Static-first, release-scoped, and explicit about what is still synthetic.</h1>
      <p className="lede">
        SeaRise Europe precomputes deterministic geospatial work, publishes verifiable
        artifacts, and lets the browser search and look up projections locally. The normal
        journey requires no application backend, database, tile server, or runtime geocoder.
      </p>

      <dl className="evidence-grid">
        <div><dt>Application build</dt><dd><code>{runtimeConfig.appBuildId}</code></dd></div>
        <div><dt>Data release</dt><dd><code>{runtimeConfig.dataReleaseId}</code></dd></div>
        <div><dt>Release status</dt><dd>{releaseLabel()}</dd></div>
        <div><dt>Manifest entry point</dt><dd><code>{runtimeConfig.manifestUrl}</code></dd></div>
      </dl>

      <section aria-labelledby="flow-title">
        <h2 id="flow-title">One immutable path from source to browser</h2>
        <ol className="architecture-flow">
          {flow.map(([title, description], index) => (
            <li key={title}>
              <span>{String(index + 1).padStart(2, "0")}</span>
              <strong>{title}</strong>
              <p>{description}</p>
            </li>
          ))}
        </ol>
      </section>

      <section className="boundary-panel" aria-labelledby="boundary-title">
        <div>
          <p className="eyebrow">Runtime boundary</p>
          <h2 id="boundary-title">Static files and immutable data only</h2>
        </div>
        <ul>
          <li>React and Vite emit browser assets with no server entry point.</li>
          <li>Map visuals and scientific lookup remain separate.</li>
          <li>Technical failures never become an extra scientific outcome.</li>
          <li>Private Phase 1 candidate bytes are not part of this build or release.</li>
        </ul>
      </section>

      <p className="architecture-note">
        Current evidence is generated from the committed synthetic fixture. Performance,
        public delivery, and promoted-release claims remain gated by later roadmap work.
      </p>
    </main>
  );
}
