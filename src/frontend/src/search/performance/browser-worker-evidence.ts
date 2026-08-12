import { createHash } from "node:crypto";
import {
  closeSync,
  constants as fsConstants,
  fsyncSync,
  mkdirSync,
  mkdtempSync,
  openSync,
  readFileSync,
  rmSync,
  writeSync,
} from "node:fs";
import { cpus, platform, release, tmpdir, totalmem } from "node:os";
import { basename, isAbsolute, join } from "node:path";
import { performance } from "node:perf_hooks";
import { brotliDecompressSync } from "node:zlib";
import { Worker } from "node:worker_threads";

import {
  DEFAULT_SHARD_LIMITS,
  SHARD_FILENAMES,
  SHARD_RECEIPT_FILENAME,
  buildBrowserSearchShards,
  loadBrowserSearchShards,
} from "../shards/browser-shards";
import type { LoadedBrowserShardSet } from "../shards/browser-shards";

export const PERFORMANCE_REPORT_VERSION = "settlement-browser-worker-performance-v1";
export const PERFORMANCE_PROFILE_ID = "settlement-node-worker-reference-v1";

const SHARD_IDS = ["europe-core", "europe-coastal"] as const;
const OUTCOMES = new Set(["pass", "fail", "not-measured"]);
const CORPUS_SCALES = new Set(["synthetic-fixture", "real-source-sample", "production-candidate"]);
const WORKER_URL = new URL("./browser-worker-runner.ts", import.meta.url);
const WORKER_BOOTSTRAP_URL = new URL("./browser-worker-bootstrap.mjs", import.meta.url);

type ShardId = (typeof SHARD_IDS)[number];
type Outcome = "pass" | "fail" | "not-measured";
type CorpusScale = "synthetic-fixture" | "real-source-sample" | "production-candidate";

export type PerformanceThresholds = {
  buildP95Milliseconds: number | null;
  initializationP95Milliseconds: number | null;
  queryP95Milliseconds: number | null;
  peakWorkerMemoryBytes: number | null;
};

export type PerformanceOptions = {
  projectionPath: string;
  shardDirectory: string;
  querySetPath: string;
  buildSamples: number;
  initializationSamples: number;
  querySamples: number;
  thresholds: PerformanceThresholds;
  generatedAt?: string;
};

type QuerySet = {
  schemaVersion: 1;
  dataProvenanceClass: "real-source" | "synthetic-fixture";
  corpusScale: CorpusScale;
  queries: Array<{ id: string; query: string }>;
};

type Distribution = {
  observationsMilliseconds: number[];
  sampleCount: number;
  minimumMilliseconds: number;
  p50Milliseconds: number;
  p95Milliseconds: number;
  maximumMilliseconds: number;
  meanMilliseconds: number;
};

type Budget = {
  comparator: "less-than" | "less-than-or-equal";
  threshold: number | null;
  thresholdAuthority: "not-supplied" | "operator-supplied-diagnostic";
  outcome: Outcome;
};

type MemorySnapshot = {
  usedHeapBytes: number;
  externalBytes: number;
  observedWorkerBytes: number;
};

type WorkerReady = {
  kind: "ready";
  shardSha256: Record<ShardId, string>;
  memory: MemorySnapshot;
};

type WorkerQueryResult = {
  kind: "query-result";
  id: string;
  durationMilliseconds: number;
  resultCount: number;
  memory: MemorySnapshot;
};

type WorkerFailure = { kind: "failure"; message: string };
type WorkerResponse = WorkerReady | WorkerQueryResult | WorkerFailure;

