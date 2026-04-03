import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import NoResults from "@/app/components/shared/NoResults";
import { strings } from "@/lib/i18n/en";

describe("NoResults", () => {
  it("renders heading and body with query", () => {
    render(<NoResults query="Atlantis" />);
    expect(screen.getByText(strings.noResults.heading)).toBeInTheDocument();
    expect(
      screen.getByText(strings.noResults.body("Atlantis"))
    ).toBeInTheDocument();
  });

  it("has aria-live polite", () => {
    render(<NoResults query="test" />);
    const container = screen.getByText(strings.noResults.heading).closest("[aria-live]");
    expect(container).toHaveAttribute("aria-live", "polite");
  });

  it("has a Clear search button", () => {
    render(<NoResults query="test" />);
    expect(screen.getByText("Clear search")).toBeInTheDocument();
  });
});
