import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it } from "vitest";
import App from "./App";

afterEach(() => {
  cleanup();
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
});
