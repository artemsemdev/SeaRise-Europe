import { useQuery } from "@tanstack/react-query";
import type { ConfigData } from "@/lib/types";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "";

async function fetchScenarioConfig(): Promise<ConfigData> {
  const response = await fetch(`${API_BASE_URL}/v1/config/scenarios`);
  if (!response.ok) {
    throw new Error(`Config fetch failed: ${response.status}`);
  }
  return response.json();
}

export function useScenarioConfig() {
  return useQuery<ConfigData>({
    queryKey: ["config", "scenarios"],
    queryFn: fetchScenarioConfig,
    staleTime: Infinity,
  });
}
