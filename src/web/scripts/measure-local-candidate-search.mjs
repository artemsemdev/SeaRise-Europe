import { createHash } from "node:crypto";
import { Buffer } from "node:buffer";
import { createReadStream, readFileSync, readdirSync, statSync, writeFileSync } from "node:fs";
import { createServer } from "node:http";
import { cpus, platform, release, totalmem } from "node:os";
import { basename, extname, resolve, sep } from "node:path";
import { clearTimeout, setTimeout } from "node:timers";
import { chromium, devices } from "@playwright/test";

const options = new Map();
for (let index = 2; index < process.argv.length; index += 2) {
  options.set(process.argv[index], process.argv[index + 1]);
}
const candidateRoot = resolve(options.get("--candidate-root") ?? "");
const querySetPath = resolve(options.get("--query-set") ?? "");
const outputPath = resolve(options.get("--output") ?? "");
const sampleCount = Number(options.get("--samples") ?? "5");
if (!options.get("--candidate-root") || !options.get("--query-set") || !options.get("--output")
    || !Number.isSafeInteger(sampleCount) || sampleCount < 1 || sampleCount > 30) {
  throw new Error("Usage: --candidate-root PATH --query-set PATH --output PATH [--samples 5]");
}
const sha256 = (value) => createHash("sha256").update(value).digest("hex");
const distRoot = resolve(import.meta.dirname, "../dist");
const workerName = readdirSync(resolve(distRoot, "assets"))
  .find((name) => /^search\.worker-[A-Za-z0-9_-]+\.js$/.test(name));
if (!workerName) throw new Error("Run npm run build before this local measurement.");
const manifest = JSON.parse(readFileSync(resolve(candidateRoot, "manifest.json"), "utf8"));
const queryBytes = readFileSync(querySetPath);
const querySet = JSON.parse(queryBytes.toString("utf8"));
if (!Array.isArray(querySet.queries) || querySet.queries.length < 1) {
  throw new Error("The local query set has no queries.");
}
const shards = {};
for (const shardId of ["europe-core", "europe-coastal"]) {
  const artifact = manifest.artifacts.find((item) => item.artifactId === "settlements-" + shardId);
  if (!artifact) throw new Error("Manifest omits " + shardId);
  const path = resolve(candidateRoot, artifact.path);
  if (!path.startsWith(candidateRoot + sep)) throw new Error("Shard escapes candidate root.");
  const bytes = readFileSync(path);
  if (bytes.length !== artifact.byteSize || sha256(bytes) !== artifact.sha256) {
    throw new Error(shardId + " differs from manifest authority.");
  }
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
  "function makeWorker(){const worker=new Worker('/assets/" + workerName + "',{type:'module'});",
  "worker.onmessage=({data})=>{const item=pending.get(data.token);if(!item)return;",
  "pending.delete(data.token);data.kind==='error'?item.reject(new Error(data.error.message)):item.resolve(data)};return worker}",
  "function request(worker,message){return new Promise((resolve,reject)=>{const token=++sequence;",
  "pending.set(token,{resolve,reject});worker.postMessage({...message,token})})}",
  "globalThis.runMeasurement=async configuration=>{if(!crossOriginIsolated)throw new Error('not isolated');",
  "const initialization=[];for(let i=0;i<configuration.samples;i++){const worker=makeWorker();",
  "const ready=await request(worker,{kind:'initialize',authority:configuration.core});",
  "initialization.push(ready.durationMilliseconds);worker.postMessage({kind:'terminate',token:++sequence})}",
  "const worker=makeWorker();await request(worker,{kind:'initialize',authority:configuration.core});",
  "await request(worker,{kind:'load-shard',authority:configuration.coastal});const memory=[];",
  "if(typeof performance.measureUserAgentSpecificMemory==='function'){try{memory.push((await performance.measureUserAgentSpecificMemory()).bytes)}catch{}}",
  "const query=[];const counts=[];for(const item of configuration.queries){try{await request(worker,{kind:'query',query:item.query});}catch(error){throw new Error('query '+item.id+' failed: '+error.message)}",
  "for(let i=0;i<configuration.samples;i++){const result=await request(worker,{kind:'query',query:item.query});",
  "query.push(result.durationMilliseconds);counts.push([item.id,result.results.length])}}",
  "if(typeof performance.measureUserAgentSpecificMemory==='function'){try{memory.push((await performance.measureUserAgentSpecificMemory()).bytes)}catch{}}",
  "globalThis.liveWorker=worker;return{initialization,query,counts,memory}};",
].join("");
const html = "<!doctype html><meta charset=utf-8><title>Local measurement</title><script type=module>"
  + pageScript + "</script>";

