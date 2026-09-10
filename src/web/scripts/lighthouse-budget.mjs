const categories = ["performance", "accessibility", "best-practices", "seo"];
const target = 0.9;
const expiry = "2026-09-24T00:00:00Z";
const policyKeys = ["schemaVersion", "scope", "edition", "releaseDisposition", "owner", "issues", "sourceRun", "measuredPerformance", "target", "minimumPerformance", "expiresAt", "rationale"].sort();

function requireCondition(condition, message) {
  if (!condition) throw new Error(`Lighthouse budget: ${message}`);
}

export function evaluateLighthouseBudget({ runs, policy, edition, releaseDisposition, now = Date.now() }) {
  requireCondition(policy && Object.keys(policy).sort().join() === policyKeys.join(), "missing or malformed waiver policy");
  requireCondition(policy.schemaVersion === 1 && policy.scope === "coastal-atlas-local-adoption"
    && policy.edition === "synthetic-fixture" && policy.releaseDisposition === "synthetic-fixture"
    && policy.owner === "artemsemdev" && JSON.stringify(policy.issues) === "[65,490]"
    && policy.sourceRun === "https://github.com/artemsemdev/SeaRise-Europe/actions/runs/34493541004"
    && JSON.stringify(policy.measuredPerformance) === "[0.54,0.53,0.55]"
    && policy.target === target && policy.minimumPerformance === 0.5 && policy.expiresAt === expiry
    && typeof policy.rationale === "string" && policy.rationale.trim().length >= 40,
  "waiver policy exceeds its reviewed scope");
  requireCondition(Number.isFinite(now) && now < Date.parse(expiry), "waiver policy expired or clock is invalid");
  requireCondition(edition === "synthetic-fixture" && releaseDisposition === "synthetic-fixture", "waiver requires the labeled synthetic Atlas fixture, never a private or public release");
  requireCondition(Array.isArray(runs) && runs.length === 3, "three raw cold audits are required");
  for (const [index, run] of runs.entries()) {
    requireCondition(run?.run === index + 1 && run.scores
      && Object.keys(run.scores).sort().join() === [...categories].sort().join(), "invalid raw audit identity or categories");
    requireCondition(Array.isArray(run.renderErrors) && run.renderErrors.length === 0, "render errors cannot be waived");
    requireCondition(categories.every((id) => Number.isFinite(run.scores[id]) && run.scores[id] >= 0 && run.scores[id] <= 1), "invalid raw score");
  }
  const medianScores = Object.fromEntries(categories.map((id) =>
    [id, runs.map(({ scores }) => scores[id]).sort((a, b) => a - b)[1]]));
  const failedBudgets = [
    ...categories.filter((id) => medianScores[id] < target).map((id) => `median ${id}`),
    ...runs.flatMap(({ run, scores }) => categories.filter((id) => scores[id] < target).map((id) => `run ${run} ${id}`)),
  ];
  const performance90Passed = runs.every(({ scores }) => scores.performance >= target);
  const waiverApplied = !performance90Passed && runs.every(({ scores }) =>
    scores.performance >= policy.minimumPerformance && categories.slice(1).every((id) => scores[id] >= target));
  return {
    target, medianScores, failedBudgets, performance90Passed, waiverApplied,
    accepted: failedBudgets.length === 0 || waiverApplied,
    waiver: waiverApplied ? policy : null,
    warning: waiverApplied ? `Lighthouse performance 90 failed; temporary local-adoption waiver applied. Raw performance: ${runs.map(({ scores }) => (scores.performance * 100).toFixed(2)).join("/")}; median ${(medianScores.performance * 100).toFixed(2)}; floor 50 each run; owner ${policy.owner}; expires ${expiry}; issues #65/#490. Not public MVP or release qualification.` : null,
  };
}
