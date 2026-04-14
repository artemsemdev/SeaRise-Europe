/**
 * Prohibited Language Scanner (CONTENT_GUIDELINES §9)
 *
 * Scans all i18n string files for prohibited terms that violate
 * the scientific communication guidelines. Run as part of CI:
 *   npx tsx scripts/lint-prohibited-language.ts
 */

import * as fs from "fs";
import * as path from "path";

// Mirrors CONTENT_GUIDELINES §9 and `docs/delivery/artifacts/content-audit-log.md §1`.
// Every term here is matched case-insensitively. There is intentionally no
// APPROVED_EXCEPTIONS list: the 2026-04-13 audit showed the previous whitelist
// was allowing banned phrases ("is safe", "No risk detected") to survive in
// production copy.
//
// Terms are matched against token boundaries so that single-word bans like
// "certain" do not false-positive on "uncertainty". Multi-word bans still
// behave as substring matches against the raw line.
const PROHIBITED_TERMS: { term: string; wordBoundary: boolean }[] = [
  { term: "will flood", wordBoundary: false },
  { term: "will be underwater", wordBoundary: false },
  { term: "is safe", wordBoundary: false },
  { term: "not at risk", wordBoundary: false },
  { term: "no risk", wordBoundary: false },
  { term: "risk-free", wordBoundary: false },
  { term: "100% accurate", wordBoundary: false },
  { term: "100%", wordBoundary: false },
  { term: "predicts", wordBoundary: true },
  { term: "flood zone", wordBoundary: false },
  { term: "your home", wordBoundary: false },
  { term: "your property", wordBoundary: false },
  { term: "guaranteed", wordBoundary: true },
  { term: "threat level", wordBoundary: false },
  { term: "certain", wordBoundary: true },
  { term: "definite", wordBoundary: true },
  { term: "proven", wordBoundary: true },
  { term: "absolute", wordBoundary: true },
];

function matches(line: string, entry: { term: string; wordBoundary: boolean }): boolean {
  if (entry.wordBoundary) {
    const escaped = entry.term.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    return new RegExp(`\\b${escaped}\\b`, "i").test(line);
  }
  return line.toLowerCase().includes(entry.term.toLowerCase());
}

function scanFile(filePath: string): { term: string; line: number; text: string }[] {
  const content = fs.readFileSync(filePath, "utf-8");
  const lines = content.split("\n");
  const violations: { term: string; line: number; text: string }[] = [];

  lines.forEach((line, index) => {
    for (const entry of PROHIBITED_TERMS) {
      if (matches(line, entry)) {
        violations.push({
          term: entry.term,
          line: index + 1,
          text: line.trim(),
        });
      }
    }
  });

  return violations;
}

function main() {
  const i18nDir = path.resolve(__dirname, "../src/lib/i18n");
  const files = fs.readdirSync(i18nDir).filter((f) => f.endsWith(".ts"));

  let totalViolations = 0;

  for (const file of files) {
    const filePath = path.join(i18nDir, file);
    const violations = scanFile(filePath);

    if (violations.length > 0) {
      console.error(`\n${filePath}:`);
      for (const v of violations) {
        console.error(`  Line ${v.line}: Found "${v.term}" in: ${v.text}`);
        totalViolations++;
      }
    }
  }

  if (totalViolations > 0) {
    console.error(`\n${totalViolations} prohibited language violation(s) found.`);
    process.exit(1);
  } else {
    console.log("Prohibited language scan passed: zero violations.");
    process.exit(0);
  }
}

main();
