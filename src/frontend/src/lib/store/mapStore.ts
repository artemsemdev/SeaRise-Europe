import { create } from "zustand";
import type { SelectedLocation } from "@/lib/types";

interface Viewport {
  center: [number, number];
  zoom: number;
}

interface MapStore {
  viewport: Viewport;
  selectedLocation: SelectedLocation | null;
  setViewport: (viewport: Viewport) => void;
  setSelectedLocation: (location: SelectedLocation | null) => void;
}

export const useMapStore = create<MapStore>((set) => ({
  viewport: { center: [10, 54], zoom: 4 },
  selectedLocation: null,

  setViewport: (viewport) => set({ viewport }),
  setSelectedLocation: (location) => set({ selectedLocation: location }),
}));

export const useViewport = () => useMapStore((s) => s.viewport);
export const useSelectedLocation = () =>
  useMapStore((s) => s.selectedLocation);
