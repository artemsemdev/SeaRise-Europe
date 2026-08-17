import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { existsSync, readFileSync, readdirSync, statSync } from "node:fs";
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
  const files = [];
  const visit = (path) => {
    for (const name of readdirSync(path).sort()) {
      const child = resolve(path, name);
      if (statSync(child).isDirectory()) visit(child);
      else files.push(child);
    }
  };
  visit(root);
  return files;
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
    const absolute = resolve(root, path);
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

export function validateStaticSupplyChainProfile(document, readPath) {
  if (!document || document.schemaVersion !== "2.0.0"
      || document.profileId !== "static-browser-supply-chain-v2"
      || !Array.isArray(document.components)) {
    throw new Error("Static-target supply-chain profile is not the required v2 authority");
  }
  const componentCount = document.components.length;
  const inputCount = document.components.reduce((count, component) =>
    count + (Array.isArray(component?.inputs) ? component.inputs.length : 0), 0);
  if (componentCount !== 14 || inputCount !== 57) {
    throw new Error(`Static-target supply-chain profile count drift: ${componentCount} components / ${inputCount} inputs`);
  }
  const byId = new Map(document.components.map((component) => [component.id, component]));
  if (byId.size !== componentCount) throw new Error("Static-target supply-chain component IDs are not unique");
  const required = new Map([
    [".github/workflows/static-quality.yml", ["github-actions", "workflow"]],
    ["tools/static-quality/package-lock.json", ["static-quality-npm", "lock"]],
    ["tools/static-quality/package.json", ["static-quality-npm", "manifest"]],
  ]);
  const qualityInputs = byId.get("static-quality-npm")?.inputs ?? [];
  if (qualityInputs.length !== 2) throw new Error("Static-quality tooling authority must contain exactly two inputs");
  for (const [path, [componentId, role]] of required) {
    const input = byId.get(componentId)?.inputs?.find((candidate) => candidate.path === path);
    if (!input || input.role !== role || !/^[a-f0-9]{64}$/u.test(input.sha256 ?? "")) {
      throw new Error(`Static-target supply-chain authority is missing exact ${componentId} input: ${path}`);
    }
    const actual = createHash("sha256").update(readPath(path)).digest("hex");
    if (actual !== input.sha256) throw new Error(`Static-target supply-chain input hash drift: ${path}`);
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
    if (!builtRoot || !existsSync(builtRoot)) throw new Error("Built-output dependency scan requires an existing directory");
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
    const profilePath = resolve(root, "contracts/supply-chain/v2/static-target-profile.json");
    if (!existsSync(profilePath)) throw new Error("Static-target supply-chain v2 profile is missing");
    supplyChainValidator(JSON.parse(readFileSync(profilePath, "utf8")), (path) => readFileSync(resolve(root, path)));
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
