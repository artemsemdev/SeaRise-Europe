// @vitest-environment node

import { createHash } from "node:crypto";
import fs, { mkdtempSync, mkdirSync, readFileSync, statSync, symlinkSync, writeFileSync } from "node:fs";
import { syncBuiltinESMExports } from "node:module";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { spawnSync } from "node:child_process";
import { brotliCompressSync, brotliDecompressSync, constants as zlibConstants } from "node:zlib";
import { describe, expect, it } from "vitest";
import {
  BrowserShardError,
  DEFAULT_SHARD_LIMITS,
  SHARD_FILENAMES,
  SHARD_RECEIPT_FILENAME,
  buildBrowserSearchShards,
  decodeBrowserShard,
  mergeCoreFirst,
  searchBrowserShard,
  validateBrowserSearchShards,
} from "./browser-shards";

const fixture = resolve(process.cwd(), "src/search/shards/fixtures/projection.synthetic.ndjson");
const temporary = () => mkdtempSync(join(tmpdir(), "searise-browser-shards-"));
const canonicalBrotli = (raw: Buffer) => brotliCompressSync(raw, { params: {
  [zlibConstants.BROTLI_PARAM_MODE]: zlibConstants.BROTLI_MODE_TEXT,
  [zlibConstants.BROTLI_PARAM_QUALITY]: 11,
  [zlibConstants.BROTLI_PARAM_SIZE_HINT]: raw.length,
} });

function withFsPatch<T>(patch: Record<string, unknown>, action: () => T): T {
  const mutable = fs as unknown as Record<string, unknown>;
  const originals = Object.fromEntries(Object.keys(patch).map((key) => [key, mutable[key]]));
  Object.assign(mutable, patch); syncBuiltinESMExports();
  try { return action(); } finally { Object.assign(mutable, originals); syncBuiltinESMExports(); }
}

function build(): { output: string; core: Buffer; coastal: Buffer } {
  const output = temporary();
  buildBrowserSearchShards(fixture, output);
  return {
    output,
    core: readFileSync(join(output, SHARD_FILENAMES["europe-core"])),
    coastal: readFileSync(join(output, SHARD_FILENAMES["europe-coastal"])),
  };
}

