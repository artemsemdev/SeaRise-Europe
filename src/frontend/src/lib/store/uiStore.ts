import { create } from "zustand";

interface UiStore {
  isMethodologyPanelOpen: boolean;
  openMethodologyPanel: () => void;
  closeMethodologyPanel: () => void;
}

export const useUiStore = create<UiStore>((set) => ({
  isMethodologyPanelOpen: false,

  openMethodologyPanel: () => set({ isMethodologyPanelOpen: true }),
  closeMethodologyPanel: () => set({ isMethodologyPanelOpen: false }),
}));
