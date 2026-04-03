import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import ScenarioControl from "@/app/components/assessment/ScenarioControl";
import type { ScenarioConfig } from "@/lib/types";
import { strings } from "@/lib/i18n/en";

const mockScenarios: ScenarioConfig[] = [
  { id: "ssp1-26", displayName: "Lower emissions (SSP1-2.6)", description: "Low emissions, strong climate action", sortOrder: 1 },
  { id: "ssp2-45", displayName: "Intermediate emissions (SSP2-4.5)", description: "Middle-of-the-road path", sortOrder: 2 },
  { id: "ssp5-85", displayName: "Higher emissions (SSP5-8.5)", description: "High emissions, minimal action", sortOrder: 3 },
];

describe("ScenarioControl", () => {
  const onSelect = vi.fn();

  beforeEach(() => {
    onSelect.mockReset();
  });

  it("renders all scenarios from config in sort order", () => {
    render(
      <ScenarioControl
        scenarios={mockScenarios}
        activeScenarioId="ssp2-45"
        onSelect={onSelect}
      />
    );

    expect(screen.getByText(strings.controls.scenarioLabel)).toBeInTheDocument();
    expect(screen.getByText("Lower emissions (SSP1-2.6)")).toBeInTheDocument();
    expect(screen.getByText("Intermediate emissions (SSP2-4.5)")).toBeInTheDocument();
    expect(screen.getByText("Higher emissions (SSP5-8.5)")).toBeInTheDocument();
  });

  it("marks the active scenario with aria-checked", () => {
    render(
      <ScenarioControl
        scenarios={mockScenarios}
        activeScenarioId="ssp2-45"
        onSelect={onSelect}
      />
    );

    const radios = screen.getAllByRole("radio");
    expect(radios).toHaveLength(3);
    expect(radios[0]).toHaveAttribute("aria-checked", "false");
    expect(radios[1]).toHaveAttribute("aria-checked", "true");
    expect(radios[2]).toHaveAttribute("aria-checked", "false");
  });

  it("has a radiogroup with correct aria-labelledby", () => {
    render(
      <ScenarioControl
        scenarios={mockScenarios}
        activeScenarioId="ssp2-45"
        onSelect={onSelect}
      />
    );

    expect(screen.getByRole("radiogroup")).toHaveAttribute("aria-labelledby", "scenario-label");
  });

  it("calls onSelect when a scenario is clicked", async () => {
    render(
      <ScenarioControl
        scenarios={mockScenarios}
        activeScenarioId="ssp2-45"
        onSelect={onSelect}
      />
    );

    const radios = screen.getAllByRole("radio");
    await userEvent.click(radios[2]);
    expect(onSelect).toHaveBeenCalledWith("ssp5-85");
  });

  it("navigates with arrow keys", async () => {
    render(
      <ScenarioControl
        scenarios={mockScenarios}
        activeScenarioId="ssp2-45"
        onSelect={onSelect}
      />
    );

    const radios = screen.getAllByRole("radio");
    radios[1].focus();
    await userEvent.keyboard("{ArrowDown}");
    expect(onSelect).toHaveBeenCalledWith("ssp5-85");
  });
});
