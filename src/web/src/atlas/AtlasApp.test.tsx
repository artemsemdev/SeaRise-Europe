import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { EuropeMapProps } from "./EuropeMap";
import AtlasApp from "./AtlasApp";
import { fakeDataSource } from "./ui-test-data";

const map = vi.hoisted(() => ({ props: null as EuropeMapProps | null }));
vi.mock("./EuropeMap", async () => {
  const { useEffect } = await import("react");
  return { EuropeMap: function EuropeMap(props: EuropeMapProps) {
    map.props = props;
    const { onStatus } = props;
    useEffect(() => onStatus({ loading: false, error: null, validPixels: 10, floodPixels: 4 }), [onStatus]);
    return <div aria-label="Test map controls">
      <button onClick={props.onShare}>Share map view</button>
      <button onClick={props.onOverview}>Map overview</button>
      <button onClick={() => props.onInspect?.([12.3155, 45.4408])}>Inspect map point</button>
    </div>;
  } };
});

beforeEach(() => {
  window.history.replaceState(null, "", "/");
  map.props = null;
  Object.defineProperty(Element.prototype, "scrollTo", { configurable: true, value: vi.fn() });
  Object.defineProperty(Element.prototype, "scrollIntoView", { configurable: true, value: vi.fn() });
  Object.defineProperty(HTMLDialogElement.prototype, "showModal", { configurable: true, value(this: HTMLDialogElement) { this.setAttribute("open", ""); } });
  Object.defineProperty(HTMLDialogElement.prototype, "close", { configurable: true, value(this: HTMLDialogElement) { this.removeAttribute("open"); } });
  Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText: vi.fn().mockResolvedValue(undefined) } });
  vi.stubGlobal("fetch", vi.fn(() => { throw new Error("Unexpected direct fetch"); }));
});
afterEach(() => {
  cleanup(); vi.useRealTimers(); vi.restoreAllMocks(); vi.unstubAllGlobals();
  delete (Element.prototype as Partial<Element>).scrollTo;
  delete (Element.prototype as Partial<Element>).scrollIntoView;
  delete (HTMLDialogElement.prototype as Partial<HTMLDialogElement>).showModal;
  delete (HTMLDialogElement.prototype as Partial<HTMLDialogElement>).close;
  Reflect.deleteProperty(navigator, "clipboard");
});

async function ready(source = fakeDataSource()) {
  render(<AtlasApp dataSource={source} />);
  await waitFor(() => expect(screen.getByRole("button", { name: "Play timeline" })).toBeEnabled());
  return source;
}

