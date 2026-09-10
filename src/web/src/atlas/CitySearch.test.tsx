import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { CitySearch } from "./CitySearch";
import { fakeDataSource } from "./ui-test-data";
import { SYNTHETIC_ATLAS_PLACES } from "./synthetic-fixture";
import type { AtlasPlaceSearchV1 } from "./browser-data-contract";

beforeEach(() => Object.defineProperty(Element.prototype, "scrollIntoView", { configurable: true, value: vi.fn() }));

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  delete (Element.prototype as Partial<Element>).scrollIntoView;
});

describe("atlas city search", () => {
  it("uses the injected search, selects by keyboard, and closes on Escape", async () => {
    const source = fakeDataSource();
    const onSelect = vi.fn();
    vi.stubGlobal("fetch", vi.fn(() => { throw new Error("Unexpected direct fetch"); }));
    vi.spyOn(Element.prototype, "scrollIntoView").mockImplementation(() => {});
    render(<CitySearch dataSource={source} onSelect={onSelect} />);
    const input = screen.getByRole("combobox");
    fireEvent.change(input, { target: { value: "  Venice  " } });
    const option = await screen.findByRole("option", { name: /Venice.*Italy/ });
    expect(source.search).toHaveBeenCalledWith("Venice", { signal: expect.any(AbortSignal) });
    expect(option).toHaveAttribute("aria-selected", "true");
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onSelect).toHaveBeenCalledWith(SYNTHETIC_ATLAS_PLACES[0]);
    expect(input).toHaveValue("");
    expect(input).toHaveAttribute("aria-expanded", "false");
    fireEvent.focus(input);
    fireEvent.keyDown(input, { key: "Escape" });
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
    expect(fetch).not.toHaveBeenCalled();
  });

  it("ignores a stale search and recovers from a provider failure", async () => {
    const source = fakeDataSource();
    let completeOld!: (value: AtlasPlaceSearchV1) => void;
    source.search.mockImplementationOnce(() => new Promise((resolve) => { completeOld = resolve; }));
    source.search.mockRejectedValueOnce(new Error("Unavailable"));
    vi.spyOn(Element.prototype, "scrollIntoView").mockImplementation(() => {});
    render(<CitySearch dataSource={source} onSelect={vi.fn()} />);
    const input = screen.getByRole("combobox");
    fireEvent.change(input, { target: { value: "Venice" } });
    await waitFor(() => expect(source.search).toHaveBeenCalledTimes(1));
    const oldSignal = source.search.mock.calls[0][1]?.signal;
    fireEvent.change(input, { target: { value: "Rotterdam" } });
    expect(oldSignal?.aborted).toBe(true);
    await screen.findByRole("alert");
    await act(async () => completeOld({ results: [SYNTHETIC_ATLAS_PLACES[0]], totalPlaces: 4 }));
    expect(screen.queryByRole("option")).not.toBeInTheDocument();
    fireEvent.change(input, { target: { value: "Hamburg" } });
    await screen.findByRole("option", { name: /Hamburg.*Germany/ });
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("portals results below the search and keeps them aligned as the page moves", () => {
    let resized: ResizeObserverCallback | undefined;
    vi.stubGlobal("ResizeObserver", class {
      constructor(callback: ResizeObserverCallback) { resized = callback; }
      observe() {}
      disconnect() {}
    });
    vi.stubGlobal("innerHeight", 600);

    render(<CitySearch dataSource={fakeDataSource()} onSelect={vi.fn()} />);
    const input = screen.getByRole("combobox", { name: "Find a city in Europe" });
    const search = input.closest(".atlas-search") as HTMLDivElement;
    let rect = { left: 24, bottom: 72, width: 296 };
    vi.spyOn(search, "getBoundingClientRect").mockImplementation(() => ({
      ...rect,
      x: rect.left,
      y: rect.bottom - 48,
      top: rect.bottom - 48,
      right: rect.left + rect.width,
      height: 48,
      toJSON: () => ({}),
    }));

    fireEvent.focus(input);

    const results = screen.getByRole("listbox", { name: "European places" }).closest(".search-results") as HTMLDivElement;
    expect(results.parentElement).toBe(document.body);
    expect(results).toHaveStyle({ left: "24px", top: "80px", width: "296px", maxHeight: "508px" });

    rect = { left: 40, bottom: 110, width: 260 };
    act(() => window.dispatchEvent(new Event("scroll")));
    expect(results).toHaveStyle({ left: "40px", top: "118px", width: "260px", maxHeight: "470px" });

    act(() => resized?.([], {} as ResizeObserver));
    expect(search.getBoundingClientRect).toHaveBeenCalled();

    fireEvent.blur(input, { relatedTarget: results });
    expect(input).toHaveAttribute("aria-expanded", "true");

    const outside = document.body.appendChild(document.createElement("button"));
    fireEvent.blur(input, { relatedTarget: outside });
    expect(input).toHaveAttribute("aria-expanded", "false");
    outside.remove();
  });
});