export type BrowserWorkerPerformanceReport = {
  schemaVersion: typeof PERFORMANCE_REPORT_VERSION;
  generatedAt: string;
  executionOutcome: "pass";
  operatorThresholdOutcome: Outcome;
  acceptedBrowserBudgetOutcome: "not-measured";
  provenance: {
    dataProvenanceClass: "real-source" | "synthetic-fixture";
    corpusScale: CorpusScale;
  };
  claims: {
    browserReferenceClaim: false;
    engineSelectionClaim: false;
    ownerApprovalClaim: false;
    productionClaim: false;
    publicationClaim: false;
    scientificApprovalClaim: false;
  };
  profile: {
    profileId: typeof PERFORMANCE_PROFILE_ID;
    runtime: {
      node: string;
      v8: string;
      platform: string;
      release: string;
      architecture: string;
      cpu: string;
      logicalCpuCount: number;
      totalMemoryBytes: number;
    };
    execution: {
      workerRuntime: "Node worker_threads with tsx source loader";
      transfer: "structured-clone exact compressed shard bytes";
      cacheState: "warm local filesystem after receipt validation";
      network: "not used";
      memoryMetric: "V8 isolate used heap plus external bytes sampled after initialization and queries";
      browserRuntimeMeasured: false;
    };
    sampling: {
      buildSamples: number;
      initializationSamples: number;
      querySamplesPerQuery: number;
      warmupQueriesPerQuery: 1;
    };
  };
  artifacts: {
    receipt: { path: string; byteSize: number; sha256: string };
    shards: Array<{
      shardId: ShardId;
      path: string;
      compressedByteSize: number;
      compressedSha256: string;
      rawByteSize: number;
      recordCount: number;
    }>;
    totalCompressedBytes: number;
    totalRawBytes: number;
    totalShardRecords: number;
    uniqueRecordCount: number;
    observedEngine: { engineId: string; packageVersion: string; serializationVersion: string };
  };
  querySet: {
    byteSize: number;
    sha256: string;
    queryCount: number;
    resultCountsSha256: string;
  };
  measurements: {
    build: { executionOutcome: "pass"; distribution: Distribution; budget: Budget };
    initialization: { executionOutcome: "pass"; distribution: Distribution; budget: Budget };
    query: { executionOutcome: "pass"; distribution: Distribution; budget: Budget };
    workerMemory: {
      executionOutcome: "pass";
      peakObservedWorkerBytes: number;
      peakUsedHeapBytes: number;
      peakExternalBytes: number;
      sampleCount: number;
      budget: Budget;
    };
  };
  interpretation: {
    exactReceiptAndShardBytesMeasured: true;
    productionInputCompatible: true;
    browserOrMobilePerformanceMeasured: false;
    completeAcceptedBudgetsMeasured: false;
  };
  deterministicIdentity: string;
};

type EvidenceBindings = {
  loaded: LoadedBrowserShardSet;
  queryBytes: Buffer;
  querySet: QuerySet;
};

export class BrowserWorkerEvidenceError extends Error {}

function fail(message: string): never {
  throw new BrowserWorkerEvidenceError(message);
}

function exactKeys(value: unknown, keys: readonly string[]): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    && JSON.stringify(Object.keys(value).sort()) === JSON.stringify([...keys].sort());
}

function canonical(value: unknown): string {
  if (value === null || typeof value === "boolean" || typeof value === "string") {
    return JSON.stringify(value);
  }
  if (typeof value === "number") {
    if (!Number.isFinite(value)) fail("performance evidence contains a non-finite number");
    return JSON.stringify(value);
  }
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  if (typeof value === "object") {
    const entries = Object.entries(value as Record<string, unknown>).sort(([left], [right]) =>
      left < right ? -1 : left > right ? 1 : 0
    );
    return `{${entries.map(([key, item]) => `${JSON.stringify(key)}:${canonical(item)}`).join(",")}}`;
  }
  return fail("performance evidence contains a non-JSON value");
}

function digest(value: Uint8Array | string): string {
  return createHash("sha256").update(value).digest("hex");
}

function rounded(value: number): number {
  return Number(value.toFixed(6));
}

function positiveInteger(value: number, label: string): number {
  if (!Number.isSafeInteger(value) || value < 1) fail(`${label} must be a positive safe integer`);
  return value;
}

function nullableThreshold(value: number | null, label: string): number | null {
  if (value !== null && (!Number.isFinite(value) || value <= 0)) {
    fail(`${label} must be null or a positive finite number`);
  }
  return value;
}

function distribution(observations: readonly number[]): Distribution {
  if (!observations.length || observations.some((value) => !Number.isFinite(value) || value < 0)) {
    return fail("performance observations must be finite nonnegative numbers");
  }
  const values = observations.map(rounded);
  const sorted = [...values].sort((left, right) => left - right);
  const percentile = (fraction: number) => sorted[Math.ceil(sorted.length * fraction) - 1];
  return {
    observationsMilliseconds: values,
    sampleCount: values.length,
    minimumMilliseconds: sorted[0],
    p50Milliseconds: percentile(0.5),
    p95Milliseconds: percentile(0.95),
    maximumMilliseconds: sorted.at(-1)!,
    meanMilliseconds: rounded(values.reduce((sum, value) => sum + value, 0) / values.length),
  };
}

