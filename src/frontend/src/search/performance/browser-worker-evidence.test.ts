// @vitest-environment node

import { createHash } from "node:crypto";
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { afterAll, beforeAll, describe, expect, it } from "vitest";

import { buildBrowserSearchShards } from "../shards/browser-shards";
import {
  measureBrowserWorkerPerformance,
  readAndValidateBrowserWorkerPerformanceReport,
  writePerformanceReport,
} from "./browser-worker-evidence";
import type {
  BrowserWorkerPerformanceReport,
  PerformanceOptions,
} from "./browser-worker-evidence";

const projection = resolve(process.cwd(), "src/search/shards/fixtures/projection.synthetic.ndjson");
let root: string;
let shardDirectory: string;
let querySetPath: string;
let options: PerformanceOptions;
let measured: BrowserWorkerPerformanceReport;

function canonicalForTest(value: unknown): string {
  if (value === null || typeof value === "boolean" || typeof value === "string"
      || typeof value === "number") return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map(canonicalForTest).join(",")}]`;
  const entries = Object.entries(value as Record<string, unknown>).sort(([left], [right]) =>
    left < right ? -1 : left > right ? 1 : 0
  );
  return `{${entries.map(([key, item]) =>
    `${JSON.stringify(key)}:${canonicalForTest(item)}`).join(",")}}`;
}

function recomputeIdentity(report: BrowserWorkerPerformanceReport): void {
  const unsigned = Object.fromEntries(
    Object.entries(report).filter(([key]) => key !== "deterministicIdentity")
  );
  report.deterministicIdentity = createHash("sha256")
    .update(`${canonicalForTest(unsigned)}\n`).digest("hex");
}

describe("receipt-bound settlement browser worker performance evidence", () => {
  beforeAll(async () => {
    root = mkdtempSync(join(tmpdir(), "searise-worker-evidence-test-"));
    shardDirectory = join(root, "shards");
    mkdirSync(shardDirectory, { mode: 0o700 });
    buildBrowserSearchShards(projection, shardDirectory);
    querySetPath = join(root, "queries.json");
    writeFileSync(
      querySetPath,
      '{"corpusScale":"synthetic-fixture","dataProvenanceClass":"synthetic-fixture",'
        + '"queries":[{"id":"alternate","query":"alpha alt"},{"id":"missing","query":"missing"}],'
        + '"schemaVersion":1}\n',
    );
    options = {
      projectionPath: projection,
      shardDirectory,
      querySetPath,
      buildSamples: 1,
      initializationSamples: 2,
      querySamples: 2,
      thresholds: {
        buildP95Milliseconds: 60_000,
        initializationP95Milliseconds: 60_000,
        queryP95Milliseconds: 60_000,
        peakWorkerMemoryBytes: 4_000_000_000,
      },
      generatedAt: "2026-08-12T06:00:00.000Z",
    };
    measured = await measureBrowserWorkerPerformance(options);
  }, 60_000);

  afterAll(() => rmSync(root, { recursive: true, force: false }));

  it("binds exact compressed and raw shard sizes, records, provenance, and observations", () => {
    expect(measured).toMatchObject({
      schemaVersion: "settlement-browser-worker-performance-v1",
      executionOutcome: "pass",
      operatorThresholdOutcome: "pass",
      acceptedBrowserBudgetOutcome: "not-measured",
      provenance: {
        dataProvenanceClass: "synthetic-fixture",
        corpusScale: "synthetic-fixture",
      },
      claims: {
        browserReferenceClaim: false,
        engineSelectionClaim: false,
        productionClaim: false,
        publicationClaim: false,
        scientificApprovalClaim: false,
      },
      profile: { execution: { browserRuntimeMeasured: false } },
      interpretation: {
        exactReceiptAndShardBytesMeasured: true,
        productionInputFormatCompatible: true,
        browserOrMobilePerformanceMeasured: false,
        completeAcceptedBudgetsMeasured: false,
      },
    });
    expect(measured.artifacts.shards.map((item) => item.recordCount)).toEqual([2, 2]);
    expect(measured.artifacts.shards.every((item) =>
      item.rawByteSize > item.compressedByteSize && /^[0-9a-f]{64}$/.test(item.compressedSha256)
    )).toBe(true);
    expect(measured.artifacts.uniqueRecordCount).toBe(3);
    expect(measured.querySet).not.toHaveProperty("queries");
    expect(measured.interpretation).not.toHaveProperty("productionInputCompatible");
    expect(measured.measurements.build.distribution.sampleCount).toBe(1);
    expect(measured.measurements.initialization.distribution.sampleCount).toBe(2);
    expect(measured.measurements.query.distribution.sampleCount).toBe(4);
    expect(measured.measurements.workerMemory.peakObservedWorkerBytes).toBeGreaterThan(0);
  });

  it("rejects a replaced deterministic result identity after report reidentification", () => {
    const tampered = structuredClone(measured);
    tampered.querySet.resultCountsSha256 = "0".repeat(64);
    recomputeIdentity(tampered);
    const reportPath = join(root, "tampered-result-counts.json");
    writePerformanceReport(reportPath, tampered);
    expect(() => readAndValidateBrowserWorkerPerformanceReport(reportPath, options))
      .toThrow(/query-set binding differs/);
  });

  it("round-trips a canonical report and rejects browser or production claim mutations", () => {
    const reportPath = join(root, "report.json");
    writePerformanceReport(reportPath, measured);
    expect(readAndValidateBrowserWorkerPerformanceReport(reportPath, options).deterministicIdentity)
      .toBe(measured.deterministicIdentity);

    for (const mutation of ["production", "accepted-browser-budget"] as const) {
      const tampered = structuredClone(measured) as Omit<
        BrowserWorkerPerformanceReport, "acceptedBrowserBudgetOutcome"
      > & { acceptedBrowserBudgetOutcome: string };
      if (mutation === "production") {
        (tampered.claims as { productionClaim: boolean }).productionClaim = true;
      } else {
        tampered.acceptedBrowserBudgetOutcome = "pass";
      }
      const tamperedPath = join(root, `tampered-${mutation}.json`);
      writePerformanceReport(tamperedPath, tampered as BrowserWorkerPerformanceReport);
      expect(() => readAndValidateBrowserWorkerPerformanceReport(tamperedPath, options))
        .toThrow(mutation === "production" ? /claims differ/ : /envelope differs/);
    }
  });

  it("reports absent operator thresholds explicitly as not measured", async () => {
    const report = await measureBrowserWorkerPerformance({
      ...options,
      initializationSamples: 1,
      querySamples: 1,
      thresholds: {
        buildP95Milliseconds: null,
        initializationP95Milliseconds: null,
        queryP95Milliseconds: null,
        peakWorkerMemoryBytes: null,
      },
    });
    expect(report.operatorThresholdOutcome).toBe("not-measured");
    expect(report.acceptedBrowserBudgetOutcome).toBe("not-measured");
    expect(Object.values(report.measurements).map(({ budget }) => budget.outcome))
      .toEqual(["not-measured", "not-measured", "not-measured", "not-measured"]);
    expect(report.interpretation.completeAcceptedBudgetsMeasured).toBe(false);
  }, 60_000);
});
