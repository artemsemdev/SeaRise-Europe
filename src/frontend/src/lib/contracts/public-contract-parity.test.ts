// @vitest-environment node

import { createHash } from "node:crypto";
import { existsSync, readFileSync, readdirSync } from "node:fs";
import { resolve } from "node:path";
import Ajv2020 from "ajv/dist/2020.js";
import addFormats from "ajv-formats";
import { describe, expect, it } from "vitest";
import { validateGateReportSemantics } from "./gate-report-semantics";
import type { GateReportDocument } from "./gate-report-semantics";
import { validateSettlementSearchShardSemantics } from "./settlement-semantics";
import type { SettlementSearchShardDocument } from "./settlement-semantics";

interface ContractDocument {
  $id?: string;
  $schema?: string;
  [key: string]: unknown;
}

const repositoryContracts = resolve(process.cwd(), "../../contracts");
const releaseV1ContractDirectory = resolve(repositoryContracts, "release/v1");
const releaseV2ContractDirectory = resolve(repositoryContracts, "release/v2");
const releaseGateContractDirectory = resolve(repositoryContracts, "release-gates/v1");
const settlementV2ContractDirectory = resolve(repositoryContracts, "settlements/v2");
const settlementV3ContractDirectory = resolve(repositoryContracts, "settlements/v3");
const settlementV4ContractDirectory = resolve(repositoryContracts, "settlements/v4");
const candidateV1ContractDirectory = resolve(
  repositoryContracts,
  "candidate-completeness/v1",
);
const candidateV2ContractDirectory = resolve(
  repositoryContracts,
  "candidate-completeness/v2",
);
const contractDirectories = [
  releaseV1ContractDirectory,
  releaseV2ContractDirectory,
  releaseGateContractDirectory,
  settlementV2ContractDirectory,
  settlementV3ContractDirectory,
  settlementV4ContractDirectory,
  candidateV1ContractDirectory,
  candidateV2ContractDirectory,
];
const settlementContractDirectories = [
  settlementV2ContractDirectory,
  settlementV3ContractDirectory,
];

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
      .map(
        (key) => `${JSON.stringify(key)}:${lexicographicKeyJson(record[key])}`,
      )
      .join(",")}}`;
  }
  const encoded = JSON.stringify(value);
  if (encoded === undefined)
    throw new TypeError("value is not JSON serializable");
  return encoded;
}

function fixturePaths(kind: "valid" | "invalid"): string[] {
  return contractDirectories.flatMap((contractDirectory) => {
    const directory = resolve(contractDirectory, "fixtures", kind);
    if (!existsSync(directory)) return [];
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
    expect(paths.some((path) => path.includes("candidate-completeness"))).toBe(true);
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
        validateGateReportSemantics(document as unknown as GateReportDocument),
      ).not.toThrow();
    }
    for (const name of invalidPaths) {
      const document = readJson(
        resolve(
          releaseGateContractDirectory,
          "fixtures/semantic-invalid",
          name,
        ),
      );
      expect(validate?.(document), JSON.stringify(validate?.errors)).toBe(true);
      expect(() =>
        validateGateReportSemantics(document as unknown as GateReportDocument),
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
        validateGateReportSemantics(document as unknown as GateReportDocument),
      ).toThrow();
    }
  });

  it("shares Arrow-field JSON identity with Python", () => {
    for (const settlementContractDirectory of settlementContractDirectories) {
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
      expect(() =>
        validateSettlementSearchShardSemantics(
          search as unknown as SettlementSearchShardDocument,
        ),
      ).not.toThrow();
    }
  });

  it("shares settlement v3 semantic valid and invalid vectors with Python", () => {
    const ajv = contractValidator();
    const valid = readJson(
      resolve(
        settlementV3ContractDirectory,
        "fixtures/valid/settlement-search-shard.json",
      ),
    );
    const mismatch = readJson(
      resolve(
        settlementV3ContractDirectory,
        "fixtures/semantic-invalid/record-count-mismatch.json",
      ),
    );
    const validate = ajv.getSchema(valid.$schema as string);

    expect(validate?.(valid), JSON.stringify(validate?.errors)).toBe(true);
    expect(validate?.(mismatch), JSON.stringify(validate?.errors)).toBe(true);
    expect(() =>
      validateSettlementSearchShardSemantics(
        valid as unknown as SettlementSearchShardDocument,
      ),
    ).not.toThrow();
    expect(() =>
      validateSettlementSearchShardSemantics(
        mismatch as unknown as SettlementSearchShardDocument,
      ),
    ).toThrow(/recordCount/);
  });

  it("validates the public v4 shard and receipt and rejects count drift", () => {
    const ajv = contractValidator();
    const shard = readJson(resolve(
      settlementV4ContractDirectory,
      "fixtures/valid/settlement-browser-search-shard.json",
    ));
    const receipt = readJson(resolve(
      settlementV4ContractDirectory,
      "fixtures/valid/settlement-browser-search-shard-set-receipt.json",
    ));
    const validate = ajv.getSchema(shard.$schema as string);

    expect(validate?.(shard), JSON.stringify(validate?.errors)).toBe(true);
    expect(validate?.(receipt), JSON.stringify(validate?.errors)).toBe(true);
    expect(() => validateSettlementSearchShardSemantics(
      shard as unknown as SettlementSearchShardDocument,
    )).not.toThrow();
    const mismatch = { ...shard, recordCount: 2 };
    expect(validate?.(mismatch), JSON.stringify(validate?.errors)).toBe(true);
    expect(() => validateSettlementSearchShardSemantics(
      mismatch as unknown as SettlementSearchShardDocument,
    )).toThrow(/recordCount/);
  });
});
