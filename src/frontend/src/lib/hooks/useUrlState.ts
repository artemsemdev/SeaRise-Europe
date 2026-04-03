"use client";

import { useEffect, useRef, useCallback } from "react";
import { useSearchParams, useRouter, usePathname } from "next/navigation";
import type { ConfigData } from "@/lib/types";

interface UrlState {
  lat: number;
  lng: number;
  scenario: string;
  horizon: number;
  zoom: number;
}

function parseUrlParams(
  searchParams: URLSearchParams,
  config: ConfigData | undefined
): UrlState | null {
  const latStr = searchParams.get("lat");
  const lngStr = searchParams.get("lng");
  const scenario = searchParams.get("scenario");
  const horizonStr = searchParams.get("horizon");
  const zoomStr = searchParams.get("zoom");

  if (!latStr || !lngStr) return null;

  const lat = parseFloat(latStr);
  const lng = parseFloat(lngStr);

  if (isNaN(lat) || isNaN(lng) || lat < -90 || lat > 90 || lng < -180 || lng > 180) {
    return null;
  }

  let scenarioId = config?.defaults.scenarioId ?? "ssp2-45";
  if (scenario && config?.scenarios.some((s) => s.id === scenario)) {
    scenarioId = scenario;
  }

  let horizonYear = config?.defaults.horizonYear ?? 2050;
  if (horizonStr) {
    const parsed = parseInt(horizonStr, 10);
    if (!isNaN(parsed) && config?.horizons.some((h) => h.year === parsed)) {
      horizonYear = parsed;
    }
  }

  let zoom = 10;
  if (zoomStr) {
    const parsedZoom = parseFloat(zoomStr);
    if (!isNaN(parsedZoom) && parsedZoom >= 0 && parsedZoom <= 22) {
      zoom = parsedZoom;
    }
  }

  return { lat, lng, scenario: scenarioId, horizon: horizonYear, zoom };
}

export function useUrlStateReader(config: ConfigData | undefined) {
  const searchParams = useSearchParams();
  return parseUrlParams(searchParams, config);
}

export function useUrlStateWriter() {
  const router = useRouter();
  const pathname = usePathname();
  const debounceRef = useRef<NodeJS.Timeout | null>(null);

  const updateUrl = useCallback(
    (params: Partial<UrlState>) => {
      if (debounceRef.current) clearTimeout(debounceRef.current);

      debounceRef.current = setTimeout(() => {
        const url = new URL(window.location.href);

        if (params.lat !== undefined) url.searchParams.set("lat", params.lat.toFixed(4));
        if (params.lng !== undefined) url.searchParams.set("lng", params.lng.toFixed(4));
        if (params.scenario !== undefined) url.searchParams.set("scenario", params.scenario);
        if (params.horizon !== undefined) url.searchParams.set("horizon", String(params.horizon));
        if (params.zoom !== undefined) url.searchParams.set("zoom", params.zoom.toFixed(1));

        router.replace(`${pathname}${url.search}`, { scroll: false });
      }, 150);
    },
    [router, pathname]
  );

  const clearUrl = useCallback(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    router.replace(pathname, { scroll: false });
  }, [router, pathname]);

  return { updateUrl, clearUrl };
}
