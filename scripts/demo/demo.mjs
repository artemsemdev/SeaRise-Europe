import { execFileSync } from "node:child_process";
import { cpSync, existsSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { atlasMainRepositoryRoot, createRealLocalAtlas } from "../../src/web/scripts/real-local-atlas.mjs";
import { assertByteAffectingRuntime } from "../../src/web/scripts/search-shard-builder.mjs";
import { createOutput, dataIdentities, inventory, parseOptions, seal, verifyCandidate } from "./candidate.mjs";
import { createLifecycle } from "./lifecycle.mjs";

const repositoryRoot = resolve(import.meta.dirname, "../..");
const webRoot = resolve(repositoryRoot, "src/web");
const [command, ...args] = process.argv.slice(2);
const help = `Private local CoCliCo demonstration candidate; no MVP/scientific/public release claim.
  npm run demo:preflight -- --data-root /absolute/atlas/root [--python /absolute/python]
  npm run demo:prepare -- --data-root /absolute/atlas/root --output /checkout/.cache/demo-candidates/name [--python /absolute/python]
  npm run demo:serve -- --data-root /absolute/atlas/root --candidate /absolute/candidate [--python /absolute/python] [--port 4181]
  npm run demo:test
Prepare requires a clean checkout and pinned Node/npm; existing outputs are never overwritten.
Serve requires the exact clean source commit and matching app/data hashes, bound to 127.0.0.1.
Private datasets stay external; candidate contents are read-only. Run npm ci per architecture.
Use the official Node distribution: matching semver alone may have incompatible Brotli/ICU/zlib.
SEARISE_* and VITE_* overrides and active .env files are rejected; use explicit CLI arguments.
`;
if (args.includes("--help")) { console.log(help); process.exit(0); }
const lifecycle = createLifecycle();

async function localAtlas(options) {
  const runtime = await createRealLocalAtlas({ repositoryRoot, atlasRoot: options["data-root"], spawn: lifecycle.spawn,
    ...(options.python ? { python: options.python } : {}) });
  lifecycle.addCloser(runtime.close);
  if (lifecycle.interrupted) throw new Error("Demo startup interrupted.");
  return runtime;
}

function git(...arguments_) {
  return execFileSync("git", arguments_, { cwd: repositoryRoot, encoding: "utf8" }).trim();
}

function cleanRevision() {
  if (git("status", "--porcelain", "--untracked-files=normal")) throw new Error("Candidate operations require a clean checkout; commit or remove local changes first.");
  return git("rev-parse", "HEAD");
}

function toolchain() {
  assertByteAffectingRuntime();
  const expected = JSON.parse(readFileSync(resolve(repositoryRoot, "package.json"), "utf8")).engines;
  const npm = execFileSync("npm", ["--version"], { encoding: "utf8" }).trim();
  if (process.versions.node !== expected.node || npm !== expected.npm) throw new Error(`Use Node ${expected.node} and npm ${expected.npm}, then npm ci.`);
  return { node: process.versions.node, npm, platform: process.platform, architecture: process.arch,
    brotli: process.versions.brotli, icu: process.versions.icu, unicode: process.versions.unicode, zlib: process.versions.zlib };
}

async function preflight(options) {
  const identities = dataIdentities(options["data-root"]);
  console.log("Checking local adapter and raster integrity; startup hashes the provisioned rasters.");
  const runtime = await localAtlas(options);
  await runtime.close();
  if (JSON.stringify(dataIdentities(options["data-root"])) !== JSON.stringify(identities)) throw new Error("Data identity changed during preflight.");
  return identities;
}

async function main() {
  if (!["preflight", "prepare", "serve"].includes(command)) throw new Error("Unknown command; see --help.");
  const options = parseOptions(args);
  const allowed = { preflight: ["data-root", "python"], prepare: ["data-root", "python", "output"],
    serve: ["data-root", "python", "candidate", "port"] }[command];
  if (Object.keys(options).some((key) => !allowed.includes(key)) || !options["data-root"]
    || (command === "prepare" && !options.output) || (command === "serve" && !options.candidate)) throw new Error("Missing or inapplicable option; see --help.");
  if (Object.keys(process.env).some((key) => /^(SEARISE_|VITE_)/u.test(key))) throw new Error("Unset SEARISE_* and VITE_* overrides; use CLI arguments.");
  for (const root of [repositoryRoot, webRoot]) {
    for (const name of [".env", ".env.local", ".env.real-local", ".env.real-local.local"]) {
      if (existsSync(resolve(root, name))) throw new Error("Active .env files are forbidden for reproducible demo candidates.");
    }
  }
  const versions = toolchain();
  const { preview } = await import("vite"); // Exercise installed native dependencies before starting Python.
  if (command === "preflight") {
    await preflight(options);
    console.log(JSON.stringify({ status: "private-local-demo-preflight-passed", toolchain: versions }));
    return;
  }
  const sourceRevision = cleanRevision();
  if (command === "prepare") {
    const identities = await preflight(options);
    const output = createOutput(repositoryRoot, options.output);
    try {
      execFileSync("npm", ["run", "local:build"], { cwd: repositoryRoot, stdio: "inherit",
        env: { ...process.env, SEARISE_APP_BUILD_ID: `demo-${sourceRevision}` } });
      const dist = resolve(webRoot, "dist");
      inventory(dist); // Reject links/special files before copying any bytes.
      cpSync(dist, resolve(output, "app"), { recursive: true });
      if (cleanRevision() !== sourceRevision) throw new Error("Source changed while building.");
      if (JSON.stringify(dataIdentities(options["data-root"])) !== JSON.stringify(identities)) throw new Error("Data identity changed while building.");
      writeFileSync(resolve(output, "candidate.json"), `${JSON.stringify({
        schemaVersion: "local-demo-candidate-v1", status: "private-local-demo", atlasEdition: "real-local",
        publicPromotionAuthorized: false, mvpRelease: false, sourceRevision, toolchain: versions,
        dataIdentities: identities, appInventory: inventory(resolve(output, "app")),
      }, null, 2)}\n`, { flag: "wx" });
      verifyCandidate(output, sourceRevision, identities);
      seal(output);
      console.log(`Prepared private local demo candidate: ${output}`);
    } catch (error) { rmSync(output, { recursive: true, force: true }); throw error; }
    return;
  }
  const identities = dataIdentities(options["data-root"]);
  const { app } = verifyCandidate(options.candidate, sourceRevision, identities);
  const runtime = await localAtlas(options);
  try {
    if (cleanRevision() !== sourceRevision || JSON.stringify(dataIdentities(options["data-root"])) !== JSON.stringify(identities)) throw new Error("Source or data changed during startup.");
    await preview({ configFile: false, envDir: false, root: webRoot, build: { outDir: app },
      preview: { host: "127.0.0.1", port: options.port ?? 4181, strictPort: true, headers: { "Cache-Control": "no-store", "Content-Encoding": "identity" } },
      plugins: [{ name: "sealed-local-demo", configurePreviewServer(active) {
        lifecycle.addCloser(() => active.close());
        active.middlewares.use(runtime.middleware);
      } }],
    });
    console.log(`Private local demo ${sourceRevision}: http://127.0.0.1:${options.port ?? 4181}`);
    console.log("publicPromotionAuthorized=false mvpRelease=false; stop with Ctrl+C");
  } catch (error) { await lifecycle.close(); throw error; }
}

main().then(() => { if (command !== "serve") lifecycle.dispose(); }, async (error) => {
  const interrupted = lifecycle.interrupted;
  await lifecycle.close();
  lifecycle.dispose();
  if (!interrupted) {
    console.error(error.message.replaceAll(atlasMainRepositoryRoot(repositoryRoot), "<checkout>"));
    process.exitCode = 1;
  }
});
