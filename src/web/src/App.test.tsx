import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import fixture from "../../../contracts/release/v1/fixtures/release/searise-europe-v1.0.0-20260810-c096aeab4e09/manifest.json";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";

beforeEach(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () =>
      new Response(JSON.stringify(fixture), { headers: { "content-type": "application/json" } }),
    ),
  );
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  window.history.replaceState({}, "", "/");
});

describe("static application shell", () => {
  it("renders an honest fixture landing page with semantic navigation", () => {
    render(<App />);

    expect(screen.getByRole("heading", { level: 1, name: /take me there/i })).toBeVisible();
    expect(screen.getByText(/synthetic fixture · illustrative only/i)).toBeVisible();
    expect(screen.getByRole("navigation", { name: /primary/i })).toBeVisible();
    expect(screen.getByRole("link", { name: /skip to content/i })).toHaveAttribute("href", "#main");
  });

  it("keeps settlement query text local", async () => {
    const user = userEvent.setup();
    render(<App />);

    const input = await screen.findByRole("combobox", { name: /find a city/i });
    await user.type(input, "Porto");

    expect(screen.getByText(/your text stays in this browser/i)).toBeVisible();
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(JSON.stringify(vi.mocked(fetch).mock.calls)).not.toContain("Porto");
  });

  it("loads the architecture route as a separate lazy surface", async () => {
    window.history.replaceState({}, "", "/about/architecture/");
    render(<App />);

    expect(
      await screen.findByRole("heading", { level: 1, name: /static-first, release-scoped/i }),
    ).toBeVisible();
    expect(screen.getByText(/no application backend, database, tile server/i)).toBeVisible();
  });

  it("validates the pinned fixture and reports all nine combinations", async () => {
    render(<App />);
    expect(await screen.findByText(/release contract ready · 9 exact combinations/i)).toBeVisible();
    expect(fetch).toHaveBeenCalledWith(
      expect.objectContaining({ pathname: expect.stringContaining(`/releases/${fixture.dataReleaseId}/manifest.json`) }),
      expect.objectContaining({ credentials: "omit" }),
    );
  });

  it("bounds manual retries without substituting another release", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("", { status: 503 })));
    const user = userEvent.setup();
    render(<App />);

    await user.click(await screen.findByRole("button", { name: /retry pinned release/i }));
    await user.click(await screen.findByRole("button", { name: /retry pinned release/i }));

    expect(await screen.findByText(/retry limit reached/i)).toBeVisible();
    expect(screen.queryByRole("button", { name: /retry pinned release/i })).not.toBeInTheDocument();
  });

  it("loads the visual map surface only after explicit user intent", async () => {
    const user = userEvent.setup();
    render(<App />);

    expect(await screen.findByRole("button", { name: /open static visualization/i })).toBeVisible();
    expect(screen.queryByRole("heading", { name: /explore the source grid/i })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /open static visualization/i }));
    expect(await screen.findByRole("heading", { name: /explore the source grid/i })).toBeVisible();
    expect(screen.getByLabelText("Map text alternative")).toHaveTextContent(
      "projection-ssp2-45-2050-pmtiles",
    );
  });
});
