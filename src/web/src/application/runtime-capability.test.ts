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
  state: "online-complete" | "connection-required",
): RuntimeCapabilityV2 {
  return Object.freeze({
    contractVersion: 2,
    subject,
    data: state === "online-complete"
      ? Object.freeze({ state, pair })
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
    controller.selectSubject({ kind: "assessment", scenario: "ssp2-45", horizon: 2050 });
    await settle();
    expect(inspect.mock.calls.at(-1)?.[1].authoritativeNetworkUsable).toBe(false);

    await controller.confirmCurrentInteractionAvailable();
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
    controller.selectSubject(next);
    resolves[1](capability(next, "connection-required"));
    await settle();
    resolves[0](capability({ kind: "core" }, "online-complete"));
    await settle();

    expect(controller.getSnapshot()?.subject).toEqual(next);
    expect(controller.getSnapshot()?.data.state).toBe("connection-required");
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
