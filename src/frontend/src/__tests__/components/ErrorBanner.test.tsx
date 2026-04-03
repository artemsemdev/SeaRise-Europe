import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import ErrorBanner from "@/app/components/shared/ErrorBanner";
import { strings } from "@/lib/i18n/en";

describe("ErrorBanner", () => {
  it("renders geocoding error copy", () => {
    render(<ErrorBanner variant="geocoding" onRetry={() => {}} />);
    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(screen.getByRole("alert").textContent).toContain(
      strings.errors.geocodingFailure.heading
    );
  });

  it("renders assessment error copy", () => {
    render(<ErrorBanner variant="assessment" onRetry={() => {}} />);
    expect(screen.getByRole("alert").textContent).toContain(
      strings.errors.assessmentFailure.heading
    );
  });

  it("has role alert", () => {
    render(<ErrorBanner variant="geocoding" onRetry={() => {}} />);
    expect(screen.getByRole("alert")).toBeInTheDocument();
  });

  it("calls onRetry when retry button clicked", async () => {
    const onRetry = vi.fn();
    render(<ErrorBanner variant="geocoding" onRetry={onRetry} />);
    await userEvent.click(screen.getByText("Retry"));
    expect(onRetry).toHaveBeenCalledOnce();
  });

  it("renders assessment error with location header and New search button", () => {
    render(
      <ErrorBanner variant="assessment" onRetry={() => {}} locationLabel="Bordeaux, France" locationContext="Atlantic coast" />
    );
    expect(screen.getByText("Bordeaux, France")).toBeInTheDocument();
    expect(screen.getByText("Atlantic coast")).toBeInTheDocument();
    expect(screen.getByText(strings.actions.newSearch)).toBeInTheDocument();
  });
});
