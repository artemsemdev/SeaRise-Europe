import { lazy, Suspense, useCallback, useEffect, useRef, useState } from "react";
import { ArrowClockwise, ArrowsLeftRight, CaretDown, CaretUp, Crosshair, Eye, EyeSlash, Info, X, Pause, Play } from "@phosphor-icons/react";
const EuropeMap = lazy(() => import("./EuropeMap").then((module) => ({ default: module.EuropeMap })));
import { MapChunkBoundary } from "./MapChunkBoundary";
import { AboutDialog } from "./AboutDialog";
import { PointInspection } from "./PointInspection";
import { CitySearch } from "./CitySearch";
import { YEARS, parseCity, parseCatalog, readSelection, selectionUrl, type AtlasCatalog, type Camera, type City, type Point, type Protection, type Year } from "./model";

import type { AtlasDataSource } from "./data-source";
import "./atlas.css";

export default function AtlasApp({ dataSource }: { dataSource: AtlasDataSource }) {
  const [qaMapEnabled] = useState(() => new URLSearchParams(window.location.search).get("qa") === "map");
  const [selection, setSelection] = useState(() => readSelection(window.location.search));
  const { cityId, year, protection, visible, compare, camera, point } = selection;
  const [mapRevision, setMapRevision] = useState(0);
  const mapModuleFailed = useRef(false);
  const [expanded, setExpanded] = useState(false);
  const [pointOpen, setPointOpen] = useState(true);
  const [focusRequest, setFocusRequest] = useState(0);
  const [initialCamera, setInitialCamera] = useState(camera);
  const [restoreCity, setRestoreCity] = useState(Boolean(cityId));
  const title = useRef<HTMLHeadingElement>(null);
  const story = useRef<HTMLElement>(null);
  const panel = useRef<HTMLDivElement>(null);
  const [resolvedCity, setResolvedCity] = useState<City | null>(null);
  const [placeError, setPlaceError] = useState<string | null>(null);
  const city = resolvedCity?.id === cityId ? resolvedCity : null;
  const [catalog, setCatalog] = useState<AtlasCatalog | null>(null);
  const [catalogError, setCatalogError] = useState<string | null>(null);
  const [retry, setRetry] = useState(0);
  const [about, setAbout] = useState(false);
  const [playing, setPlaying] = useState(false);
  const [mapStatus, setMapStatus] = useState<{ loading: boolean; error: string | null; validPixels: number | null; floodPixels: number | null }>({ loading: true, error: null, validPixels: null, floodPixels: null });
  const [shared, setShared] = useState(false);
  const [shareError, setShareError] = useState(false);
  const layer = catalog?.layers.find((item) => item.year === year && item.protection === protection);
  const loading = !catalog && !catalogError || mapStatus.loading;
  const error = catalogError ?? mapStatus.error ?? placeError;
  const onStatus = useCallback((status: { loading: boolean; error: string | null; validPixels: number | null; floodPixels: number | null }) => setMapStatus(status), []);

  const onMapFailure = useCallback(() => {
    mapModuleFailed.current = true;
    setMapStatus({ loading: false, error: "The map application could not load. Retry to reload this view.", validPixels: null, floodPixels: null });
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    dataSource.getCatalog({ signal: controller.signal })
      .then((value: unknown) => { if (!controller.signal.aborted) { setCatalog(parseCatalog(value)); setCatalogError(null); } })
      .catch((reason: unknown) => { if (!controller.signal.aborted) setCatalogError(reason instanceof Error ? reason.message : "The local map data could not be loaded."); });
    return () => controller.abort();
  }, [retry, dataSource]);

  const onCameraChange = useCallback((next: Camera) => setSelection((current) => ({ ...current, camera: next })), []);
  const onInspect = useCallback((next: Point) => { setPointOpen(true); setSelection((current) => ({ ...current, point: next })); }, []);
  const inspectedPoint = point ?? city?.coordinates ?? null;
  useEffect(() => {
    if (!pointOpen || !inspectedPoint) return;
    story.current?.scrollTo({ top: 0 });
    panel.current?.scrollTo({ top: 0 });
  }, [inspectedPoint, pointOpen]);
  const timelineYears: readonly Year[] = compare ? [2030, 2100] : YEARS;
  useEffect(() => {
    window.history.replaceState(null, "", selectionUrl(cityId, year, protection, visible, { camera, point, compare }));
  }, [cityId, year, protection, visible, camera, point, compare]);
  useEffect(() => {
    if (!cityId || resolvedCity?.id === cityId) return;
    const controller = new AbortController();
    async function resolvePlace() {
      let value = await dataSource.getPlace(cityId!, { signal: controller.signal });
      if (!value && !cityId!.includes(":")) {
        const result = await dataSource.search(cityId!.replaceAll("-", " "), { signal: controller.signal });
        value = result.results.find((entry) => entry.name.toLowerCase() === cityId!.replaceAll("-", " ").toLowerCase()) ?? null;
      }
      if (!value) throw new Error("This place could not be found. Search for a city to continue.");
      const next = parseCity(value);
      if (controller.signal.aborted) return;
      setPlaceError(null);
      setResolvedCity(next);
      setSelection((current) => ({ ...current, cityId: next.id }));
    }
    void resolvePlace().catch((reason: unknown) => { if (!controller.signal.aborted) setPlaceError(reason instanceof Error ? reason.message : "The selected place could not be loaded."); });
    return () => controller.abort();
  }, [cityId, resolvedCity, retry, dataSource]);
  useEffect(() => {
    const restore = () => {
      const next = readSelection(window.location.search);
      setInitialCamera(next.camera);
      setRestoreCity(Boolean(next.cityId));
      setPlaying(false); setSelection(next); setMapRevision((value) => value + 1);
    };
    window.addEventListener("popstate", restore);
    return () => window.removeEventListener("popstate", restore);
  }, []);
  useEffect(() => {
    if (!playing || loading || error) return;
    const timer = window.setTimeout(() => setSelection((current) => ({ ...current, year: YEARS[(YEARS.indexOf(current.year) + 1) % YEARS.length] })), 3000);
    return () => window.clearTimeout(timer);
  }, [playing, loading, error, year]);
  useEffect(() => {
    if (!shared) return;
    const timer = window.setTimeout(() => setShared(false), 2400);
    return () => window.clearTimeout(timer);
  }, [shared]);

  function selectCity(next: City) {
    setPointOpen(true);
    setRestoreCity(false);
    setResolvedCity(next); setPlaceError(null);
    setSelection((current) => ({ ...current, cityId: next.id, point: null }));
    requestAnimationFrame(() => title.current?.focus({ preventScroll: true }));
  }
  function exploreEurope() {
    setResolvedCity(null); setPlaceError(null);
    setInitialCamera(null); setRestoreCity(false); setPointOpen(true);
    setSelection((current) => ({ ...current, cityId: null, point: null, camera: null }));
    setMapRevision((value) => value + 1);
  }
  function toggleCompare() {
    setPlaying(false);
    setSelection((current) => ({ ...current, compare: !current.compare, year: !current.compare ? 2100 : current.year, visible: true }));
  }
  function retryMap() {
    if (mapModuleFailed.current) {
      // React.lazy retains a rejected import; a new document retries the module.
      window.location.reload();
      return;
    }
    setCatalogError(null); setPlaceError(null);
    setMapStatus({ loading: true, error: null, validPixels: null, floodPixels: null });
    setInitialCamera(camera);
    setRetry((value) => value + 1);
  }
  function selectYear(next: Year) { setPlaying(false); setSelection((current) => ({ ...current, year: next })); }
  async function share() {
    try { await navigator.clipboard.writeText(window.location.href); setShared(true); setShareError(false); }
    catch { setShareError(true); }
  }

  const placeName = city?.name ?? "Europe";
  const destinations = [{ name: "Venice", detail: "Italy · Venetian Lagoon" }, { name: "Rotterdam", detail: "Netherlands · Rhine–Meuse delta" }, { name: "Hamburg", detail: "Germany · Elbe estuary" }, { name: "Bordeaux", detail: "France · Gironde estuary" }];
  const hasPlace = Boolean(city || point);
  const setProtection = (next: Protection) => { setPlaying(false); setSelection((current) => ({ ...current, protection: next })); };

  return <main className={`atlas-app${hasPlace ? " has-selection" : ""}`}>
    <header className="atlas-header">
      <div className="brand-row"><a className="atlas-brand" href="/" aria-label="SeaRise Europe home">SeaRise <span>Europe</span></a><button className="mobile-about" type="button" aria-label="About the map" onClick={() => setAbout(true)}><Info size={20} /></button></div>
      {!hasPlace && !error && <p className="intro">How Europe's coasts change as seas rise. <span>Choose a place, then move through 2030, 2050, and 2100.</span></p>}
      {dataSource.edition === "synthetic-fixture" && <p className="atlas-fixture-label"><strong>Illustrative fixture</strong><span>Software demonstration · Not CoCliCo data</span></p>}
      <CitySearch dataSource={dataSource} onSelect={selectCity} />
      {!hasPlace && !error && <div className="coast-examples" aria-label="Explore a coast"><h2>Start with a coast</h2>{destinations.map(({ name, detail }) => <button type="button" key={name} onClick={() => { setPlaceError(null); setPointOpen(true); setSelection((current) => ({ ...current, cityId: name.toLowerCase(), point: null })); }}><span><strong>{name}</strong><small>{detail}</small></span><CaretDown size={15} /></button>)}</div>}
    </header>
    <div className="scenario-pill"><span><strong>SSP5-8.5</strong> · Spring high tide · {protection === "protected" ? "High protection" : "No additional defenses"}</span><button type="button" className="about-trigger" aria-label="About the map" onClick={() => setAbout(true)}><Info size={19} /></button></div>
    <div className="atlas-geography" aria-label="Interactive coastal flood map" data-testid="atlas-map" data-model={dataSource.edition === "synthetic-fixture" ? "illustrative-fixture" : "coclico"} data-year={year} data-layer={layer?.id ?? ""}>
      <MapChunkBoundary onFailure={onMapFailure}><Suspense fallback={<div className="map-loading" role="status">Loading the European map…</div>}><EuropeMap qaMapEnabled={qaMapEnabled} dataSource={dataSource} key={`${retry}-${mapRevision}`} city={city} year={year} protection={protection} visible={visible && !!layer} onStatus={onStatus}
        initialCamera={initialCamera} restoreCity={restoreCity} onCameraChange={onCameraChange} inspectionPoint={inspectedPoint} onInspect={onInspect} focusRequest={focusRequest}
        onOverview={exploreEurope} onShare={() => void share()} shared={shared} onRefocus={() => setFocusRequest((value) => value + 1)}
        onPlace={(id) => { setPointOpen(true); setPlaceError(null); setSelection((current) => ({ ...current, cityId: id, point: null })); }} /></Suspense></MapChunkBoundary>
      <div className="map-view-label"><span>{compare ? "COMPARING · HIGH TIDE" : "HIGH EMISSIONS · HIGH TIDE"}</span><strong>{year}</strong>{!visible && <small>Flood layer hidden</small>}</div>
    </div>

    <div ref={panel} className={`atlas-panel${expanded ? " is-expanded" : ""}`} data-testid="exploration-panel">
      <section ref={story} className={`atlas-story${!hasPlace && !error ? " is-overview" : ""}`} aria-labelledby="city-title">
        <div className="place-heading"><div><h1 ref={title} tabIndex={-1} id="city-title" className={placeName.length > 14 ? "long-place-name" : undefined}>{placeName}</h1><p className="atlas-country">{city ? <><span className="place-scope">Selected place · </span>{city.countryName}</> : "Explore the European coastline"}</p></div>
          <button className="panel-toggle" aria-expanded={expanded} aria-controls="exploration-details" type="button" onClick={() => setExpanded((value) => !value)}>{expanded ? <CaretDown size={18} /> : <CaretUp size={18} />}<span>{expanded ? "Less detail" : "More detail"}</span></button>
          {hasPlace && <button className="close-place" type="button" onClick={exploreEurope} aria-label="Explore Europe"><X size={16} /></button>}
        </div>
        {inspectedPoint && pointOpen && <section className="point-inspector" aria-label="Selected point"><div className="point-heading"><span>Selected point</span><button type="button" onClick={() => setPointOpen(false)} aria-label="Close point result"><X size={16} /></button></div><PointInspection dataSource={dataSource} point={inspectedPoint} protection={protection} year={year} /></section>}
        <div className="panel-details" id="exploration-details">
          <div className="year-summary"><strong>{year}</strong><p>Land modeled as exposed at spring high tide with sea-level rise.</p></div>
          <div className={`atlas-legend${!visible ? " is-hidden" : ""}`} aria-label="Map legend"><strong>{visible ? "Modeled flood depth at high tide" : "Flood layer hidden"}</strong>{visible && <><div className="depth-key" aria-label="Flood depth in meters"><span>0–0.25</span><span>0.25–0.5</span><span>0.5–1</span><span>1–2</span><span>2–5</span><span>5+ m</span></div><p>Uncolored land may be unknown. Tap a point to check.</p></>}</div>
          <div className="atlas-settings"><span>Coastal defenses</span><div className="defense-control" role="group" aria-label="Coastal defenses"><button type="button" aria-pressed={protection === "unprotected"} onClick={() => setProtection("unprotected")}>No additional defenses</button><button type="button" aria-pressed={protection === "protected"} onClick={() => setProtection("protected")}>High protection</button></div></div>
          {city && <button className="text-button back-to-place" type="button" onClick={() => setFocusRequest((value) => value + 1)}><Crosshair size={15} />Back to {city.name}</button>}
        </div>
        {catalog && !layer && <div className="atlas-notice" role="status">This year and defense setting is unavailable. Choose another combination.</div>}
        {error && <div className="atlas-notice atlas-notice--error" role="alert"><p><strong>The map needs another try.</strong>{error}</p><button type="button" onClick={retryMap}><ArrowClockwise size={18} />Retry</button></div>}
      </section>

      <section className="atlas-time" aria-label="Explore coastal change over time">
        <div className="timeline-row">
          {!compare && <button className={`play-button${playing ? " is-playing" : ""}`} type="button" disabled={!catalog || !!error} aria-label={playing ? "Pause timeline" : "Play timeline"} onClick={() => setPlaying((value) => !value)}>{playing ? <Pause size={17} weight="fill" /> : <Play size={17} weight="fill" />}</button>}
          <div className="timeline-track"><input type="range" min={0} max={timelineYears.length - 1} step={1} value={timelineYears.indexOf(year)} aria-label="Projection year" aria-valuetext={String(year)} onChange={(event) => selectYear(timelineYears[Number(event.target.value)])} /><div className="timeline-years">{timelineYears.map((value) => <button type="button" key={value} className={year === value ? "selected" : ""} aria-pressed={year === value} onClick={() => selectYear(value)}>{value}</button>)}</div></div>
          <div className="atlas-actions"><button className="compare-button" type="button" aria-label={compare ? "Exit comparison" : "Compare 2030 & 2100"} aria-pressed={compare} onClick={toggleCompare}><ArrowsLeftRight size={17} /><span>{compare ? "Exit" : "Compare"}</span></button><button className="layer-button" type="button" aria-pressed={visible} aria-label={visible ? "Hide flood layer" : "Show flood layer"} onClick={() => setSelection((current) => ({ ...current, visible: !current.visible }))}>{visible ? <Eye size={18} /> : <EyeSlash size={18} />}<span>Overlay</span></button></div>
        </div>
        <div className="time-heading"><p>{`${placeName} · ${year}${compare ? " · Compare 2030 & 2100" : ""}`}</p><span className="map-loading" role="status">{loading && !error ? "Loading the coast…" : ""}</span><span className="timeline-explanation">Three calculated years</span></div>
        {compare && <p className="comparison-hint">Switch years to compare the same view.</p>}
        <p className="model-caveat">High tide, not a permanent shoreline. Uncolored land may lack data.</p>
      </section>
    </div>
    <p className="share-feedback" role="status">{shared ? "Link copied. Share this view." : shareError ? "Copy the address in your browser to share this view." : ""}</p>
    <footer className="atlas-footer"><button type="button" onClick={() => setAbout(true)}>{dataSource.edition === "synthetic-fixture" ? "Fixture · Data & methods" : "CoCliCo · Data & methods"}</button><span className="map-source-credit">{dataSource.edition === "synthetic-fixture" ? "Natural Earth · Illustrative data" : <>© <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">OpenStreetMap contributors</a> · Protomaps</>}</span><span className="local-edition">{dataSource.edition === "synthetic-fixture" ? "Illustrative fixture · Europe" : "Local edition · Europe"}</span></footer>
    <AboutDialog edition={dataSource.edition} open={about} onClose={() => setAbout(false)} catalog={catalog} />
  </main>;
}
