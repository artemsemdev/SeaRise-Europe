import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import { extname, relative, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";

const webRoot = resolve(fileURLToPath(new URL("..", import.meta.url)));
const repositoryRoot = resolve(webRoot, "../..");
const historicalMethodologyMarker = "## Historical binary-method evidence (superseded)";

const sourceExtensions = new Set([".css", ".html", ".md", ".ts", ".tsx"]);
const builtExtensions = new Set([".css", ".html", ".js"]);
const excludedSourceParts = [
  `${sep}contracts${sep}generated${sep}`,
  ".test.ts",
  ".test.tsx",
];
const historicalPathAllowlist = [
  `docs${sep}architecture${sep}adr${sep}`,
  `docs${sep}evidence${sep}`,
  `docs${sep}science${sep}`,
  `docs${sep}product${sep}Mock${sep}SeaRise-Flight.html`,
];

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

function filesBelow(root, extensions) {
  if (!existsSync(root)) throw new Error(`Content scan root does not exist: ${root}`);
  const files = [];
  const visit = (path) => {
    for (const name of readdirSync(path).sort()) {
      const child = resolve(path, name);
      if (statSync(child).isDirectory()) visit(child);
      else if (extensions.has(extname(child))) files.push(child);
    }
  };
  visit(root);
  return files;
}

function activeMethodology(content, path) {
  if (path !== resolve(repositoryRoot, "docs/methodology.md")) return content;
  const marker = content.indexOf(historicalMethodologyMarker);
  if (marker < 0) {
    throw new Error("Methodology is missing its explicit historical-evidence boundary");
  }
  return content.slice(0, marker);
}

export function scanContent(content) {
  const violations = [];
  for (const claim of prohibitedTargetClaims) {
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

function repositorySources() {
  const production = filesBelow(resolve(webRoot, "src"), sourceExtensions).filter(
    (path) => !excludedSourceParts.some((part) => path.includes(part)),
  );
  const documents = filesBelow(resolve(repositoryRoot, "docs"), sourceExtensions).filter(
    (path) => !historicalPathAllowlist.some((part) => path.includes(part)),
  );
  return [...production, resolve(webRoot, "index.html"), ...documents];
}

function verifyMutationSensitivity() {
  const controls = [
    "ModeledExposureDetected",
    "This location is modelled as exposed.",
    "Binary exposure classification",
    "Property risk score",
  ];
  for (const control of controls) {
    if (scanContent(control).length === 0) {
      throw new Error(`Content scan mutation control was not rejected: ${control}`);
    }
  }
}

function main() {
  verifyMutationSensitivity();
  const builtIndex = process.argv.indexOf("--built");
  const builtRoot = builtIndex < 0 ? null : process.argv[builtIndex + 1];
  if (builtIndex >= 0 && !builtRoot) throw new Error("--built requires a directory");
  const files = builtRoot
    ? filesBelow(resolve(webRoot, builtRoot), builtExtensions)
    : repositorySources();
  const violations = [];
  for (const path of files) {
    const content = activeMethodology(readFileSync(path, "utf8"), path);
    for (const violation of scanContent(content)) {
      violations.push(`${relative(repositoryRoot, path)}:${violation.line}: ${violation.claim} (${violation.text})`);
    }
  }
  if (violations.length > 0) {
    throw new Error(`Prohibited target-domain claims found:\n${violations.join("\n")}`);
  }
  const scope = builtRoot ? `built assets in ${builtRoot}` : "static target source and active documentation";
  console.log(`Target content contract passed for ${files.length} files (${scope}).`);
}

main();
