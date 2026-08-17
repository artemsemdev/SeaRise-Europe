import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { lstatSync, readFileSync, readdirSync } from "node:fs";
import { extname, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { loadHistoricalAllowlist } from "./check-target-content.mjs";

const moduleUrl = new URL(import.meta.url);
const webRoot = moduleUrl.protocol === "file:"
  ? resolve(fileURLToPath(new URL("..", moduleUrl)))
  : process.cwd();
const repositoryRoot = resolve(webRoot, "../..");

const EXECUTABLE_NAMES = new Set([
  "Dockerfile", "docker-compose.yml", "docker-compose.yaml", "package.json",
  "package-lock.json", "packages.lock.json", "SeaRise.sln", "SeaRise Europe.sln",
]);
const EXECUTABLE_EXTENSIONS = new Set([
  ".cs", ".csproj", ".fsproj", ".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx",
  ".json", ".py", ".sh", ".sql", ".toml", ".props", ".targets", ".yml", ".yaml",
  ".html", ".css", ".svg", ".xml", ".tf", ".tfvars", ".env", ".conf", ".config",
]);
const ARCHIVE_EXTENSIONS = /\.(?:7z|rar|tar|tar\.bz2|tar\.gz|tar\.xz|tgz|zip)$/iu;

const staticSupplyChainComponents = new Map([
  ["active-sboms", ["cyclonedx", "candidate", "locked"]],
  ["github-actions", ["github-actions", "candidate", "locked"]],
  ["native-build-plane", ["native", "candidate", "locked"]],
  ["pending-legacy-python-authorities", ["python", "development", "range-constrained"]],
  ["pipeline-container", ["container", "candidate", "locked"]],
  ["pipeline-geoid-evaluator", ["python", "candidate", "locked"]],
  ["pipeline-python-contributor", ["python", "development", "range-constrained"]],
  ["pipeline-python-release", ["python", "candidate", "locked"]],
  ["profile-contract", ["standard-schema", "candidate", "locked"]],
  ["provenance-signing-contracts", ["standard-schema", "candidate", "locked"]],
  ["settlement-spatial-python", ["python", "candidate", "locked"]],
  ["static-quality-npm", ["npm", "development", "locked"]],
  ["static-web-npm", ["npm", "candidate", "locked"]],
  ["vendored-cyclonedx-schemas", ["standard-schema", "candidate", "locked"]],
]);

const staticSupplyChainInputs = new Map([
  ["contracts/supply-chain/v1/sboms/python-release-linux-x86-64-cp311.cdx.json", ["active-sboms", "sbom", "100644"]],
  ["contracts/supply-chain/v1/sboms/python-release-macos-arm64-cp311.cdx.json", ["active-sboms", "sbom", "100644"]],
  ["contracts/supply-chain/v1/sboms/python-settlement-spatial-linux-x86-64-cp311.cdx.json", ["active-sboms", "sbom", "100644"]],
  ["contracts/supply-chain/v1/sboms/python-settlement-spatial-macos-arm64-cp311.cdx.json", ["active-sboms", "sbom", "100644"]],
  ["contracts/supply-chain/v2/sboms/static-web-npm.cdx.json", ["active-sboms", "sbom", "100644"]],
  [".github/workflows/ci.yml", ["github-actions", "workflow", "100644"]],
  [".github/workflows/codeql.yml", ["github-actions", "workflow", "100644"]],
  [".github/workflows/offline-release-controlled.yml", ["github-actions", "workflow", "100644"]],
  [".github/workflows/phase-0r-owner-promotion.yml", ["github-actions", "workflow", "100644"]],
  [".github/workflows/phase-1-release-sign.yml", ["github-actions", "workflow", "100644"]],
  [".github/workflows/static-quality.yml", ["github-actions", "workflow", "100644"]],
  ["contracts/supply-chain/v1/tools/cosign-linux-amd64.json", ["native-build-plane", "lock", "100644"]],
  ["src/pipeline/toolchain/Dockerfile.tippecanoe-linux-x86_64", ["native-build-plane", "recipe", "100644"]],
  ["src/pipeline/toolchain/build_macos_tippecanoe.sh", ["native-build-plane", "recipe", "100755"]],
  ["src/pipeline/toolchain/duckdb-spatial-extensions.json", ["native-build-plane", "lock", "100644"]],
  ["src/pipeline/toolchain/tippecanoe-darwin-arm64-build-receipt.json", ["native-build-plane", "receipt", "100644"]],
  ["src/pipeline/toolchain/tippecanoe-linux-x86_64-build-receipt.json", ["native-build-plane", "receipt", "100644"]],
  ["src/pipeline/pyproject.toml", ["pending-legacy-python-authorities", "manifest", "100644"]],
  ["src/pipeline/requirements-pipeline.txt", ["pending-legacy-python-authorities", "manifest", "100644"]],
  ["src/pipeline/offline_release/Dockerfile", ["pipeline-container", "recipe", "100644"]],
  ["src/pipeline/offline_release/Dockerfile.dockerignore", ["pipeline-container", "recipe", "100644"]],
  ["src/pipeline/offline_release/profiles/fixture.json", ["pipeline-container", "manifest", "100644"]],
  ["src/pipeline/offline_release/profiles/full-europe.json", ["pipeline-container", "manifest", "100644"]],
  ["src/pipeline/offline_release/profiles/profile.schema.json", ["pipeline-container", "schema", "100644"]],
  ["src/pipeline/offline_release/profiles/regional.json", ["pipeline-container", "manifest", "100644"]],
  ["src/pipeline/science/geoid-evaluator-requirements.txt", ["pipeline-geoid-evaluator", "lock", "100644"]],
  ["contracts/supply-chain/v2/python/static-target-contributor-requirements.txt", ["pipeline-python-contributor", "manifest", "100644"]],
  ["contracts/supply-chain/v1/python-graphs/release-runtime.json", ["pipeline-python-release", "manifest", "100644"]],
  ["src/pipeline/requirements-phase1-final-macos-x86_64.lock", ["pipeline-python-release", "lock", "100644"]],
  ["src/pipeline/requirements-release-macos-arm64.lock", ["pipeline-python-release", "lock", "100644"]],
  ["src/pipeline/requirements-release.lock", ["pipeline-python-release", "lock", "100644"]],
  ["contracts/supply-chain/v2/historical/v1-contracts.py", ["profile-contract", "manifest", "100644"]],
  ["contracts/supply-chain/v2/static-target-profile.schema.json", ["profile-contract", "schema", "100644"]],
  ["contracts/release/v2/browser-derivation-provenance.schema.json", ["provenance-signing-contracts", "schema", "100644"]],
  ["contracts/supply-chain/v1/build-types/offline-release-real-source-v1.json", ["provenance-signing-contracts", "manifest", "100644"]],
  ["contracts/supply-chain/v1/build-types/offline-release-v1.json", ["provenance-signing-contracts", "manifest", "100644"]],
  ["contracts/supply-chain/v1/cosign-tool-lock.schema.json", ["provenance-signing-contracts", "schema", "100644"]],
  ["contracts/supply-chain/v1/cryptographic-verification-receipt.schema.json", ["provenance-signing-contracts", "schema", "100644"]],
  ["contracts/supply-chain/v1/evidence-envelope.schema.json", ["provenance-signing-contracts", "schema", "100644"]],
  ["contracts/supply-chain/v1/identity-policy.json", ["provenance-signing-contracts", "manifest", "100644"]],
  ["contracts/supply-chain/v1/identity-policy.schema.json", ["provenance-signing-contracts", "schema", "100644"]],
  ["contracts/supply-chain/v1/public-readback-verification-receipt.schema.json", ["provenance-signing-contracts", "schema", "100644"]],
  ["contracts/supply-chain/v1/real-source-unverified-evidence-envelope.schema.json", ["provenance-signing-contracts", "schema", "100644"]],
  ["contracts/supply-chain/v1/release-evidence-retention-receipt.schema.json", ["provenance-signing-contracts", "schema", "100644"]],
  ["contracts/supply-chain/v1/python-graphs/settlement-spatial-runtime.json", ["settlement-spatial-python", "manifest", "100644"]],
  ["src/pipeline/requirements-settlements-spatial-linux-x86_64.lock", ["settlement-spatial-python", "lock", "100644"]],
  ["src/pipeline/requirements-settlements-spatial-macos-arm64.lock", ["settlement-spatial-python", "lock", "100644"]],
  ["tools/static-quality/package-lock.json", ["static-quality-npm", "lock", "100644"]],
  ["tools/static-quality/package.json", ["static-quality-npm", "manifest", "100644"]],
  ["package-lock.json", ["static-web-npm", "lock", "100644"]],
  ["package.json", ["static-web-npm", "manifest", "100644"]],
  ["src/web/package.json", ["static-web-npm", "manifest", "100644"]],
  ["contracts/supply-chain/v1/vendor/bom-1.7.schema.json", ["vendored-cyclonedx-schemas", "schema", "100644"]],
  ["contracts/supply-chain/v1/vendor/cryptography-defs.schema.json", ["vendored-cyclonedx-schemas", "schema", "100644"]],
  ["contracts/supply-chain/v1/vendor/jsf-0.82.schema.json", ["vendored-cyclonedx-schemas", "schema", "100644"]],
  ["contracts/supply-chain/v1/vendor/manifest.json", ["vendored-cyclonedx-schemas", "lock", "100644"]],
  ["contracts/supply-chain/v1/vendor/spdx.schema.json", ["vendored-cyclonedx-schemas", "schema", "100644"]],
]);

export const forbiddenDependencyRules = Object.freeze([
  Object.freeze({ id: "nextjs-runtime", pattern: /(?:["'](?:next|eslint-config-next)["']|\bnext\/(?:server|headers|navigation|router|image)\b|\bnext (?:build|dev|start)\b|\b\.next\/)/giu }),
  Object.freeze({ id: "dotnet-csharp-nuget", pattern: /(?:\bdotnet\s+(?:build|run|test|restore|publish|format)\b|\bMicrosoft\.AspNetCore\b|\bASP\.NET\b|\bNuGet\b|<TargetFramework>|\.csproj\b|\.sln\b|(?:^|\/)global\.json\b)/gimu }),
  Object.freeze({ id: "postgres-postgis-npgsql", pattern: /(?:\bPostgreSQL\b|\bPostGIS\b|\bNpgsql\b|postgres(?:ql)?:\/\/|\bpostgis\/postgis:|\bpostgres:(?:\d|latest)\b|\b(?:POSTGRES_[A-Z_]+|PGHOST|PGPORT|PGDATABASE|PGUSER|PGPASSWORD)\b)/giu }),
  Object.freeze({ id: "titiler-runtime", pattern: /(?:\bTiTiler\b|\btitiler(?:\.|-)|developmentseed\/titiler)/giu }),
  Object.freeze({ id: "azurite-runtime", pattern: /(?:\bAzurite\b|mcr\.microsoft\.com\/azure-storage\/azurite|UseDevelopmentStorage=true)/giu }),
  Object.freeze({ id: "azure-runtime-geocoder", pattern: /(?:\bAzure Maps\b.{0,80}\bgeocod|atlas\.microsoft\.com\/(?:search|geocode|sdk)|maps\.azure\.com.{0,120}(?:search|geocode)|\bAZURE_MAPS_[A-Z_]+\b|azure-maps-control|subscription-key.{0,80}(?:atlas|maps\.azure))/giu }),
  Object.freeze({ id: "legacy-compose-runtime", pattern: /^\s{0,8}(?:api|frontend|db|postgres|postgis|titiler|azurite):\s*$/gimu }),
  Object.freeze({ id: "node-production-server", pattern: /(?:\bvite preview\b|\bnext start\b|\bnode\s+(?:\.\/)?(?:server|app|index)\.(?:js|mjs|cjs)\b|\bcreateServer\s*\(|["'](?:@hono\/node-server|express|fastify|hono|http-server|koa)["']\s*:|\bnpx\s+(?:http-server|serve)\b|\bfastify\s+start\b|\b(?:Bun|Deno)\.serve\s*\()/giu }),
]);

const pendingRemovalPaths = Object.freeze([
  /^SeaRise(?: Europe)?\.sln$/u,
  /^src\/(?:api|frontend)\//u,
  /^infra\/(?:db|blob-seed)\//u,
  /^(?:docker-compose|compose)\.ya?ml$/u,
  /^\.env\.(?:local|pipeline)\.example$/u,
  /^scripts\/compose-smoke\.sh$/u,
  /^src\/pipeline\/(?:__init__|cogify|compute_exposure|config|download|preprocess|register|run_pipeline|upload|validate)\.py$/u,
]);
const legacyPipelineAdapters = /^src\/pipeline\/(?:__init__|cogify|compute_exposure|config|download|preprocess|register|run_pipeline|upload|validate)\.py$/u;
const mustDeletePrefixes = Object.freeze(["src/api/", "src/frontend/", "infra/db/", "infra/blob-seed/"]);
const exactRetainedRulePurpose = new Map([
  ["src/web/package.json", new Map([["node-production-server", new Set(["vite preview"])]])],
  ["src/web/scripts/measure-ar6-release.mjs", new Map([["node-production-server", new Set(["createserver("])]])],
  ["src/web/scripts/measure-local-candidate-search.mjs", new Map([["node-production-server", new Set(["createserver("])]])],
  ["src/web/scripts/offline-lifecycle-server.mjs", new Map([["node-production-server", new Set(["createserver("])]])],
  ["src/web/scripts/run-local-candidate-e2e.mjs", new Map([["node-production-server", new Set(["createserver("])]])],
  ["src/web/scripts/serve-committed-release.mjs", new Map([["node-production-server", new Set(["createserver("])]])],
  ["src/web/scripts/serve-range-cache-spike.mjs", new Map([["node-production-server", new Set(["createserver("])]])],
  ["src/web/scripts/verify-boundary-pmtiles-browser.mjs", new Map([["node-production-server", new Set(["createserver("])]])],
  ["tests/evidence/mutation-pilot-result-state.json", new Map([["dotnet-csharp-nuget", new Set(["dotnet test", ".sln"])]])],
  ["tests/evidence/tdd-slices.json", new Map([["dotnet-csharp-nuget", new Set(["dotnet test", ".sln"])]])],
  ["tests/harness/test_immutable_dependencies.py", new Map([["postgres-postgis-npgsql", new Set(["postgis"])]])],
  ["tests/test-inventory.json", new Map([
    ["dotnet-csharp-nuget", new Set(["dotnet test", ".sln"])],
    ["postgres-postgis-npgsql", new Set(["postgis"])],
    ["titiler-runtime", new Set(["titiler", "developmentseed/titiler"])],
  ])],
  ["contracts/supply-chain/v2/historical/v1-contracts.py", new Map([
    ["dotnet-csharp-nuget", new Set(["nuget", ".csproj"])],
  ])],
  ["contracts/supply-chain/v2/static-target-profile.json", new Map([
    ["dotnet-csharp-nuget", new Set(["nuget", ".csproj", ".sln"])],
    ["postgres-postgis-npgsql", new Set(["postgis"])],
    ["azurite-runtime", new Set(["azurite"])],
  ])],
  ["contracts/supply-chain/v2/static-target-profile.schema.json", new Map([
    ["dotnet-csharp-nuget", new Set(["nuget"])],
    ["azurite-runtime", new Set(["azurite"])],
  ])],
  ["src/pipeline/searise_pipeline/supply_chain/static_profile.py", new Map([
    ["nextjs-runtime", new Set(["\"next\""])],
    ["dotnet-csharp-nuget", new Set(["nuget", ".csproj", ".sln"])],
    ["postgres-postgis-npgsql", new Set(["postgis"])],
    ["azurite-runtime", new Set(["azurite"])],
  ])],
  ["src/pipeline/tests/supply_chain/test_static_target_profile.py", new Map([
    ["nextjs-runtime", new Set(["\"next\""])],
    ["dotnet-csharp-nuget", new Set([".sln"])],
    ["postgres-postgis-npgsql", new Set(["postgis"])],
  ])],
  ["tests/harness/test_changed_suites.py", new Map([
    ["postgres-postgis-npgsql", new Set(["postgis"])],
  ])],
]);
const allPolicyRuleIds = new Set(forbiddenDependencyRules.map(({ id }) => id));
const gatePolicyRulePurpose = new Map([
  ["src/web/scripts/static-repository-gates.mjs", allPolicyRuleIds],
  ["src/web/scripts/static-repository-gates.test.mjs", allPolicyRuleIds],
  ["contracts/repository-removal/v1/census.json", new Set(["dotnet-csharp-nuget"])],
  ["contracts/repository-removal/v1/historical-allowlist.preapproval.json", new Set(["dotnet-csharp-nuget"])],
  ["contracts/repository-removal/v1/historical-allowlist.json", new Set(["dotnet-csharp-nuget"])],
]);

function isPendingRemoval(path, ruleId) {
  return pendingRemovalPaths.some((pattern) => pattern.test(path))
    || ((path === ".github/workflows/ci.yml" || path === ".github/workflows/codeql.yml")
      && ruleId !== "must-delete-path")
    || (path === "scripts/ci/changed_components.py" && ruleId === "dotnet-csharp-nuget")
    || (ruleId === "dotnet-csharp-nuget" && (
      path.startsWith("src/pipeline/searise_pipeline/supply_chain/")
      || path.startsWith("src/pipeline/tests/supply_chain/")
      || path === "scripts/release/validate_supply_chain_contract.py"
    ));
}

function retainedClass(path, ruleId, findingText, historicalEntries) {
  if (historicalEntries.get(path)?.rule === "immutable-v1-supply-chain-evidence") {
    return "immutable-v1-supply-chain-evidence";
  }
  if (gatePolicyRulePurpose.get(path)?.has(ruleId)) {
    return "gate-policy-definition";
  }
  if (exactRetainedRulePurpose.get(path)?.get(ruleId)?.has(findingText.toLocaleLowerCase("en-US"))) {
    if (path.startsWith("contracts/supply-chain/v2/")
        || path.includes("/supply_chain/static_profile.py")) return "retained-build-science";
    return path.startsWith("tests/") ? "retained-test-evidence" : "retained-test-tooling";
  }
  return null;
}

function scanText(path, text) {
  const findings = [];
  for (const rule of forbiddenDependencyRules) {
    rule.pattern.lastIndex = 0;
    for (const match of text.matchAll(rule.pattern)) {
      findings.push(Object.freeze({
        path,
        rule: rule.id,
        line: text.slice(0, match.index).split("\n").length,
        text: match[0].replace(/\s+/gu, " ").slice(0, 120),
      }));
    }
  }
  if (/\.(?:cs|csproj|fsproj|sln)$/u.test(path) && !findings.some(({ rule }) => rule === "dotnet-csharp-nuget")) {
    findings.push(Object.freeze({ path, rule: "dotnet-csharp-nuget", line: 1, text: "C#/.NET source path" }));
  }
  if (legacyPipelineAdapters.test(path)) {
    findings.push(Object.freeze({ path, rule: "legacy-pipeline-adapter", line: 1, text: "legacy root pipeline adapter" }));
  }
  if (path.endsWith("package.json")) {
    let manifest;
    try { manifest = JSON.parse(text); } catch { manifest = null; }
    const serverPackages = new Set([
      "@hono/node-server", "express", "fastify", "hono", "http-server", "koa", "serve",
    ]);
    for (const section of ["dependencies", "devDependencies", "optionalDependencies", "peerDependencies"]) {
      const dependencies = manifest?.[section];
      if (!dependencies || typeof dependencies !== "object" || Array.isArray(dependencies)) continue;
      for (const dependency of Object.keys(dependencies)) {
        if (serverPackages.has(dependency)) {
          findings.push(Object.freeze({
            path,
            rule: "node-production-server",
            line: 1,
            text: `${section}.${dependency}`,
          }));
        }
      }
    }
  }
  return findings;
}

function pathPresenceFindings(paths) {
  return paths.flatMap((path) => {
    const mustDelete = mustDeletePrefixes.some((prefix) => path.startsWith(prefix))
      || pendingRemovalPaths.some((pattern) => pattern.test(path));
    const privatePath = /(?:^|\/)(?:candidate[-_.]?v?\d+|local-data)(?:[/._-]|$)/iu.test(path)
      || ARCHIVE_EXTENSIONS.test(path);
    if (!mustDelete && !privatePath) return [];
    return [Object.freeze({
      path,
      rule: privatePath ? "private-or-archive-path" : "must-delete-path",
      line: 1,
      text: privatePath ? "private/archive repository path" : "approved Phase 2 must-delete path",
    })];
  });
}

export function isRepositoryScanPath(path) {
  const name = path.split("/").at(-1);
  return EXECUTABLE_NAMES.has(name) || EXECUTABLE_EXTENSIONS.has(extname(path))
    || name?.startsWith("Dockerfile") || /^\.env(?:\.|$)/u.test(name ?? "")
    || (typeof name === "string" && !name.includes("."));
}

function trackedPaths(root) {
  return execFileSync("git", ["ls-files", "-z"], { cwd: root, encoding: "utf8" })
    .split("\0").filter(Boolean).sort();
}

function filesBelow(root) {
  const rootStatus = lstatSync(root);
  if (rootStatus.isSymbolicLink()) throw new Error(`Built-output root must not be a symlink: ${root}`);
  if (!rootStatus.isDirectory()) throw new Error(`Built-output root must be a directory: ${root}`);
  const files = [];
  const visit = (path) => {
    for (const name of readdirSync(path).sort()) {
      const child = resolve(path, name);
      const status = lstatSync(child);
      if (status.isSymbolicLink()) throw new Error(`Built output must not contain symlinks: ${child}`);
      if (status.isDirectory()) visit(child);
      else if (status.isFile()) files.push(child);
      else throw new Error(`Built output must contain only regular files and directories: ${child}`);
    }
  };
  visit(root);
  return files;
}

function safeRepositoryFile(root, logicalPath) {
  if (!logicalPath || logicalPath.startsWith("/") || logicalPath.includes("\\")
      || logicalPath.split("/").some((part) => part === "" || part === "." || part === "..")) {
    throw new Error(`Unsafe repository path: ${logicalPath}`);
  }
  const rootStatus = lstatSync(root);
  if (rootStatus.isSymbolicLink() || !rootStatus.isDirectory()) {
    throw new Error(`Repository root must be a regular directory: ${root}`);
  }
  let current = root;
  for (const part of logicalPath.split("/")) {
    current = resolve(current, part);
    const status = lstatSync(current);
    if (status.isSymbolicLink()) throw new Error(`Repository path must not use symlinks: ${logicalPath}`);
  }
  const status = lstatSync(current);
  if (!status.isFile()) throw new Error(`Repository path must be a regular file: ${logicalPath}`);
  return current;
}

function trackedMode(root, logicalPath) {
  const output = execFileSync("git", ["ls-files", "--stage", "--", logicalPath], {
    cwd: root,
    encoding: "utf8",
  }).trim();
  const lines = output.split("\n").filter(Boolean);
  if (lines.length !== 1 || !lines[0].endsWith(`\t${logicalPath}`)) {
    throw new Error(`Static-target supply-chain input is not uniquely tracked: ${logicalPath}`);
  }
  return lines[0].split(" ", 1)[0];
}

export function scanDependencyRecords(records, {
  mode,
  historicalEntries = new Map(),
  paths = records.map(({ path }) => path),
}) {
  if (!["target", "built", "repository-readiness", "repository-final"].includes(mode)) {
    throw new Error(`Unknown static repository gate mode: ${mode}`);
  }
  const rawFindings = [...pathPresenceFindings(paths), ...records.flatMap(({ path, text }) => scanText(path, text))];
  const findings = rawFindings.map((finding) => {
    const { path } = finding;
    const retained = retainedClass(path, finding.rule, finding.text, historicalEntries);
    const classification = finding.rule === "private-or-archive-path" ? null : retained
      ?? (isPendingRemoval(path, finding.rule) ? "pending-removal" : null);
    return Object.freeze({ ...finding, classification });
  });
  const violations = findings.filter(({ classification }) => {
    if (mode === "built") return true;
    if (mode === "target") {
      return classification !== "retained-test-tooling" && classification !== "gate-policy-definition";
    }
    if (mode === "repository-final") return classification === "pending-removal" || classification === null;
    return classification === null;
  });
  return Object.freeze({ findings: Object.freeze(findings), violations: Object.freeze(violations) });
}

function readRecords(paths, root) {
  return paths.filter((path) => isRepositoryScanPath(path) && !ARCHIVE_EXTENSIONS.test(path)
    && !/(?:^|\/)(?:candidate[-_.]?v?\d+|local-data)(?:[/._-]|$)/iu.test(path)).map((path) => {
    const absolute = safeRepositoryFile(root, path);
    const bytes = readFileSync(absolute);
    if (bytes.includes(0)) return null;
    return Object.freeze({ path, text: bytes.toString("utf8") });
  }).filter(Boolean);
}

function inspectableOutput(bytes) {
  if (!bytes.includes(0)) return bytes.toString("utf8");
  const strings = [];
  let current = "";
  for (const byte of bytes) {
    if (byte >= 0x20 && byte <= 0x7e) current += String.fromCharCode(byte);
    else {
      if (current.length >= 4) strings.push(current);
      current = "";
    }
  }
  if (current.length >= 4) strings.push(current);
  for (const [characterOffset, zeroOffset] of [[0, 1], [1, 0]]) {
    current = "";
    for (let index = 0; index + 1 < bytes.length; index += 2) {
      const character = bytes[index + characterOffset];
      const zero = bytes[index + zeroOffset];
      if (zero === 0 && character >= 0x20 && character <= 0x7e) current += String.fromCharCode(character);
      else {
        if (current.length >= 4) strings.push(current);
        current = "";
      }
    }
    if (current.length >= 4) strings.push(current);
  }
  return strings.join("\n");
}

export function isTargetScanPath(path) {
  return path.startsWith("src/web/") || path === "package.json" || path === "package-lock.json";
}

export function validateStaticSupplyChainProfile(document, readPath, readMode) {
  if (!document || document.schemaVersion !== "2.0.0"
      || document.profileId !== "static-browser-supply-chain-v2"
      || document.$schema !== "./static-target-profile.schema.json"
      || !Array.isArray(document.components)) {
    throw new Error("Static-target supply-chain profile is not the required v2 authority");
  }
  const componentCount = document.components.length;
  const inputCount = document.components.reduce((count, component) =>
    count + (Array.isArray(component?.inputs) ? component.inputs.length : 0), 0);
  if (componentCount !== 14 || inputCount !== 57) {
    throw new Error(`Static-target supply-chain profile count drift: ${componentCount} components / ${inputCount} inputs`);
  }
  if (typeof readMode !== "function") throw new Error("Static-target supply-chain mode authority is required");
  const componentIds = document.components.map(({ id }) => id);
  if (componentIds.join("\0") !== [...staticSupplyChainComponents.keys()].join("\0")) {
    throw new Error("Static-target supply-chain component set or order drifted");
  }
  const recorded = new Set();
  for (const component of document.components) {
    const expectedComponent = staticSupplyChainComponents.get(component.id);
    if (!expectedComponent || [component.ecosystem, component.releaseUse, component.coverage].join("\0")
        !== expectedComponent.join("\0")) {
      throw new Error(`Static-target supply-chain component contract drift: ${component.id}`);
    }
    const paths = component.inputs?.map(({ path }) => path) ?? [];
    if (paths.join("\0") !== [...paths].sort().join("\0") || new Set(paths).size !== paths.length) {
      throw new Error(`Static-target supply-chain inputs must be unique and sorted: ${component.id}`);
    }
    for (const input of component.inputs ?? []) {
      const expected = staticSupplyChainInputs.get(input.path);
      if (!expected || expected[0] !== component.id || expected[1] !== input.role
          || !/^[a-f0-9]{64}$/u.test(input.sha256 ?? "") || recorded.has(input.path)) {
        throw new Error(`Static-target supply-chain input set, owner, or role drift: ${input.path}`);
      }
      const bytes = readPath(input.path);
      const actual = createHash("sha256").update(bytes).digest("hex");
      if (actual !== input.sha256) throw new Error(`Static-target supply-chain input hash drift: ${input.path}`);
      const mode = readMode(input.path);
      if (mode !== expected[2]) throw new Error(`Static-target supply-chain input mode drift: ${input.path}`);
      recorded.add(input.path);
    }
  }
  const missing = [...staticSupplyChainInputs.keys()].filter((path) => !recorded.has(path));
  if (missing.length || recorded.size !== staticSupplyChainInputs.size) {
    throw new Error(`Static-target supply-chain input set drifted; missing=${JSON.stringify(missing)}`);
  }
  const schemaPath = document.$schema.replace(/^\.\//u, "contracts/supply-chain/v2/");
  const schemaInput = document.components.find(({ id }) => id === "profile-contract")?.inputs
    ?.find(({ path }) => path === schemaPath);
  if (!schemaInput || schemaInput.role !== "schema") {
    throw new Error("Static-target supply-chain profile is not bound to its declared schema");
  }
  return Object.freeze({ componentCount, inputCount });
}

export function validateStaticRepository({
  mode,
  builtRoot = null,
  root = repositoryRoot,
  approvalValidator,
  supplyChainValidator = validateStaticSupplyChainProfile,
} = {}) {
  let records;
  if (mode === "built") {
    if (!builtRoot) throw new Error("Built-output dependency scan requires an existing directory");
    const absolutePaths = filesBelow(builtRoot);
    const paths = absolutePaths.map((path) => relative(builtRoot, path).replaceAll("\\", "/"));
    records = absolutePaths.filter((path) => {
      const logical = relative(builtRoot, path).replaceAll("\\", "/");
      return !ARCHIVE_EXTENSIONS.test(logical)
        && !/(?:^|\/)(?:candidate[-_.]?v?\d+|local-data)(?:[/._-]|$)/iu.test(logical);
    }).map((path) => {
      const bytes = readFileSync(path);
      return { path: relative(builtRoot, path).replaceAll("\\", "/"), text: inspectableOutput(bytes) };
    });
    const result = scanDependencyRecords(records, { mode, historicalEntries: new Map(), paths });
    if (result.violations.length) {
      const details = result.violations.map(({ path, line, rule, text }) => `${path}:${line}: ${rule} (${text})`);
      throw new Error(`Forbidden static dependency references found:\n${details.join("\n")}`);
    }
    return result;
  } else {
    const profileLogicalPath = "contracts/supply-chain/v2/static-target-profile.json";
    const profileBytes = readFileSync(safeRepositoryFile(root, profileLogicalPath));
    supplyChainValidator(JSON.parse(profileBytes.toString("utf8")),
      (path) => readFileSync(safeRepositoryFile(root, path)),
      (path) => trackedMode(root, path));
    const paths = trackedPaths(root).filter((path) => mode !== "target" || isTargetScanPath(path));
    records = readRecords(paths, root);
    const historicalEntries = mode.startsWith("repository-")
      ? loadHistoricalAllowlist({
        authority: mode === "repository-final" ? "approved" : "readiness",
        root,
        ...(approvalValidator ? { validateApproval: approvalValidator } : {}),
      })
      : new Map();
    const result = scanDependencyRecords(records, { mode, historicalEntries, paths });
    if (result.violations.length) {
      const details = result.violations.map(({ path, line, rule, text }) => `${path}:${line}: ${rule} (${text})`);
      throw new Error(`Forbidden static dependency references found:\n${details.join("\n")}`);
    }
    return result;
  }
}

function main() {
  const option = process.argv[2] ?? "--target";
  const mode = option === "--target" ? "target"
    : option === "--repository-readiness" ? "repository-readiness"
      : option === "--repository-final" ? "repository-final"
        : option === "--built" ? "built" : null;
  if (!mode) throw new Error(`Unknown option: ${option}`);
  const builtRoot = mode === "built" ? resolve(webRoot, process.argv[3] ?? "dist") : null;
  const result = validateStaticRepository({ mode, builtRoot });
  const pending = result.findings.filter(({ classification }) => classification === "pending-removal").length;
  console.log(`Static dependency gate passed (${mode}; ${result.findings.length} classified references; ${pending} pending-removal references).`);
}

if (moduleUrl.protocol === "file:" && process.argv[1]
    && resolve(process.argv[1]) === fileURLToPath(moduleUrl)) main();
