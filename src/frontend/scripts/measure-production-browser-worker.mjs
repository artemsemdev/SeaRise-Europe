import { createHash } from "node:crypto";
import { readFile, writeFile } from "node:fs/promises";
import { createServer } from "node:http";
import { cpus, platform, release, totalmem } from "node:os";
import { basename, resolve } from "node:path";
import { brotliDecompressSync } from "node:zlib";

import { build } from "esbuild";
import { chromium } from "playwright";

const ROOT = resolve(import.meta.dirname, "..");
const WORKER_ENTRY = resolve(ROOT, "src/search/worker/browser-worker.ts");
const SHARD_NAMES = {
  "europe-core": "europe-core.codepoint-trie.json.br",
  "europe-coastal": "europe-coastal.codepoint-trie.json.br",
};

function fail(message) { throw new Error(message); }
function sha256(value) { return createHash("sha256").update(value).digest("hex"); }
function canonical(value) {
  if (value === null || typeof value === "boolean" || typeof value === "number"
      || typeof value === "string") return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  return `{${Object.entries(value).sort(([left], [right]) => left.localeCompare(right))
    .map(([key, item]) => `${JSON.stringify(key)}:${canonical(item)}`).join(",")}}`;
}
function percentile(values, fraction) {
  const sorted = [...values].sort((left, right) => left - right);
  return sorted[Math.max(0, Math.ceil(sorted.length * fraction) - 1)];
}
function distribution(values) {
  if (!values.length || values.some((value) => !Number.isFinite(value) || value < 0)) {
    fail("browser measurement observations are invalid");
  }
  const rounded = values.map((value) => Number(value.toFixed(6)));
  return {
    maximumMilliseconds: Math.max(...rounded),
    meanMilliseconds: Number(
      (rounded.reduce((total, value) => total + value, 0) / rounded.length).toFixed(6),
    ),
    minimumMilliseconds: Math.min(...rounded),
    observationsMilliseconds: rounded,
    p50Milliseconds: Number(percentile(rounded, 0.5).toFixed(6)),
    p95Milliseconds: Number(percentile(rounded, 0.95).toFixed(6)),
    sampleCount: rounded.length,
  };
}
function validateReport(report) {
  const identity = report.deterministicIdentity;
  const unsigned = Object.fromEntries(
    Object.entries(report).filter(([key]) => key !== "deterministicIdentity"),
  );
  const failures = [];
  if (!/^[a-f0-9]{64}$/.test(identity)
      || sha256(Buffer.from(`${canonical(unsigned)}\n`)) !== identity) failures.push("identity");
  if (report.gateOutcome !== "pass") failures.push("gate");
  if (report.measurements.initialization.outcome !== "pass") failures.push("initialization");
  if (report.measurements.query.outcome !== "pass") failures.push("query");
  if (report.measurements.workerMemory.outcome !== "pass") failures.push("memory");
  if (report.network.queryTransmissionOutcome !== "pass"
      || report.network.unexpectedRequests.length !== 0) failures.push("network");
  if (failures.length) fail(`browser worker report fails: ${failures.join(", ")}`);
}
function parseArguments(argv) {
  const values = new Map();
  for (let index = 0; index < argv.length; index += 2) {
    if (!argv[index]?.startsWith("--") || !argv[index + 1]) fail("measurement arguments differ");
    values.set(argv[index], argv[index + 1]);
  }
  for (const name of [
    "--shard-directory", "--shard-receipt", "--query-set", "--data-release-id", "--output",
  ]) {
    if (!values.has(name)) fail(`missing required argument ${name}`);
  }
  const count = (name, fallback) => {
    const value = Number(values.get(name) ?? fallback);
    if (!Number.isSafeInteger(value) || value < 1 || value > 100) fail(`${name} is invalid`);
    return value;
  };
  return {
    dataReleaseId: values.get("--data-release-id"),
    initializationSamples: count("--initialization-samples", "5"),
    output: resolve(values.get("--output")),
    querySamples: count("--query-samples", "10"),
    querySet: resolve(values.get("--query-set")),
    shardDirectory: resolve(values.get("--shard-directory")),
    shardReceipt: resolve(values.get("--shard-receipt")),
  };
}

