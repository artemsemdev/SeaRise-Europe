import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { mkdtempSync, mkdirSync, readFileSync, rmSync, symlinkSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { test } from "node:test";
import { createOutput, DATA_IDENTITIES, dataIdentities, inventory, parseOptions, verifyCandidate } from "./candidate.mjs";

test("CLI refuses inherited overrides before reading data and never prints their values", () => {
  const result = spawnSync(process.execPath, [resolve(import.meta.dirname, "demo.mjs"), "preflight", "--data-root", "/absent-demo-data"],
    { encoding: "utf8", env: { ...process.env, SEARISE_TEST_OVERRIDE: "private-test-sentinel" } });
  assert.equal(result.status, 1);
  assert.match(result.stderr, /Unset SEARISE_\*/);
  assert.ok(!`${result.stdout}${result.stderr}`.includes("private-test-sentinel"));
});

test("CLI rejects unknown, repeated, missing, relative and invalid port options", () => {
  for (const args of [["--unknown", "x"], ["--data-root"], ["--data-root", "x"],
    ["--port", "0"], ["--port", "4181x"], ["--port", "65536"],
    ["--data-root", "/x", "--data-root", "/y"]]) {
    assert.throws(() => parseOptions(args));
  }
  assert.deepEqual(parseOptions(["--data-root", "/x", "--port", "4181"]), { "data-root": "/x", port: 4181 });
});

test("preparation confines outputs and never overwrites a candidate or follows parent links", () => {
  const root = mkdtempSync(join(tmpdir(), "searise-demo-test-"));
  try {
    assert.throws(() => createOutput(root, join(root, "outside")), /beneath/);
    const output = join(root, ".cache/demo-candidates/first");
    createOutput(root, output);
    writeFileSync(join(output, "preserve"), "original");
    assert.throws(() => createOutput(root, output));
    assert.equal(readFileSync(join(output, "preserve"), "utf8"), "original");
    symlinkSync(output, join(root, ".cache/demo-candidates/link"));
    assert.throws(() => createOutput(root, join(root, ".cache/demo-candidates/link/nested")), /real directory/);
    assert.throws(() => createOutput(root, join(root, ".cache/demo-candidates/link")));
  } finally { rmSync(root, { recursive: true, force: true }); }
});

test("data identities reject manifest and parent symlink escapes without storing private paths", () => {
  const root = mkdtempSync(join(tmpdir(), "searise-demo-test-"));
  try {
    for (const name of DATA_IDENTITIES) {
      mkdirSync(join(root, name, ".."), { recursive: true });
      writeFileSync(join(root, name), "{}");
    }
    const identities = dataIdentities(root);
    assert.equal(identities.length, DATA_IDENTITIES.length);
    assert.ok(!JSON.stringify(identities).includes(root));
    rmSync(join(root, "manifest.json"));
    symlinkSync(join(root, "context/manifest.json"), join(root, "manifest.json"));
    assert.throws(() => dataIdentities(root), /symbolic link/);
    rmSync(join(root, "manifest.json"));
    writeFileSync(join(root, "manifest.json"), "{}");
    rmSync(join(root, "context"), { recursive: true });
    symlinkSync(join(root, "basemap"), join(root, "context"));
    assert.throws(() => dataIdentities(root), /symbolic link/);
  } finally { rmSync(root, { recursive: true, force: true }); }
});

test("candidate verifies inventory, source, edition, data and private-only disposition", () => {
  const root = mkdtempSync(join(tmpdir(), "searise-demo-test-"));
  const app = join(root, "app");
  mkdirSync(app);
  const html = '<meta name="searise-atlas-edition" content="real-local" />';
  writeFileSync(join(app, "index.html"), html);
  const sourceRevision = "a".repeat(40);
  writeFileSync(join(app, "build-identity.json"), JSON.stringify({ appBuildId: `demo-${sourceRevision}` }));
  const identities = [{ path: "manifest.json", sha256: "b".repeat(64) }];
  const manifest = { schemaVersion: "local-demo-candidate-v1", status: "private-local-demo",
    publicPromotionAuthorized: false, mvpRelease: false, atlasEdition: "real-local",
    sourceRevision, dataIdentities: identities, appInventory: inventory(app) };
  const write = (value = manifest) => writeFileSync(join(root, "candidate.json"), JSON.stringify(value));
  try {
    write();
    verifyCandidate(root, sourceRevision, identities);
    assert.throws(() => verifyCandidate(root, "c".repeat(40), identities), /source revision/);
    assert.throws(() => verifyCandidate(root, sourceRevision, []), /data identity/);
    for (const change of [{ publicPromotionAuthorized: true }, { mvpRelease: true },
      { atlasEdition: "synthetic-fixture" }, { status: "public" }]) {
      write({ ...manifest, ...change });
      assert.throws(() => verifyCandidate(root, sourceRevision, identities), /private local demo/);
    }
    write();
    writeFileSync(join(app, "unexpected.txt"), "extra");
    assert.throws(() => verifyCandidate(root, sourceRevision, identities), /inventory/);
    rmSync(join(app, "unexpected.txt"));
    writeFileSync(join(app, "index.html"), html.replace("real-local", "synthetic-fixture"));
    assert.throws(() => verifyCandidate(root, sourceRevision, identities), /inventory/);
    write({ ...manifest, appInventory: inventory(app) });
    assert.throws(() => verifyCandidate(root, sourceRevision, identities), /real-local/);
    symlinkSync(join(root, "candidate.json"), join(app, "leak"));
    assert.throws(() => inventory(app), /symbolic link/);
    assert.ok(!readFileSync(join(root, "candidate.json"), "utf8").includes(root));
  } finally { rmSync(root, { recursive: true, force: true }); }
});
