import { beforeAll, describe, expect, it, vi } from "vitest";
import type { AssessmentResult } from "../domain/scientific-lookup";
import {
  TechnicalFailure,
  type ReleaseContext,
  type Selection,
  type TechnicalErrorCode,
} from "../domain/release";
import { visibleAcceptedProjection } from "../domain/projection-state";
import { fixtureReleaseContext } from "../test/release-fixture";
import {
  AssessmentController,
  type AssessmentService,
} from "./assessment-controller";

let context: ReleaseContext;

beforeAll(async () => {
  context = await fixtureReleaseContext();
});

function selection(latitude = 51.9, scenario: Selection["scenario"] = "ssp2-45"): Selection {
  return {
    dataReleaseId: context.dataReleaseId,
    scenario,
    horizon: 2050,
    location: { kind: "coordinate", coordinates: { latitude, longitude: 4.5 } },
  };
}

function result(
  resultState: AssessmentResult["resultState"],
  selected = selection(),
): AssessmentResult {
  const dataset = context.dataset(selected.scenario, selected.horizon);
  const analysis = context.artifact(dataset.analysisArtifactId);
  const visual = context.artifact(dataset.visualArtifactId);
  const identity = {
    dataReleaseId: context.dataReleaseId,
    methodologyVersion: context.methodologyVersion,
    scenario: selected.scenario,
    horizon: selected.horizon,
    analysisArtifactId: analysis.artifactId,
    analysisArtifactSha256: analysis.sha256,
    visualArtifactId: visual.artifactId,
    visualArtifactSha256: visual.sha256,
    visualArtifactUrl: visual.url,
  };
  const source = { locationId: 1, latitude: 52, longitude: 4, distanceKilometres: 36 };
  switch (resultState) {
    case "ProjectionAvailable":
      return {
        ...identity, resultState, reason: "projection-available", source,
        lowerMillimetres: 156, medianMillimetres: 247, upperMillimetres: 351,
        lowerMetres: 0.156, medianMetres: 0.247, upperMetres: 0.351, units: "m",
        baseline: "1995-2014 mean", confidence: "medium", sourceRelease: "20210809",
        sourceMemberSha256: "c".repeat(64), nativeResolutionDegrees: 1,
      };
    case "DataUnavailable":
      return { ...identity, resultState, reason: "source-value-nodata", source };
    case "OutOfScope":
      return { ...identity, resultState, reason: "outside-coastal-scope" };
    case "UnsupportedGeography":
      return { ...identity, resultState, reason: "outside-europe-support" };
  }
}

function technical(code: TechnicalErrorCode): TechnicalFailure {
  return new TechnicalFailure({
    kind: "technical-error", code, message: `${code} from test`, recoverable: true,
  });
}

function immediate(
  evaluate: AssessmentService["evaluate"],
): AssessmentService {
  return { evaluate, cancel: vi.fn() };
}

interface PendingEvaluation {
  readonly selection: Selection;
  readonly signal: AbortSignal;
  resolve(value: AssessmentResult): void;
  reject(error: unknown): void;
}

function deferred(): AssessmentService & {
  readonly calls: PendingEvaluation[];
} {
  const calls: PendingEvaluation[] = [];
  return {
    calls,
    cancel: vi.fn(),
    evaluate: (_context, selected, signal) => new Promise((resolve, reject) => {
      calls.push({
        selection: selected,
        signal,
        resolve: (value) => resolve({ evaluationToken: calls.length, result: value }),
        reject,
      });
    }),
  };
}