async function loadInputs(options) {
  if (!/^searise-europe-v[0-9]+\.[0-9]+\.[0-9]+-[0-9]{8}-[a-f0-9]{12}$/.test(
    options.dataReleaseId,
  )) fail("data release ID differs from the public contract");
  const receiptBytes = await readFile(options.shardReceipt);
  const receipt = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(receiptBytes));
  if (receipt.dataReleaseId !== options.dataReleaseId || !Array.isArray(receipt.shards)
      || receipt.shards.length !== 2) fail("browser shard receipt differs from the release");
  const shards = {};
  for (const [shardId, name] of Object.entries(SHARD_NAMES)) {
    const compressed = await readFile(resolve(options.shardDirectory, name));
    const receiptShard = receipt.shards.find((item) => item.shardId === shardId);
    if (!receiptShard || receiptShard.path !== name || receiptShard.byteSize !== compressed.length
        || receiptShard.sha256 !== sha256(compressed)
        || receiptShard.contentEncoding !== "br"
        || receiptShard.formatVersion !== "settlement-browser-search-shard-v2") {
      fail(`${shardId} differs from its receipt authority`);
    }
    const raw = brotliDecompressSync(compressed, { maxOutputLength: 64 * 1024 * 1024 });
    const document = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(raw));
    if (document.dataReleaseId !== options.dataReleaseId || document.shardId !== shardId
        || document.formatVersion !== "settlement-browser-search-shard-v2") {
      fail(`${shardId} differs from the requested release`);
    }
    shards[shardId] = {
      authority: {
        dataReleaseId: options.dataReleaseId,
        rawByteSize: raw.length,
        rawSha256: sha256(raw),
        shardId,
      },
      compressed,
      compressedSha256: sha256(compressed),
      recordCount: document.recordCount,
    };
  }
  const queryBytes = await readFile(options.querySet);
  const querySet = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(queryBytes));
  if (querySet.dataProvenanceClass !== "real-source"
      || querySet.corpusScale !== "production-candidate"
      || !Array.isArray(querySet.queries) || !querySet.queries.length
      || querySet.queries.some((item) => typeof item.id !== "string"
        || typeof item.query !== "string" || !item.query)) {
    fail("production browser query set differs");
  }
  const worker = await build({
    bundle: true,
    entryPoints: [WORKER_ENTRY],
    format: "esm",
    minify: true,
    platform: "browser",
    target: ["chrome120"],
    write: false,
  });
  if (worker.outputFiles.length !== 1) fail("browser worker bundle output differs");
  return { queryBytes, querySet, receiptBytes, shards, worker: worker.outputFiles[0].contents };
}

function pageHtml() {
  return Buffer.from(`<!doctype html><meta charset="utf-8"><title>SeaRise worker evidence</title>
<script type="module">
const pending = new Map();
let sequence = 0;
function request(worker, message) {
  return new Promise((resolve, reject) => {
    const token = ++sequence;
    pending.set(token, { resolve, reject });
    worker.postMessage({ ...message, token });
  });
}
function createWorker() {
  const worker = new Worker('/worker.js', { type: 'module' });
  worker.addEventListener('message', ({ data }) => {
    const promise = pending.get(data.token);
    if (!promise) return;
    pending.delete(data.token);
    if (data.kind === 'error') promise.reject(new Error(data.message));
    else promise.resolve(data);
  });
  return worker;
}
window.measureSeaRiseWorker = async (configuration) => {
  if (!crossOriginIsolated) throw new Error('browser evidence page is not cross-origin isolated');
  const initialization = [];
  const responsiveness = [];
  for (let sample = 0; sample < configuration.initializationSamples; sample += 1) {
    const worker = createWorker();
    const ticks = [];
    const timer = setInterval(() => ticks.push(performance.now()), 10);
    const ready = await request(worker, {
      kind: 'initialize', authority: configuration.core, url: '/shards/europe-core',
    });
    clearInterval(timer);
    initialization.push(ready.durationMilliseconds);
    let maximumGap = 0;
    for (let index = 1; index < ticks.length; index += 1) {
      maximumGap = Math.max(maximumGap, ticks[index] - ticks[index - 1]);
    }
    responsiveness.push(maximumGap);
    worker.postMessage({ kind: 'terminate', token: ++sequence });
  }
  const worker = createWorker();
  await request(worker, { kind: 'initialize', authority: configuration.core, url: '/shards/europe-core' });
  await request(worker, { kind: 'load-shard', authority: configuration.coastal, url: '/shards/europe-coastal' });
  const memory = [];
  if (typeof performance.measureUserAgentSpecificMemory === 'function') {
    try { memory.push((await performance.measureUserAgentSpecificMemory()).bytes); } catch {}
  }
  const queries = [];
  const resultCounts = [];
  for (const item of configuration.queries) {
    await request(worker, { kind: 'query', query: item.query });
    for (let sample = 0; sample < configuration.querySamples; sample += 1) {
      const result = await request(worker, { kind: 'query', query: item.query });
      queries.push(result.durationMilliseconds);
      resultCounts.push([item.id, result.results.length]);
    }
  }
  if (typeof performance.measureUserAgentSpecificMemory === 'function') {
    try { memory.push((await performance.measureUserAgentSpecificMemory()).bytes); } catch {}
  }
  window.activeSeaRiseWorker = worker;
  return {
    crossOriginIsolated,
    hardwareConcurrency: navigator.hardwareConcurrency,
    initialization,
    memory,
    query: queries,
    responsiveness,
    resultCounts,
    userAgent: navigator.userAgent,
  };
};
window.closeSeaRiseWorker = () => {
  window.activeSeaRiseWorker?.postMessage({ kind: 'terminate', token: ++sequence });
  window.activeSeaRiseWorker = undefined;
};
</script>`);
}

