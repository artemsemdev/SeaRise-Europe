import { useQuery } from "@tanstack/react-query";
import type { MethodologyData } from "@/lib/types";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "";

async function fetchMethodology(): Promise<MethodologyData> {
  const response = await fetch(`${API_BASE_URL}/v1/config/methodology`);
  if (!response.ok) {
    throw new Error(`Methodology fetch failed: ${response.status}`);
  }
  return response.json();
}

export function useMethodology() {
  return useQuery<MethodologyData>({
    queryKey: ["methodology"],
    queryFn: fetchMethodology,
    staleTime: Infinity,
  });
}
