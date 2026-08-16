import { describe, expect, it, vi } from "vitest";
import { registerServiceWorkerAfterInteractivity } from "./register-service-worker";

function environment(overrides: Record<string, unknown> = {}) {
  const register = vi.fn().mockResolvedValue({});
  const listeners: Array<() => void> = [];
  const idle: Array<() => void> = [];
  return {
    register,
    listeners,
    idle,
    value: {
      production: true,
      releaseDisposition: "synthetic-fixture" as const,
      serviceWorker: { register },
      readyState: "loading" as DocumentReadyState,
      addLoadListener: (listener: () => void) => listeners.push(listener),
      requestIdle: (listener: () => void) => idle.push(listener),
      ...overrides,
    },
  };
}

describe("service worker registration", () => {
  it.each([
    [{ releaseDisposition: "private-engineering" }, "refused-private-engineering"],
    [{ production: false }, "disabled-development"],
    [{ serviceWorker: undefined }, "unsupported"],
  ] as const)("refuses ineligible environments before scheduling", (overrides, expected) => {
    const test = environment(overrides);
    expect(registerServiceWorkerAfterInteractivity(test.value)).toBe(expected);
    expect(test.listeners).toEqual([]);
    expect(test.register).not.toHaveBeenCalled();
  });

  it("waits for load and idle before exact root-scope registration", async () => {
    const test = environment();
    expect(registerServiceWorkerAfterInteractivity(test.value)).toBe("scheduled");
    expect(test.register).not.toHaveBeenCalled();
    test.listeners[0]();
    expect(test.register).not.toHaveBeenCalled();
    test.idle[0]();
    expect(test.register).toHaveBeenCalledWith("/service-worker.js", {
      scope: "/",
      type: "module",
      updateViaCache: "none",
    });
    await Promise.resolve();
  });

  it("registers from idle after an already complete document and contains failures", async () => {
    const test = environment({ readyState: "complete" });
    test.register.mockRejectedValueOnce(new TypeError("blocked"));
    expect(registerServiceWorkerAfterInteractivity(test.value)).toBe("scheduled");
    expect(test.listeners).toEqual([]);
    test.idle[0]();
    await Promise.resolve();
    await Promise.resolve();
  });
});
