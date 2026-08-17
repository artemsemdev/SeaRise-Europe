// @vitest-environment node

import { createHash } from "node:crypto";
import { Buffer } from "node:buffer";
import {
  chmodSync, lstatSync, mkdtempSync, mkdirSync, readFileSync, readdirSync, unlinkSync,
  writeFileSync, writeSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import {
  QUERY_TARGET_MILLISECONDS, STARTUP_TARGET_MILLISECONDS, canonicalJson, distribution,
  finalizePerformanceReport, loadPerformanceInputs, parsePerformanceQuerySet,
  performanceReportBytes, publishPerformanceReport, sha256, validatePerformanceReport,
} from "./search-performance-evidence.mjs";

const RELEASE = "searise-europe-v1.0.0-20260817-0123456789ab";
const querySet = {
  corpusScale: "production-candidate", dataProvenanceClass: "real-source",
  queries: [{ id: "exact-name", query: "Málaga" }, { id: "no-match", query: "missing" }],
  schemaVersion: 1,
};
const canonicalBytes = (value, newline = true) => Buffer.from(`${canonicalJson(value)}${newline ? "\n" : ""}`);
const clone = (value) => JSON.parse(JSON.stringify(value));

function candidateFixture() {
  const root = mkdtempSync(resolve(tmpdir(), "search-performance-input-"));
  mkdirSync(resolve(root, "search"), 0o700);
  const shardBytes = { "europe-core": Buffer.from("core"), "europe-coastal": Buffer.from("coastal") };
  const receipt = {
    $schema: "https://artemsemdev.github.io/SeaRise-Europe/contracts/settlements/v4/search-artifact.schema.json",
    complete: true, dataProvenanceClass: "real-source", dataReleaseId: RELEASE,
    formatVersion: "settlement-browser-search-shard-set-v2",
    schemaVersion: "4.0.0", source: { projectionSha256: "1".repeat(64) }, spatialIdentity: { predicate: "covers" },
    shards: Object.entries(shardBytes).map(([shardId, bytes]) => ({
      byteSize: bytes.length, contentEncoding: "br", formatVersion: "settlement-browser-search-shard-v2",
      path: `${shardId}.codepoint-trie.json.br`, sha256: sha256(bytes), shardId,
    })), writeSequence: 3,
  };
  const receiptBytes = canonicalBytes(receipt);
  const artifacts = Object.entries(shardBytes).map(([shardId, bytes]) => ({
    artifactId: `settlements-${shardId}`, byteSize: bytes.length,
    path: `search/${shardId}.codepoint-trie.json.br`, sha256: sha256(bytes),
  }));
  artifacts.push({
    artifactId: "settlements-search-shard-set-receipt", byteSize: receiptBytes.length,
    path: "search/settlement-browser-search-shards.receipt.json", sha256: sha256(receiptBytes),
  });
  const manifest = { artifacts, dataProvenanceClass: "real-source", dataReleaseId: RELEASE };
  writeFileSync(resolve(root, "manifest.json"), JSON.stringify(manifest));
  for (const [shardId, bytes] of Object.entries(shardBytes)) {
    writeFileSync(resolve(root, `search/${shardId}.codepoint-trie.json.br`), bytes);
  }
  writeFileSync(resolve(root, "search/settlement-browser-search-shards.receipt.json"), receiptBytes);
  const queryPath = resolve(root, "queries.json");
  writeFileSync(queryPath, canonicalBytes(querySet));
  return { root, queryPath };
}

function validReport() {
  const init = distribution([410.125, 450.25]);
  const query = distribution([3.5, 8.25]);
  return finalizePerformanceReport({
    artifacts: {
      manifest: { byteSize: 10, sha256: "a".repeat(64) },
      receipt: { byteSize: 20, sha256: "b".repeat(64) },
      shards: [
        { artifactId: "settlements-europe-core", byteSize: 4, path: "search/europe-core.codepoint-trie.json.br", sha256: "e".repeat(64) },
        { artifactId: "settlements-europe-coastal", byteSize: 7, path: "search/europe-coastal.codepoint-trie.json.br", sha256: "f".repeat(64) },
      ],
    },
    claims: {
      mobileDeviceClaim: false, ownerApprovalClaim: false, productionClaim: false,
      publicationClaim: false, scientificApprovalClaim: false,
    },
    dataReleaseId: RELEASE, gateOutcome: "pass",
    measurements: {
      initialization: { distribution: init, outcome: "pass", targetMilliseconds: STARTUP_TARGET_MILLISECONDS },
      memory: { measuredConservativeUpperBoundBytes: 123 },
      query: { distribution: query, outcome: "pass", targetMilliseconds: QUERY_TARGET_MILLISECONDS },
      responsiveness: { distribution: distribution([12, 14]), metric: "maximum main-thread 10 ms timer gap during Worker initialization" },
    },
    network: {
      queryTransmissionOutcome: "pass", requests: [{ method: "GET", path: "/search.worker.js" }],
      unexpectedRequests: [],
    },
    profile: { browser: "Chromium 151", scope: "local-read-only-candidate" },
    provenance: { corpusScale: "production-candidate", dataProvenanceClass: "real-source", scope: "local-read-only-candidate" },
    querySet: { byteSize: 100, queryCount: 2, resultCountsSha256: "c".repeat(64), sha256: "d".repeat(64) },
    recordedAt: "2026-08-17T04:00:00.000Z", schemaVersion: "static-search-browser-performance-v2",
  });
}

function reidentify(report) {
  const unsigned = clone(report); delete unsigned.deterministicIdentity;
  return { ...unsigned, deterministicIdentity: createHash("sha256").update(`${canonicalJson(unsigned)}\n`).digest("hex") };
}

describe("static production-search performance evidence", () => {
  it("accepts only canonical, provenance-matched, bounded query sets", () => {
    expect(parsePerformanceQuerySet(canonicalBytes(querySet), "real-source").queries).toHaveLength(2);
    expect(() => parsePerformanceQuerySet(Buffer.from(JSON.stringify(querySet)), "real-source")).toThrow(/canonical/);
    expect(() => parsePerformanceQuerySet(canonicalBytes({ ...querySet, dataProvenanceClass: "synthetic-fixture" }), "real-source")).toThrow(/provenance/);
    expect(() => parsePerformanceQuerySet(canonicalBytes({ ...querySet, queries: [querySet.queries[0], querySet.queries[0]] }), "real-source")).toThrow(/entry/);
  });

  it("binds manifest, receipt, both shards, and query provenance", () => {
    const fixture = candidateFixture();
    const loaded = loadPerformanceInputs(fixture.root, fixture.queryPath);
    expect(loaded.receiptBytes.length).toBeGreaterThan(0);
    expect(Object.keys(loaded.shards)).toEqual(["europe-core", "europe-coastal"]);
    const manifest = JSON.parse(readFileSync(resolve(fixture.root, "manifest.json"), "utf8"));
    manifest.artifacts.find(({ artifactId }) => artifactId === "settlements-europe-core").sha256 = "0".repeat(64);
    writeFileSync(resolve(fixture.root, "manifest.json"), JSON.stringify(manifest));
    expect(() => loadPerformanceInputs(fixture.root, fixture.queryPath)).toThrow(/manifest and receipt authority/);
  });

  it("self-validates derivations, bindings, network privacy, and nonclaims", () => {
    const report = validReport();
    expect(validatePerformanceReport(report).gateOutcome).toBe("pass");
    expect(performanceReportBytes(report).toString()).toBe(`${canonicalJson(report)}\n`);
    for (const mutate of [
      (value) => { value.claims.productionClaim = true; },
      (value) => { value.network.requests[0].path = "/search.worker.js?q=private"; },
      (value) => { value.measurements.query.distribution.p95Milliseconds = 0; },
      (value) => { value.artifacts.receipt.sha256 = "0".repeat(64); },
    ]) {
      const changed = clone(report); mutate(changed); const identified = reidentify(changed);
      if (changed.artifacts.receipt.sha256 === "0".repeat(64)) {
        expect(() => validatePerformanceReport(identified, {
          dataProvenanceClass: "real-source", dataReleaseId: RELEASE,
          artifacts: report.artifacts,
          querySet: { byteSize: 100, queryCount: 2, sha256: "d".repeat(64) },
        })).toThrow(/binding/);
      } else expect(() => validatePerformanceReport(identified)).toThrow();
    }
  });

  it("durably publishes exact read-only bytes and refuses overwrite", () => {
    const root = mkdtempSync(resolve(tmpdir(), "search-performance-output-"));
    const output = resolve(root, "report.json"); const bytes = performanceReportBytes(validReport());
    expect(publishPerformanceReport(output, bytes)).toMatchObject({ byteSize: bytes.length, sha256: sha256(bytes) });
    expect(readFileSync(output)).toEqual(bytes);
    expect(lstatSync(output).mode & 0o777).toBe(0o400);
    expect(() => publishPerformanceReport(output, bytes)).toThrow(/overwrite/);
  });

  it("handles short writes and cleans a failed private stage", () => {
    const root = mkdtempSync(resolve(tmpdir(), "search-performance-short-"));
    const bytes = performanceReportBytes(validReport()); const output = resolve(root, "report.json");
    publishPerformanceReport(output, bytes, {
      write: (descriptor, buffer, offset, length) => writeSync(descriptor, buffer, offset, Math.max(1, Math.floor(length / 2))),
    });
    expect(readFileSync(output)).toEqual(bytes);
    chmodSync(output, 0o600); unlinkSync(output);
    expect(() => publishPerformanceReport(output, bytes, { afterStage: () => { throw new Error("injected stage failure"); } })).toThrow("injected stage failure");
    expect(readdirSync(root)).toEqual([]);
    expect(() => publishPerformanceReport(output, bytes, { fsync: () => { throw new Error("injected fsync failure"); } })).toThrow("injected fsync failure");
    expect(readdirSync(root)).toEqual([]);
  });

  it("rolls back its own promotion without deleting a foreign replacement", () => {
    const bytes = performanceReportBytes(validReport());
    const first = mkdtempSync(resolve(tmpdir(), "search-performance-rollback-"));
    expect(() => publishPerformanceReport(resolve(first, "report.json"), bytes, {
      afterPromote: () => { throw new Error("injected promotion failure"); },
    })).toThrow("injected promotion failure");
    expect(readdirSync(first)).toEqual([]);
    const second = mkdtempSync(resolve(tmpdir(), "search-performance-foreign-"));
    const output = resolve(second, "report.json");
    expect(() => publishPerformanceReport(output, bytes, { afterPromote: () => {
      unlinkSync(output); writeFileSync(output, "foreign", { mode: 0o600 }); throw new Error("foreign replacement");
    } })).toThrow("foreign replacement");
    expect(readFileSync(output, "utf8")).toBe("foreign");
  });
});