function budget(
  threshold: number | null,
  observed: number,
  comparator: Budget["comparator"] = "less-than",
): Budget {
  if (threshold === null) {
    return { comparator, threshold, thresholdAuthority: "not-supplied", outcome: "not-measured" };
  }
  const passed = comparator === "less-than" ? observed < threshold : observed <= threshold;
  return {
    comparator,
    threshold,
    thresholdAuthority: "operator-supplied-diagnostic",
    outcome: passed ? "pass" : "fail",
  };
}

function parseCanonicalJson(bytes: Buffer, label: string): unknown {
  try {
    const value: unknown = JSON.parse(bytes.toString("utf8"));
    if (bytes.toString("utf8") !== `${canonical(value)}\n`) fail(`${label} is not canonical JSON`);
    return value;
  } catch (error) {
    if (error instanceof BrowserWorkerEvidenceError) throw error;
    return fail(`${label} is not valid UTF-8 JSON`);
  }
}

function querySet(bytes: Buffer): QuerySet {
  const value = parseCanonicalJson(bytes, "performance query set");
  if (!exactKeys(value, ["schemaVersion", "dataProvenanceClass", "corpusScale", "queries"])
      || value.schemaVersion !== 1
      || !["real-source", "synthetic-fixture"].includes(value.dataProvenanceClass as string)
      || !CORPUS_SCALES.has(value.corpusScale as CorpusScale)
      || !Array.isArray(value.queries) || value.queries.length < 1 || value.queries.length > 100) {
    return fail("performance query set fields differ");
  }
  if ((value.dataProvenanceClass === "synthetic-fixture") !== (value.corpusScale === "synthetic-fixture")) {
    return fail("performance query provenance and corpus scale differ");
  }
  const identifiers = new Set<string>();
  for (const item of value.queries) {
    if (!exactKeys(item, ["id", "query"])
        || typeof item.id !== "string" || !/^[a-z0-9][a-z0-9-]{0,63}$/.test(item.id)
        || identifiers.has(item.id)
        || typeof item.query !== "string" || !item.query.trim()
        || Array.from(item.query).length > 256 || /[\u0000-\u001f\u007f-\u009f]/.test(item.query)) {
      return fail("performance query entry is invalid");
    }
    identifiers.add(item.id);
  }
  return value as unknown as QuerySet;
}

function inputBindings(options: PerformanceOptions): EvidenceBindings {
  for (const [label, path] of [
    ["projection", options.projectionPath],
    ["shard directory", options.shardDirectory],
    ["query set", options.querySetPath],
  ] as const) {
    if (!isAbsolute(path)) fail(`${label} path must be absolute`);
  }
  const loaded = loadBrowserSearchShards(options.projectionPath, options.shardDirectory);
  const queryBytes = readFileSync(options.querySetPath);
  const queries = querySet(queryBytes);
  const provenance = new Set(SHARD_IDS.map((id) => loaded.shards[id].shard.dataProvenanceClass));
  if (provenance.size !== 1 || !provenance.has(queries.dataProvenanceClass)) {
    fail("query provenance differs from the exact browser shards");
  }
  return { loaded, queryBytes, querySet: queries };
}

function exactBuildSamples(options: PerformanceOptions, expected: LoadedBrowserShardSet): number[] {
  const observations: number[] = [];
  for (let index = 0; index < options.buildSamples; index += 1) {
    const root = mkdtempSync(join(tmpdir(), "searise-settlement-search-build-"));
    const output = join(root, "output");
    mkdirSync(output, { mode: 0o700 });
    try {
      const started = performance.now();
      buildBrowserSearchShards(options.projectionPath, output);
      observations.push(performance.now() - started);
      for (const shardId of SHARD_IDS) {
        if (!readFileSync(join(output, SHARD_FILENAMES[shardId])).equals(expected.shards[shardId].bytes)) {
          fail("measured shard build differs from the receipt-gated bytes");
        }
      }
      if (!readFileSync(join(output, SHARD_RECEIPT_FILENAME)).equals(expected.receipt)) {
        fail("measured shard build receipt differs from the receipt-gated bytes");
      }
    } finally {
      rmSync(root, { recursive: true, force: false });
    }
  }
  return observations;
}

