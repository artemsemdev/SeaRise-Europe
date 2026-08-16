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
  type IntentConsumptionResultV1,
  type StaticUpdateCoordinatorPorts,
  type TransitionArmPermitV1,
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
let instanceSequence = 0;

function boot(bootId = "boot-1", controller = active): ControllerBootProofV1 {
  return Object.freeze({ contractVersion: 1, bootId, controller });
}

function deferred<T>() {
  let resolve: ((value: T) => void) | undefined;
  let reject: ((reason: unknown) => void) | undefined;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return {
    promise,
    resolve: (value: T) => resolve?.(value),
    reject: (reason: unknown) => reject?.(reason),
  };
}

function durableIntentStore() {
  let record: Readonly<{ intent: CloseAndReopenIntentV1; state: "pending" | "armed" | "consumed" | "tombstoned" }> | null = null;
  return {
    pendingIntent: () => record?.intent ?? null,
    state: () => record?.state ?? null,
    recordPending: async (intent: CloseAndReopenIntentV1) => {
      record = Object.freeze({ intent, state: "pending" as const });
    },
    arm: async (intent: CloseAndReopenIntentV1, permit: TransitionArmPermitV1) => {
      if (permit.signal.aborted) throw new Error("arm cancelled");
      if (!record) return "missing" as const;
      if (record.state === "tombstoned") return "mismatch" as const;
      if (record.intent.transitionId !== intent.transitionId || record.state !== "pending") return "mismatch" as const;
      record = Object.freeze({ intent: record.intent, state: "armed" as const });
      return "armed" as const;
    },
    discardPending: async (intent: CloseAndReopenIntentV1) => {
      if (record?.state === "pending" && record.intent.transitionId === intent.transitionId) record = null;
    },
    tombstone: async (intent: CloseAndReopenIntentV1) => {
      if (!record) return "missing" as const;
      if (record.intent.transitionId !== intent.transitionId || record.state === "tombstoned") return "mismatch" as const;
      record = Object.freeze({ intent: record.intent, state: "tombstoned" as const });
      return "tombstoned" as const;
    },
    consume: async (intent: CloseAndReopenIntentV1) => {
      if (!record || record.intent.transitionId !== intent.transitionId) return "missing" as const;
      if (record.state === "pending" || record.state === "tombstoned") return "not-armed" as const;
      if (record.state === "consumed") return "already-consumed" as const;
      record = Object.freeze({ intent: record.intent, state: "consumed" as const });
      return "consumed" as const;
    },
  };
}

