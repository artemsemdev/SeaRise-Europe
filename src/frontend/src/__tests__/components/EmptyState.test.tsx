import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import EmptyState from "@/app/components/shared/EmptyState";
import { strings } from "@/lib/i18n/en";

function renderWithProviders(ui: React.ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>
  );
}

describe("EmptyState", () => {
  it("renders hero heading with gradient accent", () => {
    renderWithProviders(<EmptyState onSubmitQuery={vi.fn()} />);
    expect(screen.getByText(/your coast/)).toBeInTheDocument();
  });

  it("renders body from strings", () => {
    renderWithProviders(<EmptyState onSubmitQuery={vi.fn()} />);
    expect(screen.getByText(strings.emptyState.body)).toBeInTheDocument();
  });

  it("renders disclaimer subtext", () => {
    renderWithProviders(<EmptyState onSubmitQuery={vi.fn()} />);
    expect(screen.getByText(strings.emptyState.subtext)).toBeInTheDocument();
  });

  it("has aria-live polite on the heading", () => {
    renderWithProviders(<EmptyState onSubmitQuery={vi.fn()} />);
    const heading = screen.getByText(/your coast/).closest("[aria-live]");
    expect(heading).toHaveAttribute("aria-live", "polite");
  });

  it("renders search bar", () => {
    renderWithProviders(<EmptyState onSubmitQuery={vi.fn()} />);
    expect(screen.getByRole("search")).toBeInTheDocument();
  });
});
