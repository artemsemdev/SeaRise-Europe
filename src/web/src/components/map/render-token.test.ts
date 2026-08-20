import { describe, expect, it } from "vitest";
import { RenderToken } from "./render-token";

describe("map render token", () => {
  it("rejects stale style/source callbacks after rapid selection changes", () => {
    const token = new RenderToken();
    const first = token.next();
    const second = token.next();
    const third = token.next();

    expect(token.isCurrent(first)).toBe(false);
    expect(token.isCurrent(second)).toBe(false);
    expect(token.isCurrent(third)).toBe(true);
    token.invalidate();
    expect(token.isCurrent(third)).toBe(false);
  });
});