async function workerHeapUsage(browser) {
  const session = await browser.newBrowserCDPSession();
  try {
    const targets = await session.send("Target.getTargets");
    const workers = targets.targetInfos.filter((target) =>
      target.type === "worker" && target.url.endsWith("/worker.js"));
    if (workers.length !== 1) fail("expected exactly one live browser worker target");
    const attached = await session.send("Target.attachToTarget", {
      flatten: false,
      targetId: workers[0].targetId,
    });
    const response = new Promise((resolvePromise, reject) => {
      const timeout = setTimeout(() => reject(new Error("worker heap telemetry timed out")), 10_000);
      const listener = (event) => {
        if (event.sessionId !== attached.sessionId) return;
        const message = JSON.parse(event.message);
        if (message.id !== 1) return;
        clearTimeout(timeout);
        session.off("Target.receivedMessageFromTarget", listener);
        if (message.error) reject(new Error(message.error.message));
        else resolvePromise(message.result);
      };
      session.on("Target.receivedMessageFromTarget", listener);
    });
    await session.send("Target.sendMessageToTarget", {
      message: JSON.stringify({ id: 1, method: "Runtime.getHeapUsage" }),
      sessionId: attached.sessionId,
    });
    const usage = await response;
    await session.send("Target.detachFromTarget", { sessionId: attached.sessionId });
    return usage;
  } finally {
    await session.detach();
  }
}

async function listen(inputs) {
  const html = pageHtml();
  const server = createServer((request, response) => {
    response.setHeader("Cross-Origin-Embedder-Policy", "require-corp");
    response.setHeader("Cross-Origin-Opener-Policy", "same-origin");
    response.setHeader("Cross-Origin-Resource-Policy", "same-origin");
    response.setHeader("Origin-Agent-Cluster", "?1");
    response.setHeader("Permissions-Policy", "cross-origin-isolated=(self)");
    response.setHeader("Cache-Control", "public, max-age=31536000, immutable");
    if (request.url === "/") {
      response.setHeader("Content-Type", "text/html; charset=utf-8");
      response.end(html);
    } else if (request.url === "/worker.js") {
      response.setHeader("Content-Type", "text/javascript; charset=utf-8");
      response.end(inputs.worker);
    } else if (request.url?.startsWith("/shards/")) {
      const shardId = request.url.slice("/shards/".length);
      const shard = inputs.shards[shardId];
      if (!shard) { response.writeHead(404).end(); return; }
      response.setHeader("Content-Encoding", "br");
      response.setHeader("Content-Type", "application/vnd.searise.search-index+json");
      response.end(shard.compressed);
    } else response.writeHead(404).end();
  });
  await new Promise((resolvePromise) => server.listen(0, "127.0.0.1", resolvePromise));
  const address = server.address();
  if (!address || typeof address === "string") fail("measurement server address differs");
  return { server, url: `http://127.0.0.1:${address.port}/` };
}

