// @vitest-environment node

import { createHash } from "node:crypto";
import childProcess from "node:child_process";
import {
  mkdirSync,
  mkdtempSync,
  readFileSync,
  readdirSync,
  rmSync,
  statSync,
  writeFileSync,
} from "node:fs";
import { syncBuiltinESMExports } from "node:module";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { brotliDecompressSync } from "node:zlib";
import { afterAll, beforeAll, describe, expect, it } from "vitest";

import {
  SHARD_FORMAT_VERSION,
  SHARD_FILENAMES,
  SHARD_RECEIPT_FILENAME,
  buildBrowserSearchShards,
} from "../shards/browser-shards";
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
const shardFixtureRoot = resolve(process.cwd(), "src/search/shards/fixtures");
const spatialDatabase = join(shardFixtureRoot, "spatial.synthetic.duckdb");
const spatialReceipt = join(shardFixtureRoot, "spatial-receipt.synthetic.json");
const projectionAuthority = join(shardFixtureRoot, "projection-authority.synthetic.json");
const dataReleaseId = "searise-europe-v1.0.0-20260812-0123456789ab";
const usesV4Shards = String(SHARD_FORMAT_VERSION) === "settlement-browser-search-shard-v2";
const publishedFixtureRoot = resolve(process.cwd(), "src/search/performance/fixtures");
const publishedV3Projection = join(publishedFixtureRoot, "projection.v3.synthetic.ndjson");
const publishedFixtureOptions: PerformanceOptions = {
  projectionPath: publishedV3Projection,
  shardDirectory: join(publishedFixtureRoot, "browser-shards"),
  querySetPath: join(publishedFixtureRoot, "performance-queries.synthetic.json"),
  buildSamples: 1,
  initializationSamples: 3,
  querySamples: 3,
  thresholds: {
    buildP95Milliseconds: null,
    initializationP95Milliseconds: null,
    queryP95Milliseconds: null,
    peakWorkerMemoryBytes: null,
  },
};
let root: string;
let shardDirectory: string;
let querySetPath: string;
let options: PerformanceOptions;
let measured: BrowserWorkerPerformanceReport;
const originalSpawnSync = childProcess.spawnSync;

type BuildShards = {
  (projectionPath: string, outputDirectory: string): unknown;
  (
    projectionPath: string,
    spatialDatabasePath: string,
    spatialReceiptPath: string,
    validationWorkDirectory: string,
    releaseId: string,
    outputDirectory: string,
  ): unknown;
};

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

function v4Options(): Partial<PerformanceOptions> {
  return usesV4Shards ? {
    spatialDatabasePath: spatialDatabase,
    spatialReceiptPath: spatialReceipt,
    validationWorkDirectory: shardFixtureRoot,
    dataReleaseId,
  } : {};
}

function buildFixture(output: string): void {
  const build = buildBrowserSearchShards as unknown as BuildShards;
  if (usesV4Shards) {
    build(
      projection,
      spatialDatabase,
      spatialReceipt,
      shardFixtureRoot,
      dataReleaseId,
      output,
    );
  } else {
    build(projection, output);
  }
}

function validatePublishedV3Bytes(): BrowserWorkerPerformanceReport {
  const reportBytes = readFileSync(
    join(publishedFixtureRoot, "browser-worker-performance.synthetic.json")
  );
  const report = JSON.parse(reportBytes.toString("utf8")) as BrowserWorkerPerformanceReport;
  expect(reportBytes.toString("utf8")).toBe(`${canonicalForTest(report)}\n`);
  const unsigned = Object.fromEntries(
    Object.entries(report).filter(([key]) => key !== "deterministicIdentity")
  );
  expect(createHash("sha256").update(`${canonicalForTest(unsigned)}\n`).digest("hex"))
    .toBe(report.deterministicIdentity);
  const queryBytes = readFileSync(publishedFixtureOptions.querySetPath);
  const queries = JSON.parse(queryBytes.toString("utf8"));
  expect({
    byteSize: queryBytes.length,
    sha256: createHash("sha256").update(queryBytes).digest("hex"),
    queryCount: queries.queries.length,
  }).toEqual({
    byteSize: report.querySet.byteSize,
    sha256: report.querySet.sha256,
    queryCount: report.querySet.queryCount,
  });
  const projectionBytes = readFileSync(publishedV3Projection);
  const projectionLines = projectionBytes.toString("utf8").trimEnd().split("\n")
    .map((line) => JSON.parse(line));
  const header = projectionLines[0];
  const footer = projectionLines.at(-1);
  const source = {
    projectionDeterministicIdentity: footer.deterministicIdentity,
    projectionDocumentsSha256: footer.documentsSha256,
    projectionSchemaVersion: header.schemaVersion,
    projectionSha256: createHash("sha256").update(projectionBytes).digest("hex"),
    ...header.source,
  };
  const receipt = readFileSync(join(
    publishedFixtureOptions.shardDirectory,
    SHARD_RECEIPT_FILENAME,
  ));
  const receiptDocument = JSON.parse(receipt.toString("utf8"));
  expect({
    byteSize: receipt.length,
    sha256: createHash("sha256").update(receipt).digest("hex"),
  }).toEqual({
    byteSize: report.artifacts.receipt.byteSize,
    sha256: report.artifacts.receipt.sha256,
  });
  for (const shard of report.artifacts.shards) {
    const bytes = readFileSync(join(
      publishedFixtureOptions.shardDirectory,
      SHARD_FILENAMES[shard.shardId],
    ));
    const document = JSON.parse(brotliDecompressSync(bytes).toString("utf8"));
    const receiptShard = receiptDocument.shards.find(
      (item: { shardId: string }) => item.shardId === shard.shardId
    );
    expect({
      compressedByteSize: bytes.length,
      compressedSha256: createHash("sha256").update(bytes).digest("hex"),
      rawByteSize: brotliDecompressSync(bytes).length,
      recordCount: document.recordCount,
      receiptByteSize: receiptShard.byteSize,
      receiptSha256: receiptShard.sha256,
      source: document.source,
    }).toEqual({
      compressedByteSize: shard.compressedByteSize,
      compressedSha256: shard.compressedSha256,
      rawByteSize: shard.rawByteSize,
      recordCount: shard.recordCount,
      receiptByteSize: shard.compressedByteSize,
      receiptSha256: shard.compressedSha256,
      source,
    });
  }
  return report;
}