function harness(options: Readonly<{
  boot?: ControllerBootProofV1;
  instanceId?: string;
  useDefaultEntropy?: boolean;
  read?: StaticUpdateCoordinatorPorts["readControllerBoot"];
  inspect?: StaticUpdateCoordinatorPorts["inspectWaitingCandidate"];
  token?: StaticUpdateCoordinatorPorts["issueConfirmationToken"];
  record?: StaticUpdateCoordinatorPorts["recordPendingTransitionIntent"];
  arm?: StaticUpdateCoordinatorPorts["armTransitionIntent"];
  discard?: StaticUpdateCoordinatorPorts["discardPendingTransitionIntent"];
  tombstone?: StaticUpdateCoordinatorPorts["tombstoneTransitionIntent"];
  consume?: StaticUpdateCoordinatorPorts["consumeTransitionIntent"];
}> = {}) {
  let currentBoot = options.boot ?? boot();
  const recorded: CloseAndReopenIntentV1[] = [];
  let tokenSequence = 0;
  const ports: StaticUpdateCoordinatorPorts = {
    readControllerBoot: options.read ?? vi.fn(async () => currentBoot),
    inspectWaitingCandidate: options.inspect ?? vi.fn(async () => ({ status: "sealed" as const, candidate })),
    issueConfirmationToken: options.token ?? vi.fn(() => `provider-${++tokenSequence}`),
    recordPendingTransitionIntent: options.record ?? vi.fn(async (intent) => { recorded.splice(0, recorded.length, intent); }),
    armTransitionIntent: options.arm ?? vi.fn(async (_intent, permit) => {
      if (permit.signal.aborted) throw new Error("arm cancelled");
      return "armed" as const;
    }),
    discardPendingTransitionIntent: options.discard ?? vi.fn(async (intent) => {
      if (recorded[0]?.transitionId === intent.transitionId) recorded.splice(0, 1);
    }),
    tombstoneTransitionIntent: options.tombstone ?? vi.fn(async (intent) => {
      if (recorded[0]?.transitionId === intent.transitionId) recorded.splice(0, 1);
      return "tombstoned" as const;
    }),
    consumeTransitionIntent: options.consume ?? vi.fn(async () => "consumed" as const),
  };
  const coordinatorOptions = options.useDefaultEntropy
    ? undefined
    : { instanceId: options.instanceId ?? `test-instance-${String(++instanceSequence).padStart(8, "0")}` };
  return {
    coordinator: new StaticHostUpdateCoordinator(ports, coordinatorOptions),
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
    expect(test.ports.recordPendingTransitionIntent).not.toHaveBeenCalled();
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
    expect(test.ports.recordPendingTransitionIntent).not.toHaveBeenCalled();
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
    expect(test.ports.recordPendingTransitionIntent).not.toHaveBeenCalled();
  });

  it("records a generation-bound intent exactly once", async () => {
    const { test, prepared } = await confirmedIntent();

    await test.coordinator.confirmUpdate(prepared.confirmationToken);

    expect(test.ports.recordPendingTransitionIntent).toHaveBeenCalledTimes(1);
  });

  it("uses collision-resistant instance identity when coordinators share one boot", async () => {
    const first = await confirmedIntent(harness({ instanceId: "instance-00000001" }));
    const second = await confirmedIntent(harness({ instanceId: "instance-00000002" }));

    expect(first.intent.transitionId).toBe("boot-1.instance-00000001.g1");
    expect(second.intent.transitionId).toBe("boot-1.instance-00000002.g1");
    expect(first.intent.transitionId).not.toBe(second.intent.transitionId);
  });

  it("mints distinct coordinator identities from production cryptographic entropy", async () => {
    const first = await confirmedIntent(harness({ useDefaultEntropy: true }));
    const second = await confirmedIntent(harness({ useDefaultEntropy: true }));

    expect(first.intent.transitionId).not.toBe(second.intent.transitionId);
  });

  it("rejects duplicate injected coordinator identities in one JavaScript realm", () => {
    const instanceId = `duplicate-test-${String(++instanceSequence).padStart(8, "0")}`;
    harness({ instanceId });

    expect(() => harness({ instanceId })).toThrow("already active");
  });

  it("discards a persisted pending intent when a newer operation cancels confirmation", async () => {
    let releaseRecord: (() => void) | undefined;
    const recordGate = new Promise<void>((resolve) => { releaseRecord = resolve; });
    const persisted: CloseAndReopenIntentV1[] = [];
    const test = harness({
      record: vi.fn(async (intent) => {
        persisted.splice(0, persisted.length, intent);
        await recordGate;
      }),
      discard: vi.fn(async (intent) => {
        if (persisted[0]?.transitionId === intent.transitionId) persisted.splice(0, 1);
      }),
    });
    const prepared = await test.coordinator.prepareUpdate(candidate.pair);
    if (prepared.phase !== "waiting-candidate-verified") throw new Error("expected verified waiting candidate");

    const confirming = test.coordinator.confirmUpdate(prepared.confirmationToken);
    await vi.waitFor(() => expect(test.ports.recordPendingTransitionIntent).toHaveBeenCalledOnce());
    const rollingBack = test.coordinator.requestRollback();
    releaseRecord?.();
    const cancelled = await confirming;
    const rollback = await rollingBack;

    expect(rollback).toMatchObject({ phase: "deployment-required", currentUsable: true });
    expect(cancelled).toMatchObject({ phase: "recording-close-and-reopen-intent", currentUsable: true });
    expect(test.ports.discardPendingTransitionIntent).toHaveBeenCalledOnce();
    expect(persisted).toEqual([]);
  });

  it("does not let a rejected record overwrite the operation that cancelled it", async () => {
    const record = deferred<void>();
    const test = harness({ record: vi.fn(async () => await record.promise) });
    const prepared = await test.coordinator.prepareUpdate(candidate.pair);
    if (prepared.phase !== "waiting-candidate-verified") throw new Error("expected verified waiting candidate");

    const confirming = test.coordinator.confirmUpdate(prepared.confirmationToken);
    await vi.waitFor(() => expect(test.ports.recordPendingTransitionIntent).toHaveBeenCalledOnce());
    const rollingBack = test.coordinator.requestRollback();
    record.reject(new Error("record rejected"));

    await expect(confirming).resolves.toMatchObject({ phase: "recording-close-and-reopen-intent" });
    const rollback = await rollingBack;
    expect(test.coordinator.state()).toEqual(rollback);
  });

  it("does not let a rejected stale-intent revocation overwrite its cancelling operation", async () => {
    const record = deferred<void>();
    const discard = deferred<void>();
    const test = harness({
      record: vi.fn(async () => await record.promise),
      discard: vi.fn(async () => await discard.promise),
    });
    const prepared = await test.coordinator.prepareUpdate(candidate.pair);
    if (prepared.phase !== "waiting-candidate-verified") throw new Error("expected verified waiting candidate");

    const confirming = test.coordinator.confirmUpdate(prepared.confirmationToken);
    await vi.waitFor(() => expect(test.ports.recordPendingTransitionIntent).toHaveBeenCalledOnce());
    const rollingBack = test.coordinator.requestRollback();
    record.resolve();
    await vi.waitFor(() => expect(test.ports.discardPendingTransitionIntent).toHaveBeenCalledOnce());
    discard.reject(new Error("discard rejected"));

    await expect(confirming).resolves.toMatchObject({ phase: "recording-close-and-reopen-intent" });
    const rollback = await rollingBack;
    expect(test.coordinator.state()).toEqual(rollback);
  });

  it("never arms a pending intent when cancellation races a failed cleanup", async () => {
    const store = durableIntentStore();
    const recordGate = deferred<void>();
    const arm = vi.fn(store.arm);
    const test = harness({
      record: vi.fn(async (intent) => {
        await store.recordPending(intent);
        await recordGate.promise;
      }),
      arm,
      discard: vi.fn(async () => { throw new Error("cleanup rejected"); }),
      tombstone: vi.fn(store.tombstone),
    });
    const prepared = await test.coordinator.prepareUpdate(candidate.pair);
    if (prepared.phase !== "waiting-candidate-verified") throw new Error("expected verified waiting candidate");

    const confirming = test.coordinator.confirmUpdate(prepared.confirmationToken);
    await vi.waitFor(() => expect(store.state()).toBe("pending"));
    const poisonedIntent = store.pendingIntent();
    if (!poisonedIntent) throw new Error("expected pending intent");
    const rollingBack = test.coordinator.requestRollback();
    recordGate.resolve();

    await expect(confirming).resolves.toMatchObject({ phase: "recording-close-and-reopen-intent" });
    const rollback = await rollingBack;
    expect(rollback).toMatchObject({ phase: "deployment-required" });
    expect(arm).not.toHaveBeenCalled();
    expect(store.state()).toBe("tombstoned");

    const reopened = harness({ boot: boot("boot-2", candidate), consume: vi.fn(store.consume) });
    await expect(reopened.coordinator.verifyNextBoot(poisonedIntent)).resolves.toMatchObject({
      phase: "failed", code: "intent-stale", currentUsable: true,
    });
    expect(store.state()).toBe("tombstoned");
  });

  it("serializes rollback after an unresolved committed arm and tombstones it", async () => {
    const store = durableIntentStore();
    const armGate = deferred<void>();
    const test = harness({
      record: vi.fn(store.recordPending),
      arm: vi.fn(async (intent, permit) => {
        const result = await store.arm(intent, permit);
        await armGate.promise;
        return result;
      }),
      discard: vi.fn(store.discardPending),
      tombstone: vi.fn(store.tombstone),
    });
    const prepared = await test.coordinator.prepareUpdate(candidate.pair);
    if (prepared.phase !== "waiting-candidate-verified") throw new Error("expected verified waiting candidate");

    const confirming = test.coordinator.confirmUpdate(prepared.confirmationToken);
    await vi.waitFor(() => expect(store.state()).toBe("armed"));
    const armedIntent = store.pendingIntent();
    if (!armedIntent) throw new Error("expected armed intent");
    const rollingBack = test.coordinator.requestRollback();
    expect(test.coordinator.state()).toMatchObject({ phase: "recording-close-and-reopen-intent" });
    armGate.resolve();

    await expect(confirming).resolves.toMatchObject({ phase: "recording-close-and-reopen-intent" });
    await expect(rollingBack).resolves.toMatchObject({ phase: "deployment-required" });
    expect(store.state()).toBe("tombstoned");

    const reopened = harness({ boot: boot("boot-2", candidate), consume: vi.fn(store.consume) });
    await expect(reopened.coordinator.verifyNextBoot(armedIntent)).resolves.toMatchObject({
      phase: "failed", code: "intent-stale", currentUsable: true,
    });
  });

  it("surfaces tombstone failure without claiming rollback over armed authority", async () => {
    const store = durableIntentStore();
    const armGate = deferred<void>();
    const test = harness({
      record: vi.fn(store.recordPending),
      arm: vi.fn(async (intent, permit) => {
        const result = await store.arm(intent, permit);
        await armGate.promise;
        return result;
      }),
      discard: vi.fn(store.discardPending),
      tombstone: vi.fn(async () => { throw new Error("tombstone unavailable"); }),
    });
    const prepared = await test.coordinator.prepareUpdate(candidate.pair);
    if (prepared.phase !== "waiting-candidate-verified") throw new Error("expected verified waiting candidate");

    const confirming = test.coordinator.confirmUpdate(prepared.confirmationToken);
    await vi.waitFor(() => expect(store.state()).toBe("armed"));
    const armedIntent = store.pendingIntent();
    if (!armedIntent) throw new Error("expected armed intent");
    const rollingBack = test.coordinator.requestRollback();
    armGate.resolve();

    await confirming;
    const rollback = await rollingBack;
    expect(rollback).toMatchObject({
      phase: "rollback-failed", operation: "rollback", code: "intent-tombstone-failed",
      durableIntentState: "armed", intent: armedIntent, message: "tombstone unavailable",
      currentUsable: true,
    });
    expect(store.state()).toBe("armed");

    const reopened = harness({ boot: boot("boot-2", candidate), consume: vi.fn(store.consume) });
    await expect(reopened.coordinator.verifyNextBoot(armedIntent)).resolves.toMatchObject({
      phase: "controller-verified-activation", currentUsable: true,
    });
  });

  it("reports a current record and cleanup failure without arming durable poison", async () => {
    const store = durableIntentStore();
    const test = harness({
      record: vi.fn(async (intent) => {
        await store.recordPending(intent);
        throw new Error("record completion ambiguous");
      }),
      arm: vi.fn(store.arm),
      discard: vi.fn(async () => { throw new Error("cleanup rejected"); }),
    });
    const prepared = await test.coordinator.prepareUpdate(candidate.pair);
    if (prepared.phase !== "waiting-candidate-verified") throw new Error("expected verified waiting candidate");

    const state = await test.coordinator.confirmUpdate(prepared.confirmationToken);
    const poisonedIntent = store.pendingIntent();
    if (!poisonedIntent) throw new Error("expected pending intent");

    expect(state).toMatchObject({
      phase: "failed", operation: "confirm-update", code: "intent-record-failed",
      message: "cleanup rejected", currentUsable: true,
    });
    expect(test.ports.armTransitionIntent).not.toHaveBeenCalled();
    expect(store.state()).toBe("pending");

    const reopened = harness({ boot: boot("boot-2", candidate), consume: vi.fn(store.consume) });
    await expect(reopened.coordinator.verifyNextBoot(poisonedIntent)).resolves.toMatchObject({
      phase: "failed", code: "intent-stale", currentUsable: true,
    });
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

  it("does not let a rejected intent consumption overwrite a newer operation", async () => {
    const { intent } = await confirmedIntent();
    const consume = deferred<IntentConsumptionResultV1>();
    const reopened = harness({
      boot: boot("boot-2", candidate),
      consume: vi.fn(async () => await consume.promise),
    });

    const verifying = reopened.coordinator.verifyNextBoot(intent);
    await vi.waitFor(() => expect(reopened.ports.consumeTransitionIntent).toHaveBeenCalledOnce());
    const rollback = await reopened.coordinator.requestRollback();
    consume.reject(new Error("consume rejected"));

    await expect(verifying).resolves.toEqual(rollback);
    expect(reopened.coordinator.state()).toEqual(rollback);
  });

  it.each(["resolve", "reject"] as const)(
    "does not let stale initialize read %s overwrite a newer rollback",
    async (settlement) => {
      const firstRead = deferred<ControllerBootProofV1>();
      const read = vi.fn()
        .mockImplementationOnce(async () => await firstRead.promise)
        .mockResolvedValue(boot());
      const test = harness({ read });

      const initializing = test.coordinator.initialize();
      const rollback = await test.coordinator.requestRollback();
      if (settlement === "resolve") firstRead.resolve(boot());
      else firstRead.reject(new Error("initialize read rejected"));

      await expect(initializing).resolves.toEqual(rollback);
      expect(test.coordinator.state()).toEqual(rollback);
    },
  );

  it.each(["resolve", "reject"] as const)(
    "does not let stale rollback read %s overwrite a newer initialization",
    async (settlement) => {
      const firstRead = deferred<ControllerBootProofV1>();
      const read = vi.fn()
        .mockImplementationOnce(async () => await firstRead.promise)
        .mockResolvedValue(boot());
      const test = harness({ read });

      const rollingBack = test.coordinator.requestRollback();
      const initialized = await test.coordinator.initialize();
      if (settlement === "resolve") firstRead.resolve(boot());
      else firstRead.reject(new Error("rollback read rejected"));

      await expect(rollingBack).resolves.toEqual(initialized);
      expect(test.coordinator.state()).toEqual(initialized);
    },
  );

  it.each(["resolve", "reject"] as const)(
    "does not let stale verification read %s overwrite a newer rollback",
    async (settlement) => {
      const { intent } = await confirmedIntent();
      const firstRead = deferred<ControllerBootProofV1>();
      const read = vi.fn()
        .mockImplementationOnce(async () => await firstRead.promise)
        .mockResolvedValue(boot("boot-2", candidate));
      const reopened = harness({ read });

      const verifying = reopened.coordinator.verifyNextBoot(intent);
      const rollback = await reopened.coordinator.requestRollback();
      if (settlement === "resolve") firstRead.resolve(boot("boot-2", candidate));
      else firstRead.reject(new Error("verification read rejected"));

      await expect(verifying).resolves.toEqual(rollback);
      expect(reopened.coordinator.state()).toEqual(rollback);
    },
  );

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
    expect(test.ports.recordPendingTransitionIntent).not.toHaveBeenCalled();
    await test.coordinator.confirmUpdate(prepared.confirmationToken);
    expect(test.ports.recordPendingTransitionIntent).not.toHaveBeenCalled();
  });
});

function samePairForTest(left: AppReleasePairV1, right: AppReleasePairV1): boolean {
  return left.appBuildId === right.appBuildId && left.dataReleaseId === right.dataReleaseId;
}
