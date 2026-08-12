import {
  BrowserWorkerEvidenceError,
  measureBrowserWorkerPerformance,
  readAndValidateBrowserWorkerPerformanceReport,
  writePerformanceReport,
} from "../src/search/performance/browser-worker-evidence";
import type { PerformanceOptions, PerformanceThresholds } from "../src/search/performance/browser-worker-evidence";

function fail(message: string): never { throw new BrowserWorkerEvidenceError(message); }

function argumentsByName(values: string[]): { command: string; options: Map<string, string> } {
  const [command, ...rest] = values;
  if (!["measure", "validate"].includes(command)) fail("command must be measure or validate");
  if (rest.length % 2) fail("every option requires one value");
  const options = new Map<string, string>();
  for (let index = 0; index < rest.length; index += 2) {
    const name = rest[index];
    if (!name.startsWith("--") || options.has(name)) fail("options must be unique named pairs");
    options.set(name, rest[index + 1]);
  }
  return { command, options };
}

function required(options: Map<string, string>, name: string): string {
  const value = options.get(name);
  if (!value) fail(`${name} is required`);
  options.delete(name);
  return value;
}

function count(options: Map<string, string>, name: string, fallback: number): number {
  const raw = options.get(name);
  options.delete(name);
  return raw === undefined ? fallback : Number(raw);
}

function threshold(options: Map<string, string>, name: string): number | null {
  const raw = options.get(name);
  options.delete(name);
  return raw === undefined || raw === "not-measured" ? null : Number(raw);
}

async function main(): Promise<void> {
  const parsed = argumentsByName(process.argv.slice(2));
  const reportPath = required(parsed.options, "--report");
  const thresholds: PerformanceThresholds = {
    buildP95Milliseconds: threshold(parsed.options, "--max-build-p95-ms"),
    initializationP95Milliseconds: threshold(parsed.options, "--max-init-p95-ms"),
    queryP95Milliseconds: threshold(parsed.options, "--max-query-p95-ms"),
    peakWorkerMemoryBytes: threshold(parsed.options, "--max-worker-memory-bytes"),
  };
  const options: PerformanceOptions = {
    projectionPath: required(parsed.options, "--projection"),
    shardDirectory: required(parsed.options, "--shard-dir"),
    querySetPath: required(parsed.options, "--queries"),
    buildSamples: count(parsed.options, "--build-samples", 1),
    initializationSamples: count(parsed.options, "--init-samples", 5),
    querySamples: count(parsed.options, "--query-samples", 30),
    thresholds,
  };
  if (parsed.options.size) fail(`unsupported option: ${parsed.options.keys().next().value}`);
  if (parsed.command === "measure") {
    const report = await measureBrowserWorkerPerformance(options);
    writePerformanceReport(reportPath, report);
    process.stdout.write(`${JSON.stringify({
      report: reportPath,
      deterministicIdentity: report.deterministicIdentity,
      executionOutcome: report.executionOutcome,
      operatorThresholdOutcome: report.operatorThresholdOutcome,
      acceptedBrowserBudgetOutcome: report.acceptedBrowserBudgetOutcome,
    })}\n`);
  } else {
    const report = readAndValidateBrowserWorkerPerformanceReport(reportPath, options);
    process.stdout.write(`${JSON.stringify({
      report: reportPath,
      deterministicIdentity: report.deterministicIdentity,
      validation: "pass",
    })}\n`);
  }
}

void main().catch((error: unknown) => {
  process.stderr.write(`${String(error)}\n`);
  process.exitCode = 1;
});