describe("receipt-bound settlement browser worker performance evidence", () => {
  it("validates the published representative synthetic worker fixture without budget claims", () => {
    const exactV3 = validatePublishedV3Bytes();
    const report = usesV4Shards ? exactV3 : readAndValidateBrowserWorkerPerformanceReport(
      join(publishedFixtureRoot, "browser-worker-performance.synthetic.json"),
      publishedFixtureOptions,
    );
    expect(report.provenance).toEqual({
      dataProvenanceClass: "synthetic-fixture",
      corpusScale: "synthetic-fixture",
    });
    expect(report.acceptedBrowserBudgetOutcome).toBe("not-measured");
    expect(report.operatorThresholdOutcome).toBe("not-measured");
    expect(report.claims).toEqual({
      browserReferenceClaim: false,
      engineSelectionClaim: false,
      ownerApprovalClaim: false,
      productionClaim: false,
      publicationClaim: false,
      scientificApprovalClaim: false,
    });
    expect(report.artifacts.totalShardRecords).toBe(4);
    expect(report.artifacts.uniqueRecordCount).toBe(3);
  });

  beforeAll(async () => {
    (childProcess as unknown as Record<string, unknown>).spawnSync = (
      command: string,
      args: string[] = [],
      spawnOptions: Record<string, unknown> = {},
    ) => {
      if (usesV4Shards && command === "python3"
          && args[0]?.endsWith("validate_settlement_search_projection.py")) {
        return {
          pid: 1,
          output: [],
          status: 0,
          signal: null,
          error: undefined,
          stdout: readFileSync(projectionAuthority),
          stderr: Buffer.alloc(0),
        };
      }
      return originalSpawnSync(command, args, spawnOptions as never);
    };
    syncBuiltinESMExports();
    root = mkdtempSync(join(tmpdir(), "searise-worker-evidence-test-"));
    shardDirectory = join(root, "shards");
    mkdirSync(shardDirectory, { mode: 0o700 });
    buildFixture(shardDirectory);
    querySetPath = join(root, "queries.json");
    writeFileSync(
      querySetPath,
      '{"corpusScale":"synthetic-fixture","dataProvenanceClass":"synthetic-fixture",'
        + '"queries":[{"id":"alternate","query":"alpha alt"},{"id":"missing","query":"missing"}],'
        + '"schemaVersion":1}\n',
    );
    options = {
      projectionPath: projection,
      ...v4Options(),
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

  afterAll(() => {
    (childProcess as unknown as Record<string, unknown>).spawnSync = originalSpawnSync;
    syncBuiltinESMExports();
    rmSync(root, { recursive: true, force: false });
  });

  it("requires authority inputs to match the active shard contract", () => {
    const mismatched = structuredClone(options);
    if (usesV4Shards) delete mismatched.spatialReceiptPath;
    else mismatched.spatialReceiptPath = spatialReceipt;
    expect(() => readAndValidateBrowserWorkerPerformanceReport(
      join(publishedFixtureRoot, "browser-worker-performance.synthetic.json"),
      mismatched,
    )).toThrow(/v[34] performance evidence/);
  });

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
    expect(statSync(reportPath).mode & 0o777).toBe(0o400);
    expect(readdirSync(root).filter((name) => name.startsWith(".worker-performance-")))
      .toEqual([]);
    expect(readAndValidateBrowserWorkerPerformanceReport(reportPath, options).deterministicIdentity)
      .toBe(measured.deterministicIdentity);
    expect(() => writePerformanceReport(reportPath, measured)).toThrow(/overwrite is refused/);

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
