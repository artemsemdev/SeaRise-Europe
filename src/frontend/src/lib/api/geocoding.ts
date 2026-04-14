import { useQuery } from "@tanstack/react-query";
import type { GeocodingCandidate } from "@/lib/types";

interface GeocodeResponse {
  requestId: string;
  candidates: GeocodingCandidate[];
}

interface GeocodeErrorBody {
  requestId?: string;
  error?: { code: string; message: string };
}

export interface GeocodeError {
  code: string;
  message: string;
}

async function geocode(query: string, signal?: AbortSignal): Promise<GeocodeResponse> {
  const response = await fetch(`/v1/geocode`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query }),
    signal,
  });

  if (!response.ok) {
    const errorBody: GeocodeErrorBody = await response.json().catch(() => ({}));
    throw (errorBody.error ?? { code: "UNKNOWN", message: "Geocoding request failed" }) as GeocodeError;
  }

  return response.json();
}

export function useGeocodeQuery(query: string | null) {
  const normalizedKey = query?.trim().toLowerCase() ?? "";
  return useQuery<GeocodeResponse, GeocodeError>({
    queryKey: ["geocode", normalizedKey],
    queryFn: ({ signal }) => geocode(query!, signal),
    enabled: normalizedKey.length > 0,
    staleTime: 5 * 60 * 1000,
    retry: 1,
    refetchOnWindowFocus: false,
  });
}
