import { createReadStream, readFileSync, readdirSync, statSync } from "node:fs";
import { createServer } from "node:http";
import { cpus, platform, release, totalmem } from "node:os";
import { basename, extname, resolve, sep } from "node:path";
import { clearTimeout, setTimeout } from "node:timers";
import { chromium, devices } from "@playwright/test";
import { assertPrivateMeasurementOutput } from "./local-measurement-paths.mjs";
import {
  QUERY_TARGET_MILLISECONDS, STARTUP_TARGET_MILLISECONDS, canonicalJson, distribution,
  finalizePerformanceReport, loadPerformanceInputs, performanceReportBytes,
  publishPerformanceReport, sha256, validatePerformanceReport,
} from "./search-performance-evidence.mjs";

const options = new Map();
for (let index = 2; index < process.argv.length; index += 2) {
  options.set(process.argv[index], process.argv[index + 1]);
}
const candidateRoot = resolve(options.get("--candidate-root") ?? "");
const querySetPath = resolve(options.get("--query-set") ?? "");
const requestedOutputPath = resolve(options.get("--output") ?? "");
const sampleCount = Number(options.get("--samples") ?? "5");
if (!options.get("--candidate-root") || !options.get("--query-set") || !options.get("--output")
    || !Number.isSafeInteger(sampleCount) || sampleCount < 1 || sampleCount > 30) {
  throw new Error("Usage: --candidate-root PATH --query-set PATH --output PATH [--samples 5]");
}
const distRoot = resolve(import.meta.dirname, "../dist");
const outputPath = assertPrivateMeasurementOutput({
  outputPath: requestedOutputPath,
  candidateRoot,
  distRoot,
});
const workerName = readdirSync(resolve(distRoot, "assets"))
  .find((name) => /^search\.worker-[A-Za-z0-9_-]+\.js$/.test(name));
if (!workerName) throw new Error("Run npm run build before this local measurement.");
const inputs = loadPerformanceInputs(candidateRoot, querySetPath);
const { manifest, manifestBytes, queryBytes, querySet, receiptBytes } = inputs;
const shards = {};
for (const shardId of ["europe-core", "europe-coastal"]) {
  const { artifact, path } = inputs.shards[shardId];
  shards[shardId] = {
    path,
    authority: {
      shardId,
      dataReleaseId: manifest.dataReleaseId,
      dataProvenanceClass: manifest.dataProvenanceClass,
      artifact: {
        artifactId: artifact.artifactId,
        byteSize: artifact.byteSize,
        sha256: artifact.sha256,
        url: "",
      },
    },
  };
}

const pageScript = [
  "let sequence=0;const pending=new Map();",
  "function makeWorker(){const worker=new Worker('/search.worker.js',{type:'module'});",
  "worker.onmessage=({data})=>{const item=pending.get(data.token);if(!item)return;",
  "pending.delete(data.token);data.kind==='error'?item.reject(new Error(data.error.message)):item.resolve(data)};return worker}",
  "function request(worker,message){return new Promise((resolve,reject)=>{const token=++sequence;",
  "pending.set(token,{resolve,reject});worker.postMessage({...message,token})})}",
  "globalThis.runMeasurement=async configuration=>{if(!crossOriginIsolated)throw new Error('not isolated');",
  "const initialization=[],responsiveness=[];for(let i=0;i<configuration.samples;i++){const worker=makeWorker();",
  "let previous=performance.now(),maximumGap=0;const timer=setInterval(()=>{const now=performance.now();maximumGap=Math.max(maximumGap,now-previous);previous=now},10);",
  "const ready=await request(worker,{kind:'initialize',authority:configuration.core});",
  "clearInterval(timer);maximumGap=Math.max(maximumGap,performance.now()-previous);responsiveness.push(maximumGap);",
  "initialization.push(ready.durationMilliseconds);worker.postMessage({kind:'terminate',token:++sequence})}",
  "const worker=makeWorker();await request(worker,{kind:'initialize',authority:configuration.core});",
  "await request(worker,{kind:'load-shard',authority:configuration.coastal});const memory=[];",
  "if(typeof performance.measureUserAgentSpecificMemory==='function'){try{memory.push((await performance.measureUserAgentSpecificMemory()).bytes)}catch{}}",
  "const query=[];const counts=[];for(const item of configuration.queries){try{await request(worker,{kind:'query',query:item.query});}catch(error){throw new Error('query '+item.id+' failed: '+error.message)}",
  "for(let i=0;i<configuration.samples;i++){const result=await request(worker,{kind:'query',query:item.query});",
  "query.push(result.durationMilliseconds);counts.push([item.id,result.results.length])}}",
  "if(typeof performance.measureUserAgentSpecificMemory==='function'){try{memory.push((await performance.measureUserAgentSpecificMemory()).bytes)}catch{}}",
  "globalThis.liveWorker=worker;return{initialization,query,counts,memory,responsiveness}};",
].join("");
const html = "<!doctype html><meta charset=utf-8><title>Local measurement</title>"
  + "<script type=module src=/measurement-harness.js></script>";

