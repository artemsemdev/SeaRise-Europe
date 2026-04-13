/**
 * i18n Externalization Lint Script (NFR-018)
 *
 * Scans all React component files (.tsx) for hardcoded user-visible strings.
 * Covers two kinds of leaks:
 *   1. JSX text content:  <p>Clear search</p>
 *   2. User-facing attributes:  title="Clear search", aria-label="...", placeholder="...", alt="..."
 *
 * Every .tsx file is scanned, regardless of whether it imports from `@/lib/i18n/en`.
 * Partial externalization is normal and the file-level skip used to let hardcoded
 * strings ride on the coattails of a single i18n import.
 *
 * Run as part of CI:
 *   npx tsx scripts/lint-i18n-externalization.ts
 */

import * as fs from "fs";
import * as path from "path";

const COMPONENT_DIR = path.resolve(__dirname, "../src/app/components");

// JSX text content: >Some Capitalized Text With Spaces<
const JSX_TEXT_PATTERN = />([A-Z][a-z]+(?:\s[a-zA-Z]+)+)</;

// User-facing attributes whose string-literal values must come from i18n.
// Matches:  title="Clear search"   aria-label="Close panel"
// Does NOT match JSX expressions:  title={strings.search.clearLabel}
const USER_FACING_ATTR_PATTERN =
  /(?:title|aria-label|aria-description|alt|placeholder)="([A-Z][a-z]+(?:\s[a-zA-Z]+)+)"/;

// Line-level filters: lines that cannot contain user-visible content.
const IGNORED_LINE_PATTERNS = [
  /^import\s/,
  /^from\s/,
  /^\/\//,
  /^\*\s/,
  /^\*\//,
  /^\/\*/,
  /console\./,
];

// Role/type attribute values are not user-facing (they are ARIA/HTML contract strings).
// A line that only contains these should not trip the JSX text scan either.
const TECHNICAL_ATTRS = /\b(?:role|type|href|key|id|data-testid|tabIndex)=/;

function getComponentFiles(dir: string): string[] {
  const files: string[] = [];
  const entries = fs.readdirSync(dir, { withFileTypes: true });

  for (const entry of entries) {
    const fullPath = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      files.push(...getComponentFiles(fullPath));
    } else if (entry.name.endsWith(".tsx")) {
      files.push(fullPath);
    }
  }

  return files;
}

interface Finding {
  file: string;
  line: number;
  kind: "jsx-text" | "attribute";
  snippet: string;
}

function scanFile(file: string): Finding[] {
  const findings: Finding[] = [];
  const content = fs.readFileSync(file, "utf-8");
  const lines = content.split("\n");

  lines.forEach((line, index) => {
    const trimmed = line.trim();
    if (!trimmed) return;
    if (IGNORED_LINE_PATTERNS.some((p) => p.test(trimmed))) return;

    const attrMatch = trimmed.match(USER_FACING_ATTR_PATTERN);
    if (attrMatch) {
      findings.push({
        file,
        line: index + 1,
        kind: "attribute",
        snippet: attrMatch[0],
      });
    }

    // Only scan JSX text on lines that look like JSX (contain a `>...<` shape
    // and are not pure technical-attribute declarations like type=/role=).
    if (!TECHNICAL_ATTRS.test(trimmed) || trimmed.includes(">")) {
      const jsxMatch = trimmed.match(JSX_TEXT_PATTERN);
      if (jsxMatch) {
        findings.push({
          file,
          line: index + 1,
          kind: "jsx-text",
          snippet: jsxMatch[0],
        });
      }
    }
  });

  return findings;
}

function main() {
  const files = getComponentFiles(COMPONENT_DIR);
  const allFindings: Finding[] = [];

  for (const file of files) {
    allFindings.push(...scanFile(file));
  }

  if (allFindings.length > 0) {
    console.error(`i18n externalization check failed: ${allFindings.length} finding(s).\n`);
    for (const f of allFindings) {
      const rel = path.relative(path.resolve(__dirname, ".."), f.file);
      console.error(`  ${rel}:${f.line} [${f.kind}]  ${f.snippet}`);
    }
    console.error(
      "\nExternalize these strings to lib/i18n/en.ts. If a finding is a false positive, tighten the scanner rather than whitelisting the line."
    );
    process.exit(1);
  }

  console.log("i18n externalization check passed: no hardcoded strings found.");
  process.exit(0);
}

main();
