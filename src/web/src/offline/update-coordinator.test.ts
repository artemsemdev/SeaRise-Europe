// @vitest-environment node

import { describe, expect, it, vi } from "vitest";
import { validateAppReleasePair, type AppReleasePairV1 } from "./contracts/keys";
import {
  ROLLBACK_MESSAGE,
  StaticHostUpdateCoordinator,
  UPDATE_READY_MESSAGE,
  type AcceptedPairIdentityV1,
  type CloseAndReopenIntentV1,
  type ControllerBootProofV1,
  type StaticUpdateCoordinatorPorts,
} from "./update-coordinator";

function pair(build: string, release: string): AppReleasePairV1 {
  return validateAppReleasePair({ contractVersion: 1, appBuildId: build, dataReleaseId: release });
}

function accepted(value: AppReleasePairV1, suffix = ""): AcceptedPairIdentityV1 {
  const digest = (seed: string) => `${seed}${suffix}`.padEnd(64, seed).slice(0, 64);
  return Object.freeze({
    contractVersion: 1,
    pair: value,
    precacheSetSha256: digest("a"),
    resourcePlanSha256: digest("b"),
    receiptSha256: digest("c"),
  });
}

const active = accepted(pair("build-1", "release-1"));
const candidate = accepted(pair("build-2", "release-2"));
const anotherCandidate = accepted(pair("build-3", "release-3"), "d");

function boot(bootId = "boot-1", controller = active): ControllerBootProofV1 {
  return Object.freeze({ contractVersion: 1, bootId, controller });
}

function harness(options: Readonly<{
  boot?: ControllerBootProofV1;
  instanceId?: string;
  inspect?: StaticUpdateCoordinatorPorts["inspectWaitingCandidate"];
  token?: StaticUpdateCoordinatorPorts["issueConfirmationToken"];
  record?: StaticUpdateCoordinatorPorts["recordTransitionIntent"];
  revoke?: StaticUpdateCoordinatorPorts["revokeTransitionIntent"];
  consume?: StaticUpdateCoordinatorPorts["consumeTransitionIntent"];
}> = {}) {
  let currentBoot = options.boot ?? boot();
  const recorded: CloseAndReopenIntentV1[] = [];
  let tokenSequence = 0;
  const ports: StaticUpdateCoordinatorPorts = {
    readControllerBoot: vi.fn(async () => currentBoot),
    inspectWaitingCandidate: options.inspect ?? vi.fn(async () => ({ status: "sealed" as const, candidate })),
    issueConfirmationToken: options.token ?? vi.fn(() => `provider-${++tokenSequence}`),
    issueCoordinatorInstanceId: vi.fn(() => options.instanceId ?? "instance-00000001"),
    recordTransitionIntent: options.record ?? vi.fn(async (intent) => { recorded.splice(0, recorded.length, intent); }),
    revokeTransitionIntent: options.revoke ?? vi.fn(async (intent) => {
      if (recorded[0]?.transitionId === intent.transitionId) recorded.splice(0, 1);
    }),
    consumeTransitionIntent: options.consume ?? vi.fn(async () => "consumed" as const),
  };
  return {
    coordinator: new StaticHostUpdateCoordinator(ports),
    ports,
    recorded,
    setBoot: (value: ControllerBootProofV1) => { currentBoot = value; },
  };
}

async function confirmedIntent(test = harness()) {
  const prepared = await test.coordinator.prepareUpdate(candidate.pair);
  if (prepared.phase !== "waiting-candidate-verified") throw new Error("expected verified waiting candidate");
  const confirmed = await test.coordinator.confirmUpdate(prepared.confirmationToken);
  if (confirmed.phase !== "close-and-reopen-required") throw new Error("expected close-and-reopen intent");
  return { test, prepared, confirmed, intent: confirmed.intent };
}

