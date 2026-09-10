import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { evaluateLighthouseBudget } from "./lighthouse-budget.mjs";

const policy = JSON.parse(readFileSync(resolve("../../tools/static-quality/atlas-local-performance-waiver.json")));
const input = (values = [0.54, 0.53, 0.55]) => ({
  policy: globalThis.structuredClone(policy), now: Date.parse("2026-09-10T15:08:49Z"),
  edition: "synthetic-fixture", releaseDisposition: "synthetic-fixture",
  runs: values.map((performance, i) => ({ run: i + 1, renderErrors: [], scores: {
    performance, accessibility: 0.96, "best-practices": 1, seo: 1,
  } })),
});

describe("temporary local Atlas performance waiver", () => {
  it("preserves the Linux raw failures and reports a waiver, never a 90-point pass", () => {
    const value = input(), result = evaluateLighthouseBudget(value);
    expect(result).toMatchObject({ accepted: true, waiverApplied: true, performance90Passed: false,
      medianScores: { performance: 0.54 }, target: 0.9 });
    expect(result.failedBudgets).toEqual(["median performance", "run 1 performance", "run 2 performance", "run 3 performance"]);
    expect(value.runs.map(({ scores }) => scores.performance)).toEqual([0.54, 0.53, 0.55]);
  });
  it("keeps the default 90 target and does not apply a waiver when every run passes", () => {
    expect(evaluateLighthouseBudget(input([0.9, 0.95, 1]))).toMatchObject({ accepted: true, waiverApplied: false, performance90Passed: true });
  });
  it("requires the floor in every run, even with a passing median", () => {
    expect(evaluateLighthouseBudget(input([0.499, 0.95, 1])).accepted).toBe(false);
    expect(evaluateLighthouseBudget(input([0.5, 0.5, 0.5])).waiverApplied).toBe(true);
  });
  it.each(["accessibility", "best-practices", "seo"])("does not waive %s", (category) => {
    const value = input(); value.runs[0].scores[category] = 0.899;
    expect(evaluateLighthouseBudget(value).accepted).toBe(false);
  });
  it.each(["real-local", "private-engineering", "public-promoted", undefined])("rejects edition or disposition %s", (edition) => {
    expect(() => evaluateLighthouseBudget({ ...input(), edition })).toThrow();
    expect(() => evaluateLighthouseBudget({ ...input(), releaseDisposition: edition })).toThrow();
  });
  it("rejects missing, malformed, extended, or expired policy", () => {
    for (const bad of [undefined, {}, { ...policy, unknown: true }, { ...policy, minimumPerformance: 0.1 },
      { ...policy, owner: "" }, { ...policy, expiresAt: "2027-01-01T00:00:00Z" }, { ...policy, target: 0.5 }]) {
      expect(() => evaluateLighthouseBudget({ ...input(), policy: bad })).toThrow();
    }
    expect(() => evaluateLighthouseBudget({ ...input(), now: Date.parse(policy.expiresAt) })).toThrow(/expired/);
  });
  it("rejects renderer failures and incomplete or invalid raw evidence", () => {
    const value = input(); value.runs[0].renderErrors.push("WebGL failed");
    expect(() => evaluateLighthouseBudget(value)).toThrow(/render/);
    expect(() => evaluateLighthouseBudget({ ...input(), runs: input().runs.slice(1) })).toThrow();
    for (const score of [NaN, -1, 1.01, undefined]) {
      const bad = input(); bad.runs[0].scores.performance = score;
      expect(() => evaluateLighthouseBudget(bad)).toThrow();
    }
  });
});