const server = createServer((request, response) => {
  response.setHeader("Cross-Origin-Embedder-Policy", "require-corp");
  response.setHeader("Cross-Origin-Opener-Policy", "same-origin");
  response.setHeader("Cross-Origin-Resource-Policy", "same-origin");
  response.setHeader("Origin-Agent-Cluster", "?1");
  response.setHeader("Content-Encoding", "identity");
  if (request.url === "/") {
    response.setHeader(
      "Content-Security-Policy",
      "default-src 'self'; script-src 'self'; worker-src 'self'; connect-src 'self'",
    );
    response.setHeader("Content-Type", "text/html; charset=utf-8");
    response.end(html);
    return;
  }
  if (request.url === "/measurement-harness.js") {
    response.setHeader("Content-Type", "text/javascript; charset=utf-8");
    response.end(pageScript);
    return;
  }
  if (request.url === "/search.worker.js") {
    response.setHeader("Content-Type", "text/javascript; charset=utf-8");
    createReadStream(resolve(distRoot, "assets", workerName))
      .on("error", () => response.destroy())
      .pipe(response);
    return;
  }
  if (request.url?.startsWith("/assets/")) {
    const path = resolve(distRoot, request.url.slice(1));
    if (!path.startsWith(distRoot + sep)) return response.writeHead(400).end();
    response.setHeader("Content-Type", extname(path) === ".js" ? "text/javascript" : "application/wasm");
    createReadStream(path).on("error", () => response.destroy()).pipe(response);
    return;
  }
  for (const shard of Object.values(shards)) {
    if (request.url === new URL(shard.authority.artifact.url).pathname) {
      response.setHeader("Content-Type", "application/vnd.searise.search-index+json");
      response.setHeader("Content-Length", String(statSync(shard.path).size));
      createReadStream(shard.path).pipe(response);
      return;
    }
  }
  response.writeHead(404).end();
});
async function workerHeapUsage(browser) {
  const session = await browser.newBrowserCDPSession();
  try {
    const targets = await session.send("Target.getTargets");
    const target = targets.targetInfos.find(
      (item) => item.type === "worker" && new URL(item.url).pathname === "/search.worker.js",
    );
    if (!target) throw new Error("Live Worker target was not found.");
    const attached = await session.send("Target.attachToTarget", { flatten: false, targetId: target.targetId });
    const response = new Promise((resolvePromise, reject) => {
      const timeout = setTimeout(() => reject(new Error("Worker heap telemetry timed out.")), 10_000);
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
    return await response;
  } finally {
    await session.detach();
  }
}

await new Promise((resolvePromise) => server.listen(0, "127.0.0.1", resolvePromise));
const address = server.address();
if (!address || typeof address === "string") throw new Error("Loopback server failed.");
const origin = "http://127.0.0.1:" + address.port;
for (const shard of Object.values(shards)) {
  shard.authority.artifact.url = origin + "/releases/" + manifest.dataReleaseId + "/"
    + basename(shard.path);
}
const browser = await chromium.launch({
  headless: true,
  args: ["--enable-blink-features=ForceEagerMeasureMemory", "--js-flags=--max-old-space-size=512"],
});
try {
  const context = await browser.newContext({ ...devices["Pixel 7"] });
  const page = await context.newPage();
  const browserRequests = [];
  page.on("request", (request) => browserRequests.push({ method: request.method(), url: request.url() }));
  await page.goto(origin);
  const observed = await page.evaluate((configuration) =>
    globalThis.runMeasurement(configuration), {
    core: shards["europe-core"].authority,
    coastal: shards["europe-coastal"].authority,
    queries: querySet.queries,
    samples: sampleCount,
  });
  const cdp = await workerHeapUsage(browser);
  const cdpUpperBound = cdp.usedSize + cdp.embedderHeapUsedSize + cdp.backingStorageSize;
  const measuredConservativeUpperBoundBytes = Math.max(cdpUpperBound, ...observed.memory);
  const allowedPaths = new Set([
    "/", "/measurement-harness.js", "/search.worker.js",
    ...readdirSync(resolve(distRoot, "assets")).map((name) => `/assets/${name}`),
    ...Object.values(shards).map(({ authority }) => new URL(authority.artifact.url).pathname),
  ]);
  const capturedRequests = browserRequests.map(({ method, url }) => {
    const parsed = new URL(url);
    return { method, path: parsed.pathname, search: parsed.search };
  });
  const unexpectedRequests = capturedRequests.filter(({ method, path, search }) =>
    method !== "GET" || search !== "" || !allowedPaths.has(path));
  const initialization = distribution(observed.initialization);
  const query = distribution(observed.query);
  const responsiveness = distribution(observed.responsiveness);
  const report = finalizePerformanceReport({
    schemaVersion: "static-search-browser-performance-v2",
    recordedAt: new Date().toISOString(),
    dataReleaseId: manifest.dataReleaseId,
    provenance: {
      corpusScale: querySet.corpusScale,
      dataProvenanceClass: manifest.dataProvenanceClass,
      scope: "local-read-only-candidate",
    },
    profile: {
      browser: await browser.version(),
      deviceEmulation: "Pixel 7",
      workerV8OldSpaceLimitMiB: 512,
      host: { platform: platform(), release: release(), cpu: cpus()[0]?.model, totalMemoryBytes: totalmem() },
    },
    artifacts: {
      manifest: { byteSize: manifestBytes.length, sha256: sha256(manifestBytes) },
      receipt: { byteSize: receiptBytes.length, sha256: sha256(receiptBytes) },
      shards: Object.values(inputs.shards).map(({ artifact }) => ({
        artifactId: artifact.artifactId,
        byteSize: artifact.byteSize,
        path: artifact.path,
        sha256: artifact.sha256,
      })),
    },
    querySet: {
      byteSize: queryBytes.length,
      queryCount: querySet.queries.length,
      sha256: sha256(queryBytes),
      resultCountsSha256: sha256(canonicalJson(observed.counts)),
    },
    measurements: {
      initialization: {
        distribution: initialization,
        outcome: initialization.p95Milliseconds < STARTUP_TARGET_MILLISECONDS ? "pass" : "fail",
        targetMilliseconds: STARTUP_TARGET_MILLISECONDS,
      },
      query: {
        distribution: query,
        outcome: query.p95Milliseconds < QUERY_TARGET_MILLISECONDS ? "pass" : "fail",
        targetMilliseconds: QUERY_TARGET_MILLISECONDS,
      },
      responsiveness: {
        distribution: responsiveness,
        metric: "maximum main-thread 10 ms timer gap during Worker initialization",
      },
      memory: {
        measureUserAgentSpecificMemoryBytes: observed.memory,
        cdpRuntimeGetHeapUsage: cdp,
        measuredConservativeUpperBoundBytes,
        caveat: "CDP heap/backing storage and user-agent-specific memory do not equal device RSS; their maximum is retained as a numeric local upper bound.",
      },
    },
    network: {
      queryTransmissionOutcome: unexpectedRequests.length === 0 ? "pass" : "fail",
      requests: capturedRequests.map(({ method, path }) => ({ method, path })),
      unexpectedRequests: unexpectedRequests.map(({ method, path }) => ({ method, path })),
    },
    claims: {
      mobileDeviceClaim: false, ownerApprovalClaim: false, productionClaim: false,
      publicationClaim: false, scientificApprovalClaim: false,
    },
    gateOutcome: initialization.p95Milliseconds < STARTUP_TARGET_MILLISECONDS
      && query.p95Milliseconds < QUERY_TARGET_MILLISECONDS
      && unexpectedRequests.length === 0 ? "pass" : "fail",
  });
  const expected = {
    dataProvenanceClass: manifest.dataProvenanceClass,
    dataReleaseId: manifest.dataReleaseId,
    artifacts: report.artifacts,
    querySet: { byteSize: queryBytes.length, queryCount: querySet.queries.length, sha256: sha256(queryBytes) },
  };
  validatePerformanceReport(report, expected);
  const bytes = performanceReportBytes(report);
  publishPerformanceReport(outputPath, bytes);
  validatePerformanceReport(JSON.parse(readFileSync(outputPath, "utf8")), expected);
  console.log(JSON.stringify({
    output: basename(outputPath),
    gateOutcome: report.gateOutcome,
    initializationP95Milliseconds: initialization.p95Milliseconds,
    queryP95Milliseconds: query.p95Milliseconds,
    measuredConservativeUpperBoundBytes,
  }));
  if (report.gateOutcome !== "pass") process.exitCode = 1;
} finally {
  await browser.close();
  await new Promise((resolvePromise, reject) =>
    server.close((error) => error ? reject(error) : resolvePromise()));
}
