import { readFileSync, readdirSync, statSync } from "node:fs";
import { extname, join, relative, resolve } from "node:path";

const root = resolve(import.meta.dirname, "..");
const sourceRoot = resolve(root, "src");
const forbidden = [
  { label: "legacy frontend import", pattern: /(?:from|import\()\s*["'][^"']*src\/frontend/ },
  { label: "Next.js import", pattern: /(?:from|import\()\s*["']next(?:\/|["'])/ },
  { label: "legacy assessment endpoint", pattern: /["'`]\/[^"'`]*assess(?:[/?"'`]|$)/ },
  { label: "legacy geocoder endpoint", pattern: /["'`]\/[^"'`]*geocode(?:[/?"'`]|$)/ },
  { label: "legacy configuration endpoint", pattern: /["'`]\/[^"'`]*config(?:[/?"'`]|$)/ },
  { label: "private candidate path", pattern: /candidate-v7|local-data\/phase-1/i },
  { label: "provider SDK", pattern: /@azure\/|azure-maps|nominatim/i },
  { label: "unsafe HTML injection", pattern: /dangerouslySetInnerHTML/ },
  { label: "backend request identity", pattern: /\brequestId\b/ },
];

function files(directory) {
  return readdirSync(directory)
    .flatMap((name) => {
      const path = join(directory, name);
      return statSync(path).isDirectory() ? files(path) : [path];
    })
    .filter((path) => [".ts", ".tsx", ".css"].includes(extname(path)));
}

const violations = [];
const sourceFiles = files(sourceRoot);
for (const path of sourceFiles) {
  const text = readFileSync(path, "utf8");
  for (const rule of forbidden) {
    if (rule.pattern.test(text)) {
      violations.push(`${relative(root, path)}: ${rule.label}`);
    }
  }
  if (path.includes(`${join("src", "domain")}`)) {
    const domainRules = [
      { label: "framework import in target domain", pattern: /(?:from|import\()\s*["'](?:react|maplibre-gl|next|zustand)(?:\/|["'])/ },
      { label: "network access in target domain", pattern: /\bfetch\s*\(/ },
      { label: "provider import in target domain", pattern: /(?:from|import\()\s*["'][^"']*(?:azure|nominatim)/i },
    ];
    for (const rule of domainRules) {
      if (rule.pattern.test(text)) violations.push(`${relative(root, path)}: ${rule.label}`);
    }
  }
}

if (violations.length > 0) {
  throw new Error(`Static target boundary violations:\n${violations.join("\n")}`);
}

console.log(`validated static target boundaries across ${sourceFiles.length} files`);
