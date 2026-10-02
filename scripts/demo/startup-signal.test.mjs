import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { createHash } from "node:crypto";
import { once } from "node:events";
import { chmodSync, existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { setTimeout } from "node:timers/promises";
import { test } from "node:test";
import { brotliCompressSync } from "node:zlib";
import { DATA_IDENTITIES } from "./candidate.mjs";

function fixture(root) {
  for (const name of DATA_IDENTITIES) {
    mkdirSync(dirname(join(root, name)), { recursive: true });
    writeFileSync(join(root, name), "{}");
  }
  writeFileSync(join(root, "cell.tif"), "x"); // Interpreter stub deliberately never opens raster bytes.
  const input = { file: "cell.tif", bytes: 1, sha256: "a".repeat(64), crs: "EPSG:3035", pixelSizeMeters: [25, 25], bounds: [0, 0, 1, 1] };
  const layers = [2030, 2050, 2100].flatMap((year) => ["protected", "unprotected"].map((protection) => ({
    id: `ssp585-${year}-${protection}`, year, protection, scenario: "ssp585", status: "available", inputs: [input],
  })));
  writeFileSync(join(root, "manifest.json"), JSON.stringify({ version: 2, scenario: "ssp585", condition: "high-tide", bounds: [0, 0, 1, 1], layers,
    source: { name: "Signal test", url: "https://example.org", methodologyUrl: "https://example.org", license: "fixture", notes: ["Not scientific data"] } }));
  const index = brotliCompressSync(JSON.stringify({ schemaVersion: 1, totalPlaces: 1, cities: [["geonames:1", "Test", "XX", "Test", 0, 0, 1, ["test"]]] }));
  writeFileSync(join(root, "context/cities.json.br"), index);
  writeFileSync(join(root, "context/manifest.json"), JSON.stringify({ schemaVersion: 1, totalPlaces: 1,
    index: { file: "cities.json.br", byteSize: index.length, sha256: createHash("sha256").update(index).digest("hex") } }));
}

function alive(pid) {
  try { process.kill(pid, 0); return true; } catch (error) { if (error.code === "ESRCH") return false; throw error; }
}

for (const [signal, ignoresTerm] of [["SIGTERM", false], ["SIGINT", false], ["SIGTERM", true]]) test(`CLI ${signal} during native startup reaps its ${ignoresTerm ? "uncooperative" : "cooperative"} child`, { timeout: 15_000 }, async () => {
  const root = mkdtempSync(join(tmpdir(), "searise-signal-test-"));
  const pidFile = join(root, "pid");
  let launcher;
  let nativePid;
  try {
    fixture(root);
    const python = join(root, "interpreter-stub");
    writeFileSync(python, `#!/usr/bin/env node\nrequire("node:fs").writeFileSync(${JSON.stringify(pidFile)}, String(process.pid));\nprocess.on("SIGTERM", () => ${ignoresTerm ? "{}" : "process.exit(0)"});\nsetInterval(() => {}, 1000);\n`);
    chmodSync(python, 0o755);
    launcher = spawn(process.execPath, [resolve(import.meta.dirname, "demo.mjs"), "preflight", "--data-root", root, "--python", python], { stdio: ["ignore", "pipe", "pipe"] });
    const exited = once(launcher, "exit");
    let output = "";
    launcher.stdout.on("data", (data) => { output += data; });
    launcher.stderr.on("data", (data) => { output += data; });
    const deadline = Date.now() + 10_000;
    while (!existsSync(pidFile) && launcher.exitCode === null && Date.now() < deadline) await setTimeout(20);
    assert.ok(existsSync(pidFile), output);
    nativePid = Number(readFileSync(pidFile, "utf8"));
    assert.ok(alive(nativePid));
    launcher.kill(signal);
    await exited;
    for (let attempt = 0; attempt < 50 && alive(nativePid); attempt++) await setTimeout(20);
    assert.equal(alive(nativePid), false, "launcher orphaned its native child before readiness");
    assert.equal(launcher.exitCode, 0);
  } finally {
    if (launcher?.exitCode === null && launcher?.signalCode === null) launcher.kill("SIGKILL");
    if (nativePid && alive(nativePid)) process.kill(nativePid, "SIGKILL");
    rmSync(root, { recursive: true, force: true });
  }
});