function nextMessage<T extends WorkerResponse["kind"]>(
  worker: Worker,
  kind: T,
): Promise<Extract<WorkerResponse, { kind: T }>> {
  return new Promise((resolve, reject) => {
    const message = (value: WorkerResponse) => {
      if (value.kind === "failure") {
        cleanup();
        reject(new BrowserWorkerEvidenceError(`worker measurement failed: ${value.message}`));
      } else if (value.kind === kind) {
        cleanup();
        resolve(value as Extract<WorkerResponse, { kind: T }>);
      }
    };
    const error = (cause: Error) => { cleanup(); reject(cause); };
    const exit = (code: number) => {
      cleanup();
      reject(new BrowserWorkerEvidenceError(`worker exited with ${code} before ${kind}`));
    };
    const cleanup = () => {
      worker.off("message", message);
      worker.off("error", error);
      worker.off("exit", exit);
    };
    worker.on("message", message);
    worker.on("error", error);
    worker.on("exit", exit);
  });
}

function startWorker(loaded: LoadedBrowserShardSet): { worker: Worker; ready: Promise<WorkerReady> } {
  const started = performance.now();
  const worker = new Worker(WORKER_BOOTSTRAP_URL, {
    workerData: {
      moduleUrl: WORKER_URL.href,
      shards: Object.fromEntries(SHARD_IDS.map((id) => [id, new Uint8Array(loaded.shards[id].bytes)])),
    },
  });
  return {
    worker,
    ready: nextMessage(worker, "ready").then((value) => ({
      ...value,
      initializationMilliseconds: performance.now() - started,
    }) as WorkerReady & { initializationMilliseconds: number }),
  };
}

async function workerMeasurements(
  options: PerformanceOptions,
  bindings: EvidenceBindings,
): Promise<{
  initialization: number[];
  query: number[];
  memory: MemorySnapshot[];
  resultCountsSha256: string;
}> {
  const initialization: number[] = [];
  const memory: MemorySnapshot[] = [];
  let queryWorker: Worker | null = null;
  for (let index = 0; index < options.initializationSamples; index += 1) {
    const active = startWorker(bindings.loaded);
    let ready: WorkerReady & { initializationMilliseconds: number };
    try {
      ready = await active.ready as WorkerReady & { initializationMilliseconds: number };
    } catch (error) {
      await active.worker.terminate();
      throw error;
    }
    for (const shardId of SHARD_IDS) {
      if (ready.shardSha256[shardId] !== digest(bindings.loaded.shards[shardId].bytes)) {
        await active.worker.terminate();
        fail("worker received bytes that differ from the receipt-gated shards");
      }
    }
    initialization.push(ready.initializationMilliseconds);
    memory.push(ready.memory);
    if (index + 1 === options.initializationSamples) queryWorker = active.worker;
    else await active.worker.terminate();
  }
  if (!queryWorker) return fail("query worker was not initialized");
  const resultCounts = new Map<string, number>();
  const observations: number[] = [];
  try {
    for (const item of bindings.querySet.queries) {
      for (let sample = -1; sample < options.querySamples; sample += 1) {
        const response = nextMessage(queryWorker, "query-result");
        queryWorker.postMessage({ kind: "query", id: item.id, query: item.query });
        const measured = await response;
        const existing = resultCounts.get(item.id);
        if (existing !== undefined && existing !== measured.resultCount) {
          fail("worker query result count changed between samples");
        }
        resultCounts.set(item.id, measured.resultCount);
        if (sample >= 0) {
          observations.push(measured.durationMilliseconds);
          memory.push(measured.memory);
        }
      }
    }
  } finally {
    await queryWorker.terminate();
  }
  return {
    initialization,
    query: observations,
    memory,
    resultCountsSha256: digest(`${canonical(Array.from(resultCounts.entries()))}\n`),
  };
}

