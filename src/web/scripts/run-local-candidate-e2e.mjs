import { spawn } from "node:child_process";
import { Buffer } from "node:buffer";
import { lstatSync, readdirSync, realpathSync } from "node:fs";
import { get } from "node:http";
import { tmpdir } from "node:os";
import { resolve } from "node:path";
import { pathToFileURL } from "node:url";
import { servePrivateCandidate } from "./local-candidate-binding.mjs";

const repositoryRoot = resolve(import.meta.dirname, "../../..");
const webRoot = resolve(repositoryRoot, "src/web");
const fixtureReleaseId = "searise-europe-v1.0.0-20260810-c096aeab4e09";
const fixtureManifest = resolve(
  repositoryRoot,
  "contracts/release/v2/fixtures/browser-release",
  fixtureReleaseId,
  "manifest.json",
);
const fontCss = resolve(
  repositoryRoot,
  "node_modules/@fontsource-variable/instrument-sans/index.css",
);

export function privateOverlayInventory() {
  return readdirSync(tmpdir(), { withFileTypes: true })
    .filter((entry) => entry.isDirectory() && entry.name.startsWith("searise-private-binding-"))
    .map((entry) => {
      const path = resolve(tmpdir(), entry.name);
      const info = lstatSync(path);
      return `${entry.name}:${info.dev}:${info.ino}:${realpathSync(path)}`;
    })
    .sort();
}

function assertNoNewOverlays(before, after) {
  const existing = new Set(before);
  const created = after.filter((identity) => !existing.has(identity));
  if (created.length > 0) {
    throw new Error(`Private Candidate run left residual overlay identities: ${created.join(", ")}`);
  }
}

export async function withOwnedPrivateCandidate({ serve, run }) {
  const before = privateOverlayInventory();
  let active;
  let result;
  let taskError;
  let cleanupError;
  try {
    active = await serve();
    result = await run(active);
  } catch (error) {
    taskError = error;
  } finally {
    try {
      if (active) await active.close();
    } catch (error) {
      cleanupError = error;
    }
    try {
      assertNoNewOverlays(before, privateOverlayInventory());
    } catch (error) {
      cleanupError = cleanupError
        ? new AggregateError([cleanupError, error], "Private Candidate cleanup failed")
        : error;
    }
  }
  if (taskError && cleanupError) {
    throw new AggregateError(
      [taskError, cleanupError],
      "Private Candidate task and cleanup both failed",
    );
  }
  if (cleanupError) throw cleanupError;
  if (taskError) throw taskError;
  return result;
}

function responseBody(origin, path) {
  const target = new URL(origin);
  return new Promise((resolveResponse, rejectResponse) => {
    const request = get(
      {
        hostname: target.hostname,
        path,
        port: target.port,
        protocol: target.protocol,
      },
      (response) => {
        const chunks = [];
        response.on("data", (chunk) => chunks.push(Buffer.from(chunk)));
        response.once("end", () =>
          resolveResponse({ status: response.statusCode, body: Buffer.concat(chunks) }),
        );
      },
    );
    request.once("error", rejectResponse);
  });
}

export async function verifyNormalViteFilesystemBoundary({ candidateRoot, sourceGrid }) {
  const { createServer } = await import("vite");
  const vite = await createServer({
    configFile: resolve(webRoot, "vite.config.ts"),
    root: webRoot,
    logLevel: "error",
    server: { host: "127.0.0.1", port: 0, strictPort: false },
  });
  try {
    await vite.listen();
    const address = vite.httpServer?.address();
    if (!address || typeof address === "string") throw new Error("Vite did not bind a TCP port");
    const origin = `http://127.0.0.1:${address.port}`;
    const expected = [
      ["/", "<!doctype html"],
      ["/@vite/client", "import"],
      ["/src/main.tsx", "createRoot"],
      [`/@fs${fontCss}`, "@font-face"],
      [`/@fs${fixtureManifest}`, fixtureReleaseId],
    ];
    for (const [path, marker] of expected) {
      const response = await responseBody(origin, path);
      if (response.status !== 200 || !response.body.toString("utf8").includes(marker)) {
        throw new Error(`Required Vite dev resource failed: ${path} (${response.status})`);
      }
    }

    const candidateManifest = resolve(candidateRoot, "manifest.json");
    const forbidden = [
      encodeURI(`/@fs${candidateManifest}`),
      encodeURI(`/@fs${sourceGrid}`),
      `/@fs/${encodeURIComponent(candidateManifest)}`,
      `/@fs/${encodeURIComponent(sourceGrid)}`,
      `/@fs/%2e%2e/${encodeURIComponent(candidateManifest)}`,
      `/%40fs/%252e%252e/${encodeURIComponent(sourceGrid)}`,
    ];
    for (const path of forbidden) {
      const response = await responseBody(origin, path);
      if (![400, 403, 404].includes(response.status)) {
        throw new Error(`Vite exposed a forbidden local path: ${path} (${response.status})`);
      }
    }
  } finally {
    await vite.close();
  }
}

function runPlaywright() {
  const cli = resolve(repositoryRoot, "node_modules/@playwright/test/cli.js");
  return new Promise((resolveRun, rejectRun) => {
    const child = spawn(
      process.execPath,
      [cli, "test", "--config", "playwright.private-candidate.config.ts"],
      { cwd: webRoot, env: process.env, stdio: "inherit" },
    );
    const forwardInterrupt = () => child.kill("SIGINT");
    const forwardTerminate = () => child.kill("SIGTERM");
    process.once("SIGINT", forwardInterrupt);
    process.once("SIGTERM", forwardTerminate);
    child.once("error", rejectRun);
    child.once("exit", (code, signal) => {
      process.removeListener("SIGINT", forwardInterrupt);
      process.removeListener("SIGTERM", forwardTerminate);
      if (code === 0) resolveRun();
      else rejectRun(new Error(`Private Playwright exited with ${signal ?? `code ${code}`}`));
    });
  });
}

async function main() {
  const candidateRoot = process.env.SEARISE_LOCAL_CANDIDATE_ROOT;
  const sourceGrid = process.env.SEARISE_LOCAL_SOURCE_GRID;
  if (!candidateRoot || !sourceGrid) {
    throw new Error(
      "Set explicit SEARISE_LOCAL_CANDIDATE_ROOT and SEARISE_LOCAL_SOURCE_GRID absolute paths.",
    );
  }
  await verifyNormalViteFilesystemBoundary({ candidateRoot, sourceGrid });
  await withOwnedPrivateCandidate({
    serve: () =>
      servePrivateCandidate({
        candidateRoot,
        sourceGrid,
        port: process.env.SEARISE_LOCAL_PORT,
      }),
    run: runPlaywright,
  });
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  await main();
}
