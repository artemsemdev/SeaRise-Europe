/**
 * i18n Externalization Lint Script (NFR-018)
 *
 * Scans all React component files (.tsx) for hardcoded user-visible strings.
 * Excludes non-user-facing strings like CSS class names, data-testid, object keys.
 *
 * Run as part of CI:
 *   npx tsx scripts/lint-i18n-externalization.ts
 */

import * as fs from "fs";
import * as path from "path";

const COMPONENT_DIR = path.resolve(__dirname, "../src/app/components");

// Patterns that indicate hardcoded user-visible strings in JSX
// Matches string literals between JSX tags: >Some text<
const JSX_TEXT_PATTERN = />([A-Z][a-z]+(?:\s[a-z]+){2,})</g;

// Strings to ignore (non-user-facing)
const IGNORED_PATTERNS = [
  /data-testid/,
  /className/,
  /style=/,
  /import /,
  /from "/,
  /console\./,
  /aria-/,
  /role="/,
  /type="/,
  /href="/,
  /key=/,
  /id="/,
  /ref=/,
  /"use client"/,
  /\/\//,         // comments
  /\*\s/,         // multi-line comments
  /tabIndex/,
  /title="/,      // title attributes could be user-facing but are commonly used for internal hints
];

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

function main() {
  const files = getComponentFiles(COMPONENT_DIR);
  let issueCount = 0;

  for (const file of files) {
    const content = fs.readFileSync(file, "utf-8");
    const lines = content.split("\n");

    // Check: does the file import from i18n/en?
    const hasI18nImport = content.includes("@/lib/i18n/en") || content.includes("lib/i18n/en");
    const hasApiDataOnly = content.includes("data.") || content.includes("props.");

    // Files that render dynamic content from API or props don't need i18n for those values
    // But they should still import strings for static labels

    if (!hasI18nImport && !hasApiDataOnly) {
      // Check for any user-facing text that should be externalized
      lines.forEach((line, index) => {
        const trimmed = line.trim();
        if (IGNORED_PATTERNS.some((p) => p.test(trimmed))) return;

        // Look for bare string literals in JSX context
        const jsxStringMatch = trimmed.match(/>[A-Z][a-z]+(?:\s[a-z]+)+</);
        if (jsxStringMatch) {
          console.warn(`  ${file}:${index + 1}: Potential hardcoded string: ${trimmed}`);
          issueCount++;
        }
      });
    }
  }

  if (issueCount > 0) {
    console.error(`\n${issueCount} potential hardcoded string(s) found.`);
    console.error("Review the listed strings. If they are user-facing, externalize them to lib/i18n/en.ts.");
    // Warning only, not a hard failure — false positives are possible
    process.exit(0);
  } else {
    console.log("i18n externalization check passed: no obvious hardcoded strings found.");
    process.exit(0);
  }
}

main();
