import { describe, expect, it } from "vitest";
import { isTargetScanPath, scanDependencyRecords } from "./static-repository-gates.mjs";

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
    expect(scanDependencyRecords(records, { mode: "repository-final" }).violations).toHaveLength(1);
  });

  it("allows only explicit retained test/evidence and policy classes in the final repository", () => {
    const records = [
      { path: "src/web/tests/static-shell.spec.ts", text: "node server.js" },
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
    expect(scanDependencyRecords(records, { mode: "repository-final" }).violations).toHaveLength(1);
    const historicalEntries = new Map([[path, { rule: "immutable-v1-supply-chain-evidence" }]]);
    expect(scanDependencyRecords(records, { mode: "repository-final", historicalEntries }).violations).toHaveLength(0);
  });

  it.each(["SeaRise.sln", "SeaRise Europe.sln"])("classifies root solution %s as pending", (path) => {
    const records = [{ path, text: "" }];
    expect(scanDependencyRecords(records, { mode: "repository-readiness" }).findings[0].classification)
      .toBe("pending-removal");
    expect(scanDependencyRecords(records, { mode: "repository-final" }).violations).toHaveLength(1);
  });

  it.each([
    "__init__.py", "cogify.py", "compute_exposure.py", "config.py", "download.py",
    "preprocess.py", "register.py", "run_pipeline.py", "upload.py", "validate.py",
  ])("classifies root pipeline adapter %s as pending even without a dependency token", (name) => {
    const records = [{ path: `src/pipeline/${name}`, text: "# legacy adapter" }];
    const readiness = scanDependencyRecords(records, { mode: "repository-readiness" });
    expect(readiness.findings).toHaveLength(1);
    expect(readiness.findings[0].classification).toBe("pending-removal");
    expect(scanDependencyRecords(records, { mode: "repository-final" }).violations).toHaveLength(1);
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
  });
});