function reportArtifacts(loaded: LoadedBrowserShardSet): BrowserWorkerPerformanceReport["artifacts"] {
  const shards = SHARD_IDS.map((shardId) => {
    const item = loaded.shards[shardId];
    const raw = brotliDecompressSync(item.bytes, {
      maxOutputLength: DEFAULT_SHARD_LIMITS.maxRawShardBytes,
    });
    return {
      shardId,
      path: SHARD_FILENAMES[shardId],
      compressedByteSize: item.bytes.length,
      compressedSha256: digest(item.bytes),
      rawByteSize: raw.length,
      recordCount: item.shard.recordCount,
    };
  });
  const coreRecords = loaded.shards["europe-core"].shard.records;
  const coastalRecords = loaded.shards["europe-coastal"].shard.records;
  let coreIndex = 0;
  let coastalIndex = 0;
  let overlap = 0;
  while (coreIndex < coreRecords.length && coastalIndex < coastalRecords.length) {
    const coreId = BigInt(coreRecords[coreIndex].placeId.slice("geonames:".length));
    const coastalId = BigInt(coastalRecords[coastalIndex].placeId.slice("geonames:".length));
    if (coreId === coastalId) { overlap += 1; coreIndex += 1; coastalIndex += 1; }
    else if (coreId < coastalId) coreIndex += 1;
    else coastalIndex += 1;
  }
  const engines = SHARD_IDS.map((id) => loaded.shards[id].shard.engine);
  if (canonical(engines[0]) !== canonical(engines[1])) fail("browser shard engines differ");
  return {
    receipt: {
      path: SHARD_RECEIPT_FILENAME,
      byteSize: loaded.receipt.length,
      sha256: digest(loaded.receipt),
    },
    shards,
    totalCompressedBytes: shards.reduce((sum, item) => sum + item.compressedByteSize, 0),
    totalRawBytes: shards.reduce((sum, item) => sum + item.rawByteSize, 0),
    totalShardRecords: shards.reduce((sum, item) => sum + item.recordCount, 0),
    uniqueRecordCount: coreRecords.length + coastalRecords.length - overlap,
    observedEngine: engines[0],
  };
}

function allBudgetOutcome(outcomes: readonly Outcome[]): Outcome {
  if (outcomes.includes("fail")) return "fail";
  return outcomes.every((outcome) => outcome === "pass") ? "pass" : "not-measured";
}

