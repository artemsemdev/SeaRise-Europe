import { ATLAS_YEARS as YEARS } from "./browser-data-contract";
import type { AtlasPoint } from "./browser-data-contract";

export { ATLAS_YEARS as YEARS, validateAtlasCatalog as parseCatalog,
  validateAtlasPlace as parseCity, validateAtlasInspection as parseInspection } from "./browser-data-contract";
export type { AtlasYear as Year, AtlasProtection as Protection, AtlasPlaceV1 as City,
  AtlasPoint as Point, AtlasPointResultV1 as PointResult, AtlasInspectionV1 as Inspection,
  AtlasCatalogV1 as AtlasCatalog } from "./browser-data-contract";
import type { AtlasYear as Year, AtlasProtection as Protection } from "./browser-data-contract";
export type Camera = { lng: number; lat: number; zoom: number };
type Point = AtlasPoint;

function geographicPair(raw: string | null): Point | null {
  if (!raw || !/^-?\d+(?:\.\d+)?(?:e[+-]?\d+)?,-?\d+(?:\.\d+)?(?:e[+-]?\d+)?$/.test(raw)) return null;
  const pair = raw.split(",").map(Number);
  return pair[0] >= -31 && pair[0] <= 46 && pair[1] >= 28 && pair[1] <= 77 ? [pair[0], pair[1]] : null;
}
export function readSelection(search: string) {
  const query = new URLSearchParams(search);
  const candidate = Number(query.get("year"));
  const year: Year = YEARS.includes(candidate as Year) ? candidate as Year : 2050;
  const protection: Protection = query.get("defenses") === "protected" ? "protected" : "unprotected";
  const id = query.get("city")?.trim();
  const view = query.get("view")?.split(",");
  const center = view?.length === 3 ? geographicPair(view.slice(0, 2).join(",")) : null;
  const zoom = view?.[2] ? Number(view[2]) : NaN;
  const camera: Camera | null = center && Number.isFinite(zoom) && zoom >= 0 && zoom <= 16 ? { lng: center[0], lat: center[1], zoom } : null;
  const compare = query.get("compare") === "on";
  return { cityId: id && id.length <= 128 ? id : null, year: compare && year === 2050 ? 2100 as Year : year, protection,
    visible: query.get("flooding") !== "off", compare, camera, point: geographicPair(query.get("point")) };
}

export function selectionUrl(cityId: string | null, year: Year, protection: Protection, visible: boolean,
  view: { camera?: Camera | null; point?: Point | null; compare?: boolean } = {}) {
  const params = new URLSearchParams({ year: String(year), defenses: protection, flooding: visible ? "on" : "off" });
  if (cityId) params.set("city", cityId);
  if (view.compare) params.set("compare", "on");
  if (view.camera) params.set("view", [view.camera.lng.toFixed(6), view.camera.lat.toFixed(6), view.camera.zoom.toFixed(4)].join(","));
  if (view.point) params.set("point", view.point.join(","));
  return `/?${params}`;
}