describe("conservative static-host update coordinator", () => {
  it("verifies a waiting candidate without changing the controlling authority", async () => {
    const test = harness();

    const state = await test.coordinator.prepareUpdate(candidate.pair);

    expect(state).toMatchObject({
      phase: "waiting-candidate-verified",
      boot: boot(),
      candidate,
      confirmationToken: "g1.provider-1",
      currentUsable: true,
    });
    expect(test.ports.recordTransitionIntent).not.toHaveBeenCalled();
    expect("reloadAllowed" in state).toBe(false);
  });

  it("records only a close-and-reopen intent after explicit confirmation", async () => {
    const { test, confirmed } = await confirmedIntent();

    expect(confirmed).toMatchObject({
      phase: "close-and-reopen-required",
      boot: boot(),
      message: UPDATE_READY_MESSAGE,
      currentUsable: true,
      intent: { sourceController: active, candidate },
    });
    expect(confirmed.boot.controller).toEqual(active);
    expect(test.recorded).toHaveLength(1);
    expect("reloadAllowed" in confirmed).toBe(false);
  });

  it("cannot claim activation on the same page even after confirmation", async () => {
    const { test, intent } = await confirmedIntent();

    const state = await test.coordinator.verifyNextBoot(intent);

    expect(state).toMatchObject({
      phase: "failed", operation: "verify-next-boot", code: "controller-mismatch",
      boot: boot(), currentUsable: true,
    });
    expect(test.ports.consumeTransitionIntent).not.toHaveBeenCalled();
  });

  it("rejects same-page finalization when the controller port changes its boot proof", async () => {
    const { test, intent } = await confirmedIntent();
    test.setBoot(boot("boot-2", candidate));

    const state = await test.coordinator.verifyNextBoot(intent);

    expect(state).toMatchObject({
      phase: "failed", operation: "verify-next-boot", code: "controller-mismatch",
      boot: boot("boot-2", candidate), currentUsable: true,
    });
    expect(test.ports.consumeTransitionIntent).not.toHaveBeenCalled();
  });

  it("finalizes only when a fresh boot proves the exact candidate controller", async () => {
    const { intent } = await confirmedIntent();
    const reopened = harness({ boot: boot("boot-2", candidate) });

    const state = await reopened.coordinator.verifyNextBoot(intent);

    expect(state).toMatchObject({
      phase: "controller-verified-activation",
      boot: boot("boot-2", candidate),
      intent,
      currentUsable: true,
    });
    expect(reopened.ports.consumeTransitionIntent).toHaveBeenCalledWith(intent, boot("boot-2", candidate));
    expect("reloadAllowed" in state).toBe(false);
  });

  it.each([
    ["same boot", boot("boot-1", candidate)],
    ["old controller", boot("boot-2", active)],
    ["different controller", boot("boot-2", anotherCandidate)],
  ])("fails closed for %s instead of claiming activation", async (_name, nextBoot) => {
    const { intent } = await confirmedIntent();
    const reopened = harness({ boot: nextBoot });

    const state = await reopened.coordinator.verifyNextBoot(intent);

    expect(state).toMatchObject({ phase: "failed", code: "controller-mismatch", boot: nextBoot, currentUsable: true });
    expect(reopened.ports.consumeTransitionIntent).not.toHaveBeenCalled();
  });

  it("fails closed when a matching next-boot intent is stale or already consumed", async () => {
    const { intent } = await confirmedIntent();
    const reopened = harness({
      boot: boot("boot-2", candidate),
      consume: vi.fn(async () => "already-consumed" as const),
    });

    const state = await reopened.coordinator.verifyNextBoot(intent);

    expect(state).toMatchObject({ phase: "failed", code: "intent-stale", currentUsable: true });
  });

  it.each(["incomplete", "corrupt", "mixed", "stale"] as const)(
    "keeps the current controller usable when the waiting candidate is %s",
    async (status) => {
      const test = harness({ inspect: vi.fn(async () => ({ status, reason: `candidate-${status}` })) });

      const state = await test.coordinator.prepareUpdate(candidate.pair);

      expect(state).toMatchObject({
        phase: "failed", operation: "prepare-update", code: `candidate-${status}`,
        boot: boot(), currentUsable: true,
      });
    },
  );

  it("classifies controller, inspection-port, and token-provider failures as technical preparation failures", async () => {
    const controllerFailure = harness();
    await controllerFailure.coordinator.initialize();
    vi.mocked(controllerFailure.ports.readControllerBoot).mockRejectedValueOnce(new Error("controller unavailable"));
    await expect(controllerFailure.coordinator.prepareUpdate(candidate.pair)).resolves.toMatchObject({
      phase: "failed", code: "preparation-failed", currentUsable: true,
    });

    const inspectionFailure = harness({ inspect: vi.fn(async () => { throw new Error("inspection unavailable"); }) });
    await expect(inspectionFailure.coordinator.prepareUpdate(candidate.pair)).resolves.toMatchObject({
      phase: "failed", code: "preparation-failed", currentUsable: true,
    });

    const tokenFailure = harness({ token: vi.fn(() => { throw new Error("token unavailable"); }) });
    await expect(tokenFailure.coordinator.prepareUpdate(candidate.pair)).resolves.toMatchObject({
      phase: "failed", code: "preparation-failed", currentUsable: true,
    });
  });

  it("synchronously revokes an older confirmation while a newer candidate is inspected", async () => {
    let release: (() => void) | undefined;
    const gate = new Promise<void>((resolve) => { release = resolve; });
    const test = harness({
      inspect: vi.fn(async (requested) => {
        if (samePairForTest(requested, anotherCandidate.pair)) await gate;
        return { status: "sealed" as const, candidate: samePairForTest(requested, candidate.pair) ? candidate : anotherCandidate };
      }),
    });
    const older = await test.coordinator.prepareUpdate(candidate.pair);
    if (older.phase !== "waiting-candidate-verified") throw new Error("expected verified waiting candidate");

    const newer = test.coordinator.prepareUpdate(anotherCandidate.pair);
    const stale = await test.coordinator.confirmUpdate(older.confirmationToken);

    expect(stale).toMatchObject({ phase: "preparing", currentUsable: true });
    expect(test.ports.recordTransitionIntent).not.toHaveBeenCalled();
    release?.();
    await expect(newer).resolves.toMatchObject({ phase: "waiting-candidate-verified", candidate: anotherCandidate });
  });

  it("binds provider collisions to coordinator generations and rejects the older token", async () => {
    const test = harness({
      token: vi.fn(() => "provider-collision"),
      inspect: vi.fn(async (requested) => ({
        status: "sealed" as const,
        candidate: samePairForTest(requested, candidate.pair) ? candidate : anotherCandidate,
      })),
    });
    const older = await test.coordinator.prepareUpdate(candidate.pair);
    const newer = await test.coordinator.prepareUpdate(anotherCandidate.pair);
    if (older.phase !== "waiting-candidate-verified" || newer.phase !== "waiting-candidate-verified") {
      throw new Error("expected verified waiting candidate");
    }

    expect(older.confirmationToken).toBe("g1.provider-collision");
    expect(newer.confirmationToken).toBe("g2.provider-collision");
    await test.coordinator.confirmUpdate(older.confirmationToken);
    expect(test.ports.recordTransitionIntent).not.toHaveBeenCalled();
  });

  it("records a generation-bound intent exactly once", async () => {
    const { test, prepared } = await confirmedIntent();

    await test.coordinator.confirmUpdate(prepared.confirmationToken);

    expect(test.ports.recordTransitionIntent).toHaveBeenCalledTimes(1);
  });

  it("uses collision-resistant instance identity when coordinators share one boot", async () => {
    const first = await confirmedIntent(harness({ instanceId: "instance-00000001" }));
    const second = await confirmedIntent(harness({ instanceId: "instance-00000002" }));

    expect(first.intent.transitionId).toBe("boot-1.instance-00000001.g1");
    expect(second.intent.transitionId).toBe("boot-1.instance-00000002.g1");
    expect(first.intent.transitionId).not.toBe(second.intent.transitionId);
  });

  it("revokes a persisted intent when a newer operation cancels confirmation", async () => {
    let releaseRecord: (() => void) | undefined;
    const recordGate = new Promise<void>((resolve) => { releaseRecord = resolve; });
    const persisted: CloseAndReopenIntentV1[] = [];
    const test = harness({
      record: vi.fn(async (intent) => {
        persisted.splice(0, persisted.length, intent);
        await recordGate;
      }),
      revoke: vi.fn(async (intent) => {
        if (persisted[0]?.transitionId === intent.transitionId) persisted.splice(0, 1);
      }),
    });
    const prepared = await test.coordinator.prepareUpdate(candidate.pair);
    if (prepared.phase !== "waiting-candidate-verified") throw new Error("expected verified waiting candidate");

    const confirming = test.coordinator.confirmUpdate(prepared.confirmationToken);
    await vi.waitFor(() => expect(test.ports.recordTransitionIntent).toHaveBeenCalledOnce());
    const rollback = await test.coordinator.requestRollback();
    releaseRecord?.();
    const cancelled = await confirming;

    expect(rollback).toMatchObject({ phase: "deployment-required", currentUsable: true });
    expect(cancelled).toEqual(rollback);
    expect(test.ports.revokeTransitionIntent).toHaveBeenCalledOnce();
    expect(persisted).toEqual([]);
  });

  it("does not overwrite a newer operation after concurrent intent consumption", async () => {
    const { intent } = await confirmedIntent();
    let releaseConsume: (() => void) | undefined;
    const consumeGate = new Promise<void>((resolve) => { releaseConsume = resolve; });
    const reopened = harness({
      boot: boot("boot-2", candidate),
      consume: vi.fn(async () => {
        await consumeGate;
        return "consumed" as const;
      }),
    });

    const verifying = reopened.coordinator.verifyNextBoot(intent);
    await vi.waitFor(() => expect(reopened.ports.consumeTransitionIntent).toHaveBeenCalledOnce());
    const rollback = await reopened.coordinator.requestRollback();
    releaseConsume?.();

    await expect(verifying).resolves.toEqual(rollback);
    expect(reopened.coordinator.state()).toEqual(rollback);
  });

  it("reports rollback as deployment-required without changing browser authority", async () => {
    const test = harness();
    const prepared = await test.coordinator.prepareUpdate(candidate.pair);
    if (prepared.phase !== "waiting-candidate-verified") throw new Error("expected verified waiting candidate");

    const state = await test.coordinator.requestRollback();

    expect(state).toEqual({
      phase: "deployment-required",
      operation: "rollback",
      boot: boot(),
      code: "rollback-unavailable",
      message: ROLLBACK_MESSAGE,
      currentUsable: true,
    });
    expect(test.ports.recordTransitionIntent).not.toHaveBeenCalled();
    await test.coordinator.confirmUpdate(prepared.confirmationToken);
    expect(test.ports.recordTransitionIntent).not.toHaveBeenCalled();
  });
});

function samePairForTest(left: AppReleasePairV1, right: AppReleasePairV1): boolean {
  return left.appBuildId === right.appBuildId && left.dataReleaseId === right.dataReleaseId;
}
