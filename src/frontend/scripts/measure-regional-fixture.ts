/** Measure exact lookup and byte-range behavior on the blocked real-source fixture. */

import { createHash } from "node:crypto";
import { readFileSync, writeFileSync } from "node:fs";
import { createServer } from "node:http";
import { cpus, freemem, platform, release, totalmem } from "node:os";
import { resolve } from "node:path";
import { performance } from "node:perf_hooks";
import { once } from "node:events";

import { RegionalFixture } from "../src/lib/regional-fixture/reference-reader";

const repoRoot = resolve(process.argv[2] ?? process.cwd());
const fixtureDirectory = resolve(repoRoot, "src/pipeline/fixtures/regional");
const archivePath = resolve(fixtureDirectory, "copernicus-dem-window.cog.tif");
const outputPath = resolve(fixtureDirectory, "delivery-measurements.json");
const archive = readFileSync(archivePath);
const fixtureDocument = JSON.parse(
  readFileSync(resolve(fixtureDirectory, "lookup-fixture.json"), "utf8"),
);
const golden = JSON.parse(
  readFileSync(resolve(fixtureDirectory, "golden-vectors.json"), "utf8"),
);

interface RangeMeasurement {
  label: string;
  requestedRange: string;
  status: number;
  contentRange: string | null;
  responseBytes: number;
  exactBytes: boolean;
  elapsedMilliseconds: number;
}

function percentile(values: number[], fraction: number): number {
  const sorted = [...values].sort((left, right) => left - right);
  return sorted[Math.min(sorted.length - 1, Math.floor(sorted.length * fraction))];
}

async function measureLookup() {
  const parseStarted = performance.now();
  const fixture = await RegionalFixture.parse(fixtureDocument);
  const parseMilliseconds = performance.now() - parseStarted;
  const vector = golden.vectors[0];
  const samples: number[] = [];
  for (let index = 0; index < 10_000; index += 1) {
    const started = performance.now();
    const result = fixture.lookup(
      vector.longitude,
      vector.latitude,
      vector.scenario,
      vector.horizon,
    );
    samples.push(performance.now() - started);
    if (result.state !== vector.expectedState) throw new Error("lookup result drifted");
  }
  return {
    parseMilliseconds: Number(parseMilliseconds.toFixed(6)),
    warmIterations: samples.length,
    warmMedianMilliseconds: Number(percentile(samples, 0.5).toFixed(6)),
    warmP95Milliseconds: Number(percentile(samples, 0.95).toFixed(6)),
  };
}

async function measureRanges() {
  let requestCount = 0;
  const server = createServer((request, response) => {
    requestCount += 1;
    const match = /^bytes=(\d+)-(\d+)$/.exec(request.headers.range ?? "");
    response.setHeader("Accept-Ranges", "bytes");
    response.setHeader("Cache-Control", "public, max-age=31536000, immutable");
    response.setHeader("Content-Type", "image/tiff");
    if (!match) {
      response.writeHead(200, { "Content-Length": archive.length });
      response.end(archive);
      return;
    }
    const start = Number(match[1]);
    const end = Math.min(Number(match[2]), archive.length - 1);
    const body = archive.subarray(start, end + 1);
    response.writeHead(206, {
      "Content-Length": body.length,
      "Content-Range": `bytes ${start}-${end}/${archive.length}`,
    });
    response.end(body);
  });
  server.listen(0, "127.0.0.1");
  await once(server, "listening");
  const address = server.address();
  if (!address || typeof address === "string") throw new Error("server address unavailable");
  const url = `http://127.0.0.1:${address.port}/fixture.tif`;

  const ranges = [
    { label: "cold-header", start: 0, end: Math.min(16_383, archive.length - 1) },
    { label: "cold-tail", start: Math.max(0, archive.length - 16_384), end: archive.length - 1 },
    { label: "warm-header", start: 0, end: Math.min(16_383, archive.length - 1) },
  ];
  const measurements: RangeMeasurement[] = [];
  try {
    for (const range of ranges) {
      const requestedRange = `bytes=${range.start}-${range.end}`;
      const started = performance.now();
      const response = await fetch(url, { headers: { Range: requestedRange } });
      const body = Buffer.from(await response.arrayBuffer());
      const elapsedMilliseconds = performance.now() - started;
      measurements.push({
        label: range.label,
        requestedRange,
        status: response.status,
        contentRange: response.headers.get("content-range"),
        responseBytes: body.length,
        exactBytes: body.equals(archive.subarray(range.start, range.end + 1)),
        elapsedMilliseconds: Number(elapsedMilliseconds.toFixed(6)),
      });
    }
  } finally {
    server.close();
    await once(server, "close");
  }
  return { requestCount, measurements };
}

async function main() {
  const lookup = await measureLookup();
  const ranges = await measureRanges();
  if (ranges.measurements.some((item) => item.status !== 206 || !item.exactBytes)) {
    throw new Error("reference profile failed exact HTTP byte-range delivery");
  }
  const document = {
    schemaVersion: 1,
    fixtureId: golden.fixtureId,
    measuredAt: new Date().toISOString(),
    scientificClassificationStatus: "blocked",
    referenceProfile: {
      runtime: process.version,
      operatingSystem: `${platform()} ${release()}`,
      architecture: process.arch,
      cpu: cpus()[0]?.model ?? "unknown",
      totalMemoryBytes: totalmem(),
      freeMemoryBytesAtStart: freemem(),
      transport: "Node fetch against loopback HTTP/1.1 immutable static server",
    },
    artifacts: {
      cogByteSize: archive.length,
      cogSha256: createHash("sha256").update(archive).digest("hex"),
      pmtiles: { status: "not-generated", reason: "scientific classification gate blocked" },
    },
    lookup,
    byteRanges: ranges,
    interpretation: {
      supportsExactCogRangesOnReferenceProfile: true,
      supportsProductionNetworkLatencyClaim: false,
      supportsPmtilesClaim: false,
    },
  };
  writeFileSync(outputPath, `${JSON.stringify(document, null, 2)}\n`, "utf8");
  process.stdout.write(`${JSON.stringify(document, null, 2)}\n`);
}

void main().catch((error: unknown) => {
  process.stderr.write(`${String(error)}\n`);
  process.exitCode = 1;
});
