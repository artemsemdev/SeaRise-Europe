// @vitest-environment node

import { createHash } from "node:crypto";
import { Buffer } from "node:buffer";
import { once } from "node:events";
import { mkdtempSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import {
  OFFLINE_LIFECYCLE_DEPLOYMENTS,
  OFFLINE_LIFECYCLE_RELEASE_ID,
} from "./offline-lifecycle-fixtures.mjs";
import {
  createOfflineLifecycleServer,
  OFFLINE_LIFECYCLE_CONTROL_HEADER,
} from "./offline-lifecycle-server.mjs";

const roots = [];
const servers = [];
const token = "offline-lifecycle-control-token-0001";
const request = globalThis.fetch;

function deployment(expected) {
  const root = mkdtempSync(join(tmpdir(), `searise-server-${expected.label.toLowerCase()}-`));
  roots.push(root);
  const identity = Object.freeze({
    schemaVersion: "1.0.0",
    appBuildId: expected.appBuildId,
    dataReleaseId: OFFLINE_LIFECYCLE_RELEASE_ID,
    releaseDisposition: "synthetic-fixture",
    manifestPath: `/releases/${OFFLINE_LIFECYCLE_RELEASE_ID}/manifest.json`,
  });
  const releaseRoot = join(root, "releases", OFFLINE_LIFECYCLE_RELEASE_ID);
  const bytes = Buffer.from(`range-${expected.label}`);
  mkdirSync(join(root, "assets"), { recursive: true });
  mkdirSync(join(releaseRoot, "analysis"), { recursive: true });
  writeFileSync(join(root, "index.html"), `<h1>${expected.label}</h1>`);
  writeFileSync(join(root, "service-worker.js"), `// ${expected.label}`);
  writeFileSync(join(root, "assets/app-12345678.js"), `export const deployment="${expected.label}";`);
  writeFileSync(join(releaseRoot, "analysis/value.tif"), bytes);
  writeFileSync(join(releaseRoot, "manifest.json"), JSON.stringify({
    dataReleaseId: OFFLINE_LIFECYCLE_RELEASE_ID,
    artifacts: [{
      artifactId: "value",
      role: "analysis-cog",
      path: "analysis/value.tif",
      mediaType: "image/tiff",
      byteSize: bytes.length,
      sha256: createHash("sha256").update(bytes).digest("hex"),
    }],
  }));
  return Object.freeze({ label: expected.label, root, identity, precacheSetSha256: expected.label.toLowerCase().repeat(64) });
}

async function harness({ beforeCreate } = {}) {
  const deployments = new Map(Object.values(OFFLINE_LIFECYCLE_DEPLOYMENTS).map((expected) => [expected.label, deployment(expected)]));
  beforeCreate?.(deployments);
  const created = createOfflineLifecycleServer({
    fixtures: { deployments },
    controlToken: token,
    validateDeployment: (root, expected) => {
      const candidate = deployments.get(expected.label);
      if (candidate.root !== root) throw new Error("unexpected root");
      if (readFileSync(join(root, "index.html"), "utf8") !== `<h1>${expected.label}</h1>`) {
        throw new Error("deployment bytes differ from seal");
      }
      return candidate;
    },
    maxLogEntries: 20,
  });
  servers.push(created.server);
  created.server.listen(0, "127.0.0.1");
  await once(created.server, "listening");
  const address = created.server.address();
  return { ...created, deployments, origin: `http://127.0.0.1:${address.port}` };
}

afterEach(async () => {
  for (const server of servers.splice(0)) {
    if (server.listening) {
      server.close();
      await once(server, "close");
    }
  }
  for (const root of roots.splice(0)) rmSync(root, { force: true, recursive: true });
});

describe("offline lifecycle server", () => {
  it("switches sealed deployments atomically and authenticates controls", async () => {
    const { origin } = await harness();
    expect(await (await request(`${origin}/`)).text()).toContain("A");
    expect((await request(`${origin}/__lifecycle/deployment`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ deployment: "B" }),
    })).status).toBe(403);
    const switched = await request(`${origin}/__lifecycle/deployment`, {
      method: "POST",
      headers: { "content-type": "application/json", [OFFLINE_LIFECYCLE_CONTROL_HEADER]: token },
      body: JSON.stringify({ deployment: "B" }),
    });
    expect(await switched.json()).toMatchObject({ deployment: "B", generation: 2 });
    expect(await (await request(`${origin}/`)).text()).toContain("B");

    const state = await (await request(`${origin}/__lifecycle/state`, {
      headers: { [OFFLINE_LIFECYCLE_CONTROL_HEADER]: token },
    })).json();
    expect(state.requests.map(({ deployment, path, status }) => ({ deployment, path, status }))).toEqual([
      { deployment: "A", path: "/", status: 200 },
      { deployment: "B", path: "/", status: 200 },
    ]);
  });

  it("serves strict cache, worker, byte-range, and path boundaries", async () => {
    const { origin } = await harness();
    const worker = await request(`${origin}/service-worker.js`);
    expect(worker.headers.get("cache-control")).toBe("no-store");
    expect(worker.headers.get("service-worker-allowed")).toBe("/");
    const asset = await request(`${origin}/assets/app-12345678.js`);
    expect(asset.headers.get("cache-control")).toBe("public, max-age=31536000, immutable");

    const path = `/releases/${OFFLINE_LIFECYCLE_RELEASE_ID}/analysis/value.tif`;
    const ranged = await request(`${origin}${path}`, { headers: { range: "bytes=1-4" } });
    expect(ranged.status).toBe(206);
    expect(ranged.headers.get("content-range")).toBe("bytes 1-4/7");
    expect(await ranged.text()).toBe("ange");
    const invalid = await request(`${origin}${path}`, { headers: { range: "bytes=1-2,4-5" } });
    expect(invalid.status).toBe(416);
    expect(invalid.headers.get("content-range")).toBe("bytes */7");
    expect((await request(`${origin}/%255cetc/passwd`)).status).toBe(404);
    expect((await request(`${origin}/unknown/`)).status).toBe(404);
    expect((await request(`${origin}/`, { method: "POST" })).status).toBe(405);
  });

  it("rejects unknown deployment controls without changing authority", async () => {
    const { origin } = await harness();
    const response = await request(`${origin}/__lifecycle/deployment`, {
      method: "POST",
      headers: { "content-type": "application/json", [OFFLINE_LIFECYCLE_CONTROL_HEADER]: token },
      body: JSON.stringify({ deployment: "D" }),
    });
    expect(response.status).toBe(400);
    expect(await (await request(`${origin}/__lifecycle/healthz`)).json()).toMatchObject({ deployment: "A", generation: 1 });
  });

  it("fails closed for byte mutation before startup and before a later switch", async () => {
    await expect(harness({
      beforeCreate(deployments) {
        writeFileSync(join(deployments.get("A").root, "index.html"), "mutated before startup");
      },
    })).rejects.toThrow(/bytes differ/);

    const { origin, deployments } = await harness();
    writeFileSync(join(deployments.get("B").root, "index.html"), "mutated before switch");
    const response = await request(`${origin}/__lifecycle/deployment`, {
      method: "POST",
      headers: { "content-type": "application/json", [OFFLINE_LIFECYCLE_CONTROL_HEADER]: token },
      body: JSON.stringify({ deployment: "B" }),
    });
    expect(response.status).toBe(400);
    expect(await (await request(`${origin}/__lifecycle/healthz`)).json())
      .toMatchObject({ deployment: "A", generation: 1 });
  });
});
