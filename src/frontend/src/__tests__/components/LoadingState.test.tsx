import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import LoadingState from "@/app/components/shared/LoadingState";
import { strings } from "@/lib/i18n/en";

describe("LoadingState", () => {
  it("renders geocoding loading text", () => {
    render(<LoadingState variant="geocoding" />);
    expect(screen.getByText(strings.loading.geocoding)).toBeInTheDocument();
  });

  it("renders assessing card with title and subtitle", () => {
    render(<LoadingState variant="assessing" locationLabel="Amsterdam" />);
    expect(screen.getByText(strings.loading.title)).toBeInTheDocument();
    expect(
      screen.getByText(strings.loading.subtitle("Amsterdam"))
    ).toBeInTheDocument();
  });

  it("renders assessing card with step list", () => {
    render(<LoadingState variant="assessing" locationLabel="Amsterdam" />);
    for (const step of strings.loading.steps) {
      expect(screen.getByText(step)).toBeInTheDocument();
    }
  });

  it("has aria-busy true", () => {
    render(<LoadingState variant="geocoding" />);
    const container = screen.getByText(strings.loading.geocoding).closest("[aria-busy]");
    expect(container).toHaveAttribute("aria-busy", "true");
  });
});
