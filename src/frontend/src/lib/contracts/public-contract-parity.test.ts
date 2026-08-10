// @vitest-environment node

import { createHash } from "node:crypto";
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

const contractDirectories = [
  resolve(process.cwd(), "../../contracts/release/v1"),
  resolve(process.cwd(), "../../contracts/settlements/v2"),
];
const settlementContractDirectory = contractDirectories[1];

function readJson(path: string): ContractDocument {
  return JSON.parse(readFileSync(path, "utf8")) as ContractDocument;
}

function lexicographicKeyJson(value: unknown): string {
  if (Array.isArray(value)) {
    return `[${value.map(lexicographicKeyJson).join(",")}]`;
  }
  if (value !== null && typeof value === "object") {
    const record = value as Record<string, unknown>;
    return `{${Object.keys(record)
      .sort()
      .map((key) => `${JSON.stringify(key)}:${lexicographicKeyJson(record[key])}`)
      .join(",")}}`;
  }
  const encoded = JSON.stringify(value);
  if (encoded === undefined) throw new TypeError("value is not JSON serializable");
  return encoded;
}

function assertSearchSemantics(document: ContractDocument): void {
  const records = document.documents;
  if (!Array.isArray(records) || document.recordCount !== records.length) {
    throw new TypeError("search shard recordCount differs from documents length");
  }
}

function fixturePaths(kind: "valid" | "invalid"): string[] {
  return contractDirectories.flatMap((contractDirectory) => {
    const directory = resolve(contractDirectory, "fixtures", kind);
    return readdirSync(directory)
      .filter((name) => name.endsWith(".json"))
      .sort()
      .map((name) => resolve(directory, name));
  });
}

function contractValidator(): Ajv2020 {
  const ajv = new Ajv2020({
    allErrors: true,
    strict: true,
    strictRequired: false,
    strictTypes: false,
  });
  addFormats(ajv);
  for (const contractDirectory of contractDirectories) {
    for (const name of readdirSync(contractDirectory).sort()) {
      if (!name.endsWith(".schema.json")) continue;
      ajv.addSchema(readJson(resolve(contractDirectory, name)));
    }
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

  it("shares Arrow-field JSON identity and search-count semantics with Python", () => {
    const geoparquet = readJson(
      resolve(
        settlementContractDirectory,
        "fixtures/valid/settlement-geoparquet.json",
      ),
    );
    const search = readJson(
      resolve(
        settlementContractDirectory,
        "fixtures/valid/settlement-search-shard.json",
      ),
    );
    const preimage = lexicographicKeyJson(geoparquet.arrowFields);

    expect(geoparquet.arrowFieldsCanonicalization).toBe(
      "lexicographic-key-json-v1",
    );
    expect(createHash("sha256").update(preimage, "utf8").digest("hex")).toBe(
      geoparquet.arrowFieldsJsonSha256,
    );
    expect(() => assertSearchSemantics(search)).not.toThrow();

    expect(() =>
      assertSearchSemantics({ ...search, recordCount: Number(search.recordCount) + 1 }),
    ).toThrow(/recordCount/);
  });
});
