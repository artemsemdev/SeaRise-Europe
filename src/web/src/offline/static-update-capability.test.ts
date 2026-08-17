import { describe, expect, it } from "vitest";
import { validateAppReleasePair } from "./contracts/keys";
import { StaticUpdateCapabilityCoordinator } from "./static-update-capability";
import {
  StaticHostUpdateCoordinator,
  type AcceptedPairIdentityV1,
  type StaticUpdateCoordinatorPorts,
} from "./update-coordinator";

const hash = (digit: string): string => digit.repeat(64);
const currentPair = validateAppReleasePair({
  contractVersion: 1, appBuildId: "current-build", dataReleaseId: "current-release",
});
const candidatePair = validateAppReleasePair({
  contractVersion: 1, appBuildId: "candidate-build", dataReleaseId: "candidate-release",
});
const identity = (pair: typeof currentPair, digit: string): AcceptedPairIdentityV1 => Object.freeze({
  contractVersion: 1,
  pair,
  precacheSetSha256: hash(digit),
  resourcePlanSha256: hash(digit),
  receiptSha256: hash(digit),
});

describe("static update capability adapter", () => {
  it("drives the real coordinator from available candidate to close-and-reopen", async () => {
    const current = identity(currentPair, "1");
    const candidate = identity(candidatePair, "2");
    const ports: StaticUpdateCoordinatorPorts = {
      readControllerBoot: async () => Object.freeze({ contractVersion: 1, bootId: "boot-current", controller: current }),
      inspectWaitingCandidate: async () => Object.freeze({ status: "sealed", candidate }),
      issueConfirmationToken: () => "confirmed-candidate",
      recordPendingTransitionIntent: async () => undefined,
      armTransitionIntent: async () => "armed",
      discardPendingTransitionIntent: async () => undefined,
      tombstoneTransitionIntent: async () => "tombstoned",
      consumeTransitionIntent: async () => "consumed",
    };
    const coordinator = new StaticHostUpdateCoordinator(ports, {
      instanceId: "flightadapter0001",
    });
    await coordinator.initialize();
    const adapter = new StaticUpdateCapabilityCoordinator(coordinator, {
      candidate: async () => candidatePair,
    });

    expect(await adapter.inspect()).toEqual({ state: "update-available", candidate: candidatePair });
    await adapter.requestAction(Object.freeze({
      contractVersion: 2,
      subject: Object.freeze({ kind: "core" }),
      data: Object.freeze({ state: "online-complete", pair: currentPair }),
      update: Object.freeze({ state: "update-available", candidate: candidatePair }),
    }));
    expect(await adapter.inspect()).toEqual({ state: "ready-to-activate", candidate: candidatePair });
  });
});
