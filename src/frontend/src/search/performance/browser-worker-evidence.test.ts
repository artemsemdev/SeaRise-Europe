// @vitest-environment node

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
        productionInputCompatible: true,
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
    expect(measured.measurements.build.distribution.sampleCount).toBe(1);
    expect(measured.measurements.initialization.distribution.sampleCount).toBe(2);
    expect(measured.measurements.query.distribution.sampleCount).toBe(4);
    expect(measured.measurements.workerMemory.peakObservedWorkerBytes).toBeGreaterThan(0);
  });

  it("round-trips a canonical report and rejects a semantic claim mutation", () => {
    const reportPath = join(root, "report.json");
    writePerformanceReport(reportPath, measured);
    expect(readAndValidateBrowserWorkerPerformanceReport(reportPath, options).deterministicIdentity)
      .toBe(measured.deterministicIdentity);

    const tampered = structuredClone(measured);
    (tampered.claims as { productionClaim: boolean }).productionClaim = true;
    const tamperedPath = join(root, "tampered.json");
    writePerformanceReport(tamperedPath, tampered as BrowserWorkerPerformanceReport);
    expect(() => readAndValidateBrowserWorkerPerformanceReport(tamperedPath, options))
      .toThrow(/claims differ/);
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
