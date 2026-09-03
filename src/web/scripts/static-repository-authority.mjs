import { Buffer } from "node:buffer";
import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { existsSync, lstatSync, readFileSync } from "node:fs";
import { relative, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";

const moduleUrl = new URL(import.meta.url);
const webRoot = moduleUrl.protocol === "file:"
  ? resolve(fileURLToPath(new URL("..", moduleUrl)))
  : process.cwd();
const repositoryRoot = resolve(webRoot, "../..");

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
const gatePolicyTrustPaths = Object.freeze([
  "src/web/scripts/static-repository-gates.mjs",
]);

export const repositoryAuthorityValidatorPath =
  "scripts/repository/validate_static_delivery_owner_verifier_chain_correction.py";
export const staticSupplyChainValidatorPath =
  "scripts/release/validate_supply_chain_contract.py";

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

export function staticSupplyChainValidationArguments(root) {
  return [
    resolve(root, staticSupplyChainValidatorPath),
    "static-profile",
    "--document",
    "contracts/supply-chain/v2/static-target-profile.json",
    "--repository-root",
    root,
  ];
}

export function approvedRemovalChain(root) {
  const validator = resolve(root, repositoryAuthorityValidatorPath);
  if (!existsSync(validator)) throw new Error("Static-delivery authority validator is missing");
  readRegularFile(validator, null, root);
  let headCommit;
  try {
    headCommit = execFileSync("git", ["rev-parse", "HEAD"], {
      cwd: root,
      encoding: "utf8",
    }).trim();
  } catch (error) {
    throw new Error(`Issue-71 authority anchors cannot be derived: ${error.message}`);
  }
  try {
    execFileSync("python3", [
      validator,
      "--repository-root", root,
      "ci",
      "--head-commit", headCommit,
      "--verify-owner-comment",
    ], {
      cwd: root,
      encoding: "utf8",
      stdio: "pipe",
    });
  } catch (error) {
    const detail = error?.stdout?.toString().trim() || error?.stderr?.toString().trim();
    throw new Error(`Static-delivery approval chain is invalid${detail ? `: ${detail}` : ""}`);
  }
  const plan = JSON.parse(readRegularFile(
    resolve(root, "contracts/repository-removal/v2/issue-71/removal-plan.json"),
    "utf8",
    root,
  ));
  const currentAuthority = JSON.parse(readRegularFile(
    resolve(root, "contracts/repository-removal/v11/phase-3-issue-62/preapproval.json"),
    "utf8",
    root,
  ));
  return resolveApprovedGatePolicyBlobs(plan, currentAuthority);
}

export function resolveApprovedGatePolicyBlobs(plan, currentAuthority) {
  return new Map(gatePolicyTrustPaths.map((path) => {
    const matches = plan.entries.filter((entry) =>
      entry.path === path && entry.after?.state === "present");
    const historicalBlob = matches[0]?.after?.gitBlobSha;
    const transitions = currentAuthority.governedPaths?.filter((entry) => entry.path === path) ?? [];
    const transition = transitions[0];
    const approvedBlob = transition?.after?.gitBlobSha;
    if (matches.length !== 1 || transitions.length !== 1
        || transition?.before?.gitBlobSha !== historicalBlob
        || !/^[a-f0-9]{40}$/u.test(approvedBlob ?? "")) {
      throw new Error(`Issue-71 plan lacks one exact approved gate-policy blob: ${path}`);
    }
    return [path, approvedBlob];
  }));
}

function validateGatePolicyTrustRoots(root, auditedCommit, approvedBlobs) {
  for (const path of gatePolicyTrustPaths) {
    const currentBlob = gitBlobSha(readRegularFile(resolve(root, path), null, root));
    const auditedBlob = execFileSync("git", ["rev-parse", `${auditedCommit}:${path}`], {
      cwd: root,
      encoding: "utf8",
    }).trim();
    if (currentBlob !== (approvedBlobs?.get(path) ?? auditedBlob)) {
      throw new Error(`Gate-policy trust root differs from the owner-approved audited blob: ${path}`);
    }
  }
}

export function loadHistoricalAllowlist({
  authority = "readiness",
  root = repositoryRoot,
  validateApproval = approvedRemovalChain,
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
  const approvedGatePolicyBlobs = effectiveAuthority === "approved"
    ? validateApproval(root)
    : undefined;
  const path = approvedExists ? approvedPath : preapprovalPath;
  if (!existsSync(path)) throw new Error("Exact historical terminology allowlist is missing");
  const document = JSON.parse(readRegularFile(path, "utf8", root));
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
  if (effectiveAuthority === "approved") {
    validateGatePolicyTrustRoots(root, document.auditedCommit, approvedGatePolicyBlobs);
  }
  return entries;
}