const server = createServer((request, response) => {
  response.setHeader("Cross-Origin-Embedder-Policy", "require-corp");
  response.setHeader("Cross-Origin-Opener-Policy", "same-origin");
  response.setHeader("Cross-Origin-Resource-Policy", "same-origin");
  response.setHeader("Origin-Agent-Cluster", "?1");
  response.setHeader("Content-Encoding", "identity");
  if (request.url === "/") {
    response.setHeader("Content-Type", "text/html; charset=utf-8");
    response.end(html);
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
const percentile = (values, fraction) =>
  [...values].sort((left, right) => left - right)[Math.ceil(values.length * fraction) - 1];
const distribution = (values) => ({
  p50Milliseconds: percentile(values, 0.5),
  p95Milliseconds: percentile(values, 0.95),
  maximumMilliseconds: Math.max(...values),
  sampleCount: values.length,
});
async function workerHeapUsage(browser) {
  const session = await browser.newBrowserCDPSession();
  try {
    const targets = await session.send("Target.getTargets");
    const target = targets.targetInfos.find((item) => item.type === "worker" && item.url.includes(workerName));
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
  const report = {
    schemaVersion: "static-search-local-candidate-measurement-v1",
    recordedAt: new Date().toISOString(),
    dataReleaseId: manifest.dataReleaseId,
    profile: {
      browser: await browser.version(),
      deviceEmulation: "Pixel 7",
      workerV8OldSpaceLimitMiB: 512,
      host: { platform: platform(), release: release(), cpu: cpus()[0]?.model, totalMemoryBytes: totalmem() },
      scope: "local-read-only-candidate",
    },
    limits: { maximumCompressedBytes: 16777216, maximumDecodedBytes: 67108864 },
    artifacts: Object.values(shards).map(({ authority }) => authority.artifact),
    querySet: {
      byteSize: queryBytes.length,
      queryCount: querySet.queries.length,
      sha256: sha256(queryBytes),
      resultCountsSha256: sha256(Buffer.from(JSON.stringify(observed.counts))),
    },
    measurements: {
      initialization: distribution(observed.initialization),
      query: distribution(observed.query),
      memory: {
        measureUserAgentSpecificMemoryBytes: observed.memory,
        cdpRuntimeGetHeapUsage: cdp,
        measuredConservativeUpperBoundBytes,
        caveat: "CDP heap/backing storage and user-agent-specific memory do not equal device RSS; their maximum is retained as a numeric local upper bound.",
      },
    },
    claims: { mobileDevice: false, publication: false, production: false, scientificOutcome: false },
  };
  writeFileSync(outputPath, JSON.stringify(report, null, 2) + "\n", { flag: "wx", mode: 0o600 });
  console.log(JSON.stringify({
    output: basename(outputPath),
    initializationP95Milliseconds: report.measurements.initialization.p95Milliseconds,
    queryP95Milliseconds: report.measurements.query.p95Milliseconds,
    measuredConservativeUpperBoundBytes,
  }));
} finally {
  await browser.close();
  await new Promise((resolvePromise, reject) =>
    server.close((error) => error ? reject(error) : resolvePromise()));
}