describe("AssessmentController", () => {
  it("publishes immutable snapshots through a useSyncExternalStore-compatible contract", async () => {
    const service = immediate(async (_context, selected) => ({
      evaluationToken: 1, result: result("ProjectionAvailable", selected),
    }));
    const controller = new AssessmentController({ context, assessment: service });
    const snapshots: string[] = [];
    const unsubscribe = controller.subscribe(() => snapshots.push(controller.getSnapshot().phase));

    expect(controller.getSnapshot().phase).toBe("ready");
    expect(Object.isFrozen(controller.getSnapshot())).toBe(true);
    await controller.select(selection());
    expect(snapshots).toEqual(["evaluating", "result"]);
    expect(Object.isFrozen(visibleAcceptedProjection(controller.getSnapshot()))).toBe(true);

    unsubscribe();
    controller.reset();
    expect(snapshots).toHaveLength(2);
  });

  it("cancels a superseded engine call and rejects its out-of-order completion", async () => {
    const service = deferred();
    const controller = new AssessmentController({ context, assessment: service });
    const firstSelection = selection(51);
    const secondSelection = selection(53, "ssp5-85");

    const first = controller.select(firstSelection);
    const firstSignal = service.calls[0].signal;
    const second = controller.select(secondSelection);
    expect(firstSignal.aborted).toBe(true);
    expect(service.cancel).toHaveBeenCalledOnce();
    expect(controller.getSnapshot()).toMatchObject({ phase: "evaluating", operationToken: 2 });

    service.calls[0].resolve(result("OutOfScope", firstSelection));
    await first;
    expect(controller.getSnapshot().phase).toBe("evaluating");
    service.calls[1].resolve(result("ProjectionAvailable", secondSelection));
    await second;
    expect(visibleAcceptedProjection(controller.getSnapshot())?.selection).toEqual(secondSelection);
  });

  it("keeps the accepted tuple visible while a later selection is updating", async () => {
    const service = deferred();
    const controller = new AssessmentController({ context, assessment: service });
    const acceptedSelection = selection(51);
    const first = controller.select(acceptedSelection);
    service.calls[0].resolve(result("ProjectionAvailable", acceptedSelection));
    await first;
    const accepted = visibleAcceptedProjection(controller.getSnapshot());

    const nextSelection = selection(54, "ssp5-85");
    const update = controller.select(nextSelection);
    expect(controller.getSnapshot().phase).toBe("updating");
    expect(visibleAcceptedProjection(controller.getSnapshot())).toBe(accepted);
    service.calls[1].resolve(result("OutOfScope", nextSelection));
    await update;
    expect(visibleAcceptedProjection(controller.getSnapshot())?.selection).toEqual(nextSelection);
  });

  it.each([
    "ProjectionAvailable", "DataUnavailable", "OutOfScope", "UnsupportedGeography",
  ] as const)("publishes the ADR-024 %s outcome", async (outcome) => {
    const service = immediate(async (_context, selected) => ({
      evaluationToken: 1, result: result(outcome, selected),
    }));
    const controller = new AssessmentController({ context, assessment: service });
    await controller.select(selection());
    expect(visibleAcceptedProjection(controller.getSnapshot())?.result.resultState).toBe(outcome);
  });

  it.each([
    ["FetchFailed", "technical-error"],
    ["DecodeFailed", "technical-error"],
    ["IntegrityFailed", "integrity-error"],
    ["UnsupportedBrowser", "unsupported-browser"],
  ] as const)("keeps %s as the separate %s state", async (code, phase) => {
    const controller = new AssessmentController({
      context,
      assessment: immediate(async () => { throw technical(code); }),
    });
    await controller.select(selection());
    expect(controller.getSnapshot()).toMatchObject({ phase, error: { code } });
    expect(JSON.stringify(controller.getSnapshot())).not.toContain('"resultState":"DataUnavailable"');
  });

  it.each(["offline", "connection-required"] as const)(
    "classifies FetchFailed as %s without creating a scientific outcome",
    async (availability) => {
      const controller = new AssessmentController({
        context,
        assessment: immediate(async () => { throw technical("FetchFailed"); }),
        classifyAvailability: () => availability,
      });
      await controller.select(selection());
      expect(controller.getSnapshot().phase).toBe(availability);
      expect(visibleAcceptedProjection(controller.getSnapshot())).toBeNull();
    },
  );

  it("retries the exact failed selection and no other operation", async () => {
    const evaluated: Selection[] = [];
    let attempt = 0;
    const service = immediate(async (_context, selected) => {
      evaluated.push(selected);
      attempt += 1;
      if (attempt === 1) throw technical("DecodeFailed");
      return { evaluationToken: attempt, result: result("ProjectionAvailable", selected) };
    });
    const controller = new AssessmentController({ context, assessment: service });
    const failedSelection = selection(54, "ssp1-26");

    await controller.select(failedSelection);
    expect(controller.getSnapshot().phase).toBe("technical-error");
    expect(await controller.retry()).toBe(true);
    expect(evaluated).toHaveLength(2);
    expect(evaluated[1]).toEqual(evaluated[0]);
    expect(visibleAcceptedProjection(controller.getSnapshot())?.selection).toEqual(failedSelection);
    expect(await controller.retry()).toBe(false);
  });

  it("invalidates pending work on reset and release replacement", async () => {
    const service = deferred();
    const controller = new AssessmentController({ context, assessment: service });

    const resetSelection = selection(50);
    const resetWork = controller.select(resetSelection);
    controller.reset();
    expect(service.calls[0].signal.aborted).toBe(true);
    service.calls[0].resolve(result("ProjectionAvailable", resetSelection));
    await resetWork;
    expect(controller.getSnapshot().phase).toBe("ready");

    const replacedSelection = selection(52);
    const replacedWork = controller.select(replacedSelection);
    controller.replaceRelease(context);
    expect(service.calls[1].signal.aborted).toBe(true);
    service.calls[1].resolve(result("ProjectionAvailable", replacedSelection));
    await replacedWork;
    expect(controller.getSnapshot()).toMatchObject({ phase: "ready", operationToken: 4 });
  });

  it("maps unknown failures and reducer-detected release mismatches without publishing a result", async () => {
    const unknown = new AssessmentController({
      context,
      assessment: immediate(async () => { throw new Error("unexpected decoder exception"); }),
    });
    await unknown.select(selection());
    expect(unknown.getSnapshot()).toMatchObject({ phase: "technical-error", error: { code: "DecodeFailed" } });

    const mismatch = new AssessmentController({
      context,
      assessment: immediate(async (_context, selected) => ({
        evaluationToken: 1,
        result: { ...result("ProjectionAvailable", selected), dataReleaseId: "different-release" },
      })),
    });
    await mismatch.select(selection());
    expect(mismatch.getSnapshot()).toMatchObject({ phase: "integrity-error", error: { code: "ReleaseIdentityMismatch" } });
    expect(visibleAcceptedProjection(mismatch.getSnapshot())).toBeNull();
  });

  it("aborts on dispose, ignores late completion, and rejects later commands", async () => {
    const service = deferred();
    const controller = new AssessmentController({ context, assessment: service });
    const notifications = vi.fn();
    controller.subscribe(notifications);
    const selected = selection();
    const pending = controller.select(selected);
    controller.dispose();
    expect(service.calls[0].signal.aborted).toBe(true);
    service.calls[0].resolve(result("ProjectionAvailable", selected));
    await pending;
    expect(controller.getSnapshot().phase).toBe("evaluating");
    expect(notifications).toHaveBeenCalledOnce();
    await expect(controller.select(selected)).rejects.toThrow("disposed");
  });
});
