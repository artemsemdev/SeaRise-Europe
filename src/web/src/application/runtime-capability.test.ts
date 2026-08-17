import { describe, expect, it, vi } from "vitest";
import type {
  InteractionSubjectV1,
  RuntimeCapabilityV2,
} from "../offline/contracts/policy";
import { validateAppReleasePair } from "../offline/contracts/keys";
import { RuntimeCapabilityController } from "./runtime-capability";

const pair = validateAppReleasePair({
  contractVersion: 1,
  appBuildId: "flight-capability-test",
  dataReleaseId: "fixture-release",
});

function capability(
  subject: InteractionSubjectV1,
  state: "online-complete" | "available-offline" | "connection-required",
): RuntimeCapabilityV2 {
  return Object.freeze({
    contractVersion: 2,
    subject,
    data: state === "online-complete"
      ? Object.freeze({ state, pair })
      : state === "available-offline"
        ? Object.freeze({ state, pair, resourceCount: 2, byteCount: 512 })
      : Object.freeze({
          state,
          pair,
          missing: Object.freeze([{ kind: "range" as const, identity: "projection-range-1" }]),
          retryable: true as const,
        }),
    update: Object.freeze({ state: "current" as const }),
  });
}

async function settle(): Promise<void> {
  await new Promise<void>((resolve) => setTimeout(resolve, 0));
}

describe("runtime capability controller", () => {
  it("requires interaction-scoped authoritative evidence and never reads navigator.onLine", async () => {
    const inspect = vi.fn(async (subject: InteractionSubjectV1, options: {
      readonly authoritativeNetworkUsable?: boolean;
    }) => capability(subject, options.authoritativeNetworkUsable ? "online-complete" : "connection-required"));
    const controller = new RuntimeCapabilityController({ inspect });
    await settle();

    expect(controller.getSnapshot()?.data.state).toBe("connection-required");
    expect(inspect.mock.calls[0][1].authoritativeNetworkUsable).toBe(false);
    const interaction = controller.beginInteraction({
      kind: "assessment", scenario: "ssp2-45", horizon: 2050,
    });
    await settle();
    expect(controller.getSnapshot()).toBeNull();
    expect(inspect).toHaveBeenCalledOnce();

    await controller.confirmInteractionAvailable(interaction);
    expect(controller.getSnapshot()?.data.state).toBe("online-complete");
    expect(inspect.mock.calls.at(-1)?.[1].authoritativeNetworkUsable).toBe(true);
    expect(inspect.toString()).not.toContain("navigator.onLine");
    controller.dispose();
  });

  it("drops stale inspection completion after the current interaction changes", async () => {
    const resolves: Array<(value: RuntimeCapabilityV2) => void> = [];
    const inspect = vi.fn(() => new Promise<RuntimeCapabilityV2>((resolve) => {
      resolves.push((value) => resolve(value));
    }));
    const controller = new RuntimeCapabilityController({ inspect });
    const next = { kind: "assessment", scenario: "ssp5-85", horizon: 2100 } as const;
    const interaction = controller.beginInteraction(next);
    const confirmed = controller.confirmInteractionAvailable(interaction);
    resolves[1](capability(next, "connection-required"));
    await confirmed;
    await settle();
    resolves[0](capability({ kind: "core" }, "online-complete"));
    await settle();

    expect(controller.getSnapshot()?.subject).toEqual(next);
    expect(controller.getSnapshot()?.data.state).toBe("connection-required");
    controller.dispose();
  });

  it("clears point A capability before point B with the same scenario and horizon can fail", async () => {
    const inspect = vi.fn(async (subject: InteractionSubjectV1) => capability(
      subject,
      subject.kind === "assessment" ? "available-offline" : "connection-required",
    ));
    const controller = new RuntimeCapabilityController({ inspect });
    await settle();
    const pointA = controller.beginInteraction({ kind: "assessment", scenario: "ssp2-45", horizon: 2050 });
    await controller.confirmInteractionAvailable(pointA);
    expect(controller.getSnapshot()?.data.state).toBe("available-offline");

    const pointB = controller.beginInteraction({ kind: "assessment", scenario: "ssp2-45", horizon: 2050 });
    expect(pointB.generation).toBeGreaterThan(pointA.generation);
    expect(controller.getSnapshot()).toBeNull();
    await settle();
    expect(controller.getSnapshot()).toBeNull();

    // A late completion from point A cannot restore its offline pill after B
    // has started and failed without a successful capability confirmation.
    await controller.confirmInteractionAvailable(pointA);
    expect(controller.getSnapshot()).toBeNull();
    controller.dispose();
  });

  it("rejects an in-flight point A inspection after point B starts with the same wire subject", async () => {
    let resolveAssessment!: (value: RuntimeCapabilityV2) => void;
    const inspect = vi.fn((subject: InteractionSubjectV1) => subject.kind === "assessment"
      ? new Promise<RuntimeCapabilityV2>((resolve) => { resolveAssessment = resolve; })
      : Promise.resolve(capability(subject, "connection-required")));
    const controller = new RuntimeCapabilityController({ inspect });
    await settle();
    const subject = { kind: "assessment", scenario: "ssp2-45", horizon: 2050 } as const;
    const pointA = controller.beginInteraction(subject);
    const pointAConfirmation = controller.confirmInteractionAvailable(pointA);
    controller.beginInteraction(subject);
    resolveAssessment(capability(subject, "available-offline"));
    await pointAConfirmation;
    expect(controller.getSnapshot()).toBeNull();
    controller.dispose();
  });

  it("routes update actions through the explicit action port", async () => {
    const requestAction = vi.fn(async () => undefined);
    const controller = new RuntimeCapabilityController({
      inspect: async (subject) => capability(subject, "online-complete"),
      updateAction: { requestAction },
    });
    await settle();
    await controller.requestUpdateAction();
    expect(requestAction).toHaveBeenCalledWith(controller.getSnapshot());
    controller.dispose();
  });
});