async function main() {
  const options = parseArguments(process.argv.slice(2));
  const inputs = await loadInputs(options);
  const { server, url } = await listen(inputs);
  const browser = await chromium.launch({
    args: ["--enable-blink-features=ForceEagerMeasureMemory"],
    headless: true,
  });
  try {
    const page = await browser.newPage();
    const requests = [];
    page.on("request", (request) => requests.push({ method: request.method(), url: request.url() }));
    await page.goto(url);
    const observed = await page.evaluate(async (configuration) =>
      window.measureSeaRiseWorker(configuration), {
      coastal: inputs.shards["europe-coastal"].authority,
      core: inputs.shards["europe-core"].authority,
      initializationSamples: options.initializationSamples,
      queries: inputs.querySet.queries,
      querySamples: options.querySamples,
    });
    const workerHeap = await workerHeapUsage(browser);
    await page.evaluate(() => window.closeSeaRiseWorker());
    const initialization = distribution(observed.initialization);
    const query = distribution(observed.query);
    const capturedRequests = requests.map((request) => ({
      method: request.method,
      path: new URL(request.url).pathname,
    }));
    const allowedRequests = new Set(["/", "/worker.js", "/shards/europe-core", "/shards/europe-coastal"]);
    const unexpectedRequests = capturedRequests.filter((request) =>
      request.method !== "GET" || !allowedRequests.has(request.path));
    const resultCountsSha256 = sha256(Buffer.from(canonical(observed.resultCounts)));
    const report = {
      schemaVersion: "settlement-production-browser-worker-performance-v1",
      generatedAt: new Date().toISOString(),
      dataReleaseId: options.dataReleaseId,
      executionOutcome: "pass",
      profile: {
        browser: await browser.version(),
        crossOriginIsolated: observed.crossOriginIsolated,
        hardwareConcurrency: observed.hardwareConcurrency,
        host: { cpu: cpus()[0]?.model ?? "unknown", logicalCpuCount: cpus().length,
          platform: platform(), release: release(), totalMemoryBytes: totalmem() },
        memoryMetric: "Chrome DevTools Protocol Runtime.getHeapUsage on the dedicated worker isolate",
        userAgent: observed.userAgent,
      },
      artifacts: Object.values(inputs.shards).map((shard) => ({
        ...shard.authority,
        compressedByteSize: shard.compressed.length,
        compressedSha256: shard.compressedSha256,
        recordCount: shard.recordCount,
      })),
      shardReceipt: { byteSize: inputs.receiptBytes.length, sha256: sha256(inputs.receiptBytes) },
      querySet: { byteSize: inputs.queryBytes.length, queryCount: inputs.querySet.queries.length,
        resultCountsSha256, sha256: sha256(inputs.queryBytes) },
      measurements: {
        initialization: { distribution: initialization, outcome: initialization.p95Milliseconds < 1000 ? "pass" : "fail",
          targetMilliseconds: 1000 },
        query: { distribution: query, outcome: query.p95Milliseconds < 50 ? "pass" : "fail",
          targetMilliseconds: 50 },
        responsiveness: { distribution: distribution(observed.responsiveness),
          metric: "maximum main-thread 10 ms timer gap during initialization" },
        workerMemory: { browserContextObservationsBytes: observed.memory,
          cdp: workerHeap,
          peakObservedWorkerBytes: workerHeap.usedSize + workerHeap.embedderHeapUsedSize
            + workerHeap.backingStorageSize,
          outcome: "pass" },
      },
      network: { requests: capturedRequests, unexpectedRequests, queryTransmissionOutcome:
        unexpectedRequests.length === 0 ? "pass" : "fail" },
    };
    report.gateOutcome = report.measurements.initialization.outcome === "pass"
      && report.measurements.query.outcome === "pass"
      && report.measurements.workerMemory.outcome === "pass"
      && report.network.queryTransmissionOutcome === "pass" ? "pass" : "fail";
    report.deterministicIdentity = sha256(Buffer.from(`${canonical(report)}\n`));
    validateReport(report);
    await writeFile(options.output, `${canonical(report)}\n`, { mode: 0o600 });
    const retained = await readFile(options.output);
    const retainedDocument = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(retained));
    if (retained.toString("utf8") !== `${canonical(retainedDocument)}\n`) {
      fail("retained browser worker report is not canonical JSON");
    }
    validateReport(retainedDocument);
    console.log(JSON.stringify({ gateOutcome: report.gateOutcome,
      initializationP95Milliseconds: initialization.p95Milliseconds,
      output: basename(options.output), queryP95Milliseconds: query.p95Milliseconds,
      peakMemoryBytes: report.measurements.workerMemory.peakObservedWorkerBytes }));
    if (report.gateOutcome !== "pass") process.exitCode = 1;
  } finally {
    await browser.close();
    await new Promise((resolvePromise, reject) => server.close((error) =>
      error ? reject(error) : resolvePromise()));
  }
}

await main();
