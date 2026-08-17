import { createHash } from "node:crypto";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { TextEncoder } from "node:util";
import { afterEach, describe, expect, it } from "vitest";
import { validateGenericStaticHost } from "./generic-static-host.mjs";

const roots = [];
afterEach(() => {
  for (const root of roots.splice(0)) rmSync(root, { force: true, recursive: true });
});

function json(value) {
  return new TextEncoder().encode(`${JSON.stringify(value)}\n`);
}

function fixture() {
  const dist = mkdtempSync(join(tmpdir(), "searise-generic-host-test-"));
  roots.push(dist);
  const releaseId = "fixture-release";
  const configBytes = json({ dataReleaseId: releaseId, dataProvenanceClass: "synthetic-fixture" });
  const artifact = {
    path: "config/scenarios.json",
    role: "scenario-config",
    mediaType: "application/json",
    byteSize: configBytes.byteLength,
    sha256: createHash("sha256").update(configBytes).digest("hex"),
  };
  const main = new TextEncoder().encode("console.log('static');\n");
  writeFileSync(join(dist, "build-report.json"), `${JSON.stringify({ assets: [{ path: "assets/main-test.js", bytes: main.byteLength }] })}\n`);
  const responses = new Map([
    ["GET /", new globalThis.Response('<div id="root"></div>', { headers: { "content-type": "text/html" } })],
    ["GET /about/architecture/", new globalThis.Response('<div id="root"></div>', { headers: { "content-type": "text/html" } })],
    ["GET /build-identity.json", new globalThis.Response(json({ dataReleaseId: releaseId, manifestPath: `/releases/${releaseId}/manifest.json` }), { headers: { "content-type": "application/json" } })],
    ["GET /releases/fixture-release/manifest.json", new globalThis.Response(json({ dataReleaseId: releaseId, dataProvenanceClass: "synthetic-fixture", artifacts: [artifact] }), { headers: { "content-type": "application/json" } })],
    ["GET /releases/fixture-release/config/scenarios.json", new globalThis.Response(configBytes, { headers: { "content-type": "application/json" } })],
    ["GET /assets/main-test.js", new globalThis.Response(main, { headers: { "content-encoding": "br", "content-type": "text/javascript" } })],
  ]);
  const request = async (url, init = {}) => {
    const key = `${init.method ?? "GET"} ${url.pathname}`;
    return responses.get(key)?.clone() ?? new globalThis.Response("not found", { status: 404 });
  };
  return { dist, request, responses, configBytes };
}

describe("generic static-host contract", () => {
  it("accepts manifest-authorized release config and static legacy endpoint 404s", async () => {
    const test = fixture();
    await expect(validateGenericStaticHost("https://fixture.test", test.dist, test.request)).resolves.toBeUndefined();
  });

  it("rejects dynamic handling at a versioned legacy endpoint", async () => {
    const test = fixture();
    test.responses.set("POST /v1/assess", new globalThis.Response("dynamic", { status: 200 }));
    await expect(validateGenericStaticHost("https://fixture.test", test.dist, test.request)).rejects.toThrow(
      /POST \/v1\/assess returned 200/u,
    );
  });

  it("rejects a mutated release-scoped config", async () => {
    const test = fixture();
    const mutated = new Uint8Array(test.configBytes);
    mutated[mutated.length - 2] ^= 1;
    test.responses.set(
      "GET /releases/fixture-release/config/scenarios.json",
      new globalThis.Response(mutated, { headers: { "content-type": "application/json" } }),
    );
    await expect(validateGenericStaticHost("https://fixture.test", test.dist, test.request)).rejects.toThrow(
      /hash differs from the release manifest/u,
    );
  });
});
