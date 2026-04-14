import { useQuery } from "@tanstack/react-query";
import type { AssessmentResult } from "@/lib/types";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "";

interface AssessParams {
  latitude: number;
  longitude: number;
  scenarioId: string;
  horizonYear: number;
}

async function assess(
  params: AssessParams,
  signal?: AbortSignal
): Promise<AssessmentResult> {
  const response = await fetch(`${API_BASE_URL}/v1/assess`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(params),
    signal,
  });

  if (!response.ok) {
    const errorBody = await response.json().catch(() => ({
      error: { code: "UNKNOWN", message: "Assessment request failed" },
    }));
    throw errorBody.error ?? { code: "UNKNOWN", message: "Assessment request failed" };
  }

  return response.json();
}

export function useAssessment(params: AssessParams | null) {
  return useQuery<AssessmentResult>({
    queryKey: params
      ? ["assess", params.latitude, params.longitude, params.scenarioId, params.horizonYear]
      : ["assess"],
    queryFn: ({ signal }) => assess(params!, signal),
    enabled: params !== null,
    staleTime: 60_000,
    retry: 1,
    refetchOnWindowFocus: false,
  });
}