describe("provider-backed coastal atlas experience", () => {
  it.each(["synthetic-fixture", "real-local"] as const)("discloses the %s edition and injects the same source into the map", async (edition) => {
    const source = await ready(fakeDataSource(edition));
    expect(screen.getByRole("heading", { name: "Europe", level: 1 })).toBeInTheDocument();
    expect(map.props?.dataSource).toBe(source);
    expect(map.props?.visible).toBe(true);
    const header = document.querySelector(".atlas-header")!;
    expect(header.textContent?.includes("Illustrative fixture")).toBe(edition === "synthetic-fixture");
    expect(screen.getByTestId("atlas-map")).toHaveAttribute("data-model", edition === "synthetic-fixture" ? "illustrative-fixture" : "coclico");
    expect(fetch).not.toHaveBeenCalled();
  });

  it("resolves a coast shortcut, preserves the selected view while comparing, and changes defenses", async () => {
    const source = await ready();
    fireEvent.click(screen.getByRole("button", { name: /Venice.*Italy/ }));
    await screen.findByRole("heading", { name: "Venice", level: 1 });
    expect(source.getPlace).toHaveBeenCalledWith("venice", { signal: expect.any(AbortSignal) });
    expect(source.search).toHaveBeenCalledWith("venice", { signal: expect.any(AbortSignal) });
    await screen.findByText("0.4 m depth", { selector: ".point-summary strong" });
    act(() => map.props?.onCameraChange?.({ lng: 12.3, lat: 45.4, zoom: 10 }));
    fireEvent.click(screen.getByRole("button", { name: "Compare 2030 & 2100" }));
    expect(screen.getByTestId("atlas-map")).toHaveAttribute("data-year", "2100");
    expect(screen.queryByRole("button", { name: "2050" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "2030" }));
    expect(screen.getByRole("slider", { name: "Projection year" })).toHaveAttribute("aria-valuetext", "2030");
    expect(new URLSearchParams(window.location.search).get("view")).toBe("12.300000,45.400000,10.0000");
    fireEvent.click(screen.getByRole("button", { name: "High protection" }));
    await waitFor(() => expect(source.inspect).toHaveBeenLastCalledWith(expect.objectContaining({ protection: "protected" })));
    expect(map.props?.protection).toBe("protected");
    fireEvent.click(screen.getByRole("button", { name: "Hide flood layer" }));
    expect(map.props?.visible).toBe(false);
    expect(new URLSearchParams(window.location.search).get("flooding")).toBe("off");
  });

  it("restores a shared city, camera, point, and browser history without resetting the map view", async () => {
    window.history.replaceState(null, "", "/?city=fixture:venice&year=2100&defenses=protected&view=12.25,45.43,10&point=12.2486111,45.4511111");
    const source = await ready();
    await screen.findByRole("heading", { name: "Venice", level: 1 });
    expect(map.props).toMatchObject({ initialCamera: { lng: 12.25, lat: 45.43, zoom: 10 }, restoreCity: true, inspectionPoint: [12.2486111, 45.4511111] });
    fireEvent.click(screen.getByRole("button", { name: "Share map view" }));
    await screen.findByText("Link copied. Share this view.");
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith(window.location.href);
    act(() => {
      window.history.pushState(null, "", "/?city=fixture:rotterdam&year=2030&view=4.4,51.9,9");
      window.dispatchEvent(new PopStateEvent("popstate"));
    });
    await screen.findByRole("heading", { name: "Rotterdam", level: 1 });
    expect(map.props).toMatchObject({ year: 2030, initialCamera: { lng: 4.4, lat: 51.9, zoom: 9 }, restoreCity: true });
    expect(source.getPlace).toHaveBeenLastCalledWith("fixture:rotterdam", { signal: expect.any(AbortSignal) });
  });

  it("retries a catalog failure and offers the browser address when clipboard access fails", async () => {
    const source = fakeDataSource();
    source.getCatalog.mockRejectedValueOnce(new Error("The atlas catalog is unavailable."));
    render(<AtlasApp dataSource={source} />);
    await screen.findByRole("alert");
    expect(screen.getByRole("button", { name: "Play timeline" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Play timeline" })).toBeEnabled());
    expect(source.getCatalog).toHaveBeenCalledTimes(2);
    vi.mocked(navigator.clipboard.writeText).mockRejectedValueOnce(new Error("Clipboard denied"));
    fireEvent.click(screen.getByRole("button", { name: "Share map view" }));
    await screen.findByText("Copy the address in your browser to share this view.");
  });

  it("opens point results, expands mobile details, and returns to the Europe overview", async () => {
    await ready();
    fireEvent.click(screen.getByRole("button", { name: "Inspect map point" }));
    await screen.findByText("0.4 m depth", { selector: ".point-summary strong" });
    const details = screen.getByRole("button", { name: "More detail" });
    fireEvent.click(details);
    expect(details).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByTestId("exploration-panel")).toHaveClass("is-expanded");
    fireEvent.click(screen.getByRole("button", { name: "Close point result" }));
    expect(screen.queryByTestId("point-inspection")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Map overview" }));
    expect(map.props?.inspectionPoint).toBeNull();
    expect(new URLSearchParams(window.location.search).has("point")).toBe(false);
  });

  it("plays only the three calculated years and stops when comparison begins", async () => {
    await ready();
    vi.useFakeTimers();
    fireEvent.click(screen.getByRole("button", { name: "Play timeline" }));
    act(() => vi.advanceTimersByTime(3000));
    expect(map.props?.year).toBe(2100);
    act(() => vi.advanceTimersByTime(3000));
    expect(map.props?.year).toBe(2030);
    fireEvent.click(screen.getByRole("button", { name: "Compare 2030 & 2100" }));
    act(() => vi.advanceTimersByTime(6000));
    expect(map.props?.year).toBe(2100);
    expect(screen.queryByRole("button", { name: "Pause timeline" })).not.toBeInTheDocument();
  });

  it("explains fixture limitations in the methods dialog and supports closing it", async () => {
    await ready();
    fireEvent.click(screen.getByRole("button", { name: "Fixture · Data & methods" }));
    const dialog = screen.getByRole("dialog", { name: "About the data" });
    expect(within(dialog).getByRole("heading", { name: "Illustrative fixture" })).toBeInTheDocument();
    expect(dialog).toHaveTextContent("not CoCliCo observations or simulations");
    expect(within(dialog).getByRole("link", { name: /Read about the fixture/ })).toHaveAttribute("href", "https://github.com/artemsemdev/SeaRise-Europe/issues/495");
    fireEvent.click(within(dialog).getByRole("button", { name: "Close map information" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});
