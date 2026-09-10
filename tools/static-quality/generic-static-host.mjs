import { spawn } from "node:child_process";
import { dirname, resolve } from "node:path";
import { setTimeout } from "node:timers";
import { fileURLToPath } from "node:url";
import { stripVTControlCharacters } from "node:util";

const DEFAULT_HOST = "127.0.0.1";
const DEFAULT_PORT = 0;

export async function startGenericStaticHost({ dist, host = DEFAULT_HOST, port = DEFAULT_PORT }) {
  const sirvBin = resolve(dirname(fileURLToPath(import.meta.resolve("sirv-cli/package.json"))), "bin.js");
  const environment = { ...process.env };
  delete environment.HOST;
  delete environment.PORT;
  const child = spawn(
    process.execPath,
    [sirvBin, dist, "--host", host, "--port", String(port), "--etag", "--brotli", "--gzip"],
    { env: environment, stdio: ["ignore", "pipe", "pipe"] },
  );
  let diagnostics = "";
  child.stdout.on("data", (chunk) => { diagnostics += chunk; });
  child.stderr.on("data", (chunk) => { diagnostics += chunk; });
  let origin;
  for (let attempt = 0; attempt < 100; attempt += 1) {
    if (child.exitCode !== null) throw new Error(`generic static server exited early (${child.exitCode}): ${diagnostics}`);
    // sirv may choose a different free port. Its own readiness output is the
    // authority; probing the requested port can validate an unrelated server.
    const announced = stripVTControlCharacters(diagnostics).match(/- Local:\s+(http:\/\/[^\s]+)/u)?.[1];
    if (announced) {
      const bound = new URL(announced);
      if (bound.hostname !== host) {
        await stopGenericStaticHost(child);
        throw new Error(`generic static server announced an unexpected host: ${announced}`);
      }
      origin = bound.origin;
    }
    try {
      if (!origin) throw new Error("Waiting for the owned static listener");
      const response = await globalThis.fetch(origin);
      if (response.ok) return { child, origin };
    } catch {
      // The child has not bound its loopback socket yet.
    }
    await new Promise((resolvePromise) => setTimeout(resolvePromise, 50));
  }
  child.kill("SIGTERM");
  throw new Error(`generic static server did not become ready: ${diagnostics}`);
}

export async function stopGenericStaticHost(child) {
  if (child.exitCode !== null) return;
  await new Promise((resolvePromise) => {
    child.once("exit", resolvePromise);
    child.kill("SIGTERM");
    setTimeout(() => {
      if (child.exitCode === null) child.kill("SIGKILL");
    }, 2_000).unref();
  });
}