describe("receipt-bound browser search shards", () => {
  it("builds deterministic Brotli MiniSearch shards with exact false claims", () => {
    const first = build();
    const second = build();
    expect(first.core).toEqual(second.core);
    expect(first.coastal).toEqual(second.coastal);
    expect(validateBrowserSearchShards(fixture, first.output)).toMatchObject({
      "europe-core": { recordCount: 2 },
      "europe-coastal": { recordCount: 2 },
    });

    const core = decodeBrowserShard(first.core, "europe-core");
    expect(core.engine).toEqual({
      engineId: "minisearch", packageVersion: "7.2.0", serializationVersion: "minisearch-json-v1",
    });
    expect(core.source).toMatchObject({
      spatialDatabaseSha256: "a".repeat(64), spatialReceiptSha256: "b".repeat(64),
    });
    expect(core.records.map(({ placeId }) => placeId)).toEqual(["geonames:101", "geonames:104"]);
    expect([
      core.productionClaim, core.publicationClaim, core.publicationEligible,
      core.ownerApprovalClaim, core.scientificApprovalClaim, core.canonicalGeometryClaim,
      core.hazardExtentClaim, core.signingClaim,
    ]).toEqual(Array(8).fill(false));
  });

  it("restores both indexes and merges core first without duplicate place IDs", () => {
    const built = build();
    const core = decodeBrowserShard(built.core, "europe-core");
    const coastal = decodeBrowserShard(built.coastal, "europe-coastal");
    expect(searchBrowserShard(core, "alpha alt").map(({ placeId }) => placeId))
      .toEqual(["geonames:101"]);
    const coreMatches = searchBrowserShard(core, "charlie");
    const coastalMatches = searchBrowserShard(coastal, "charlie");
    expect(mergeCoreFirst(coreMatches, coastalMatches, 5).map(({ placeId }) => placeId))
      .toEqual(["geonames:104"]);
    expect(() => mergeCoreFirst([...coreMatches, ...coreMatches], coastalMatches, 5))
      .toThrow(/core results contain a duplicate/);
  });

  it("rejects incompatible shard format and changed exact bytes", () => {
    const built = build();
    const raw = brotliDecompressSync(built.core).toString("utf8");
    const incompatible = canonicalBrotli(Buffer.from(raw.replace(
      "settlement-browser-search-shard-v1", "settlement-browser-search-shard-v2"
    )));
    expect(() => decodeBrowserShard(incompatible, "europe-core")).toThrow(/format/);

    writeFileSync(join(built.output, SHARD_FILENAMES["europe-core"]), incompatible);
    expect(() => validateBrowserSearchShards(fixture, built.output)).toThrow(/exact projection/);
  });

  it.each(["duplicate", "reordered", "footer", "schema"])(
    "rejects %s projection drift before writing outputs",
    (mutation) => {
      const lines = readFileSync(fixture, "utf8").trimEnd().split("\n");
      if (mutation === "duplicate") lines.splice(2, 0, lines[1]);
      if (mutation === "reordered") [lines[1], lines[2]] = [lines[2], lines[1]];
      if (mutation === "footer") lines[lines.length - 1] = lines.at(-1)!.replace('"recordCount":3', '"recordCount":4');
      if (mutation === "schema") lines[0] = lines[0].replace(PROJECTION_VERSION, "unknown-projection-v1");
      const root = temporary();
      const projection = join(root, "projection.ndjson");
      const output = join(root, "output");
      mkdirSync(output);
      writeFileSync(projection, `${lines.join("\n")}\n`);
      expect(() => buildBrowserSearchShards(projection, output)).toThrow(BrowserShardError);
      expect(() => statSync(join(output, SHARD_FILENAMES["europe-core"]))).toThrow();
    }
  );

  it("enforces bounded input and rejects symlinks and existing outputs", () => {
    const root = temporary();
    const linked = join(root, "projection.ndjson");
    symlinkSync(fixture, linked);
    expect(() => buildBrowserSearchShards(linked, root)).toThrow(/non-symlink/);
    expect(() => buildBrowserSearchShards(fixture, root, {
      ...DEFAULT_SHARD_LIMITS,
      maxProjectionBytes: statSync(fixture).size - 1,
    })).toThrow(/byte limit/);

    const existing = join(root, SHARD_FILENAMES["europe-core"]);
    writeFileSync(existing, "preserve");
    expect(() => buildBrowserSearchShards(fixture, root)).toThrow(/overwrite/);
    expect(readFileSync(existing, "utf8")).toBe("preserve");
    expect(() => statSync(join(root, SHARD_FILENAMES["europe-coastal"]))).toThrow();
  });

  it("rejects same-inode source mutation and staged-file substitution", () => {
    const root = temporary(); const projection = join(root, "projection.ndjson");
    writeFileSync(projection, readFileSync(fixture)); mkdirSync(join(root, "source-output"));
    const originalRead = fs.readSync; let changed = false;
    withFsPatch({ readSync: (...args: Parameters<typeof fs.readSync>) => {
      const length = originalRead(...args);
      if (!changed && length) { changed = true; const bytes = readFileSync(projection);
        const altered = Buffer.from(bytes); altered[10] ^= 1; writeFileSync(projection, altered);
        writeFileSync(projection, bytes); fs.utimesSync(projection, new Date(), new Date(Date.now() + 1000)); }
      return length;
    } }, () => expect(() => buildBrowserSearchShards(projection, join(root, "source-output")))
      .toThrow(/changed while read/));

    const output = join(root, "temp-output"); mkdirSync(output); const originalLink = fs.linkSync;
    withFsPatch({ linkSync: (source: string, destination: string) => {
      fs.unlinkSync(source); writeFileSync(source, "foreign"); originalLink(source, destination);
    } }, () => expect(() => buildBrowserSearchShards(fixture, output)).toThrow(/inode was replaced/));
    expect(readFileSync(join(output, SHARD_FILENAMES["europe-core"]), "utf8")).toBe("foreign");
    expect(() => statSync(join(output, SHARD_RECEIPT_FILENAME))).toThrow();
  });

  it("fails on output-directory displacement while preserving its replacement", () => {
    const root = temporary(); const output = join(root, "output"); const moved = join(root, "moved");
    mkdirSync(output); const originalLink = fs.linkSync; let links = 0;
    withFsPatch({ linkSync: (source: string, destination: string) => {
      originalLink(source, destination); if (++links === 2) { fs.renameSync(output, moved);
        mkdirSync(output); writeFileSync(join(output, "foreign"), "preserve"); }
    } }, () => expect(() => buildBrowserSearchShards(fixture, output)).toThrow(/publication failed/));
    expect(readFileSync(join(output, "foreign"), "utf8")).toBe("preserve");
    expect(() => statSync(join(output, SHARD_RECEIPT_FILENAME))).toThrow();
  });

  it("exposes completion last and durably rolls back owned outputs", () => {
    const output = temporary(); const originalLink = fs.linkSync; let incomplete = 0; let links = 0;
    withFsPatch({ linkSync: (source: string, destination: string) => {
      originalLink(source, destination); if (++links < 3) {
        expect(() => validateBrowserSearchShards(fixture, output)).toThrow(); incomplete++;
      }
    } }, () => buildBrowserSearchShards(fixture, output));
    expect(incomplete).toBe(2); expect(statSync(join(output, SHARD_RECEIPT_FILENAME)).isFile()).toBe(true);

    const rollback = temporary(); let directorySyncs = 0; links = 0; const originalFsync = fs.fsyncSync;
    withFsPatch({ fsyncSync: (descriptor: number) => { if (fs.fstatSync(descriptor).isDirectory()) directorySyncs++;
      originalFsync(descriptor); }, linkSync: (source: string, destination: string) => {
      if (++links === 2) throw new Error("injected link failure"); originalLink(source, destination);
    } }, () => expect(() => buildBrowserSearchShards(fixture, rollback)).toThrow(/injected link failure/));
    expect(directorySyncs).toBeGreaterThan(0);
    for (const name of [...Object.values(SHARD_FILENAMES), SHARD_RECEIPT_FILENAME]) {
      expect(() => statSync(join(rollback, name))).toThrow();
    }
  });

  it("rejects alternate Brotli parameters and reordered records", () => {
    const built = build(); const raw = brotliDecompressSync(built.core);
    const alternate = brotliCompressSync(raw, { params: {
      [zlibConstants.BROTLI_PARAM_MODE]: zlibConstants.BROTLI_MODE_TEXT,
      [zlibConstants.BROTLI_PARAM_QUALITY]: 4,
    } });
    expect(() => decodeBrowserShard(alternate, "europe-core")).toThrow(/canonical quality-11/);
    const value = JSON.parse(raw.toString("utf8")); value.records.reverse();
    value.records.forEach((record: { ordinal: number }, index: number) => { record.ordinal = index + 1; });
    value.recordsSha256 = createHash("sha256").update(JSON.stringify(value.records)).digest("hex");
    expect(() => decodeBrowserShard(canonicalBrotli(Buffer.from(JSON.stringify(value))), "europe-core"))
      .toThrow(/record values differ/);
  });

  it("provides build and validation CLI commands", () => {
    const output = temporary();
    const script = resolve(process.cwd(), "scripts/build-settlement-search-shards.ts");
    for (const command of ["build", "validate"]) {
      const result = spawnSync(process.execPath, [
        "--import", "tsx", script, command,
        "--projection", fixture, "--output-dir", output,
      ], { encoding: "utf8" });
      expect(result.status, result.stderr).toBe(0);
      expect(JSON.parse(result.stdout)).toHaveProperty("europe-core");
    }
  });
});

const PROJECTION_VERSION = "settlement-search-projection-v1";
