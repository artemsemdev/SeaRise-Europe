import { execFileSync } from "node:child_process";
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
]);
const ARCHIVE_EXTENSIONS = /\.(?:7z|rar|tar|tar\.bz2|tar\.gz|tar\.xz|tgz|zip)$/iu;

export const forbiddenDependencyRules = Object.freeze([
  Object.freeze({ id: "nextjs-runtime", pattern: /(?:["'](?:next|eslint-config-next)["']|\bnext\/(?:server|headers|navigation|router|image)\b|\bnext (?:build|dev|start)\b|\b\.next\/)/giu }),
  Object.freeze({ id: "dotnet-csharp-nuget", pattern: /(?:\bdotnet\s+(?:build|run|test|restore|publish|format)\b|\bMicrosoft\.AspNetCore\b|\bNuGet\b|<TargetFramework>|\.csproj\b|\.sln\b)/giu }),
  Object.freeze({ id: "postgres-postgis-npgsql", pattern: /(?:\bPostgreSQL\b|\bPostGIS\b|\bNpgsql\b|postgres(?:ql)?:\/\/|\bpostgis\/postgis:|\bpostgres:\d)/giu }),
  Object.freeze({ id: "titiler-runtime", pattern: /(?:\bTiTiler\b|\btitiler(?:\.|-)|developmentseed\/titiler)/giu }),
  Object.freeze({ id: "azurite-runtime", pattern: /(?:\bAzurite\b|mcr\.microsoft\.com\/azure-storage\/azurite|UseDevelopmentStorage=true)/giu }),
  Object.freeze({ id: "azure-runtime-geocoder", pattern: /(?:\bAzure Maps\b.{0,80}\bgeocod|atlas\.microsoft\.com\/(?:search|geocode)|maps\.azure\.com.{0,120}(?:search|geocode))/giu }),
  Object.freeze({ id: "legacy-compose-runtime", pattern: /^\s{0,8}(?:api|frontend|db|postgres|postgis|titiler|azurite):\s*$/gimu }),
  Object.freeze({ id: "node-production-server", pattern: /(?:\bvite preview\b|\bnext start\b|\bnode\s+(?:\.\/)?(?:server|app|index)\.(?:js|mjs|cjs)\b|\bcreateServer\s*\()/giu }),
]);

const pendingRemovalPaths = Object.freeze([
  /^SeaRise(?: Europe)?\.sln$/u,
  /^src\/(?:api|frontend)\//u,
  /^infra\/(?:db|blob-seed)\//u,
  /^docker-compose\.ya?ml$/u,
  /^\.env\.(?:local|pipeline)\.example$/u,
  /^\.github\/workflows\/(?:ci|codeql)\.yml$/u,
  /^scripts\/(?:compose-smoke\.sh|ci\/changed_components\.py)$/u,
  /^src\/pipeline\/(?:__init__|cogify|compute_exposure|config|download|preprocess|register|run_pipeline|upload|validate)\.py$/u,
]);
const legacyPipelineAdapters = /^src\/pipeline\/(?:__init__|cogify|compute_exposure|config|download|preprocess|register|run_pipeline|upload|validate)\.py$/u;
const retainedNodeToolPaths = new Set([
  "src/web/scripts/measure-ar6-release.mjs",
  "src/web/scripts/measure-local-candidate-search.mjs",
  "src/web/scripts/run-local-candidate-e2e.mjs",
  "src/web/scripts/verify-boundary-pmtiles-browser.mjs",
]);
const retainedTestEvidencePaths = new Set([
  "tests/evidence/mutation-pilot-result-state.json",
  "tests/evidence/tdd-slices.json",
  "tests/harness/test_immutable_dependencies.py",
  "tests/test-inventory.json",
]);

function isPendingRemoval(path, ruleId) {
  return pendingRemovalPaths.some((pattern) => pattern.test(path))
    || (ruleId === "dotnet-csharp-nuget" && (
      path.startsWith("src/pipeline/searise_pipeline/supply_chain/")
      || path.startsWith("src/pipeline/tests/supply_chain/")
      || path === "scripts/release/validate_supply_chain_contract.py"
    ));
}

function retainedClass(path, ruleId, historicalEntries) {
  if (historicalEntries.get(path)?.rule === "immutable-v1-supply-chain-evidence") {
    return "immutable-v1-supply-chain-evidence";
  }
  if (path === "src/web/scripts/static-repository-gates.mjs"
      || path === "src/web/scripts/static-repository-gates.test.mjs"
      || path === "contracts/repository-removal/v1/historical-allowlist.preapproval.json"
      || path === "contracts/repository-removal/v1/historical-allowlist.json") {
    return "gate-policy-definition";
  }
  if (retainedTestEvidencePaths.has(path)) {
    return "retained-test-evidence";
  }
  if (ruleId === "node-production-server" && (
    path === "src/web/package.json" || path === "src/web/vite.config.ts"
    || path === "src/web/tests/static-shell.spec.ts"
    || /^src\/web\/scripts\/(?:serve-|offline-lifecycle-server|static-build-root)/u.test(path)
    || retainedNodeToolPaths.has(path)
  )) {
    return "retained-test-tooling";
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
  return findings;
}

function isExecutableText(path) {
  const name = path.split("/").at(-1);
  return EXECUTABLE_NAMES.has(name) || EXECUTABLE_EXTENSIONS.has(extname(path))
    || name?.startsWith("Dockerfile") || /^\.env(?:\.|$)/u.test(name ?? "");
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

export function scanDependencyRecords(records, { mode, historicalEntries = new Map() }) {
  if (!["target", "built", "repository-readiness", "repository-final"].includes(mode)) {
    throw new Error(`Unknown static repository gate mode: ${mode}`);
  }
  const findings = records.flatMap(({ path, text }) => scanText(path, text).map((finding) => {
    const classification = isPendingRemoval(path, finding.rule)
      ? "pending-removal" : retainedClass(path, finding.rule, historicalEntries);
    return Object.freeze({ ...finding, classification });
  }));
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
  return paths.filter((path) => isExecutableText(path) && !ARCHIVE_EXTENSIONS.test(path)).map((path) => {
    const absolute = resolve(root, path);
    const bytes = readFileSync(absolute);
    if (bytes.includes(0)) return null;
    return Object.freeze({ path, text: bytes.toString("utf8") });
  }).filter(Boolean);
}

export function isTargetScanPath(path) {
  return path.startsWith("src/web/") || path === "package.json" || path === "package-lock.json";
}

export function validateStaticRepository({ mode, builtRoot = null, root = repositoryRoot } = {}) {
  let records;
  if (mode === "built") {
    if (!builtRoot || !existsSync(builtRoot)) throw new Error("Built-output dependency scan requires an existing directory");
    records = filesBelow(builtRoot).filter((path) => !ARCHIVE_EXTENSIONS.test(path)).map((path) => {
      const bytes = readFileSync(path);
      return bytes.includes(0) ? null : { path: relative(builtRoot, path).replaceAll("\\", "/"), text: bytes.toString("utf8") };
    }).filter(Boolean);
  } else {
    const paths = trackedPaths(root).filter((path) => mode !== "target" || isTargetScanPath(path));
    records = readRecords(paths, root);
  }
  const result = scanDependencyRecords(records, {
    mode,
    historicalEntries: mode.startsWith("repository-") ? loadHistoricalAllowlist() : new Map(),
  });
  if (result.violations.length) {
    const details = result.violations.map(({ path, line, rule, text }) => `${path}:${line}: ${rule} (${text})`);
    throw new Error(`Forbidden static dependency references found:\n${details.join("\n")}`);
  }
  return result;
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
