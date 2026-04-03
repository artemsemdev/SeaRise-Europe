import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import Legend from "@/app/components/assessment/Legend";
import type { LegendColorStop } from "@/lib/types";

const mockColorStops: LegendColorStop[] = [
  { value: 1, color: "#E85D04", label: "Modeled exposure zone" },
  { value: 0, color: "#1A1A2E", label: "No modeled exposure" },
];

describe("Legend", () => {
  it("renders all color stops with labels", () => {
    render(<Legend colorStops={mockColorStops} />);
    expect(screen.getByText("Modeled exposure zone")).toBeInTheDocument();
    expect(screen.getByText("No modeled exposure")).toBeInTheDocument();
  });

  it("renders color swatches", () => {
    const { container } = render(<Legend colorStops={mockColorStops} />);
    const swatches = container.querySelectorAll("[aria-hidden='true']");
    expect(swatches).toHaveLength(2);
  });

  it("returns null for empty color stops", () => {
    const { container } = render(<Legend colorStops={[]} />);
    expect(container.firstChild).toBeNull();
  });

  it("has aria-label on legend container", () => {
    render(<Legend colorStops={mockColorStops} />);
    expect(screen.getByLabelText("Map legend")).toBeInTheDocument();
  });
});