export async function measureBrowserWorkerPerformance(
  options: PerformanceOptions,
): Promise<BrowserWorkerPerformanceReport> {
  positiveInteger(options.buildSamples, "build sample count");
  positiveInteger(options.initializationSamples, "initialization sample count");
  positiveInteger(options.querySamples, "query sample count");
  for (const [label, value] of Object.entries(options.thresholds)) nullableThreshold(value, label);
  const generatedAt = options.generatedAt ?? new Date().toISOString();
  if (new Date(generatedAt).toISOString() !== generatedAt) fail("generatedAt must be canonical UTC");
  const bindings = inputBindings(options);
  const build = distribution(exactBuildSamples(options, bindings.loaded));
  const workers = await workerMeasurements(options, bindings);
  const initialization = distribution(workers.initialization);
  const query = distribution(workers.query);
  const peak = (key: keyof MemorySnapshot) => Math.max(...workers.memory.map((item) => item[key]));
  const budgets = {
    build: budget(options.thresholds.buildP95Milliseconds, build.p95Milliseconds),
    initialization: budget(
      options.thresholds.initializationP95Milliseconds, initialization.p95Milliseconds
    ),
    query: budget(options.thresholds.queryP95Milliseconds, query.p95Milliseconds),
    memory: budget(
      options.thresholds.peakWorkerMemoryBytes, peak("observedWorkerBytes"), "less-than-or-equal"
    ),
  };
  const operatorThresholdOutcome = allBudgetOutcome(
    Object.values(budgets).map(({ outcome }) => outcome)
  );
  const artifacts = reportArtifacts(bindings.loaded);
  const core = bindings.loaded.shards["europe-core"].shard;
  const unsigned = {
    schemaVersion: PERFORMANCE_REPORT_VERSION,
    generatedAt,
    executionOutcome: "pass" as const,
    operatorThresholdOutcome,
    acceptedBrowserBudgetOutcome: "not-measured" as const,
    provenance: {
      dataProvenanceClass: bindings.querySet.dataProvenanceClass,
      corpusScale: bindings.querySet.corpusScale,
    },
    claims: {
      browserReferenceClaim: false as const,
      engineSelectionClaim: false as const,
      ownerApprovalClaim: false as const,
      productionClaim: false as const,
      publicationClaim: false as const,
      scientificApprovalClaim: false as const,
    },
    profile: {
      profileId: PERFORMANCE_PROFILE_ID,
      runtime: {
        node: process.versions.node,
        v8: process.versions.v8,
        platform: platform(),
        release: release(),
        architecture: process.arch,
        cpu: cpus()[0]?.model ?? "unknown",
        logicalCpuCount: cpus().length,
        totalMemoryBytes: totalmem(),
      },
      execution: {
        workerRuntime: "Node worker_threads with tsx source loader" as const,
        transfer: "structured-clone exact compressed shard bytes" as const,
        cacheState: "warm local filesystem after receipt validation" as const,
        network: "not used" as const,
        memoryMetric: "V8 isolate used heap plus external bytes sampled after initialization and queries" as const,
        browserRuntimeMeasured: false as const,
      },
      sampling: {
        buildSamples: options.buildSamples,
        initializationSamples: options.initializationSamples,
        querySamplesPerQuery: options.querySamples,
        warmupQueriesPerQuery: 1 as const,
      },
    },
    artifacts,
    querySet: {
      byteSize: bindings.queryBytes.length,
      sha256: digest(bindings.queryBytes),
      queryCount: bindings.querySet.queries.length,
      resultCountsSha256: workers.resultCountsSha256,
    },
    measurements: {
      build: { executionOutcome: "pass" as const, distribution: build, budget: budgets.build },
      initialization: {
        executionOutcome: "pass" as const, distribution: initialization, budget: budgets.initialization,
      },
      query: { executionOutcome: "pass" as const, distribution: query, budget: budgets.query },
      workerMemory: {
        executionOutcome: "pass" as const,
        peakObservedWorkerBytes: peak("observedWorkerBytes"),
        peakUsedHeapBytes: peak("usedHeapBytes"),
        peakExternalBytes: peak("externalBytes"),
        sampleCount: workers.memory.length,
        budget: budgets.memory,
      },
    },
    interpretation: {
      exactReceiptAndShardBytesMeasured: true as const,
      productionInputCompatible: true as const,
      browserOrMobilePerformanceMeasured: false as const,
      completeAcceptedBudgetsMeasured: false as const,
    },
  };
  const report = {
    ...unsigned,
    deterministicIdentity: digest(`${canonical(unsigned)}\n`),
  } as BrowserWorkerPerformanceReport;
  validateBrowserWorkerPerformanceReport(report, bindings);
  return report;
}

function validateDistribution(value: unknown, expectedSamples: number, label: string): Distribution {
  if (!exactKeys(value, [
    "observationsMilliseconds", "sampleCount", "minimumMilliseconds", "p50Milliseconds",
    "p95Milliseconds", "maximumMilliseconds", "meanMilliseconds",
  ]) || !Array.isArray(value.observationsMilliseconds)) fail(`${label} distribution fields differ`);
  const expected = distribution(value.observationsMilliseconds as number[]);
  if (expected.sampleCount !== expectedSamples || canonical(value) !== canonical(expected)) {
    fail(`${label} distribution semantics differ`);
  }
  return expected;
}

function validateBudget(value: unknown, observed: number, label: string): Outcome {
  if (!exactKeys(value, ["comparator", "threshold", "thresholdAuthority", "outcome"])
      || !["less-than", "less-than-or-equal"].includes(value.comparator as string)
      || !OUTCOMES.has(value.outcome as Outcome)) fail(`${label} budget fields differ`);
  const threshold = nullableThreshold(value.threshold as number | null, `${label} threshold`);
  const expected = budget(threshold, observed, value.comparator as Budget["comparator"]);
  if (canonical(value) !== canonical(expected)) fail(`${label} budget outcome differs`);
  return expected.outcome;
}

