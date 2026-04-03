import { describe, it, expect, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import CandidateList from "@/app/components/search/CandidateList";
import { useAppStore } from "@/lib/store/appStore";
import { useMapStore } from "@/lib/store/mapStore";
import type { GeocodingCandidate } from "@/lib/types";

const mockCandidates: GeocodingCandidate[] = [
  {
    rank: 1,
    label: "Amsterdam, Netherlands",
    country: "NL",
    latitude: 52.37,
    longitude: 4.9,
    displayContext: "North Holland, Netherlands",
  },
  {
    rank: 2,
    label: "Amsterdam, New York",
    country: "US",
    latitude: 42.94,
    longitude: -74.19,
    displayContext: "New York, United States",
  },
  {
    rank: 3,
    label: "Amsterdam, Missouri",
    country: "US",
    latitude: 39.9,
    longitude: -94.6,
    displayContext: "Missouri, United States",
  },
];

describe("CandidateList", () => {
  beforeEach(() => {
    useAppStore.getState().reset();
    useMapStore.setState({ selectedLocation: null });
  });

  it("renders correct number of candidates", () => {
    render(<CandidateList candidates={mockCandidates} />);
    const options = screen.getAllByRole("option");
    expect(options).toHaveLength(3);
  });

  it("displays label and displayContext for each candidate", () => {
    render(<CandidateList candidates={mockCandidates} />);
    expect(screen.getByText("Amsterdam, Netherlands")).toBeInTheDocument();
    expect(
      screen.getByText("North Holland, Netherlands")
    ).toBeInTheDocument();
  });

  it("limits to 5 candidates", () => {
    const manyCandidates: GeocodingCandidate[] = Array.from(
      { length: 7 },
      (_, i) => ({
        rank: i + 1,
        label: `City ${i + 1}`,
        country: "XX",
        latitude: i,
        longitude: i,
        displayContext: `Context ${i + 1}`,
      })
    );
    render(<CandidateList candidates={manyCandidates} />);
    expect(screen.getAllByRole("option")).toHaveLength(5);
  });

  it("has role listbox on the container", () => {
    render(<CandidateList candidates={mockCandidates} />);
    expect(screen.getByRole("listbox")).toBeInTheDocument();
  });

  it("selects candidate on click", async () => {
    render(<CandidateList candidates={mockCandidates} />);
    await userEvent.click(screen.getByText("Amsterdam, Netherlands"));

    const { selectedLocation } = useMapStore.getState();
    expect(selectedLocation?.label).toBe("Amsterdam, Netherlands");
    expect(useAppStore.getState().appPhase.phase).toBe("assessing");
  });

  it("navigates with keyboard and selects with Enter", async () => {
    render(<CandidateList candidates={mockCandidates} />);
    const listbox = screen.getByRole("listbox");
    listbox.focus();

    await userEvent.keyboard("{ArrowDown}");
    await userEvent.keyboard("{Enter}");

    const { selectedLocation } = useMapStore.getState();
    expect(selectedLocation?.label).toBe("Amsterdam, New York");
    expect(useAppStore.getState().appPhase.phase).toBe("assessing");
  });
});
