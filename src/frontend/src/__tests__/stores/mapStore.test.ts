import { describe, it, expect, beforeEach } from "vitest";
import { useMapStore } from "@/lib/store/mapStore";

describe("mapStore", () => {
  beforeEach(() => {
    useMapStore.setState({
      viewport: { center: [10, 54], zoom: 4 },
      selectedLocation: null,
    });
  });

  it("initializes with Europe-centered viewport", () => {
    const { viewport } = useMapStore.getState();
    expect(viewport.center).toEqual([10, 54]);
    expect(viewport.zoom).toBe(4);
  });

  it("initializes with null selectedLocation", () => {
    expect(useMapStore.getState().selectedLocation).toBeNull();
  });

  it("updates viewport", () => {
    useMapStore.getState().setViewport({ center: [5, 52], zoom: 10 });
    const { viewport } = useMapStore.getState();
    expect(viewport.center).toEqual([5, 52]);
    expect(viewport.zoom).toBe(10);
  });

  it("sets selectedLocation", () => {
    const location = {
      label: "Amsterdam",
      displayContext: "North Holland",
      latitude: 52.37,
      longitude: 4.9,
    };
    useMapStore.getState().setSelectedLocation(location);
    expect(useMapStore.getState().selectedLocation).toEqual(location);
  });

  it("clears selectedLocation", () => {
    useMapStore.getState().setSelectedLocation({
      label: "Test",
      displayContext: "",
      latitude: 0,
      longitude: 0,
    });
    useMapStore.getState().setSelectedLocation(null);
    expect(useMapStore.getState().selectedLocation).toBeNull();
  });
});
