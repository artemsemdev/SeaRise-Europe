/**
 * Prohibited Language Scanner (CONTENT_GUIDELINES §9)
 *
 * Scans all i18n string files for prohibited terms that violate
 * the scientific communication guidelines. Run as part of CI:
 *   npx tsx scripts/lint-prohibited-language.ts
 */

import * as fs from "fs";
import * as path from "path";

// Mirrors CONTENT_GUIDELINES §9. Every term here must be detectable on a
// plain substring match — if a string needs to coexist with one of these, it
// must be rewritten rather than whitelisted. There is intentionally no
// APPROVED_EXCEPTIONS list: the 2026-04-13 audit showed the previous
// whitelist was allowing banned phrases to survive in production copy.
const PROHIBITED_TERMS = [
  "will flood",
  "will be underwater",
  "is safe",
  "not at risk",
  "risk-free",
  "100% accurate",
  "predicts",
  "flood zone",
  "your home",
  "your property",
  "guaranteed",
  "threat level",
];

function scanFile(filePath: string): { term: string; line: number; text: string }[] {
  const content = fs.readFileSync(filePath, "utf-8");
  const lines = content.split("\n");
  const violations: { term: string; line: number; text: string }[] = [];

  lines.forEach((line, index) => {
    const lower = line.toLowerCase();
    for (const term of PROHIBITED_TERMS) {
      if (lower.includes(term.toLowerCase())) {
        violations.push({
          term,
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
