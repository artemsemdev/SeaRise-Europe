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

  it("keeps shell search text local and labels unfinished behavior", async () => {
    const user = userEvent.setup();
    render(<App />);

    await user.type(screen.getByRole("textbox", { name: /find a city/i }), "Porto");
    await user.click(screen.getByRole("button", { name: /explore/i }));

    expect(screen.getByRole("status")).toHaveTextContent(/stayed in this browser/i);
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
});
