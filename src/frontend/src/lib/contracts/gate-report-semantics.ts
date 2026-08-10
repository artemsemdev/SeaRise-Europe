export type GateStatus = "pass" | "fail" | "not-measured";

export interface GateReportDocument {
  authority: {
    kind: "automation" | "owner";
    automatedValidation: GateStatus;
    ownerDisposition: "not-recorded" | "approved" | "rejected" | "blocked";
  };
  releasable: boolean;
  checks: Array<{
    checkId: string;
    status: GateStatus;
    nonWaivable: boolean;
    target: { operator: "at-most" | "at-least" | "exactly"; value: number };
    measuredValue: number | null;
    evidence: Array<{ path: string }>;
    stopReasonCode?: string;
  }>;
  stopReasonCodes: string[];
}

const criticalStopReasons = new Set([
  "artifact-integrity-failed",
  "cross-runtime-parity-failed",
  "owner-approval-missing",
  "reproducibility-failed",
  "required-measurement-missing",
  "rights-incomplete",
  "schema-invalid",
  "scientific-parity-failed",
  "supply-chain-invalid",
]);

function isSortedUnique(values: string[]): boolean {
  return (
    values.every((value, index) => index === 0 || values[index - 1] < value) &&
    new Set(values).size === values.length
  );
}

function targetMet(check: GateReportDocument["checks"][number]): boolean {
  const measured = check.measuredValue as number;
  if (check.target.operator === "at-most") return measured <= check.target.value;
  if (check.target.operator === "at-least") return measured >= check.target.value;
  return measured === check.target.value;
}

function aggregateStatus(checks: GateReportDocument["checks"]): GateStatus {
  const statuses = new Set(checks.map((check) => check.status));
  if (statuses.has("fail")) return "fail";
  if (statuses.has("not-measured")) return "not-measured";
  return "pass";
}

export function validateGateReportSemantics(report: GateReportDocument): void {
  const checkIds = report.checks.map((check) => check.checkId);
  if (!isSortedUnique(checkIds)) {
    throw new TypeError("checks must use unique checkId order");
  }

  const blockerReasons: string[] = [];
  for (const check of report.checks) {
    const evidencePaths = check.evidence.map((item) => item.path);
    if (!isSortedUnique(evidencePaths)) {
      throw new TypeError(`${check.checkId} evidence must use unique path order`);
    }

    if (
      check.status !== "not-measured" &&
      (check.status === "pass") !== targetMet(check)
    ) {
      throw new TypeError(`${check.checkId} status contradicts its measurement`);
    }

    if (check.status !== "pass") {
      const reason = check.stopReasonCode as string;
      blockerReasons.push(reason);
      if (criticalStopReasons.has(reason) && !check.nonWaivable) {
        throw new TypeError(
          `${check.checkId} critical stop reason must be non-waivable`,
        );
      }
    }
    if (
      !check.nonWaivable &&
      (check.status !== "fail" ||
        check.stopReasonCode !== "metric-target-missed" ||
        report.authority.kind !== "owner")
    ) {
      throw new TypeError(
        `${check.checkId} waivable metric must be owner-controlled`,
      );
    }
  }

  const expectedReasons = Array.from(new Set(blockerReasons)).sort();
  if (
    JSON.stringify(report.stopReasonCodes) !== JSON.stringify(expectedReasons)
  ) {
    throw new TypeError(
      "stopReasonCodes must be the sorted unique reasons from blocked checks",
    );
  }
  if (report.authority.automatedValidation !== aggregateStatus(report.checks)) {
    throw new TypeError("automatedValidation contradicts check statuses");
  }
  if (report.releasable) {
    if (report.checks.some((check) => check.status !== "pass")) {
      throw new TypeError("a blocked check cannot be releasable in v1");
    }
    if (
      report.authority.kind !== "owner" ||
      report.authority.ownerDisposition !== "approved"
    ) {
      throw new TypeError("release requires explicit owner approval");
    }
  }
}
