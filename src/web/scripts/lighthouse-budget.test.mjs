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

describe("owner-approved private local demo exception", () => {
  const demoPolicy = JSON.parse(readFileSync(resolve("../../tools/static-quality/atlas-local-demo-performance-waiver.json")));
  const demo = (values = [0.54, 0.56, 0.54]) => ({ ...input(values),
    policy: globalThis.structuredClone(demoPolicy), now: Date.parse("2026-10-02T12:00:00Z"),
  });
  it("accepts measured local-demo evidence while retaining every raw 90 failure", () => {
    const value = demo();
    const result = evaluateLighthouseBudget(value);
    expect(result).toMatchObject({ accepted: true, waiverApplied: true, performance90Passed: false,
      target: 0.9, medianScores: { performance: 0.54 }, waiver: demoPolicy });
    expect(result.failedBudgets).toEqual(["median performance", "run 1 performance", "run 2 performance", "run 3 performance"]);
    expect(result.warning).toMatch(/local-demo.*#518\/#519/u);
    expect(value.runs.map(({ scores }) => scores.performance)).toEqual([0.54, 0.56, 0.54]);
  });
  it("requires 50 in each cold run and 90 in every other category", () => {
    expect(evaluateLighthouseBudget(demo([0.5, 0.5, 0.5])).accepted).toBe(true);
    expect(evaluateLighthouseBudget(demo([0.499, 0.95, 1])).accepted).toBe(false);
    for (const category of ["accessibility", "best-practices", "seo"]) {
      const value = demo(); value.runs[0].scores[category] = 0.899;
      expect(evaluateLighthouseBudget(value).accepted).toBe(false);
    }
  });
  it("expires at the start of 16 October in Berlin without renewal", () => {
    const boundary = Date.parse("2026-10-15T22:00:00Z");
    expect(evaluateLighthouseBudget({ ...demo(), now: boundary - 1 }).accepted).toBe(true);
    for (const now of [boundary, boundary + 1, NaN]) {
      expect(() => evaluateLighthouseBudget({ ...demo(), now })).toThrow(/expired|clock/u);
    }
  });
  it("rejects broadening the approval, scope, release flags or measured authority", () => {
    for (const change of [{ owner: "someone-else" }, { schemaVersion: 2 },
      { scope: "public-release" }, { edition: "public-promoted" }, { ownerApproval: undefined },
      { ownerApproval: { ...demoPolicy.ownerApproval, channel: "external-signoff" } },
      { ownerApproval: { ...demoPolicy.ownerApproval, date: "2026-10-03" } },
      { ownerApproval: { ...demoPolicy.ownerApproval, summary: "" } },
      { issues: [65, 490] }, { sourceRun: policy.sourceRun }, { measuredPerformance: [0.5, 0.5, 0.5] },
      { minimumPerformance: 0.49 }, { target: 0.5 }, { expiresAt: "2026-10-17T00:00:00+02:00" },
      { publicPromotionAuthorized: true }, { mvpRelease: true }, { extra: true }]) {
      expect(() => evaluateLighthouseBudget({ ...demo(), policy: { ...demoPolicy, ...change } })).toThrow(/policy/u);
    }
  });
  it("cannot qualify real-local, scientific, private engineering or public identities", () => {
    for (const identity of ["real-local", "scientific", "private-engineering", "public-promoted", undefined]) {
      expect(() => evaluateLighthouseBudget({ ...demo(), edition: identity })).toThrow(/labeled/u);
      expect(() => evaluateLighthouseBudget({ ...demo(), releaseDisposition: identity })).toThrow(/labeled/u);
    }
  });
  it("rejects renderer errors, incomplete runs and invalid raw identities before the waiver", () => {
    const value = demo(); value.runs[0].renderErrors.push("WebGL failed");
    expect(() => evaluateLighthouseBudget(value)).toThrow(/render/u);
    expect(() => evaluateLighthouseBudget({ ...demo(), runs: demo().runs.slice(1) })).toThrow(/three raw/u);
    const bad = demo(); bad.runs[0].run = 2;
    expect(() => evaluateLighthouseBudget(bad)).toThrow(/identity/u);
  });
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
  it("accepts fresh raw passes after the historical waiver expires", () => {
    const value = { ...input([0.9, 0.95, 1]), now: Date.parse("2026-10-02T12:00:00Z") };
    expect(evaluateLighthouseBudget(value)).toMatchObject({
      accepted: true, waiverApplied: false, performance90Passed: true,
      failedBudgets: [], waiver: null, warning: null,
    });
  });
  it("does not require a waiver policy or waiver edition for raw passes", () => {
    for (const edition of ["synthetic-fixture", "real-local", "public-promoted"]) {
      expect(evaluateLighthouseBudget({ ...input([0.9, 0.95, 1]),
        policy: undefined, edition, releaseDisposition: edition,
      })).toMatchObject({ accepted: true, waiverApplied: false });
    }
  });
  it("still rejects expired waivers when one run misses 90 despite a passing median", () => {
    expect(() => evaluateLighthouseBudget({ ...input([0.89, 0.95, 1]),
      now: Date.parse("2026-10-02T12:00:00Z"),
    })).toThrow(/expired/);
  });
  it("checks render health and raw evidence before accepting a passing budget", () => {
    const value = input([0.9, 0.95, 1]);
    value.runs[0].renderErrors.push("WebGL failed");
    expect(() => evaluateLighthouseBudget({ ...value, policy: undefined })).toThrow(/render/);
    expect(() => evaluateLighthouseBudget({ ...input([0.9, 0.95, 1]),
      policy: undefined, runs: input([0.9, 0.95, 1]).runs.slice(1),
    })).toThrow(/three raw cold audits/);
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
