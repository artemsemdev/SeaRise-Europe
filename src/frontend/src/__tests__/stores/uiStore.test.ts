import { describe, it, expect, beforeEach } from "vitest";
import { useUiStore } from "@/lib/store/uiStore";

describe("uiStore", () => {
  beforeEach(() => {
    useUiStore.setState({ isMethodologyPanelOpen: false });
  });

  it("initializes with methodology panel closed", () => {
    expect(useUiStore.getState().isMethodologyPanelOpen).toBe(false);
  });

  it("opens methodology panel", () => {
    useUiStore.getState().openMethodologyPanel();
    expect(useUiStore.getState().isMethodologyPanelOpen).toBe(true);
  });

  it("closes methodology panel", () => {
    useUiStore.getState().openMethodologyPanel();
    useUiStore.getState().closeMethodologyPanel();
    expect(useUiStore.getState().isMethodologyPanelOpen).toBe(false);
  });
});
