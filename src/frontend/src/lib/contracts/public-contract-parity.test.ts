// @vitest-environment node

import { readFileSync, readdirSync } from "node:fs";
import { resolve } from "node:path";
import Ajv2020 from "ajv/dist/2020.js";
import addFormats from "ajv-formats";
import { describe, expect, it } from "vitest";

interface ContractDocument {
  $id?: string;
  $schema?: string;
  [key: string]: unknown;
}

const contractDirectory = resolve(process.cwd(), "../../contracts/release/v1");
const fixtureDirectory = resolve(contractDirectory, "fixtures");

function readJson(path: string): ContractDocument {
  return JSON.parse(readFileSync(path, "utf8")) as ContractDocument;
}

function fixturePaths(kind: "valid" | "invalid"): string[] {
  const directory = resolve(fixtureDirectory, kind);
  return readdirSync(directory)
    .filter((name) => name.endsWith(".json"))
    .sort()
    .map((name) => resolve(directory, name));
}

function contractValidator(): Ajv2020 {
  const ajv = new Ajv2020({
    allErrors: true,
    strict: true,
    strictRequired: false,
    strictTypes: false,
  });
  addFormats(ajv);
  for (const name of readdirSync(contractDirectory).sort()) {
    if (!name.endsWith(".schema.json")) continue;
    ajv.addSchema(readJson(resolve(contractDirectory, name)));
  }
  return ajv;
}

describe("Python and TypeScript public contract parity", () => {
  it("accepts every shared valid fixture", () => {
    const ajv = contractValidator();
    const paths = fixturePaths("valid");

    expect(paths.length).toBeGreaterThan(0);
    for (const path of paths) {
      const document = readJson(path);
      const validate = document.$schema
        ? ajv.getSchema(document.$schema)
        : undefined;
      expect(validate, path).toBeDefined();
      expect(validate?.(document), JSON.stringify(validate?.errors)).toBe(true);
    }
  });

  it("rejects every shared negative fixture", () => {
    const ajv = contractValidator();
    const paths = fixturePaths("invalid");

    expect(paths.length).toBeGreaterThan(0);
    for (const path of paths) {
      const document = readJson(path);
      const validate = document.$schema
        ? ajv.getSchema(document.$schema)
        : undefined;
      expect(validate, path).toBeDefined();
      expect(validate?.(document), path).toBe(false);
    }
  });
});
