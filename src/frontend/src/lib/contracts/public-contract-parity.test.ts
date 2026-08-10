// @vitest-environment node

import { createHash } from "node:crypto";
import { readFileSync, readdirSync } from "node:fs";
import { resolve } from "node:path";
import Ajv2020 from "ajv/dist/2020.js";
import addFormats from "ajv-formats";
import { describe, expect, it } from "vitest";
import { validateGateReportSemantics } from "./gate-report-semantics";
import type { GateReportDocument } from "./gate-report-semantics";

interface ContractDocument {
  $id?: string;
  $schema?: string;
  [key: string]: unknown;
}

const contractDirectories = [
  resolve(process.cwd(), "../../contracts/release/v1"),
  resolve(process.cwd(), "../../contracts/release-gates/v1"),
  resolve(process.cwd(), "../../contracts/settlements/v2"),
];
const releaseGateContractDirectory = contractDirectories[1];
const settlementContractDirectory = contractDirectories[2];

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

  it("shares release gate semantic valid and invalid vectors", () => {
    const ajv = contractValidator();
    const validate = ajv.getSchema(
      "https://artemsemdev.github.io/SeaRise-Europe/contracts/release-gates/v1/gate-report.schema.json",
    );
    const validPaths = readdirSync(
      resolve(releaseGateContractDirectory, "fixtures/valid"),
    )
      .filter((name) => name.endsWith(".json"))
      .sort();
    const invalidPaths = readdirSync(
      resolve(releaseGateContractDirectory, "fixtures/semantic-invalid"),
    )
      .filter((name) => name.endsWith(".json"))
      .sort();

    for (const name of validPaths) {
      const document = readJson(
        resolve(releaseGateContractDirectory, "fixtures/valid", name),
      );
      expect(validate?.(document), JSON.stringify(validate?.errors)).toBe(true);
      expect(() =>
        validateGateReportSemantics(
          document as unknown as GateReportDocument,
        ),
      ).not.toThrow();
    }
    for (const name of invalidPaths) {
      const document = readJson(
        resolve(releaseGateContractDirectory, "fixtures/semantic-invalid", name),
      );
      expect(validate?.(document), JSON.stringify(validate?.errors)).toBe(true);
      expect(() =>
        validateGateReportSemantics(
          document as unknown as GateReportDocument,
        ),
      ).toThrow();
    }
    for (const name of [
      "automation-release.json",
      "blocked-waivable-metric-releasable.json",
      "critical-flag-downgrade.json",
      "waivable-metric-automation.json",
    ]) {
      const document = readJson(
        resolve(releaseGateContractDirectory, "fixtures/invalid", name),
      );
      expect(validate?.(document), name).toBe(false);
      expect(() =>
        validateGateReportSemantics(
          document as unknown as GateReportDocument,
        ),
      ).toThrow();
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
