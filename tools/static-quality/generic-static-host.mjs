import { spawn } from "node:child_process";
import { dirname, resolve } from "node:path";
import { setTimeout } from "node:timers";
import { fileURLToPath } from "node:url";

const DEFAULT_HOST = "127.0.0.1";
const DEFAULT_PORT = 4174;

export async function startGenericStaticHost({ dist, host = DEFAULT_HOST, port = DEFAULT_PORT }) {
  const sirvBin = resolve(dirname(fileURLToPath(import.meta.resolve("sirv-cli/package.json"))), "bin.js");
  const environment = { ...process.env };
  delete environment.HOST;
  delete environment.PORT;
  const child = spawn(
    process.execPath,
    [sirvBin, dist, "--host", host, "--port", String(port), "--quiet", "--etag", "--brotli", "--gzip"],
    { env: environment, stdio: ["ignore", "pipe", "pipe"] },
  );
  let diagnostics = "";
  child.stdout.on("data", (chunk) => { diagnostics += chunk; });
  child.stderr.on("data", (chunk) => { diagnostics += chunk; });
  const origin = `http://${host}:${port}`;
  for (let attempt = 0; attempt < 100; attempt += 1) {
    if (child.exitCode !== null) throw new Error(`generic static server exited early (${child.exitCode}): ${diagnostics}`);
    try {
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
