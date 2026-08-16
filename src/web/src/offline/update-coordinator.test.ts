// @vitest-environment node

import { describe, expect, it, vi } from "vitest";
import { validateAppReleasePair, type AppReleasePairV1 } from "./contracts/keys";
import type { ClientLeaseV1 } from "./contracts/policy";
import {
  ExplicitUpdateCoordinator,
  type AcceptedPairIdentityV1,
  type AtomicPairTransitionV1,
  type PairAuthoritySnapshotV1,
  type UpdateCoordinatorPorts,
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

const first = accepted(pair("build-1", "release-1"));
const second = accepted(pair("build-2", "release-2"));
const third = accepted(pair("build-3", "release-3"));

function snapshot(
  revision: string,
  active: AcceptedPairIdentityV1 = second,
  previous: AcceptedPairIdentityV1 | null = first,
): PairAuthoritySnapshotV1 {
  return Object.freeze({ contractVersion: 1, revision, active, previous });
}

function transition(
  before: PairAuthoritySnapshotV1,
  active: AcceptedPairIdentityV1,
  previous: AcceptedPairIdentityV1,
): AtomicPairTransitionV1 {
  return Object.freeze({
    contractVersion: 1,
    before,
    after: snapshot(`${before.revision}-next`, active, previous),
  });
}

function harness(options: Readonly<{
  initial?: PairAuthoritySnapshotV1;
  inspect?: UpdateCoordinatorPorts["inspectCandidate"];
  issueConfirmationToken?: UpdateCoordinatorPorts["issueConfirmationToken"];
}> = {}) {
  let current = options.initial ?? snapshot("revision-1");
  const inspectCandidate = options.inspect ?? vi.fn(async () => ({ status: "sealed" as const, candidate: third }));
  const activate = vi.fn(async (request: Parameters<UpdateCoordinatorPorts["activate"]>[0]) => {
    const result = transition(current, request.candidate, current.active);
    current = result.after;
    return result;
  });
  const rollback = vi.fn(async (request: Parameters<UpdateCoordinatorPorts["rollback"]>[0]) => {
    const result = transition(current, request.target, current.active);
    current = result.after;
    return result;
  });
  const cleanupRetiredPair = vi.fn<UpdateCoordinatorPorts["cleanupRetiredPair"]>(
    async () => ({ status: "removed" as const }),
  );
  let token = 0;
  const ports: UpdateCoordinatorPorts = {
    readSnapshot: vi.fn(async () => current),
    inspectCandidate,
    issueConfirmationToken: options.issueConfirmationToken ?? vi.fn(() => `confirm-${++token}`),
    activate,
    rollback,
    cleanupRetiredPair,
  };
  return { coordinator: new ExplicitUpdateCoordinator(ports), ports, activate, rollback, cleanupRetiredPair };
}

describe("explicit update coordinator", () => {
  it("does not activate, reload, or clean a sealed candidate before exact confirmation", async () => {
    const test = harness();

    const prepared = await test.coordinator.prepareUpdate(third.pair);

    expect(prepared).toMatchObject({
      phase: "awaiting-confirmation",
      action: "update",
      confirmationToken: "g1.confirm-1",
      target: third,
    });
    expect("reloadAllowed" in prepared).toBe(false);
    expect(test.activate).not.toHaveBeenCalled();
    expect(test.cleanupRetiredPair).not.toHaveBeenCalled();
  });

  it("atomically moves current to previous, activates the sealed candidate, then fences retired cleanup", async () => {
    const test = harness();
    const prepared = await test.coordinator.prepareUpdate(third.pair);
    if (prepared.phase !== "awaiting-confirmation") throw new Error("expected confirmation");

    const activated = await test.coordinator.confirm(prepared.confirmationToken);

    expect(test.activate).toHaveBeenCalledWith(expect.objectContaining({
      expected: snapshot("revision-1"),
      candidate: third,
      confirmationToken: "g1.confirm-1",
    }));
    expect(activated).toMatchObject({
      phase: "activated",
      reloadAllowed: true,
      snapshot: { active: third, previous: second },
      cleanup: { status: "removed", pair: first.pair },
    });
    expect(test.cleanupRetiredPair).toHaveBeenCalledWith(expect.objectContaining({
      protectedSnapshot: expect.objectContaining({ active: third, previous: second }),
      pair: first.pair,
    }));
  });

  it.each(["incomplete", "corrupt", "mixed", "stale"] as const)(
    "keeps the current pair usable when a candidate is %s",
    async (status) => {
      const test = harness({ inspect: vi.fn(async () => ({ status, reason: `candidate-${status}` })) });

      const state = await test.coordinator.prepareUpdate(third.pair);

      expect(state).toMatchObject({
        phase: "failed",
        operation: "prepare-update",
        code: `candidate-${status}`,
        recoverable: true,
        snapshot: snapshot("revision-1"),
      });
      expect(test.activate).not.toHaveBeenCalled();
    },
  );

  it("classifies update snapshot failure as technical preparation failure", async () => {
    const test = harness();
    await test.coordinator.initialize();
    vi.mocked(test.ports.readSnapshot).mockRejectedValueOnce(new Error("synthetic snapshot port failure"));

    const state = await test.coordinator.prepareUpdate(third.pair);

    expect(state).toMatchObject({
      phase: "failed", operation: "prepare-update", code: "transition-failed",
      currentUsable: true, snapshot: snapshot("revision-1"),
    });
  });

  it("classifies update inspection-port failure as technical rather than candidate corruption", async () => {
    const test = harness({ inspect: vi.fn(async () => { throw new Error("synthetic inspection port failure"); }) });

    const state = await test.coordinator.prepareUpdate(third.pair);

    expect(state).toMatchObject({
      phase: "failed", operation: "prepare-update", code: "transition-failed",
      currentUsable: true, snapshot: snapshot("revision-1"),
    });
  });

  it("classifies update token-provider failure as technical preparation failure", async () => {
    const test = harness({
      issueConfirmationToken: vi.fn(() => { throw new Error("synthetic update token failure"); }),
    });

    const state = await test.coordinator.prepareUpdate(third.pair);

    expect(state).toMatchObject({
      phase: "failed", operation: "prepare-update", code: "transition-failed",
      currentUsable: true, snapshot: snapshot("revision-1"),
    });
  });

  it("rejects a wrong or stale confirmation token without invoking atomic activation", async () => {
    const test = harness();
    await test.coordinator.prepareUpdate(third.pair);

    const state = await test.coordinator.confirm("g1.confirm-wrong");

    expect(state).toMatchObject({ phase: "failed", code: "confirmation-rejected", snapshot: snapshot("revision-1") });
    expect(test.activate).not.toHaveBeenCalled();
  });

  it("allows only the last concurrently inspected candidate to reach confirmation", async () => {
    let releaseFirst: (() => void) | undefined;
    let markFirstEntered: (() => void) | undefined;
    const firstEntered = new Promise<void>((resolve) => { markFirstEntered = resolve; });
    const fourth = accepted(pair("build-4", "release-4"), "d");
    const inspect = vi.fn(async (candidate: AppReleasePairV1) => {
      if (candidate.appBuildId === third.pair.appBuildId) {
        markFirstEntered?.();
        await new Promise<void>((resolve) => { releaseFirst = resolve; });
        return { status: "sealed" as const, candidate: third };
      }
      return { status: "sealed" as const, candidate: fourth };
    });
    const test = harness({ inspect });

    const older = test.coordinator.prepareUpdate(third.pair);
    await firstEntered;
    const newer = await test.coordinator.prepareUpdate(fourth.pair);
    releaseFirst?.();
    const superseded = await older;

    expect(newer).toMatchObject({ phase: "awaiting-confirmation", target: fourth });
    expect(superseded).toMatchObject({ phase: "awaiting-confirmation", target: fourth });
    if (newer.phase !== "awaiting-confirmation") throw new Error("expected confirmation");
    await test.coordinator.confirm(newer.confirmationToken);
    expect(test.activate).toHaveBeenCalledTimes(1);
    expect(test.activate).toHaveBeenCalledWith(expect.objectContaining({ candidate: fourth }));
  });

  it("synchronously revokes an update token while a newer update is still being inspected", async () => {
    const fourth = accepted(pair("build-4", "release-4"), "d");
    let releaseInspection: (() => void) | undefined;
    const inspectionGate = new Promise<void>((resolve) => { releaseInspection = resolve; });
    const test = harness({
      inspect: vi.fn(async (candidate) => {
        if (candidate.appBuildId === fourth.pair.appBuildId) await inspectionGate;
        return { status: "sealed" as const, candidate: candidate.appBuildId === fourth.pair.appBuildId ? fourth : third };
      }),
    });
    const older = await test.coordinator.prepareUpdate(third.pair);
    if (older.phase !== "awaiting-confirmation") throw new Error("expected confirmation");

    const newerPreparation = test.coordinator.prepareUpdate(fourth.pair);
    const staleConfirmation = await test.coordinator.confirm(older.confirmationToken);

    expect(staleConfirmation).toMatchObject({ phase: "preparing", action: "update" });
    expect(test.activate).not.toHaveBeenCalled();
    releaseInspection?.();
    await expect(newerPreparation).resolves.toMatchObject({ phase: "awaiting-confirmation", target: fourth });
  });

  it("synchronously revokes an update token while rollback preparation is awaiting authority", async () => {
    const test = harness();
    const older = await test.coordinator.prepareUpdate(third.pair);
    if (older.phase !== "awaiting-confirmation") throw new Error("expected confirmation");
    let releaseAuthority: (() => void) | undefined;
    const authorityGate = new Promise<void>((resolve) => { releaseAuthority = resolve; });
    vi.mocked(test.ports.readSnapshot).mockImplementationOnce(async () => {
      await authorityGate;
      return snapshot("revision-1");
    });

    const rollbackPreparation = test.coordinator.prepareRollback();
    const staleConfirmation = await test.coordinator.confirm(older.confirmationToken);

    expect(staleConfirmation).toMatchObject({ phase: "preparing", action: "rollback" });
    expect(test.activate).not.toHaveBeenCalled();
    releaseAuthority?.();
    await expect(rollbackPreparation).resolves.toMatchObject({ phase: "awaiting-confirmation", action: "rollback" });
  });

  it("synchronously revokes a rollback token while a newer update is still being inspected", async () => {
    let releaseInspection: (() => void) | undefined;
    const inspectionGate = new Promise<void>((resolve) => { releaseInspection = resolve; });
    const test = harness({
      inspect: vi.fn(async () => {
        await inspectionGate;
        return { status: "sealed" as const, candidate: third };
      }),
    });
    const older = await test.coordinator.prepareRollback();
    if (older.phase !== "awaiting-confirmation") throw new Error("expected confirmation");

    const updatePreparation = test.coordinator.prepareUpdate(third.pair);
    const staleConfirmation = await test.coordinator.confirm(older.confirmationToken);

    expect(staleConfirmation).toMatchObject({ phase: "preparing", action: "update" });
    expect(test.rollback).not.toHaveBeenCalled();
    releaseInspection?.();
    await expect(updatePreparation).resolves.toMatchObject({ phase: "awaiting-confirmation", action: "update" });
  });

  it("binds provider-token collisions to distinct coordinator generations", async () => {
    const fourth = accepted(pair("build-4", "release-4"), "d");
    const issueConfirmationToken = vi.fn(() => "provider-collision");
    const test = harness({
      issueConfirmationToken,
      inspect: vi.fn(async (candidate) => ({
        status: "sealed" as const, candidate: candidate.appBuildId === fourth.pair.appBuildId ? fourth : third,
      })),
    });
    const older = await test.coordinator.prepareUpdate(third.pair);
    const newer = await test.coordinator.prepareUpdate(fourth.pair);
    if (older.phase !== "awaiting-confirmation" || newer.phase !== "awaiting-confirmation") {
      throw new Error("expected confirmation");
    }

    expect(older.confirmationToken).toBe("g1.provider-collision");
    expect(newer.confirmationToken).toBe("g2.provider-collision");
    expect(issueConfirmationToken).toHaveBeenNthCalledWith(1, expect.objectContaining({ coordinatorGeneration: 1 }));
    expect(issueConfirmationToken).toHaveBeenNthCalledWith(2, expect.objectContaining({ coordinatorGeneration: 2 }));
    await test.coordinator.confirm(older.confirmationToken);
    expect(test.activate).not.toHaveBeenCalled();
  });

  it("consumes a generation-bound confirmation exactly once", async () => {
    const test = harness({ issueConfirmationToken: vi.fn(() => "provider-reused") });
    const prepared = await test.coordinator.prepareUpdate(third.pair);
    if (prepared.phase !== "awaiting-confirmation") throw new Error("expected confirmation");

    await test.coordinator.confirm(prepared.confirmationToken);
    await test.coordinator.confirm(prepared.confirmationToken);

    expect(test.activate).toHaveBeenCalledTimes(1);
  });

  it("fails closed when authority changes between inspection and confirmation", async () => {
    const test = harness();
    const prepared = await test.coordinator.prepareUpdate(third.pair);
    if (prepared.phase !== "awaiting-confirmation") throw new Error("expected confirmation");
    vi.mocked(test.ports.readSnapshot).mockResolvedValueOnce(snapshot("revision-raced", second, null));

    const state = await test.coordinator.confirm(prepared.confirmationToken);

    expect(state).toMatchObject({ phase: "failed", code: "authority-stale", snapshot: snapshot("revision-raced", second, null) });
    expect(test.activate).not.toHaveBeenCalled();
  });

  it("allows only one atomic transition for concurrent uses of the same confirmation", async () => {
    const test = harness();
    const prepared = await test.coordinator.prepareUpdate(third.pair);
    if (prepared.phase !== "awaiting-confirmation") throw new Error("expected confirmation");
    let releaseRead: (() => void) | undefined;
    vi.mocked(test.ports.readSnapshot).mockImplementationOnce(async () => {
      await new Promise<void>((resolve) => { releaseRead = resolve; });
      return snapshot("revision-1");
    });

    const firstConfirmation = test.coordinator.confirm(prepared.confirmationToken);
    const duplicateConfirmation = await test.coordinator.confirm(prepared.confirmationToken);
    releaseRead?.();
    await firstConfirmation;

    expect(duplicateConfirmation).toMatchObject({ phase: "transitioning", action: "update", target: third });
    expect(test.activate).toHaveBeenCalledTimes(1);
  });

  it("keeps a successful new current usable when cleanup is blocked by an exact active lease", async () => {
    const test = harness();
    const lease: ClientLeaseV1 = {
      contractVersion: 1,
      leaseId: "client-lease-1",
      pair: first.pair,
      expiresAtEpochMs: 1_800_000_000_000,
      state: "active",
    };
    test.cleanupRetiredPair.mockResolvedValueOnce({ status: "blocked", leases: [lease] });
    const prepared = await test.coordinator.prepareUpdate(third.pair);
    if (prepared.phase !== "awaiting-confirmation") throw new Error("expected confirmation");

    const state = await test.coordinator.confirm(prepared.confirmationToken);

    expect(state).toMatchObject({
      phase: "activated",
      reloadAllowed: true,
      snapshot: { active: third, previous: second },
      cleanup: { status: "blocked", pair: first.pair, leases: [lease] },
    });
  });

  it("withholds reload but preserves the new authority when post-activation cleanup fails", async () => {
    const test = harness();
    test.cleanupRetiredPair.mockRejectedValueOnce(new Error("synthetic cleanup fence failure"));
    const prepared = await test.coordinator.prepareUpdate(third.pair);
    if (prepared.phase !== "awaiting-confirmation") throw new Error("expected confirmation");

    const state = await test.coordinator.confirm(prepared.confirmationToken);

    expect(state).toMatchObject({
      phase: "failed",
      operation: "cleanup",
      code: "cleanup-failed",
      currentUsable: true,
      snapshot: { active: third, previous: second },
    });
    expect("reloadAllowed" in state).toBe(false);
  });

  it("reports activation failure as technical state and refreshes the usable current pair", async () => {
    const test = harness();
    test.activate.mockRejectedValueOnce(new Error("synthetic atomic failure"));
    const prepared = await test.coordinator.prepareUpdate(third.pair);
    if (prepared.phase !== "awaiting-confirmation") throw new Error("expected confirmation");

    const state = await test.coordinator.confirm(prepared.confirmationToken);

    expect(state).toMatchObject({
      phase: "failed",
      operation: "activate-update",
      code: "transition-failed",
      recoverable: true,
      snapshot: snapshot("revision-1"),
    });
  });

  it("requires confirmation and atomically swaps the exact active and previous pair for rollback", async () => {
    const test = harness();

    const prepared = await test.coordinator.prepareRollback();
    expect(test.rollback).not.toHaveBeenCalled();
    if (prepared.phase !== "awaiting-confirmation") throw new Error("expected confirmation");
    const rolledBack = await test.coordinator.confirm(prepared.confirmationToken);

    expect(test.rollback).toHaveBeenCalledWith(expect.objectContaining({
      expected: snapshot("revision-1"),
      target: first,
      confirmationToken: "g1.confirm-1",
    }));
    expect(rolledBack).toMatchObject({
      phase: "rolled-back",
      reloadAllowed: true,
      snapshot: { active: first, previous: second },
      cleanup: null,
    });
  });

  it("does not offer rollback without an exact previous pair", async () => {
    const test = harness({ initial: snapshot("revision-1", second, null) });

    const state = await test.coordinator.prepareRollback();

    expect(state).toMatchObject({ phase: "failed", operation: "prepare-rollback", code: "rollback-unavailable" });
    expect(test.rollback).not.toHaveBeenCalled();
  });

  it("contains snapshot failure while preparing rollback and keeps the known current usable", async () => {
    const test = harness();
    await test.coordinator.initialize();
    vi.mocked(test.ports.readSnapshot).mockRejectedValueOnce(new Error("synthetic snapshot failure"));

    const state = await test.coordinator.prepareRollback();

    expect(state).toMatchObject({
      phase: "failed",
      operation: "prepare-rollback",
      code: "transition-failed",
      currentUsable: true,
      snapshot: snapshot("revision-1"),
    });
    expect(test.rollback).not.toHaveBeenCalled();
  });

  it("contains confirmation-token issuance failure while preparing rollback", async () => {
    const test = harness();
    vi.mocked(test.ports.issueConfirmationToken).mockImplementationOnce(() => {
      throw new Error("synthetic token failure");
    });

    const state = await test.coordinator.prepareRollback();

    expect(state).toMatchObject({
      phase: "failed",
      operation: "prepare-rollback",
      code: "transition-failed",
      currentUsable: true,
      snapshot: snapshot("revision-1"),
    });
    expect(test.rollback).not.toHaveBeenCalled();
  });
});
