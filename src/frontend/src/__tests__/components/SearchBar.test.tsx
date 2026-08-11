import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import SearchBar from "@/app/components/search/SearchBar";
import { useAppStore } from "@/lib/store/appStore";
import { strings } from "@/lib/i18n/en";

function renderSearchBar(onSubmitQuery: (q: string) => void = vi.fn()) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <SearchBar onSubmitQuery={onSubmitQuery} />
    </QueryClientProvider>
  );
}

describe("SearchBar", () => {
  beforeEach(() => {
    useAppStore.getState().reset();
  });

  it("renders input and submit button", () => {
    renderSearchBar();
    expect(
      screen.getByPlaceholderText(strings.search.placeholder)
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: strings.search.submitLabel })
    ).toBeInTheDocument();
  });

  it("has role search on the form", () => {
    renderSearchBar();
    expect(screen.getByRole("search")).toBeInTheDocument();
  });

  it("has aria-label on the input", () => {
    renderSearchBar();
    expect(
      screen.getByLabelText(strings.search.placeholder)
    ).toBeInTheDocument();
  });

  it("blocks empty submission", async () => {
    const onSubmitQuery = vi.fn();
    renderSearchBar(onSubmitQuery);
    await userEvent.click(
      screen.getByRole("button", { name: strings.search.submitLabel })
    );
    expect(onSubmitQuery).not.toHaveBeenCalled();
  });

  it("has maxLength 200 on input", () => {
    renderSearchBar();
    const input = screen.getByPlaceholderText(strings.search.placeholder);
    expect(input).toHaveAttribute("maxLength", "200");
  });

  it("keeps user-facing search guidance settlement-only", () => {
    const searchScopeCopy = [
      strings.emptyState.body,
      strings.noResults.body("Fixture place"),
      strings.search.placeholder,
    ];

    for (const copy of searchScopeCopy) {
      expect(copy).toMatch(/\bcity\b/i);
      expect(copy).toMatch(/\btown\b/i);
      expect(copy).toMatch(/\bvillage\b/i);
      expect(copy).not.toMatch(/\b(?:street\s+)?addresses?\b|\bpostcodes?\b|\blandmarks?\b/i);
    }
  });
});
