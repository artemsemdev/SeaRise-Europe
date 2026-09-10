import { useEffect, useRef } from "react";
import { ArrowUpRight, X } from "@phosphor-icons/react";
import type { AtlasCatalog } from "./model";
import type { AtlasEdition } from "./browser-data-contract";

export function AboutDialog({ open, onClose, catalog, edition }: { open: boolean; onClose: () => void; catalog: AtlasCatalog | null; edition: AtlasEdition }) {
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => { if (open) dialog.current?.showModal(); else dialog.current?.close(); }, [open]);
  return <dialog ref={dialog} className="atlas-dialog" aria-labelledby="about-title" onCancel={onClose} onKeyDown={(event) => {
    if (event.key !== "Tab") return;
    const items = Array.from(event.currentTarget.querySelectorAll<HTMLElement>('button:not([disabled]), a[href], input, select, [tabindex="0"]'));
    const first = items[0];
    const last = items.at(-1);
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
  }} onClick={(event) => {
    if (event.target === dialog.current) {
      const rect = dialog.current.getBoundingClientRect();
      if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) onClose();
    }
  }}>
    <div className="atlas-dialog__top"><span className="eyebrow">BEHIND THE MAP</span><button type="button" onClick={onClose} aria-label="Close map information"><X size={24} /></button></div>
    <h2 id="about-title">About the data</h2>
    {edition === "synthetic-fixture" && <section className="atlas-fixture-label"><h3>Illustrative fixture</h3><p>This software demonstration uses authored values, not CoCliCo observations or simulations. The years and defense controls demonstrate the interface. They do not provide real flood results. The CoCliCo methodology below describes the real-data edition.</p></section>}
    <p className="about-lead">The blue areas show modeled coastal flooding at high tide under a high-emissions future. Change the year to explore how the modeled extent changes.</p>
    <section><h3>What the water means</h3><p>These CoCliCo simulations combine sea-level rise with mean spring high tide. They show a particular water condition, not land that is permanently underwater. This view does not add an extreme storm.</p></section>
    <section><h3>One consistent future</h3><p>The timeline uses SSP5-8.5 for 2030, 2050, and 2100. This is a high-emissions scenario, not a prediction of which future will happen. The control selects three calculated years; it does not invent results for the years between them.</p></section>
    <section><h3>Coastal defenses matter</h3><p>“No additional defenses” includes only protection already represented in the terrain. “High protection” applies policy-based protection levels across provinces. It does not simulate the operation of each individual dike, gate, or pump.</p></section>
    <section><h3>Read a point, compare the years</h3><p>Tap the map to inspect one original 25-meter model cell across all three years. A depth is a positive model value; “No flooding modeled” means a valid zero; “No usable data” means the source cannot answer for that cell. A point is not an assessment of the entire city. The comparison switches between 2030 and 2100 at the same position and scale. It does not compare against present-day flooding.</p></section>
    <section><h3>Map detail and flood resolution</h3><p>Explore the European coast using the project’s prepared European boundaries and place catalog. Flood coverage follows the available CoCliCo source data and varies by location. Zoom in to see streets, buildings, and place names. These map details provide geographic context; the flooding model still uses 25-meter cells, even at the closest zoom. Uncolored land is not a safety rating, and missing flood data is not evidence of no flooding. Do not use this map to assess an individual property.</p></section>
    <section className="about-source"><h3>Sources & credits</h3><p>{catalog?.source.name ?? (edition === "synthetic-fixture" ? "Illustrative synthetic coastal fixture" : "CoCliCo coastal flood simulations")}. {edition === "real-local" ? "Water is rendered directly from downloaded 25-meter flood-depth rasters. At overview scales, published lower-resolution source images provide an approximation; zoom in for more detail." : "Illustrative flood patterns and point values are authored for software tests."}</p>
      <a href={catalog?.source.methodologyUrl ?? "https://www.openearth.nl/coclico-workbench/Datasets/"} target="_blank" rel="noreferrer">{edition === "synthetic-fixture" ? "Read about the fixture" : "Read the CoCliCo methodology"} <ArrowUpRight size={16} /></a>
      <p>{edition === "real-local" ? "Geographic context: OpenStreetMap contributors (ODbL), Protomaps, and Natural Earth. Places: GeoNames. Source credits and processing notes accompany the local data. All map data is served from this computer." : "Geographic context: Natural Earth and prepared European boundaries. The small place catalog and flood values are illustrative. This fixture does not use the local basemap, GeoNames catalog, or CoCliCo raster files."}</p>
    </section>
  </dialog>;
}
