import { mkdir, mkdtemp, readFile, readdir, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { compileFromFile } from "json-schema-to-typescript";

const frontendDirectory = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const repositoryDirectory = resolve(frontendDirectory, "../..");
const schemaDirectory = join(repositoryDirectory, "contracts/release/v1");
const outputDirectory = join(frontendDirectory, "src/lib/contracts/generated");
const checkOnly = process.argv.includes("--check");

const targets = [
  ["manifest.schema.json", "manifest.ts"],
  ["projection-result.schema.json", "projection-result.ts"],
  ["scenario-config.schema.json", "scenario-config.ts"],
];

const bannerComment = `/* eslint-disable */
/** Generated from contracts/release/v1. Do not edit; run \`npm run contracts:generate\`. */`;

// json-schema-to-typescript models tuples through the draft-07 `items` array.
// Convert only that representation in the temporary bundle; published schemas
// and their 2020-12 identifiers remain untouched.
function schemaForTypeGeneration(value) {
  if (Array.isArray(value)) {
    return value.map(schemaForTypeGeneration);
  }

  if (value === null || typeof value !== "object") {
    return value;
  }

  const converted = {};
  for (const [key, child] of Object.entries(value)) {
    if (key === "prefixItems") {
      continue;
    }
    if (key === "items" && Array.isArray(value.prefixItems)) {
      continue;
    }
    converted[key] = schemaForTypeGeneration(child);
  }

  if (Array.isArray(value.prefixItems)) {
    converted.items = value.prefixItems.map(schemaForTypeGeneration);
    if (value.items === false) {
      converted.additionalItems = false;
    } else if (value.items && typeof value.items === "object") {
      converted.additionalItems = schemaForTypeGeneration(value.items);
    }
  }

  return converted;
}

async function prepareSchemaBundle(directory) {
  for (const name of (await readdir(schemaDirectory)).sort()) {
    if (!name.endsWith(".schema.json")) {
      continue;
    }

    const schema = JSON.parse(await readFile(join(schemaDirectory, name), "utf8"));
    const converted = schemaForTypeGeneration(schema);
    await writeFile(join(directory, name), `${JSON.stringify(converted, null, 2)}\n`);
  }
}

async function generatedSource(schemaPath, temporaryDirectory) {
  return compileFromFile(join(temporaryDirectory, schemaPath), {
    bannerComment,
    cwd: temporaryDirectory,
    enableConstEnums: false,
    maxItems: 20,
    unknownAny: true,
  });
}

const temporaryDirectory = await mkdtemp(join(tmpdir(), "searise-contract-types-"));
const staleFiles = [];

try {
  await prepareSchemaBundle(temporaryDirectory);
  await mkdir(outputDirectory, { recursive: true });

  for (const [schemaPath, outputPath] of targets) {
    const expected = await generatedSource(schemaPath, temporaryDirectory);
    const destination = join(outputDirectory, outputPath);

    if (checkOnly) {
      const actual = await readFile(destination, "utf8").catch(() => "");
      if (actual !== expected) {
        staleFiles.push(outputPath);
      }
      continue;
    }

    await writeFile(destination, expected);
  }
} finally {
  await rm(temporaryDirectory, { recursive: true, force: true });
}

if (staleFiles.length > 0) {
  console.error(
    `Generated public contract types are stale: ${staleFiles.join(", ")}. Run npm run contracts:generate.`,
  );
  process.exitCode = 1;
} else if (checkOnly) {
  console.log("Generated public contract types are current.");
}
