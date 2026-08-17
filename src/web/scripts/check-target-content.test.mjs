import { createHash } from "node:crypto";
import { Buffer } from "node:buffer";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { activeAuthoritativeDocument, scanContent, validateHistoricalAllowlist } from "./check-target-content.mjs";

function blob(content) {
  const bytes = Buffer.from(content);
  return createHash("sha1").update(`blob ${bytes.length}\0`).update(bytes).digest("hex");
}

function fixture(overrides = {}) {
  const content = "Historical binary exposure classification evidence.";
  return {
    content,
    document: {
      schemaVersion: "1.0.0",
      auditedCommit: "a".repeat(40),
      auditedTree: "b".repeat(40),
      entries: [{
        id: "historical-evidence",
        path: "docs/evidence/historical.md",
        gitBlobSha: blob(content),
        rule: "historical-five-state-evidence",
        reason: "Historical evidence only.",
        activeRuntimeAllowed: false,
        ...overrides,
      }],
    },
  };
}

describe("historical terminology allowlist", () => {
  it("accepts an exact path/blob/rule entry", () => {
    const { content, document } = fixture();
    expect(validateHistoricalAllowlist(document, () => content).has("docs/evidence/historical.md")).toBe(true);
  });

  it("rejects a changed blob", () => {
    const { document } = fixture();
    expect(() => validateHistoricalAllowlist(document, () => "mutated"))
      .toThrow(/blob mismatch/);
  });

  it.each([
    { path: "docs/evidence/nested/historical.md", rule: "historical-adr-term" },
    { path: "src/web/src/App.tsx", rule: "historical-five-state-evidence" },
    { path: "docs/evidence/historical.md", activeRuntimeAllowed: true },
  ])("rejects invalid rule or active-target scope %#", (overrides) => {
    const { content, document } = fixture(overrides);
    document.entries[0].gitBlobSha = blob(content);
    expect(() => validateHistoricalAllowlist(document, () => content)).toThrow(/invalid entry/);
  });

  it("accepts only the exact canonical Flight design-reference path", () => {
    const { content, document } = fixture({
      path: "docs/product/Mock/SeaRise-Flight.html",
      rule: "canonical-design-reference",
    });
    expect(validateHistoricalAllowlist(document, () => content)
      .has("docs/product/Mock/SeaRise-Flight.html")).toBe(true);
    document.entries[0].path = "docs/product/Mock/SeaRise-Flight-copy.html";
    expect(() => validateHistoricalAllowlist(document, () => content)).toThrow(/invalid entry/);
  });

  it("allows ADR-024 rejected identifiers only in its exact authoritative prohibition", () => {
    const path = resolve(process.cwd(), "../../docs/architecture/adr/ADR-024-ar6-regional-projection-contract.md");
    const exact = "`ProjectionAvailable` replaces both legacy binary exposure outcomes. The\nhistorical `ModeledExposureDetected` and `NoModeledExposureDetected` states do\nnot appear in a release governed by this ADR.";
    expect(scanContent(activeAuthoritativeDocument(exact, path))).toHaveLength(0);
    expect(scanContent(activeAuthoritativeDocument(exact.replace("do\nnot appear", "remain available"), path)))
      .toHaveLength(2);
  });
});