export function validateBrowserWorkerPerformanceReport(
  report: BrowserWorkerPerformanceReport,
  bindings: EvidenceBindings,
): void {
  const topKeys = [
    "schemaVersion", "generatedAt", "executionOutcome", "operatorThresholdOutcome",
    "acceptedBrowserBudgetOutcome", "provenance", "claims",
    "profile", "artifacts", "querySet", "measurements", "interpretation", "deterministicIdentity",
  ];
  if (!exactKeys(report, topKeys) || report.schemaVersion !== PERFORMANCE_REPORT_VERSION
      || report.executionOutcome !== "pass" || !OUTCOMES.has(report.operatorThresholdOutcome)
      || report.acceptedBrowserBudgetOutcome !== "not-measured"
      || new Date(report.generatedAt).toISOString() !== report.generatedAt) {
    fail("performance report envelope differs");
  }
  if (!exactKeys(report.claims, [
    "browserReferenceClaim", "engineSelectionClaim", "ownerApprovalClaim", "productionClaim",
    "publicationClaim", "scientificApprovalClaim",
  ]) || Object.values(report.claims).some((value) => value !== false)) {
    fail("performance report claims differ");
  }
  if (!exactKeys(report.provenance, ["dataProvenanceClass", "corpusScale"])
      || report.provenance.dataProvenanceClass !== bindings.querySet.dataProvenanceClass
      || report.provenance.corpusScale !== bindings.querySet.corpusScale) {
    fail("performance report provenance differs");
  }
  const expectedArtifacts = reportArtifacts(bindings.loaded);
  if (canonical(report.artifacts) !== canonical(expectedArtifacts)) {
    fail("performance report artifact binding differs");
  }
  if (!exactKeys(report.querySet, ["byteSize", "sha256", "queryCount", "resultCountsSha256"])
      || report.querySet.byteSize !== bindings.queryBytes.length
      || report.querySet.sha256 !== digest(bindings.queryBytes)
      || report.querySet.queryCount !== bindings.querySet.queries.length
      || !/^[0-9a-f]{64}$/.test(report.querySet.resultCountsSha256)) {
    fail("performance report query-set binding differs");
  }
  if (!exactKeys(report.profile, ["profileId", "runtime", "execution", "sampling"])
      || report.profile.profileId !== PERFORMANCE_PROFILE_ID
      || !exactKeys(report.profile.runtime, [
        "node", "v8", "platform", "release", "architecture", "cpu", "logicalCpuCount",
        "totalMemoryBytes",
      ])
      || !["node", "v8", "platform", "release", "architecture", "cpu"]
        .every((key) => typeof report.profile.runtime[key as keyof typeof report.profile.runtime]
          === "string")
      || !Number.isSafeInteger(report.profile.runtime.logicalCpuCount)
      || report.profile.runtime.logicalCpuCount < 1
      || !Number.isSafeInteger(report.profile.runtime.totalMemoryBytes)
      || report.profile.runtime.totalMemoryBytes < 1
      || !exactKeys(report.profile.execution, [
        "workerRuntime", "transfer", "cacheState", "network", "memoryMetric",
        "browserRuntimeMeasured",
      ])
      || report.profile.execution.workerRuntime !== "Node worker_threads with tsx source loader"
      || report.profile.execution.transfer !== "structured-clone exact compressed shard bytes"
      || report.profile.execution.cacheState !== "warm local filesystem after receipt validation"
      || report.profile.execution.network !== "not used"
      || report.profile.execution.memoryMetric
        !== "V8 isolate used heap plus external bytes sampled after initialization and queries"
      || report.profile.execution.browserRuntimeMeasured !== false
      || !exactKeys(report.profile.sampling, [
        "buildSamples", "initializationSamples", "querySamplesPerQuery", "warmupQueriesPerQuery",
      ]) || report.profile.sampling.warmupQueriesPerQuery !== 1) {
    fail("performance report profile differs");
  }
  const sampling = report.profile.sampling;
  positiveInteger(sampling.buildSamples, "reported build samples");
  positiveInteger(sampling.initializationSamples, "reported initialization samples");
  positiveInteger(sampling.querySamplesPerQuery, "reported query samples");
  if (!exactKeys(report.measurements, ["build", "initialization", "query", "workerMemory"])) {
    fail("performance report measurement fields differ");
  }
  const outcomes: Outcome[] = [];
  for (const [label, value, count] of [
    ["build", report.measurements.build, sampling.buildSamples],
    ["initialization", report.measurements.initialization, sampling.initializationSamples],
    ["query", report.measurements.query, sampling.querySamplesPerQuery * report.querySet.queryCount],
  ] as const) {
    if (!exactKeys(value, ["executionOutcome", "distribution", "budget"])
        || value.executionOutcome !== "pass") fail(`${label} measurement fields differ`);
    const observed = validateDistribution(value.distribution, count, label);
    outcomes.push(validateBudget(value.budget, observed.p95Milliseconds, label));
  }
  const memory = report.measurements.workerMemory;
  if (!exactKeys(memory, [
    "executionOutcome", "peakObservedWorkerBytes", "peakUsedHeapBytes", "peakExternalBytes",
    "sampleCount", "budget",
  ]) || memory.executionOutcome !== "pass"
      || !Number.isSafeInteger(memory.peakObservedWorkerBytes) || memory.peakObservedWorkerBytes < 1
      || !Number.isSafeInteger(memory.peakUsedHeapBytes) || memory.peakUsedHeapBytes < 1
      || !Number.isSafeInteger(memory.peakExternalBytes) || memory.peakExternalBytes < 0
      || memory.peakObservedWorkerBytes < memory.peakUsedHeapBytes
      || memory.peakObservedWorkerBytes < memory.peakExternalBytes
      || !Number.isSafeInteger(memory.sampleCount)
      || memory.sampleCount !== sampling.initializationSamples
        + sampling.querySamplesPerQuery * report.querySet.queryCount) {
    fail("worker memory measurement semantics differ");
  }
  outcomes.push(validateBudget(memory.budget, memory.peakObservedWorkerBytes, "worker memory"));
  const expectedOverall = allBudgetOutcome(outcomes);
  if (report.operatorThresholdOutcome !== expectedOverall
      || !exactKeys(report.interpretation, [
        "exactReceiptAndShardBytesMeasured", "productionInputCompatible",
        "browserOrMobilePerformanceMeasured", "completeAcceptedBudgetsMeasured",
      ])
      || report.interpretation.exactReceiptAndShardBytesMeasured !== true
      || report.interpretation.productionInputCompatible !== true
      || report.interpretation.browserOrMobilePerformanceMeasured !== false
      || report.interpretation.completeAcceptedBudgetsMeasured !== false) {
    fail("performance report interpretation differs");
  }
  const unsigned = Object.fromEntries(
    Object.entries(report).filter(([key]) => key !== "deterministicIdentity")
  );
  if (!/^[0-9a-f]{64}$/.test(report.deterministicIdentity)
      || report.deterministicIdentity !== digest(`${canonical(unsigned)}\n`)) {
    fail("performance report deterministic identity differs");
  }
}

