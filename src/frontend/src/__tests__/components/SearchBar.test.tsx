import { describe, it, expect, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import SearchBar from "@/app/components/search/SearchBar";
import { useAppStore } from "@/lib/store/appStore";
import { strings } from "@/lib/i18n/en";

function renderSearchBar() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <SearchBar />
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
    renderSearchBar();
    await userEvent.click(
      screen.getByRole("button", { name: strings.search.submitLabel })
    );
    expect(useAppStore.getState().appPhase.phase).toBe("idle");
  });

  it("has maxLength 200 on input", () => {
    renderSearchBar();
    const input = screen.getByPlaceholderText(strings.search.placeholder);
    expect(input).toHaveAttribute("maxLength", "200");
  });
});
