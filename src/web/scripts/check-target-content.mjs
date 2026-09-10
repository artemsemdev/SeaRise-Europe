import { createHash } from "node:crypto";
import { Buffer } from "node:buffer";
import { execFileSync } from "node:child_process";
import { existsSync, lstatSync, readdirSync, readFileSync } from "node:fs";
import { extname, relative, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";
import { namedEntryFiles } from "./service-worker-precache.mjs";

const moduleUrl = new URL(import.meta.url);
const webRoot = moduleUrl.protocol === "file:"
  ? resolve(fileURLToPath(new URL("..", moduleUrl)))
  : process.cwd();
const repositoryRoot = resolve(webRoot, "../..");
const historicalMethodologyMarker = "## Historical binary-method evidence (superseded)";
const authoritativeAdr024Path = resolve(
  repositoryRoot,
  "docs/architecture/adr/ADR-024-ar6-regional-projection-contract.md",
);
const authoritativeAdr024Rejection = "`ProjectionAvailable` replaces both legacy binary exposure outcomes. The\nhistorical `ModeledExposureDetected` and `NoModeledExposureDetected` states do\nnot appear in a release governed by this ADR.";
const canonicalFlightMockPath = resolve(
  repositoryRoot,
  "docs/product/Mock/SeaRise-Flight.html",
);
const canonicalFlightRequirementsPath = resolve(
  repositoryRoot,
  "docs/product/Mock/MOCK_REQUIREMENTS_MAP.md",
);
const canonicalFlightContractMarkers = Object.freeze([
  "AR6 PROJECTION REFERENCE ONLY.",
  "CANONICAL VISUAL AND INTERACTION REFERENCE FOR THE RETAINED PROJECTION APP.",
  "PRESERVE: layout, information hierarchy, map-first composition, controls,",
  "SCIENTIFIC CONTENT EXCEPTION (ADR-024):",
  "exposed and notexposed -> ProjectionAvailable",
  "unavailable -> DataUnavailable",
  "outofscope -> OutOfScope",
  "UnsupportedGeography is missing and must be added.",
  "technical failures stay outside the scientific outcome domain.",
]);
const canonicalFlightRequirementsMarkers = Object.freeze([
  "> **Status:** Retained AR6 projection implementation contract",
  "## Non-negotiable preservation contract",
  "| `ProjectionAvailable` | Replace both `exposed` and `notexposed` binary cards",
  "| `DataUnavailable` | Maps from `unavailable` |",
  "| `OutOfScope` | Maps from `outofscope` |",
  "| `UnsupportedGeography` | **Missing from the export** |",
]);

const sourceExtensions = new Set([".css", ".html", ".md", ".ts", ".tsx"]);
const builtExtensions = new Set([".css", ".html", ".js"]);
const excludedSourceParts = [
  `${sep}contracts${sep}generated${sep}`,
  ".test.ts",
  ".test.tsx",
];
const historicalRules = Object.freeze({
  "historical-adr-term": /^docs\/architecture\/adr\/[^/]+\.md$/u,
  "historical-changelog-term": /^CHANGELOG\.md$/u,
  "historical-five-state-evidence": /^docs\/(?:evidence|science)\/[^/]+(?:\/[^/]+)*\.md$/u,
  "immutable-v1-supply-chain-evidence": /^contracts\/supply-chain\/v1\//u,
  "canonical-design-reference": /^docs\/product\/Mock\/SeaRise-Flight\.html$/u,
});
const historicalRuleClaims = Object.freeze({
  "historical-adr-term": new Set([
    "legacy-outcome-modeled-exposure",
    "legacy-outcome-no-modeled-exposure",
  ]),
  "historical-changelog-term": new Set([
    "legacy-outcome-modeled-exposure",
    "legacy-outcome-no-modeled-exposure",
  ]),
  "historical-five-state-evidence": new Set([
    "legacy-outcome-modeled-exposure",
    "legacy-outcome-no-modeled-exposure",
    "legacy-copy-modeled-exposure",
    "legacy-copy-no-modeled-exposure",
    "binary-exposure-product",
    "terrain-comparison-product",
  ]),
  "immutable-v1-supply-chain-evidence": new Set(),
  "canonical-design-reference": new Set(),
});
const activeAuthorityPaths = new Set([
  "docs/architecture/adr/ADR-024-ar6-regional-projection-contract.md",
  "docs/methodology.md",
  "docs/product/Mock/MOCK_REQUIREMENTS_MAP.md",
]);

export const prohibitedTargetClaims = Object.freeze([
  Object.freeze({ id: "legacy-outcome-modeled-exposure", pattern: /\bModeledExposureDetected\b/giu }),
  Object.freeze({ id: "legacy-outcome-no-modeled-exposure", pattern: /\bNoModeledExposureDetected\b/giu }),
  Object.freeze({ id: "legacy-copy-modeled-exposure", pattern: /\bmodeled exposure detected\b/giu }),
  Object.freeze({ id: "legacy-copy-no-modeled-exposure", pattern: /\bno modeled exposure detected\b/giu }),
  Object.freeze({ id: "affirmative-modeled-exposure", pattern: /\bmodel(?:ed|led) as exposed\b/giu }),
  Object.freeze({ id: "affirmative-classified-exposure", pattern: /\bclassified as (?:not )?exposed\b/giu }),
  Object.freeze({ id: "binary-exposure-product", pattern: /\bbinary exposure classification\b/giu }),
  Object.freeze({ id: "terrain-comparison-product", pattern: /\bterrain comparison (?:outcome|result)\b/giu }),
  Object.freeze({ id: "property-risk-product", pattern: /\bproperty risk (?:rating|score)\b/giu }),
  Object.freeze({ id: "inundation-product", pattern: /\binundation (?:animation|map|outcome|result)\b/giu }),
]);

export const prohibitedProductCopy = Object.freeze([
  Object.freeze({ id: "future-flood-certainty", pattern: /\b(?:this|the) (?:location|place|settlement) will (?:flood|be underwater)\b/giu }),
  Object.freeze({ id: "safety-certainty", pattern: /\b(?:this|the) (?:location|place|settlement) is (?:safe|protected)\b/giu }),
  Object.freeze({ id: "risk-certainty", pattern: /\b(?:no risk|risk detected)\b/giu }),
  Object.freeze({ id: "personal-property-claim", pattern: /\byour (?:home|property)\b/giu }),
  Object.freeze({ id: "precision-certainty", pattern: /\b100% accurate\b/giu }),
  Object.freeze({ id: "complete-settlement-coverage", pattern: /\ball European settlements\b/giu }),
  Object.freeze({ id: "unqualified-offline-claim", pattern: /\bfully offline\b/giu }),
  Object.freeze({ id: "permanent-cost-claim", pattern: /\bfree forever\b/giu }),
  Object.freeze({ id: "relative-year-horizon", pattern: /(?:^|[^\w])\+\s*\d+\s*years?\b/giu }),
  Object.freeze({ id: "forecast-model-framing", pattern: /\b(?:(?:IPCC|AR6|sea-level) forecast|(?:forecast|prediction) model)\b/giu }),
  Object.freeze({ id: "five-state-target-model", pattern: /\bfive-state (?:result|outcome|product|model)\b/giu }),
  Object.freeze({ id: "flood-probability-assertion", pattern: /\bflood probability (?:is|of|equals|:)\b/giu }),
]);

function filesBelow(root, extensions) {
  const rootStatus = lstatSync(root);
  if (rootStatus.isSymbolicLink()) throw new Error(`Content-scan root must not be a symlink: ${root}`);
  if (!rootStatus.isDirectory()) throw new Error(`Content-scan root must be a directory: ${root}`);
  const files = [];
  const visit = (path) => {
    for (const name of readdirSync(path).sort()) {
      const child = resolve(path, name);
      const status = lstatSync(child);
      if (status.isSymbolicLink()) throw new Error(`Content scan must not traverse symlinks: ${child}`);
      if (status.isDirectory()) visit(child);
      else if (!status.isFile()) throw new Error(`Content scan accepts only regular files: ${child}`);
      else if (extensions.has(extname(child))) files.push(child);
    }
  };
  visit(root);
  return files;
}

function readRegularFile(path, encoding = null, root = repositoryRoot) {
  const repositoryRelative = relative(root, path);
  if (repositoryRelative.startsWith(`..${sep}`) || repositoryRelative === "..") {
    throw new Error(`Content scan input must stay inside the repository: ${path}`);
  }
  let current = root;
  const rootStatus = lstatSync(current);
  if (rootStatus.isSymbolicLink() || !rootStatus.isDirectory()) {
    throw new Error(`Content-scan repository root must be a regular directory: ${root}`);
  }
  for (const part of repositoryRelative.split(sep).filter(Boolean)) {
    current = resolve(current, part);
    const status = lstatSync(current);
    if (status.isSymbolicLink()) {
      throw new Error(`Content scan input must not use symlinks: ${path}`);
    }
  }
  if (!lstatSync(current).isFile()) {
    throw new Error(`Content scan input must be a regular file: ${path}`);
  }
  return readFileSync(current, encoding ?? undefined);
}

export function readScanFile(path, scanRoot) {
  return readRegularFile(path, "utf8", scanRoot);
}

function gitBlobSha(content) {
  const bytes = Buffer.from(content);
  return createHash("sha1").update(`blob ${bytes.length}\0`).update(bytes).digest("hex");
}

function hasExactKeys(value, expected) {
  return value && typeof value === "object" && !Array.isArray(value)
    && Object.keys(value).sort().join("\0") === [...expected].sort().join("\0");
}

export function validateHistoricalAllowlist(document, readPath, {
  authority = "approved",
  resolveTree = null,
  resolveBlob = null,
} = {}) {
  const approved = authority === "approved";
  const readiness = authority === "readiness";
  const anchorValid = approved
    ? /^[a-f0-9]{40}$/u.test(document?.auditedCommit ?? "")
      && /^[a-f0-9]{40}$/u.test(document?.auditedTree ?? "")
      && hasExactKeys(document, ["schemaVersion", "auditedCommit", "auditedTree", "entries"])
    : readiness && document?.authority === "preapproval-current-blobs"
      && hasExactKeys(document, ["schemaVersion", "authority", "entries"]);
  if (!document || document.schemaVersion !== "1.0.0" || !Array.isArray(document.entries)
      || document.entries.length === 0 || !anchorValid) {
    throw new Error("Historical terminology allowlist is not a v1 document");
  }
  if (approved && resolveTree && resolveTree(document.auditedCommit) !== document.auditedTree) {
    throw new Error("Historical terminology allowlist audited tree does not match its commit");
  }
  const entries = new Map();
  const ids = new Set();
  for (const entry of document.entries) {
    const rule = historicalRules[entry?.rule];
    if (!entry || !hasExactKeys(entry, [
      "id", "path", "gitBlobSha", "rule", "reason", "activeRuntimeAllowed",
    ]) || !/^[a-z0-9]+(?:-[a-z0-9]+)*$/u.test(entry.id ?? "")
        || typeof entry.path !== "string" || !rule || !rule.test(entry.path)
        || !/^[a-f0-9]{40}$/u.test(entry.gitBlobSha ?? "")
        || typeof entry.reason !== "string" || entry.reason.length === 0
        || entry.activeRuntimeAllowed !== false || entry.path.startsWith("src/web/")
        || entry.path.startsWith("src/pipeline/searise_pipeline/")
        || activeAuthorityPaths.has(entry.path)) {
      throw new Error(`Historical terminology allowlist has an invalid entry: ${entry?.id ?? "unknown"}`);
    }
    if (ids.has(entry.id)) throw new Error(`Historical terminology allowlist repeats id ${entry.id}`);
    if (entries.has(entry.path)) throw new Error(`Historical terminology allowlist repeats ${entry.path}`);
    ids.add(entry.id);
    const content = readPath(entry.path);
    if (gitBlobSha(content) !== entry.gitBlobSha) {
      throw new Error(`Historical terminology allowlist blob mismatch: ${entry.path}`);
    }
    if (approved && resolveBlob && resolveBlob(document.auditedCommit, entry.path) !== entry.gitBlobSha) {
      throw new Error(`Historical terminology allowlist audited blob mismatch: ${entry.path}`);
    }
    entries.set(entry.path, Object.freeze({
      rule: entry.rule,
      gitBlobSha: entry.gitBlobSha,
      allowedClaims: historicalRuleClaims[entry.rule],
    }));
  }
  return entries;
}

export function ownerCommentVerificationArguments(helpText, root) {
  const options = new Set(String(helpText).match(/--[a-z0-9-]+/gu) ?? []);
  if (!options.has("--verify-owner-comment")) {
    throw new Error(
      "Repository-removal validator lacks required --verify-owner-comment capability",
    );
  }
  return ["--repository-root", root, "--verify-owner-comment"];
}

export function postCutoverValidationArguments(root, headCommit) {
  return [
    resolve(root, "scripts/repository/validate_post_cutover.py"),
    "--repository-root", root,
    "--head-commit", headCommit,
    "--evidence-only",
  ];
}

function completedRemovalEvidence(root) {
  const headCommit = execFileSync("git", ["rev-parse", "HEAD"], {
    cwd: root,
    encoding: "utf8",
  }).trim();
  const args = postCutoverValidationArguments(root, headCommit);
  readRegularFile(args[0], null, root);
  try {
    execFileSync("python3", args, { cwd: root, encoding: "utf8", stdio: "pipe" });
  } catch (error) {
    const detail = error?.stdout?.toString().trim() || error?.stderr?.toString().trim();
    throw new Error(`Pinned completed evidence or current safeguards are invalid${detail ? `: ${detail}` : ""}`);
  }
}

export function loadHistoricalAllowlist({
  authority = "readiness",
  root = repositoryRoot,
  validateApproval = completedRemovalEvidence,
} = {}) {
  const approvedPath = resolve(root, "contracts/repository-removal/v1/historical-allowlist.json");
  const preapprovalPath = resolve(root, "contracts/repository-removal/v1/historical-allowlist.preapproval.json");
  if (authority !== "approved" && authority !== "readiness") {
    throw new Error(`Unknown historical allowlist authority: ${authority}`);
  }
  const approvedExists = existsSync(approvedPath);
  if (authority === "approved" && !approvedExists) {
    throw new Error("Approved historical allowlist is missing");
  }
  const effectiveAuthority = approvedExists ? "approved" : authority;
  if (effectiveAuthority === "approved") validateApproval(root);
  const path = approvedExists ? approvedPath : preapprovalPath;
  if (!existsSync(path)) throw new Error("Exact historical terminology allowlist is missing");
  const document = JSON.parse(readRegularFile(path, "utf8", root));
  // A pull-request checkout is intentionally shallow.  Readiness still binds
  // every allowlisted path to its declared Git-blob digest, but only the
  // owner-approved authority may require the older audited commit object and
  // its tree to be present locally.
  const approvedGitResolvers = effectiveAuthority === "approved" ? {
    resolveTree: (commit) => execFileSync("git", ["rev-parse", `${commit}^{tree}`], {
      cwd: root,
      encoding: "utf8",
    }).trim(),
    resolveBlob: (commit, repositoryPath) => execFileSync("git", ["rev-parse", `${commit}:${repositoryPath}`], {
      cwd: root,
      encoding: "utf8",
    }).trim(),
  } : {};
  const entries = validateHistoricalAllowlist(document, (repositoryPath) =>
    readRegularFile(resolve(root, repositoryPath), "utf8", root), {
      authority: effectiveAuthority,
      ...approvedGitResolvers,
    });
  return entries;
}

function activeMethodology(content, path) {
  if (path !== resolve(repositoryRoot, "docs/methodology.md")) return content;
  const marker = content.indexOf(historicalMethodologyMarker);
  if (marker < 0) {
    throw new Error("Methodology is missing its explicit historical-evidence boundary");
  }
  return content.slice(0, marker);
}

export function activeAuthoritativeDocument(content, path) {
  if (path !== authoritativeAdr024Path) return activeMethodology(content, path);
  return content.replace(authoritativeAdr024Rejection,
    "`ProjectionAvailable` replaces both explicitly rejected legacy state identifiers, which do not appear in a release governed by this ADR.");
}

export function validateFlightReferenceContract(content, requirements) {
  const doctype = content.indexOf("<!DOCTYPE html>");
  if (doctype < 0) throw new Error("Canonical Flight mock is missing its document boundary");
  const annotation = content.slice(0, doctype);
  if (annotation.includes("ACTIVE CANONICAL VISUAL AND INTERACTION REFERENCE.")) {
    throw new Error("Flight must be scoped to the retained AR6 projection reference");
  }
  for (const marker of canonicalFlightContractMarkers) {
    if (!annotation.includes(marker)) {
      throw new Error(`Canonical Flight mock is missing its authority marker: ${marker}`);
    }
  }
  for (const marker of canonicalFlightRequirementsMarkers) {
    if (!requirements.includes(marker)) {
      throw new Error(`Canonical Flight requirements are missing their authority marker: ${marker}`);
    }
  }
  const digest = createHash("sha256").update(content).digest("hex");
  if (!requirements.includes(digest)) {
    throw new Error(`Canonical Flight requirements do not declare the current mock SHA-256: ${digest}`);
  }
}

function scanClaims(content, claims) {
  const violations = [];
  for (const claim of claims) {
    claim.pattern.lastIndex = 0;
    for (const match of content.matchAll(claim.pattern)) {
      const prefix = content.slice(0, match.index);
      violations.push(Object.freeze({
        claim: claim.id,
        line: prefix.split("\n").length,
        text: match[0],
      }));
    }
  }
  return Object.freeze(violations);
}

// Only the atlas may describe source-backed modeled exposure and inundation.
// Other legacy outcomes and all certainty/property claims remain prohibited.
const atlasSourceDocuments = new Set([
  "docs/product/COASTAL_ATLAS_PRD.md",
  "docs/product/COASTAL_ATLAS_CONTENT.md",
  "docs/product/COASTAL_ATLAS_DESIGN.md",
  "docs/architecture/adr/ADR-028-coastal-atlas-adoption.md",
]);
const atlasDomainClaims = new Set(["affirmative-modeled-exposure", "inundation-product"]);

export function sourceProductScope(repositoryPath) {
  const canonical = !repositoryPath.includes("\\") && !repositoryPath.startsWith("/")
    && repositoryPath.split("/").every((part) => part && part !== "." && part !== "..");
  return canonical && (repositoryPath.startsWith("src/web/src/atlas/")
    || atlasSourceDocuments.has(repositoryPath)) ? "atlas" : "projection";
}

export function scanContent(content, product = "projection") {
  if (product !== "projection" && product !== "atlas") throw new Error("Unknown product scope");
  const claims = product === "atlas"
    ? prohibitedTargetClaims.filter((claim) => !atlasDomainClaims.has(claim.id))
    : prohibitedTargetClaims;
  return scanClaims(content, claims);
}

export function scanProductCopy(content) {
  return scanClaims(content, prohibitedProductCopy);
}

export function builtAtlasFiles(viteManifest) {
  const atlas = namedEntryFiles(viteManifest, "src/atlas/main.tsx");
  // Shared code retains the stricter projection vocabulary. The root document
  // is the only HTML route whose own copy belongs to the Atlas product.
  const others = namedEntryFiles(viteManifest, "src/main.tsx");
  for (const [key, entry] of Object.entries(viteManifest)) {
    if (entry.isEntry && key !== "src/atlas/main.tsx" && key !== "index.html") {
      for (const file of namedEntryFiles(viteManifest, key)) others.add(file);
    }
  }
  return new Set(["index.html", ...[...atlas].filter((file) => !others.has(file))]);
}

function repositorySources() {
  const production = filesBelow(resolve(webRoot, "src"), sourceExtensions).filter(
    (path) => !excludedSourceParts.some((part) => path.includes(part)),
  );
  const documents = filesBelow(resolve(repositoryRoot, "docs"), sourceExtensions).filter(
    (path) => path !== canonicalFlightMockPath,
  );
  return [...production, resolve(webRoot, "index.html"), ...documents];
}

function verifyMutationSensitivity() {
  const targetControls = [
    "ModeledExposureDetected",
    "This location is modelled as exposed.",
    "Binary exposure classification",
    "Property risk score",
  ];
  for (const control of targetControls) {
    if (scanContent(control).length === 0) {
      throw new Error(`Content scan mutation control was not rejected: ${control}`);
    }
  }
  const productCopyControls = [
    "This location will flood.",
    "This place is safe.",
    "Risk detected.",
    "Your property is exposed.",
    "This result is 100% accurate.",
    "Search all European settlements.",
    "Works fully offline.",
    "Free forever.",
    "Horizon +50 years.",
    "IPCC forecast model.",
    "Five-state outcome.",
    "Flood probability is 20%.",
  ];
  for (const control of productCopyControls) {
    if (scanProductCopy(control).length === 0) {
      throw new Error(`Product-copy mutation control was not rejected: ${control}`);
    }
  }
}

function main() {
  verifyMutationSensitivity();
  validateFlightReferenceContract(
    readRegularFile(canonicalFlightMockPath, "utf8"),
    readRegularFile(canonicalFlightRequirementsPath, "utf8"),
  );
  const builtIndex = process.argv.indexOf("--built");
  const builtRoot = builtIndex < 0 ? null : process.argv[builtIndex + 1];
  if (builtIndex >= 0 && !builtRoot) throw new Error("--built requires a directory");
  const resolvedBuiltRoot = builtRoot ? resolve(webRoot, builtRoot) : null;
  const scanRoot = resolvedBuiltRoot ?? repositoryRoot;
  const files = resolvedBuiltRoot
    ? filesBelow(resolvedBuiltRoot, builtExtensions)
    : repositorySources();
  const atlasFiles = resolvedBuiltRoot ? builtAtlasFiles(JSON.parse(
    readScanFile(resolve(resolvedBuiltRoot, "vite-manifest.json"), resolvedBuiltRoot),
  )) : null;
  const allowedHistoricalPaths = builtRoot ? new Map() : loadHistoricalAllowlist();
  const violations = [];
  for (const path of files) {
    const repositoryPath = relative(repositoryRoot, path).replaceAll("\\", "/");
    const content = activeAuthoritativeDocument(readScanFile(path, scanRoot), path);
    const product = atlasFiles
      ? (atlasFiles.has(relative(resolvedBuiltRoot, path).replaceAll("\\", "/")) ? "atlas" : "projection")
      : sourceProductScope(repositoryPath);
    const contentViolations = [...scanContent(content, product)];
    const isProductCopy = builtRoot
      || path === resolve(webRoot, "index.html")
      || path.startsWith(`${resolve(webRoot, "src")}${sep}`)
      || allowedHistoricalPaths.has(repositoryPath);
    if (isProductCopy) contentViolations.push(...scanProductCopy(content));
    for (const violation of contentViolations) {
      if (allowedHistoricalPaths.get(repositoryPath)?.allowedClaims.has(violation.claim)) continue;
      violations.push(`${relative(repositoryRoot, path)}:${violation.line}: ${violation.claim} (${violation.text})`);
    }
  }
  if (violations.length > 0) {
    throw new Error(`Prohibited target-domain claims found:\n${violations.join("\n")}`);
  }
  const repositoryGate = resolve(webRoot, "scripts/static-repository-gates.mjs");
  const gateOptions = builtRoot
    ? [["--built", builtRoot]]
    : [["--target"], ["--repository-readiness"]];
  for (const options of gateOptions) {
    execFileSync(process.execPath, [repositoryGate, ...options], {
      cwd: webRoot,
      encoding: "utf8",
      stdio: "inherit",
    });
  }
  const scope = builtRoot ? `built assets in ${builtRoot}` : "static target source and active documentation";
  console.log(`Target content contract passed for ${files.length} files (${scope}).`);
}

if (moduleUrl.protocol === "file:" && process.argv[1]
    && resolve(process.argv[1]) === fileURLToPath(moduleUrl)) main();
