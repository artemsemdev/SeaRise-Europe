import { createHash } from "node:crypto";

type QueryFixture = {
  knownGaps: { id: string }[];
  cases: { id: string; knownGapId: string | null }[];
};
type Measurement = { status: string } & Record<string, number | string | null>;
type EngineResult = {
  engineId: string;
  deterministicBuild: boolean;
  adapterEvidence: { status: string; sourceSha256: string };
  quality: { top1Accuracy: number; intendedTop5Rate: number; exactOrderRate: number; knownGapIds: string[] };
  measurements: Measurement;
};
type EvaluationReport = {
  queryFixtureSha256: string;
  corpus: { coreRecords: number; coastalRecords: number; overlapRecords: number; uniqueRecords: number };
  engines: EngineResult[];
  knownGaps: string[];
};

const sha256 = (bytes: Uint8Array) => createHash("sha256").update(bytes).digest("hex");
const isSorted = (values: readonly string[]) => values.every((value, index) => index === 0 || values[index - 1] < value);

export function validateQueryFixtureSemantics(fixture: QueryFixture): void {
  const caseIds = fixture.cases.map(({ id }) => id);
  const gapIds = fixture.knownGaps.map(({ id }) => id);
  if (new Set(caseIds).size !== caseIds.length || !isSorted(caseIds)) throw new Error("query case IDs must be unique and sorted");
  if (new Set(gapIds).size !== gapIds.length || !isSorted(gapIds)) throw new Error("query known-gap IDs must be unique and sorted");
  const known = new Set(gapIds);
  if (fixture.cases.some(({ knownGapId }) => knownGapId !== null && !known.has(knownGapId))) {
    throw new Error("query case references an unknown gap");
  }
}

export function validateEvaluationReportSemantics(
  report: EvaluationReport,
  queryFixtureBytes: Uint8Array,
  adapterEvidenceBytes: Uint8Array,
): void {
  if (report.queryFixtureSha256 !== sha256(queryFixtureBytes)) throw new Error("query fixture SHA-256 mismatch");
  const { coreRecords, coastalRecords, overlapRecords, uniqueRecords } = report.corpus;
  if (overlapRecords > Math.min(coreRecords, coastalRecords)
      || uniqueRecords !== coreRecords + coastalRecords - overlapRecords) throw new Error("corpus count arithmetic is inconsistent");
  if (report.engines.map(({ engineId }) => engineId).join(",") !== "minisearch,flexsearch") throw new Error("engine results must use stable exact order");
  if (new Set(report.knownGaps).size !== report.knownGaps.length || !isSorted(report.knownGaps)) throw new Error("report known gaps must be unique and sorted");
  const known = new Set(report.knownGaps);
  const evidenceSha256 = sha256(adapterEvidenceBytes);
  for (const engine of report.engines) {
    if (engine.quality.knownGapIds.some((id) => !known.has(id))) throw new Error("engine quality references an unknown gap");
    const values = Object.entries(engine.measurements).filter(([name]) => name !== "status").map(([, value]) => value);
    const expectedNull = engine.measurements.status === "not-measured";
    if (values.some((value) => expectedNull ? value !== null : typeof value !== "number")) throw new Error("measurement status and values disagree");
    const claimsSuccess = engine.deterministicBuild || engine.quality.top1Accuracy > 0
      || engine.quality.intendedTop5Rate > 0 || engine.quality.exactOrderRate > 0;
    if (claimsSuccess && (engine.adapterEvidence.status !== "passed" || engine.adapterEvidence.sourceSha256 !== evidenceSha256)) {
      throw new Error("successful engine claims require matching executable adapter evidence");
    }
  }
}
