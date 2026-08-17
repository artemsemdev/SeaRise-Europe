import { Buffer } from "node:buffer";
import { execFileSync } from "node:child_process";
import { mkdtempSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import {
  isRepositoryScanPath,
  isTargetScanPath,
  scanDependencyRecords,
  validateStaticSupplyChainProfile,
  validateStaticRepository,
} from "./static-repository-gates.mjs";

function git(root, ...args) {
  return execFileSync("git", args, { cwd: root, encoding: "utf8" }).trim();
}

function approvalRepository() {
  const root = mkdtempSync(resolve(tmpdir(), "repository-final-authority-"));
  git(root, "init", "-q");
  mkdirSync(resolve(root, "docs/evidence"), { recursive: true });
  writeFileSync(resolve(root, "docs/evidence/history.md"), "Historical evidence.\n");
  mkdirSync(resolve(root, "src/web/scripts"), { recursive: true });
  writeFileSync(resolve(root, "src/web/scripts/static-repository-gates.mjs"), "// synthetic gate policy\n");
  writeFileSync(resolve(root, "src/web/scripts/static-repository-gates.test.mjs"), "// synthetic gate tests\n");
  mkdirSync(resolve(root, "contracts/supply-chain/v2"), { recursive: true });
  writeFileSync(resolve(root, "contracts/supply-chain/v2/static-target-profile.json"), "{}\n");
  mkdirSync(resolve(root, "src/frontend"), { recursive: true });
  writeFileSync(resolve(root, "src/frontend/token-free"), "survivor\n");
  git(root, "add", ".");
  git(root, "-c", "user.name=Artem", "-c", "user.email=6793222+artemsemdev@users.noreply.github.com",
    "commit", "-qm", "test: create audited tree");
  const auditedCommit = git(root, "rev-parse", "HEAD");
  const auditedTree = git(root, "rev-parse", "HEAD^{tree}");
  const blob = git(root, "rev-parse", "HEAD:docs/evidence/history.md");
  const contract = {
    schemaVersion: "1.0.0",
    auditedCommit,
    auditedTree,
    entries: [{
      id: "history",
      path: "docs/evidence/history.md",
      gitBlobSha: blob,
      rule: "historical-five-state-evidence",
      reason: "Synthetic historical evidence.",
      activeRuntimeAllowed: false,
    }],
  };
  mkdirSync(resolve(root, "contracts/repository-removal/v1"), { recursive: true });
  writeFileSync(resolve(root, "contracts/repository-removal/v1/historical-allowlist.preapproval.json"),
    `${JSON.stringify(contract)}\n`);
  git(root, "add", ".");
  git(root, "-c", "user.name=Artem", "-c", "user.email=6793222+artemsemdev@users.noreply.github.com",
    "commit", "-qm", "test: add readiness authority");
  return { root, contract };
}

describe("static repository dependency gates", () => {
  it.each([
    ["nextjs-runtime", `{"dependencies":{"next":"14.2.0"}}`],
    ["dotnet-csharp-nuget", "dotnet publish SeaRise.sln"],
    ["postgres-postgis-npgsql", "postgresql://runtime.invalid/database"],
    ["titiler-runtime", "developmentseed/titiler:latest"],
    ["azurite-runtime", "UseDevelopmentStorage=true"],
    ["azure-runtime-geocoder", "https://atlas.microsoft.com/search/address/json"],
    ["legacy-compose-runtime", "services:\n  api:\n    image: legacy"],
    ["node-production-server", "node server.js"],
  ])("rejects %s in target and emitted output", (rule, text) => {
    const records = [{ path: "src/web/src/mutation.ts", text }];
    expect(scanDependencyRecords(records, { mode: "target" }).violations.map((item) => item.rule)).toContain(rule);
    expect(scanDependencyRecords(records, { mode: "built" }).violations.map((item) => item.rule)).toContain(rule);
  });

  it("classifies known removal roots without treating readiness as deletion approval", () => {
    const records = [{ path: "src/api/Program.cs", text: "dotnet run" }];
    const readiness = scanDependencyRecords(records, { mode: "repository-readiness" });
    expect(readiness.findings[0].classification).toBe("pending-removal");
    expect(readiness.violations).toHaveLength(0);
    expect(scanDependencyRecords(records, { mode: "repository-final" }).violations.length).toBeGreaterThan(0);
  });

  it("allows only explicit retained test/evidence and policy classes in the final repository", () => {
    const records = [
      { path: "src/web/package.json", text: '{"scripts":{"serve":"vite preview"}}' },
      { path: "src/web/scripts/static-repository-gates.mjs", text: "PostGIS policy mutation" },
      { path: "unexpected/runtime.yml", text: "azurite:latest" },
    ];
    const result = scanDependencyRecords(records, { mode: "repository-final" });
    expect(result.findings.map((item) => item.classification)).toEqual([
      "retained-test-tooling", "gate-policy-definition", null,
    ]);
    expect(result.violations.map((item) => item.path)).toEqual(["unexpected/runtime.yml"]);
  });

  it("requires an exact immutable-evidence allowlist entry for legacy v1 contracts", () => {
    const path = "contracts/supply-chain/v1/sboms/nuget/historical.cdx.json";
    const records = [{ path, text: "Npgsql" }];
    expect(scanDependencyRecords(records, { mode: "repository-final" }).violations.length).toBeGreaterThan(0);
    const historicalEntries = new Map([[path, { rule: "immutable-v1-supply-chain-evidence" }]]);
    expect(scanDependencyRecords(records, { mode: "repository-final", historicalEntries }).violations).toHaveLength(0);
  });

  it.each(["SeaRise.sln", "SeaRise Europe.sln"])("classifies root solution %s as pending", (path) => {
    const records = [{ path, text: "" }];
    expect(scanDependencyRecords(records, { mode: "repository-readiness" }).findings[0].classification)
      .toBe("pending-removal");
    expect(scanDependencyRecords(records, { mode: "repository-final" }).violations.length).toBeGreaterThan(0);
  });

  it.each([
    "__init__.py", "cogify.py", "compute_exposure.py", "config.py", "download.py",
    "preprocess.py", "register.py", "run_pipeline.py", "upload.py", "validate.py",
  ])("classifies root pipeline adapter %s as pending even without a dependency token", (name) => {
    const records = [{ path: `src/pipeline/${name}`, text: "# legacy adapter" }];
    const readiness = scanDependencyRecords(records, { mode: "repository-readiness" });
    expect(readiness.findings.every(({ classification }) => classification === "pending-removal")).toBe(true);
    expect(scanDependencyRecords(records, { mode: "repository-final" }).violations.length).toBeGreaterThan(0);
  });

  it("does not exempt an unclassified Node production server as build tooling", () => {
    const records = [{ path: "src/web/scripts/publish-runtime.mjs", text: "createServer(app)" }];
    expect(scanDependencyRecords(records, { mode: "target" }).violations).toHaveLength(1);
  });

  it("rejects a root target manifest that restores Next.js", () => {
    const records = [{ path: "package.json", text: '{"dependencies":{"next":"14.2.0"}}' }];
    expect(scanDependencyRecords(records, { mode: "target" }).violations[0].rule).toBe("nextjs-runtime");
  });

  it.each([
    "package.json",
    "package-lock.json",
    "src/web/package.json",
    "src/web/vite.config.ts",
    "src/web/scripts/inspect-build.mjs",
    "src/web/src/workers/search.worker.ts",
    "src/web/src/offline/service-worker.ts",
  ])("includes relevant target config/build/worker path %s", (path) => {
    expect(isTargetScanPath(path)).toBe(true);
  });

  it.each([
    "page.html", "theme.css", "icon.svg", "project.xml", "main.tf", "values.tfvars",
    ".env.production", "runtime.conf", "runtime.config", "Dockerfile.static", "extensionless",
  ])("includes tracked repository text/config path %s", (path) => {
    expect(isRepositoryScanPath(path)).toBe(true);
  });

  it("keeps retained test evidence classification exact", () => {
    const exact = [{ path: "tests/evidence/tdd-slices.json", text: "dotnet test" }];
    const unlisted = [{ path: "tests/evidence/unreviewed.json", text: "dotnet test" }];
    expect(scanDependencyRecords(exact, { mode: "repository-final" }).violations).toHaveLength(0);
    expect(scanDependencyRecords(unlisted, { mode: "repository-final" }).violations).toHaveLength(1);
  });

  it("classifies only exact removal-policy allowlist documents as gate definitions", () => {
    const exact = [{ path: "contracts/repository-removal/v1/historical-allowlist.preapproval.json", text: "NuGet" }];
    const unlisted = [{ path: "contracts/repository-removal/v1/unreviewed.json", text: "NuGet" }];
    expect(scanDependencyRecords(exact, { mode: "repository-final" }).violations).toHaveLength(0);
    expect(scanDependencyRecords(unlisted, { mode: "repository-final" }).violations).toHaveLength(1);
    expect(scanDependencyRecords([{
      path: "contracts/repository-removal/v1/historical-allowlist.preapproval.json",
      text: "AZURE_MAPS_KEY=mutation",
    }], { mode: "repository-final" }).violations).toHaveLength(1);
  });

  it.each([
    ["dotnet-csharp-nuget", "global.json"],
    ["postgres-postgis-npgsql", "postgres:latest"],
    ["postgres-postgis-npgsql", "PGHOST=database"],
    ["azure-runtime-geocoder", "AZURE_MAPS_KEY=secret"],
    ["node-production-server", '{"express":"5.0.0"}'],
  ])("rejects expanded %s token mutation", (rule, text) => {
    const result = scanDependencyRecords([{ path: "src/web/runtime.config", text }], { mode: "target" });
    expect(result.violations.map((item) => item.rule)).toContain(rule);
  });

  it.each(["docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml"])(
    "classifies token-free alternate Compose file %s by presence",
    (path) => {
      const result = scanDependencyRecords([], { mode: "repository-readiness", paths: [path] });
      expect(result.findings).toHaveLength(1);
      expect(result.findings[0].classification).toBe("pending-removal");
    },
  );

  it("classifies every token-free file under a must-delete root", () => {
    const path = "src/frontend/opaque-extension.bin";
    const result = scanDependencyRecords([], { mode: "repository-readiness", paths: [path] });
    expect(result.findings[0]).toMatchObject({ path, rule: "must-delete-path", classification: "pending-removal" });
  });

  it("rejects a private/archive path even when nested under a must-delete root", () => {
    const path = "src/frontend/candidate-v7.tar";
    const result = scanDependencyRecords([], { mode: "repository-readiness", paths: [path] });
    expect(result.violations[0]).toMatchObject({ path, rule: "private-or-archive-path", classification: null });
  });

  it("retains a shared workflow only when legacy selectors are absent", () => {
    const path = ".github/workflows/ci.yml";
    expect(scanDependencyRecords([{ path, text: "jobs:\n  web:" }], {
      mode: "repository-final", paths: [path],
    }).violations).toHaveLength(0);
    expect(scanDependencyRecords([{ path, text: "jobs:\n  api:\n    run: dotnet build" }], {
      mode: "repository-final", paths: [path],
    }).violations.length).toBeGreaterThan(0);
    expect(scanDependencyRecords([{ path, text: "jobs:\n  api:\n    runs-on: ubuntu-latest" }], {
      mode: "repository-final", paths: [path],
    }).violations.map(({ rule }) => rule)).toContain("legacy-compose-runtime");
  });

  it("does not broaden an exact retained path to an unrelated rule", () => {
    const records = [{ path: "tests/test-inventory.json", text: "AZURE_MAPS_KEY=mutation" }];
    expect(scanDependencyRecords(records, { mode: "repository-final" }).violations).toHaveLength(1);
  });

  it.each([
    ["src/web/package.json", '{"dependencies":{"express":"5.0.0"}}'],
    ["src/web/package.json", '{"dependencies":{"serve":"14.0.0"}}'],
    ["src/web/vite.config.ts", "createServer(app)"],
  ])("rejects a production server at exact formerly exempt path %s", (path, text) => {
    const result = scanDependencyRecords([{ path, text }], { mode: "repository-final", paths: [path] });
    expect(result.violations.map(({ rule }) => rule)).toContain("node-production-server");
  });

  it("extracts forbidden dependencies from binary built output", () => {
    const dist = mkdtempSync(resolve(tmpdir(), "repository-built-gate-"));
    writeFileSync(resolve(dist, "payload.bin"), Buffer.from([0, ...Buffer.from("postgres:latest"), 0]));
    expect(() => validateStaticRepository({ mode: "built", builtRoot: dist }))
      .toThrow(/postgres-postgis-npgsql/);
  });

  it("discovers token-free survivors and requires approved final authority end to end", () => {
    const { root, contract } = approvalRepository();
    const skipSupplyChain = () => {};
    const readiness = validateStaticRepository({
      mode: "repository-readiness", root, supplyChainValidator: skipSupplyChain,
    });
    expect(readiness.findings.some(({ path, rule }) =>
      path === "src/frontend/token-free" && rule === "must-delete-path")).toBe(true);
    expect(() => validateStaticRepository({
      mode: "repository-final", root, approvalValidator: () => {}, supplyChainValidator: skipSupplyChain,
    }))
      .toThrow(/Approved historical allowlist is missing/);

    writeFileSync(resolve(root, "contracts/repository-removal/v1/historical-allowlist.json"),
      `${JSON.stringify(contract)}\n`);
    git(root, "add", ".");
    git(root, "-c", "user.name=Artem", "-c", "user.email=6793222+artemsemdev@users.noreply.github.com",
      "commit", "-qm", "test: add approved authority");
    expect(() => validateStaticRepository({
      mode: "repository-final",
      root,
      approvalValidator: () => { throw new Error("invalid owner/hash chain"); },
      supplyChainValidator: skipSupplyChain,
    })).toThrow(/invalid owner\/hash chain/);
    let approvals = 0;
    const approve = () => { approvals += 1; };
    expect(() => validateStaticRepository({
      mode: "repository-final", root, approvalValidator: approve, supplyChainValidator: skipSupplyChain,
    }))
      .toThrow(/must-delete-path/);
    expect(approvals).toBe(1);

    git(root, "rm", "-q", "src/frontend/token-free");
    git(root, "-c", "user.name=Artem", "-c", "user.email=6793222+artemsemdev@users.noreply.github.com",
      "commit", "-qm", "test: remove survivor");
    expect(validateStaticRepository({
      mode: "repository-final", root, approvalValidator: approve, supplyChainValidator: skipSupplyChain,
    }).violations)
      .toHaveLength(0);
    expect(approvals).toBe(2);
    expect(readFileSync(resolve(root, "docs/evidence/history.md"), "utf8")).toBe("Historical evidence.\n");

    writeFileSync(resolve(root, "src/web/scripts/static-repository-gates.mjs"), "createServer(app)\n");
    expect(() => validateStaticRepository({
      mode: "repository-final", root, approvalValidator: approve, supplyChainValidator: skipSupplyChain,
    }))
      .toThrow(/Gate-policy trust root differs from the owner-approved audited blob/);
  });

  it("binds the current v2 profile counts and exact static-quality workflow/tooling inputs", () => {
    const root = resolve(process.cwd(), "../..");
    const profile = JSON.parse(readFileSync(resolve(root, "contracts/supply-chain/v2/static-target-profile.json"), "utf8"));
    const readPath = (path) => readFileSync(resolve(root, path));
    expect(validateStaticSupplyChainProfile(profile, readPath)).toEqual({ componentCount: 14, inputCount: 57 });

    const countMutation = JSON.parse(JSON.stringify(profile));
    countMutation.components.at(-1).inputs.pop();
    expect(() => validateStaticSupplyChainProfile(countMutation, readPath)).toThrow(/count drift/);

    const workflowMutation = JSON.parse(JSON.stringify(profile));
    workflowMutation.components.find(({ id }) => id === "github-actions")
      .inputs.find(({ path }) => path === ".github/workflows/static-quality.yml").sha256 = "0".repeat(64);
    expect(() => validateStaticSupplyChainProfile(workflowMutation, readPath)).toThrow(/input hash drift/);
  });
});
