// @vitest-environment node

import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

describe("local Candidate measurement harness", () => {
  const source = readFileSync(
    resolve(process.cwd(), "scripts/measure-local-candidate-search.mjs"),
    "utf8",
  );

  it("serves only fixed script and worker URLs under a strict CSP", () => {
    expect(source).toContain("<script type=module src=/measurement-harness.js></script>");
    expect(source).toContain("new Worker('/search.worker.js',{type:'module'})");
    expect(source).toContain('request.url === "/search.worker.js"');
    expect(source).toContain(
      "default-src 'self'; script-src 'self'; worker-src 'self'; connect-src 'self'",
    );
    expect(source).not.toContain('new Worker(\'/assets/" + workerName');
  });

  it("routes production measurements through the target-owned evidence gate", () => {
    expect(source).toContain('loadPerformanceInputs(candidateRoot, querySetPath)');
    expect(source).toContain('page.on("request"');
    expect(source).toContain('search !== "" || !allowedPaths.has(path)');
    expect(source).toContain('STARTUP_TARGET_MILLISECONDS');
    expect(source).toContain('QUERY_TARGET_MILLISECONDS');
    expect(source).toContain('finalizePerformanceReport({');
    expect(source).toContain('publishPerformanceReport(outputPath, bytes)');
    expect(source).not.toContain("query:item.query});fetch");
  });
});
