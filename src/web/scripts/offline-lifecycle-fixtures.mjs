import { spawnSync } from "node:child_process";
import { mkdtempSync, lstatSync, readFileSync, readdirSync, realpathSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { basename, isAbsolute, join, relative, resolve, sep } from "node:path";
import { validateApplicationBuildIdentity } from "./application-build-identity.mjs";
import { assertSameBuildIdentity, validateBuildIdentity } from "./build-identity.mjs";
import { extractEmbeddedPrecachePayload } from "./service-worker-precache.mjs";

export const OFFLINE_LIFECYCLE_RELEASE_ID = "searise-europe-v1.0.0-20260810-c096aeab4e09";
export const OFFLINE_LIFECYCLE_DEPLOYMENTS = Object.freeze({
  A: Object.freeze({ label: "A", appBuildId: "phase2-lifecycle-a" }),
  B: Object.freeze({ label: "B", appBuildId: "phase2-lifecycle-b" }),
  C: Object.freeze({ label: "C", appBuildId: "phase2-lifecycle-c" }),
});

function safeTemporaryRoot(value) {
  if (typeof value !== "string" || !isAbsolute(value)) throw new Error("Lifecycle fixture root must be absolute.");
  const temporary = realpathSync(tmpdir());
  const root = realpathSync(value);
  const child = relative(temporary, root);
  if (!child || child === ".." || child.startsWith(`..${sep}`) || !basename(root).startsWith("searise-offline-lifecycle-")) {
    throw new Error("Lifecycle fixture root is not an owned temporary directory.");
  }
  if (lstatSync(root).isSymbolicLink()) throw new Error("Lifecycle fixture root cannot be a symbolic link.");
  return root;
}

function files(root, directory = root) {
  return readdirSync(directory).flatMap((name) => {
    const path = join(directory, name);
    const metadata = lstatSync(path);
    if (metadata.isSymbolicLink()) throw new Error(`Lifecycle deployment contains a symlink: ${relative(root, path)}`);
    if (metadata.isDirectory()) return files(root, path);
    if (!metadata.isFile()) throw new Error(`Lifecycle deployment contains a non-file: ${relative(root, path)}`);
    return [path];
  });
}

export function validateOfflineLifecycleDeployment(root, expected) {
  files(root);
  const identity = validateBuildIdentity(JSON.parse(readFileSync(join(root, "build-identity.json"), "utf8")));
  if (
    identity.appBuildId !== expected.appBuildId ||
    identity.dataReleaseId !== OFFLINE_LIFECYCLE_RELEASE_ID ||
    identity.releaseDisposition !== "synthetic-fixture"
  ) throw new Error(`Lifecycle deployment ${expected.label} has the wrong build identity.`);
  validateApplicationBuildIdentity({ dist: root, expectedIdentity: identity });
  const embedded = extractEmbeddedPrecachePayload(readFileSync(join(root, "service-worker.js"), "utf8"));
  assertSameBuildIdentity(identity, embedded.buildIdentity, `lifecycle deployment ${expected.label} worker`);
  const report = JSON.parse(readFileSync(join(root, "build-report.json"), "utf8"));
  assertSameBuildIdentity(identity, {
    schemaVersion: report.schemaVersion,
    appBuildId: report.appBuildId,
    dataReleaseId: report.dataReleaseId,
    releaseDisposition: report.releaseDisposition,
    manifestPath: report.manifestPath,
  }, `lifecycle deployment ${expected.label} report`);
  if (
    report.serviceWorker?.appBuildId !== identity.appBuildId ||
    report.serviceWorker?.dataReleaseId !== identity.dataReleaseId ||
    report.serviceWorker?.precacheSetSha256 !== embedded.precacheSetSha256
  ) throw new Error(`Lifecycle deployment ${expected.label} has a mixed service-worker report.`);
  const manifest = JSON.parse(readFileSync(join(root, identity.manifestPath), "utf8"));
  if (manifest.dataReleaseId !== OFFLINE_LIFECYCLE_RELEASE_ID) {
    throw new Error(`Lifecycle deployment ${expected.label} has the wrong committed fixture release.`);
  }
  return Object.freeze({
    label: expected.label,
    root,
    identity,
    precacheSetSha256: embedded.precacheSetSha256,
  });
}

function cleanEnvironment(environment) {
  return Object.fromEntries(Object.entries(environment).filter(([key]) => !key.startsWith("SEARISE_")));
}

function execute({ command, args, cwd, environment, label }) {
  const result = spawnSync(command, args, { cwd, env: environment, stdio: "inherit" });
  if (result.error) throw new Error(`${label} could not start.`, { cause: result.error });
  if (result.status !== 0) throw new Error(`${label} failed with exit status ${result.status}.`);
}

function buildCommands(webRoot, outputRoot) {
  return [
    [process.execPath, [resolve(webRoot, "../../node_modules/vite/bin/vite.js"), "build"], "Vite build"],
    [process.execPath, [resolve(webRoot, "scripts/finalize-service-worker.mjs")], "service-worker finalization"],
    [process.execPath, [resolve(webRoot, "scripts/check-target-content.mjs"), "--built", outputRoot], "target-content scan"],
    [process.execPath, [resolve(webRoot, "scripts/inspect-build.mjs")], "static build inspection"],
  ];
}

export function prepareOfflineLifecycleFixtures({
  webRoot = resolve(import.meta.dirname, ".."),
  environment = process.env,
  run = execute,
  createRoot = () => mkdtempSync(join(tmpdir(), "searise-offline-lifecycle-")),
} = {}) {
  const lifecycleRoot = safeTemporaryRoot(createRoot());
  const baseEnvironment = cleanEnvironment(environment);
  const deployments = new Map();
  try {
    for (const expected of Object.values(OFFLINE_LIFECYCLE_DEPLOYMENTS)) {
      const outputRoot = join(lifecycleRoot, expected.label);
      const buildEnvironment = {
        ...baseEnvironment,
        SEARISE_APP_BUILD_ID: expected.appBuildId,
        SEARISE_DATA_RELEASE_ID: OFFLINE_LIFECYCLE_RELEASE_ID,
        SEARISE_RELEASE_DISPOSITION: "synthetic-fixture",
        SEARISE_LIFECYCLE_BUILD: "1",
        SEARISE_LIFECYCLE_ROOT: lifecycleRoot,
        SEARISE_WEB_DIST_ROOT: outputRoot,
      };
      for (const [command, args, name] of buildCommands(webRoot, outputRoot)) {
        run({ command, args, cwd: webRoot, environment: buildEnvironment, label: `${expected.label} ${name}` });
      }
      deployments.set(expected.label, validateOfflineLifecycleDeployment(outputRoot, expected));
    }
    const digests = new Set([...deployments.values()].map(({ precacheSetSha256 }) => precacheSetSha256));
    if (digests.size !== deployments.size) throw new Error("Lifecycle deployments do not have distinct sealed precache identities.");
    let removed = false;
    return Object.freeze({
      root: lifecycleRoot,
      deployments,
      cleanup() {
        if (removed) return;
        removed = true;
        rmSync(lifecycleRoot, { force: true, recursive: true });
      },
    });
  } catch (error) {
    rmSync(lifecycleRoot, { force: true, recursive: true });
    throw error;
  }
}
