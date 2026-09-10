import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { MagnifyingGlass, ArrowUpRight, MapPin, X } from "@phosphor-icons/react";
import type { City } from "./model";
import { validateAtlasPlaceSearch } from "./browser-data-contract";
import type { AtlasDataSource } from "./data-source";

const RESULTS_GAP = 8;
const VIEWPORT_MARGIN = 12;

type ResultsGeometry = {
  left: number;
  top: number;
  width: number;
  maxHeight: number;
};

export function CitySearch({ dataSource, onSelect }: { dataSource: AtlasDataSource; onSelect: (city: City) => void }) {
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const [matches, setMatches] = useState<readonly City[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(false);
  const [resultsGeometry, setResultsGeometry] = useState<ResultsGeometry | null>(null);
  const search = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLInputElement>(null);
  const results = useRef<HTMLDivElement>(null);
  const placeResults = useCallback(() => {
    const rect = search.current?.getBoundingClientRect();
    if (!rect) return;
    const top = rect.bottom + RESULTS_GAP;
    const viewport = window.visualViewport;
    const viewportBottom = viewport ? viewport.offsetTop + viewport.height : window.innerHeight;
    const next = {
      left: rect.left,
      top,
      width: rect.width,
      maxHeight: Math.max(0, viewportBottom - top - VIEWPORT_MARGIN),
    };
    setResultsGeometry((current) => current && current.left === next.left && current.top === next.top &&
      current.width === next.width && current.maxHeight === next.maxHeight ? current : next);
  }, []);
  useLayoutEffect(() => {
    if (!open) return;
    placeResults();
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(placeResults);
    if (search.current) observer?.observe(search.current);
    window.addEventListener("resize", placeResults);
    window.addEventListener("scroll", placeResults, true);
    window.visualViewport?.addEventListener("resize", placeResults);
    window.visualViewport?.addEventListener("scroll", placeResults);
    return () => {
      observer?.disconnect();
      window.removeEventListener("resize", placeResults);
      window.removeEventListener("scroll", placeResults, true);
      window.visualViewport?.removeEventListener("resize", placeResults);
      window.visualViewport?.removeEventListener("scroll", placeResults);
    };
  }, [open, placeResults]);
  useEffect(() => {
    if (!open) return;
    const abort = new AbortController();
    const timer = window.setTimeout(() => {
      setLoading(true); setError(false);
      dataSource.search(query.trim(), { signal: abort.signal })
        .then((value) => {
          const cities = validateAtlasPlaceSearch(value).results;
          if (!abort.signal.aborted) { setMatches(cities); setActive(0); }
        })
        .catch(() => { if (!abort.signal.aborted) { setError(true); setMatches([]); } })
        .finally(() => { if (!abort.signal.aborted) setLoading(false); });
    }, 160);
    return () => { abort.abort(); window.clearTimeout(timer); };
  }, [query, open, dataSource]);
  useEffect(() => {
    if (open && matches[active]) document.getElementById(`city-${matches[active].id}`)?.scrollIntoView({ block: "nearest" });
  }, [active, matches, open]);
  function choose(city: City) { onSelect(city); setQuery(""); setOpen(false); }
  function showResults() { placeResults(); setOpen(true); }
  function highlighted(name: string) {
    const start = name.toLocaleLowerCase("en-US").indexOf(query.trim().toLocaleLowerCase("en-US"));
    if (start < 0 || !query.trim()) return name;
    const end = start + query.trim().length;
    return <>{name.slice(0, start)}<mark>{name.slice(start, end)}</mark>{name.slice(end)}</>;
  }
  const menu = open && resultsGeometry ? createPortal(<div ref={results} className="search-results" style={resultsGeometry}>
    <div className="search-results__heading">EXPLORE EUROPE</div>
    <ul id="atlas-cities" role="listbox" aria-label="European places" aria-busy={loading}>
      {matches.map((city, index) => <li key={city.id} id={`city-${city.id}`} role="option" aria-selected={active === index}
        onMouseDown={(event) => event.preventDefault()} onMouseMove={() => setActive(index)} onClick={() => choose(city)}>
        <MapPin size={18} aria-hidden="true" /><span><span className="search-name">{highlighted(city.name)}</span><small>{city.countryName}</small></span><ArrowUpRight size={18} aria-hidden="true" />
      </li>)}
    </ul>
    {loading && <p className="search-empty" role="status">Searching European places…</p>}
    {error && <p className="search-empty" role="alert">Search could not load. Try typing your city again.</p>}
    {!loading && !error && !matches.length && <p className="search-empty">{query.trim() ? "No matching place. Try another spelling or a nearby city." : "Type a city name to explore the European coast."}</p>}
    <p className="search-results__footnote">Choose a place, then tap the map to inspect a point.</p>
  </div>, document.body) : null;
  return <div ref={search} className="atlas-search" onBlur={(event) => {
    const next = event.relatedTarget;
    if (!event.currentTarget.contains(next) && !results.current?.contains(next)) setOpen(false);
  }}>
    <MagnifyingGlass size={21} aria-hidden="true" />
    <input ref={input} aria-label="Find a city in Europe" role="combobox" aria-autocomplete="list"
      aria-expanded={open} aria-controls="atlas-cities" aria-activedescendant={open && matches[active] ? `city-${matches[active].id}` : undefined}
      placeholder="Search a coastal city" autoComplete="off" spellCheck={false} value={query}
      onFocus={showResults} onChange={(event) => { setQuery(event.target.value); setMatches([]); setLoading(true); setActive(0); showResults(); }}
      onKeyDown={(event) => {
        if (event.key === "Escape") { event.preventDefault(); setOpen(false); }
        if (event.key === "ArrowDown") { event.preventDefault(); showResults(); setActive((i) => Math.max(0, Math.min(i + 1, matches.length - 1))); }
        if (event.key === "ArrowUp") { event.preventDefault(); setActive((i) => Math.max(0, i - 1)); }
        if (event.key === "Enter" && open && matches[active]) { event.preventDefault(); choose(matches[active]); }
      }} />
    {query && <button className="search-clear" type="button" aria-label="Clear search" onClick={() => {
      setQuery(""); setMatches([]); setActive(0); setLoading(true); input.current?.focus(); showResults();
    }}><X size={14} /></button>}
    {menu}
  </div>;
}
