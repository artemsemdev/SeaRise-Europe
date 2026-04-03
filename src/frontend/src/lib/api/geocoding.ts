import { useMutation } from "@tanstack/react-query";
import type { GeocodingCandidate } from "@/lib/types";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "";

interface GeocodeResponse {
  requestId: string;
  candidates: GeocodingCandidate[];
}

interface GeocodeErrorResponse {
  requestId: string;
  error: {
    code: string;
    message: string;
  };
}

async function geocode(query: string): Promise<GeocodeResponse> {
  const response = await fetch(`${API_BASE_URL}/v1/geocode`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query }),
  });

  if (!response.ok) {
    const errorBody: GeocodeErrorResponse = await response.json().catch(() => ({
      requestId: "unknown",
      error: { code: "UNKNOWN", message: "Geocoding request failed" },
    }));
    throw errorBody.error;
  }

  return response.json();
}

export function useGeocodeMutation() {
  return useMutation<GeocodeResponse, { code: string; message: string }, string>({
    mutationFn: geocode,
  });
}
