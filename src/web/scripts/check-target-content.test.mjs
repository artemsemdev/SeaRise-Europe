import { createHash } from "node:crypto";
import { Buffer } from "node:buffer";
import { execFileSync, spawnSync } from "node:child_process";
import {
  cpSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  symlinkSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import {
  activeAuthoritativeDocument,
  ownerCommentVerificationArguments,
  readScanFile,
  repositoryAuthorityValidatorPath,
  resolveApprovedGatePolicyBlobs,
  scanContent,
  staticSupplyChainValidationArguments,
  validateHistoricalAllowlist,
} from "./check-target-content.mjs";

describe("built content containment", () => {
  it("reads an external build root but rejects a symlink escape", () => {
    const builtRoot = mkdtempSync(resolve(tmpdir(), "target-content-built-"));
    const outsideRoot = mkdtempSync(resolve(tmpdir(), "target-content-outside-"));
    try {
      const builtFile = resolve(builtRoot, "index.html");
      writeFileSync(builtFile, "static build");
      expect(readScanFile(builtFile, builtRoot)).toBe("static build");

      const outsideFile = resolve(outsideRoot, "outside.js");
      writeFileSync(outsideFile, "external payload");
      const linkedFile = resolve(builtRoot, "linked.js");
      symlinkSync(outsideFile, linkedFile);
      expect(() => readScanFile(linkedFile, builtRoot)).toThrow(/must not use symlinks/);
    } finally {
      rmSync(builtRoot, { recursive: true, force: true });
      rmSync(outsideRoot, { recursive: true, force: true });
    }
  });
});

function git(root, ...arguments_) {
  return execFileSync("git", arguments_, { cwd: root, encoding: "utf8" }).trim();
}

function createCliRepositoryFixture() {
  const source = resolve(process.cwd(), "../..");
  const root = mkdtempSync(resolve(tmpdir(), "target-content-cli-"));
  cpSync(source, root, {
    recursive: true,
    filter: (path) => !path.slice(source.length + 1).split("/")
      .some((part) => [".git", "node_modules", "dist", ".terraform"].includes(part)),
  });
  for (const validator of [
    "scripts/release/validate_supply_chain_contract.py",
    "scripts/repository/validate_static_delivery_owner_verifier_chain_correction.py",
  ]) {
    writeFileSync(resolve(root, validator), "raise SystemExit(0)\n");
  }
  mkdirSync(resolve(root, "src/web/dist"), { recursive: true });
  writeFileSync(resolve(root, "src/web/dist/index.html"), "<!doctype html><title>static fixture</title>\n");
  git(root, "init", "-q");
  git(root, "fetch", "-q", source, "+refs/heads/*:refs/remotes/source/*");
  git(root, "add", ".");
  git(root, "-c", "user.name=Artem", "-c",
    "user.email=6793222+artemsemdev@users.noreply.github.com",
    "commit", "-qm", "test: create static target fixture");
  return root;
}

function runContentCli(root, ...arguments_) {
  return spawnSync(process.execPath, ["scripts/check-target-content.mjs", ...arguments_], {
    cwd: resolve(root, "src/web"),
    encoding: "utf8",
  });
}

describe("target-content CLI module graph", () => {
  it("reproduces the old exit-13 cycle and runs the corrected source and built CLIs", () => {
    const root = createCliRepositoryFixture();
    const gatePath = resolve(root, "src/web/scripts/static-repository-gates.mjs");
    const authorityPath = resolve(root, "contracts/repository-removal/v11/phase-3-issue-62/preapproval.json");
    const corrected = readFileSync(gatePath, "utf8");
    const approved = readFileSync(authorityPath, "utf8");
    try {
      const cyclicGate = corrected.replace(
        'from "./static-repository-authority.mjs";',
        'from "./check-target-content.mjs";',
      );
      writeFileSync(gatePath, cyclicGate);
      const cyclicAuthority = JSON.parse(approved);
      cyclicAuthority.governedPaths.find(({ path }) =>
        path === "src/web/scripts/static-repository-gates.mjs").after.gitBlobSha = blob(cyclicGate);
      writeFileSync(authorityPath, `${JSON.stringify(cyclicAuthority, null, 2)}\n`);
      const cyclic = runContentCli(root);
      expect(cyclic.status, cyclic.stderr).toBe(13);

      writeFileSync(gatePath, corrected);
      writeFileSync(authorityPath, approved);
      const source = runContentCli(root);
      expect(source.stderr).toBe("");
      expect(source.status).toBe(0);
      expect(source.stdout).toMatch(/Target content contract passed/);

      const built = runContentCli(root, "--built", "dist");
      expect(built.stderr).toBe("");
      expect(built.status).toBe(0);
      expect(built.stdout).toMatch(/Target content contract passed/);
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  }, 30_000);
});

function blob(content) {
  const bytes = Buffer.from(content);
  return createHash("sha1").update(`blob ${bytes.length}\0`).update(bytes).digest("hex");
}

function fixture(overrides = {}) {
  const content = "Historical binary exposure classification evidence.";
  return {
    content,
    document: {
      schemaVersion: "1.0.0",
      auditedCommit: "a".repeat(40),
      auditedTree: "b".repeat(40),
      entries: [{
        id: "historical-evidence",
        path: "docs/evidence/historical.md",
        gitBlobSha: blob(content),
        rule: "historical-five-state-evidence",
        reason: "Historical evidence only.",
        activeRuntimeAllowed: false,
        ...overrides,
      }],
    },
  };
}

describe("repository-removal validator capability", () => {
  it("hands approved content checks to the complete Issue 62 v11 authority", () => {
    expect(repositoryAuthorityValidatorPath).toBe(
      "scripts/repository/validate_static_delivery_owner_verifier_chain_correction.py",
    );
  });

  it("hands off the historical Issue 71 gate only to the exact current after blob", () => {
    const historical = "1".repeat(40);
    const evolved = "2".repeat(40);
    const plan = { entries: [{
      path: "src/web/scripts/static-repository-gates.mjs",
      after: { state: "present", gitBlobSha: historical },
    }] };
    const authority = { governedPaths: [{
      path: "src/web/scripts/static-repository-gates.mjs",
      before: { state: "present", gitBlobSha: historical },
      after: { state: "present", gitBlobSha: evolved },
    }] };
    expect(resolveApprovedGatePolicyBlobs(plan, authority).get(
      "src/web/scripts/static-repository-gates.mjs",
    )).toBe(evolved);
    authority.governedPaths[0].before.gitBlobSha = "3".repeat(40);
    expect(() => resolveApprovedGatePolicyBlobs(plan, authority)).toThrow(/Issue-71 plan/);
  });

  it("hands the complete evolved profile to the current Python validator", () => {
    expect(staticSupplyChainValidationArguments("/repository")).toEqual([
      "/repository/scripts/release/validate_supply_chain_contract.py",
      "static-profile",
      "--document",
      "contracts/supply-chain/v2/static-target-profile.json",
      "--repository-root",
      "/repository",
    ]);
  });

  it("fails closed when owner-comment verification is unavailable", () => {
    expect(() => ownerCommentVerificationArguments(
      "usage: validator [--repository-root REPOSITORY_ROOT]",
      "/repository",
    )).toThrow(/lacks required --verify-owner-comment capability/);
    expect(() => ownerCommentVerificationArguments(
      "usage: validator [--verify-owner-commentary]",
      "/repository",
    )).toThrow(/lacks required --verify-owner-comment capability/);
  });

  it("passes the exact owner-comment verification flag when advertised", () => {
    expect(ownerCommentVerificationArguments(
      "usage: validator [--repository-root REPOSITORY_ROOT] [--verify-owner-comment]",
      "/repository",
    )).toEqual(["--repository-root", "/repository", "--verify-owner-comment"]);
  });
});

describe("historical terminology allowlist", () => {
  it("accepts an exact path/blob/rule entry", () => {
    const { content, document } = fixture();
    const entry = validateHistoricalAllowlist(document, () => content).get("docs/evidence/historical.md");
    expect(entry.allowedClaims.has("binary-exposure-product")).toBe(true);
    expect(entry.allowedClaims.has("property-risk-product")).toBe(false);
    expect(entry.allowedClaims.has("future-flood-certainty")).toBe(false);
  });

  it("uses current blob bindings without claiming a stale audit anchor during readiness", () => {
    const { content, document } = fixture();
    delete document.auditedCommit;
    delete document.auditedTree;
    document.authority = "preapproval-current-blobs";
    expect(validateHistoricalAllowlist(document, () => content, { authority: "readiness" })
      .has("docs/evidence/historical.md")).toBe(true);
    document.auditedCommit = "a".repeat(40);
    expect(() => validateHistoricalAllowlist(document, () => content, { authority: "readiness" }))
      .toThrow(/not a v1 document/);
  });

  it("rejects a changed blob", () => {
    const { document } = fixture();
    expect(() => validateHistoricalAllowlist(document, () => "mutated"))
      .toThrow(/blob mismatch/);
  });

  it.each([
    { path: "docs/evidence/nested/historical.md", rule: "historical-adr-term" },
    { path: "src/web/src/App.tsx", rule: "historical-five-state-evidence" },
    { path: "docs/evidence/historical.md", activeRuntimeAllowed: true },
    { path: "docs/architecture/adr/ADR-024-ar6-regional-projection-contract.md", rule: "historical-adr-term" },
  ])("rejects invalid rule or active-target scope %#", (overrides) => {
    const { content, document } = fixture(overrides);
    document.entries[0].gitBlobSha = blob(content);
    expect(() => validateHistoricalAllowlist(document, () => content)).toThrow(/invalid entry/);
  });

  it("rejects duplicate IDs and audited-tree drift", () => {
    const { content, document } = fixture();
    document.entries.push({ ...document.entries[0], path: "docs/evidence/second.md" });
    expect(() => validateHistoricalAllowlist(document, () => content)).toThrow(/repeats id/);
    document.entries.pop();
    expect(() => validateHistoricalAllowlist(document, () => content, { resolveTree: () => "c".repeat(40) }))
      .toThrow(/audited tree/);
  });

  it("rejects extra schema fields and audited-blob drift", () => {
    const { content, document } = fixture();
    document.unreviewed = true;
    expect(() => validateHistoricalAllowlist(document, () => content)).toThrow(/not a v1 document/);
    delete document.unreviewed;
    expect(() => validateHistoricalAllowlist(document, () => content, {
      resolveBlob: () => "d".repeat(40),
    })).toThrow(/audited blob mismatch/);
  });

  it("accepts only the exact canonical Flight design-reference path", () => {
    const { content, document } = fixture({
      path: "docs/product/Mock/SeaRise-Flight.html",
      rule: "canonical-design-reference",
    });
    expect(validateHistoricalAllowlist(document, () => content)
      .has("docs/product/Mock/SeaRise-Flight.html")).toBe(true);
    document.entries[0].path = "docs/product/Mock/SeaRise-Flight-copy.html";
    expect(() => validateHistoricalAllowlist(document, () => content)).toThrow(/invalid entry/);
  });

  it("allows ADR-024 rejected identifiers only in its exact authoritative prohibition", () => {
    const path = resolve(process.cwd(), "../../docs/architecture/adr/ADR-024-ar6-regional-projection-contract.md");
    const exact = "`ProjectionAvailable` replaces both legacy binary exposure outcomes. The\nhistorical `ModeledExposureDetected` and `NoModeledExposureDetected` states do\nnot appear in a release governed by this ADR.";
    expect(scanContent(activeAuthoritativeDocument(exact, path))).toHaveLength(0);
    expect(scanContent(activeAuthoritativeDocument(exact.replace("do\nnot appear", "remain available"), path)))
      .toHaveLength(2);
  });
});
