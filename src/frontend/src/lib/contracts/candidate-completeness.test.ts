// @vitest-environment node

import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import Ajv2020 from "ajv/dist/2020.js";
import { describe, expect, it } from "vitest";
import {
  CandidateCompletenessError,
  validateCandidateCompleteness,
} from "./candidate-completeness";
import type {
  CandidateDocument,
  RequiredArtifactContract,
} from "./candidate-completeness";

interface PatchOperation {
  op: "add" | "copy" | "remove" | "replace";
  path: string;
  from?: string;
  value?: unknown;
}

interface NegativeVector {
  id: string;
  expectedCode: string;
  operations: PatchOperation[];
}

const contractRoot = resolve(
  process.cwd(),
  "../../contracts/candidate-completeness/v1",
);

function readJson<T>(path: string): T {
  return JSON.parse(readFileSync(path, "utf8")) as T;
}

const schema = readJson<Record<string, unknown>>(
  resolve(contractRoot, "candidate.schema.json"),
);
const contract = readJson<RequiredArtifactContract>(
  resolve(contractRoot, "required-artifacts.json"),
);
const valid = readJson<CandidateDocument>(
  resolve(contractRoot, "fixtures/valid/engineering-candidate.json"),
);
const vectors = readJson<{ vectors: NegativeVector[] }>(
  resolve(contractRoot, "fixtures/vectors/negative-vectors.json"),
).vectors;

function pointerValue(document: unknown, pointer: string): unknown {
  return pointer
    .replace(/^\//, "")
    .split("/")
    .reduce<unknown>((value, part) =>
      Array.isArray(value)
        ? value[Number(part)]
        : (value as Record<string, unknown>)[part], document);
}

function applyPatch(
  document: CandidateDocument,
  operations: PatchOperation[],
): CandidateDocument {
  const result = structuredClone(document) as unknown as Record<string, unknown>;
  for (const operation of operations) {
    const parts = operation.path.replace(/^\//, "").split("/");
    const key = parts.pop() as string;
    const parent = parts.length
      ? pointerValue(result, `/${parts.join("/")}`)
      : result;
    const value = operation.op === "copy"
      ? structuredClone(pointerValue(result, operation.from as string))
      : structuredClone(operation.value);
    if (Array.isArray(parent)) {
      if (operation.op === "remove") parent.splice(Number(key), 1);
      else if (key === "-") parent.push(value);
      else parent[Number(key)] = value;
    } else if (operation.op === "remove") {
      delete (parent as Record<string, unknown>)[key];
    } else {
      (parent as Record<string, unknown>)[key] = value;
    }
  }
  return result as unknown as CandidateDocument;
}

describe("Phase 1 candidate completeness parity", () => {
  it("accepts the shared valid engineering candidate", () => {
    const validateSchema = new Ajv2020({ strict: true }).compile(schema);
    expect(validateSchema(valid), JSON.stringify(validateSchema.errors)).toBe(true);

    expect(validateCandidateCompleteness(valid, contract)).toEqual({
      artifactCount: 44,
      datasetCount: 9,
      manifestWrittenLast: true,
    });
  });

  for (const vector of vectors) {
    it(`rejects shared vector: ${vector.id}`, () => {
      try {
        validateCandidateCompleteness(applyPatch(valid, vector.operations), contract);
        throw new Error("expected validation to fail");
      } catch (error) {
        expect(error).toBeInstanceOf(CandidateCompletenessError);
        expect((error as CandidateCompletenessError).code).toBe(vector.expectedCode);
      }
    });
  }

  it("keeps non-canonical geometry fail-closed", () => {
    const candidate = structuredClone(valid);
    candidate.geometryPolicy.canonical = true;
    candidate.geometryPolicy.publicationEligible = true;

    expect(() => validateCandidateCompleteness(candidate, contract)).toThrow(
      CandidateCompletenessError,
    );
  });

  it("rejects malformed nested rights before typed semantic validation", () => {
    const candidate = structuredClone(valid);
    (candidate.artifacts[0] as unknown as Record<string, unknown>).rights = null;
    const validateSchema = new Ajv2020({ strict: true }).compile(schema);

    expect(validateSchema(candidate)).toBe(false);
    expect(validateSchema.errors?.[0]?.instancePath).toBe("/artifacts/0/rights");
  });
});