export function readAndValidateBrowserWorkerPerformanceReport(
  reportPath: string,
  options: PerformanceOptions,
): BrowserWorkerPerformanceReport {
  if (!isAbsolute(reportPath)) fail("performance report path must be absolute");
  const value = parseCanonicalJson(readFileSync(reportPath), "performance report");
  const bindings = inputBindings(options);
  validateBrowserWorkerPerformanceReport(value as BrowserWorkerPerformanceReport, bindings);
  return value as BrowserWorkerPerformanceReport;
}

export function writePerformanceReport(path: string, report: BrowserWorkerPerformanceReport): void {
  if (!isAbsolute(path)) fail("performance report output path must be absolute");
  let descriptor = -1;
  try {
    descriptor = openSync(
      path,
      fsConstants.O_WRONLY | fsConstants.O_CREAT | fsConstants.O_EXCL | fsConstants.O_NOFOLLOW,
      0o600,
    );
    const bytes = Buffer.from(`${canonical(report)}\n`);
    let offset = 0;
    while (offset < bytes.length) {
      const written = writeSync(descriptor, bytes, offset, bytes.length - offset);
      if (written < 1) fail("performance report write made no progress");
      offset += written;
    }
    fsyncSync(descriptor);
  } catch (error) {
    if (error instanceof BrowserWorkerEvidenceError) throw error;
    return fail(`performance report ${basename(path)} could not be written without overwrite`);
  } finally {
    if (descriptor >= 0) closeSync(descriptor);
  }
}
