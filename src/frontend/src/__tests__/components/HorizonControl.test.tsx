import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import HorizonControl from "@/app/components/assessment/HorizonControl";
import type { HorizonConfig } from "@/lib/types";
import { strings } from "@/lib/i18n/en";

const mockHorizons: HorizonConfig[] = [
  { year: 2030, displayLabel: "2030", sortOrder: 1 },
  { year: 2050, displayLabel: "2050", sortOrder: 2 },
  { year: 2100, displayLabel: "2100", sortOrder: 3 },
];

describe("HorizonControl", () => {
  const onSelect = vi.fn();

  beforeEach(() => {
    onSelect.mockReset();
  });

  it("renders all horizons from config", () => {
    render(
      <HorizonControl
        horizons={mockHorizons}
        activeHorizonYear={2050}
        onSelect={onSelect}
      />
    );

    expect(screen.getByText(strings.controls.horizonLabel)).toBeInTheDocument();
    const radios = screen.getAllByRole("radio");
    expect(radios).toHaveLength(3);
  });

  it("marks the active horizon with aria-checked", () => {
    render(
      <HorizonControl
        horizons={mockHorizons}
        activeHorizonYear={2050}
        onSelect={onSelect}
      />
    );

    const radios = screen.getAllByRole("radio");
    expect(radios[0]).toHaveAttribute("aria-checked", "false");
    expect(radios[1]).toHaveAttribute("aria-checked", "true");
    expect(radios[2]).toHaveAttribute("aria-checked", "false");
  });

  it("has a radiogroup with correct aria-labelledby", () => {
    render(
      <HorizonControl
        horizons={mockHorizons}
        activeHorizonYear={2050}
        onSelect={onSelect}
      />
    );

    expect(screen.getByRole("radiogroup")).toHaveAttribute("aria-labelledby", "horizon-label");
  });

  it("calls onSelect when a horizon is clicked", async () => {
    render(
      <HorizonControl
        horizons={mockHorizons}
        activeHorizonYear={2050}
        onSelect={onSelect}
      />
    );

    const radios = screen.getAllByRole("radio");
    await userEvent.click(radios[2]);
    expect(onSelect).toHaveBeenCalledWith(2100);
  });

  it("navigates with arrow keys", async () => {
    render(
      <HorizonControl
        horizons={mockHorizons}
        activeHorizonYear={2050}
        onSelect={onSelect}
      />
    );

    const radios = screen.getAllByRole("radio");
    radios[1].focus();
    await userEvent.keyboard("{ArrowRight}");
    expect(onSelect).toHaveBeenCalledWith(2100);
  });
});
