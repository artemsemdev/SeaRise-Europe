import type { BrowserUpdateCoordinator } from "../application/browser-runtime";
import type { RuntimeCapabilityV2, UpdateCapabilityV1 } from "./contracts/policy";
import { OFFLINE_WORKER_PROTOCOL, validateOfflineWorkerToClientMessage } from "./contracts/policy";
import type { AppReleasePairV1 } from "./contracts/keys";
import { PairLifecycleStore } from "./pair-lifecycle-store";
import { StaticUpdateCapabilityCoordinator } from "./static-update-capability";
import {
  StaticHostUpdateCoordinator,
  type AcceptedPairIdentityV1,
  type CloseAndReopenIntentV1,
  type ControllerBootProofV1,
  type DurablePortPermitV1,
  type StaticUpdateCoordinatorPorts,
} from "./update-coordinator";
import type { VerifiedResourceRouter } from "./verified-resource-router";

const INTENT_KEY = "searise:update-intent:v1";

type DurableIntent = Readonly<{ intent: CloseAndReopenIntentV1; state: "pending" | "armed" | "consumed" | "tombstoned" }>;

function exactIntent(left: CloseAndReopenIntentV1, right: CloseAndReopenIntentV1): boolean {
  return left.transitionId === right.transitionId && JSON.stringify(left) === JSON.stringify(right);
}

async function workerIdentity(worker: ServiceWorker): Promise<Readonly<{
  pair: AppReleasePairV1; precacheSetSha256: string;
}>> {
  const messageToken = `candidate-${crypto.randomUUID()}`;
  const channel = new MessageChannel();
  const raw = await new Promise<unknown>((resolve, reject) => {
    const timeout = setTimeout(() => reject(new Error("Waiting worker identity timed out.")), 5_000);
    channel.port1.onmessage = ({ data }) => { clearTimeout(timeout); channel.port1.close(); resolve(data); };
    worker.postMessage({ protocol: OFFLINE_WORKER_PROTOCOL, type: "discover-identity", messageToken }, [channel.port2]);
  });
  const message = validateOfflineWorkerToClientMessage(raw);
  if (message.type !== "worker-identity" || message.messageToken !== messageToken) {
    throw new Error("Waiting worker identity was not verified.");
  }
  return message;
}

function accepted(
  snapshot: ReturnType<VerifiedResourceRouter["current"]>,
  currentPrecacheSetSha256: string,
): AcceptedPairIdentityV1 {
  if (!snapshot) throw new Error("Current accepted resource authority is unavailable.");
  return Object.freeze({
    contractVersion: 1,
    pair: snapshot.plan.pair,
    precacheSetSha256: currentPrecacheSetSha256,
    resourcePlanSha256: snapshot.plan.resourcePlanSha256,
    receiptSha256: snapshot.gate.receiptSha256,
  });
}

export function createProductionUpdateCoordinator(
  router: VerifiedResourceRouter,
  currentPrecacheSetSha256: string,
): BrowserUpdateCoordinator {
  const lifecycle = new PairLifecycleStore({ indexedDB, cacheStorage: caches });
  const bootId = crypto.randomUUID();
  let discovered: Awaited<ReturnType<typeof workerIdentity>> | null = null;
  const readDurable = (): DurableIntent | null => {
    const value = localStorage.getItem(INTENT_KEY);
    return value ? JSON.parse(value) as DurableIntent : null;
  };
  const writeDurable = (value: DurableIntent): void => localStorage.setItem(INTENT_KEY, JSON.stringify(value));
  const guard = (permit: DurablePortPermitV1): void => {
    if (permit.signal.aborted) throw new DOMException("Update intent operation aborted.", "AbortError");
  };
  const withLock = async <T>(permit: DurablePortPermitV1, operation: () => T): Promise<T> => {
    guard(permit);
    return navigator.locks.request(INTENT_KEY, { mode: "exclusive", signal: permit.signal }, () => {
      guard(permit);
      return operation();
    });
  };
  const readBoot = async (): Promise<ControllerBootProofV1> => Object.freeze({
    contractVersion: 1, bootId, controller: await completeCurrentAuthority(),
  });
  const completeCurrentAuthority = async (): Promise<AcceptedPairIdentityV1> => {
    const identity = accepted(router.current(), currentPrecacheSetSha256);
    let stored = await lifecycle.read(identity.pair);
    if (stored.status === "missing") {
      await lifecycle.stage(identity.pair);
      await lifecycle.completeBootstrap(identity.pair, identity.precacheSetSha256);
      await lifecycle.completeCore(identity.pair, {
        precacheSetSha256: identity.precacheSetSha256,
        resourcePlanSha256: identity.resourcePlanSha256,
        receiptSha256: identity.receiptSha256,
      });
      await lifecycle.activate(identity.pair);
    } else if (stored.status === "found" && stored.record.state === "bootstrap-complete") {
      await lifecycle.completeCore(identity.pair, {
        precacheSetSha256: identity.precacheSetSha256,
        resourcePlanSha256: identity.resourcePlanSha256,
        receiptSha256: identity.receiptSha256,
      });
      await lifecycle.activate(identity.pair);
    } else if (stored.status === "found" && stored.record.state === "core-complete") {
      await lifecycle.activate(identity.pair);
    }
    stored = await lifecycle.read(identity.pair);
    if (stored.status !== "found" || stored.record.state !== "active" ||
        stored.record.acceptedIdentity.precacheSetSha256 !== identity.precacheSetSha256 ||
        stored.record.acceptedIdentity.resourcePlanSha256 !== identity.resourcePlanSha256 ||
        stored.record.acceptedIdentity.receiptSha256 !== identity.receiptSha256) {
      throw new Error("Active pair lifecycle does not match exact admitted resource authority.");
    }
    return identity;
  };
  const ports: StaticUpdateCoordinatorPorts = {
    readControllerBoot: readBoot,
    inspectWaitingCandidate: async (pair) => {
      const registration = await navigator.serviceWorker.getRegistration("/");
      if (!registration?.waiting) return Object.freeze({ status: "incomplete", reason: "No waiting static worker is installed." });
      discovered = await workerIdentity(registration.waiting);
      if (discovered.pair.appBuildId !== pair.appBuildId || discovered.pair.dataReleaseId !== pair.dataReleaseId) {
        return Object.freeze({ status: "mixed", reason: "Waiting worker pair does not match the requested candidate." });
      }
      return Object.freeze({ status: "sealed", candidate: Object.freeze({
        contractVersion: 1, pair, precacheSetSha256: discovered.precacheSetSha256,
      }) });
    },
    issueConfirmationToken: () => crypto.randomUUID(),
    recordPendingTransitionIntent: async (intent, permit) => withLock(permit, () => {
      if (readDurable()) throw new Error("A durable update intent already exists.");
      writeDurable(Object.freeze({ intent, state: "pending" }));
    }),
    armTransitionIntent: async (intent, permit) => withLock(permit, () => {
      const current = readDurable();
      if (!current) return "missing" as const;
      if (current.state !== "pending" || !exactIntent(current.intent, intent)) return "mismatch" as const;
      writeDurable(Object.freeze({ intent, state: "armed" })); return "armed" as const;
    }),
    discardPendingTransitionIntent: async (intent, permit) => withLock(permit, () => {
      const current = readDurable();
      if (current?.state === "pending" && exactIntent(current.intent, intent)) localStorage.removeItem(INTENT_KEY);
    }),
    tombstoneTransitionIntent: async (intent, permit) => withLock(permit, () => {
      const current = readDurable();
      if (!current) return "missing" as const;
      if (!exactIntent(current.intent, intent)) return "mismatch" as const;
      writeDurable(Object.freeze({ intent, state: "tombstoned" })); return "tombstoned" as const;
    }),
    consumeTransitionIntent: async (intent, boot, permit) => withLock(permit, () => {
      const current = readDurable();
      if (!current) return "missing" as const;
      if (current.state === "consumed") return "already-consumed" as const;
      if (current.state !== "armed" || !exactIntent(current.intent, intent) ||
          boot.controller.pair.appBuildId !== intent.candidate.pair.appBuildId ||
          boot.controller.pair.dataReleaseId !== intent.candidate.pair.dataReleaseId ||
          boot.controller.precacheSetSha256 !== intent.candidate.precacheSetSha256) return "not-armed" as const;
      writeDurable(Object.freeze({ intent, state: "consumed" })); return "consumed" as const;
    }),
  };
  const coordinator = new StaticHostUpdateCoordinator(ports);
  const adapter = new StaticUpdateCapabilityCoordinator(coordinator, {
    candidate: async () => {
      const registration = await navigator.serviceWorker.getRegistration("/");
      if (!registration?.waiting) return null;
      discovered = await workerIdentity(registration.waiting);
      return discovered.pair;
    },
  });
  let reconciled = false;
  let reconciliationFailure = "";
  const reconcileFreshBoot = async (): Promise<void> => {
    if (reconciled || !router.current()) return;
    const boot = await readBoot();
    if (!coordinator.state()) await coordinator.initialize();
    const durable = readDurable();
    if (durable?.state === "armed") {
      const exact = boot.controller.pair.appBuildId === durable.intent.candidate.pair.appBuildId &&
        boot.controller.pair.dataReleaseId === durable.intent.candidate.pair.dataReleaseId &&
        boot.controller.precacheSetSha256 === durable.intent.candidate.precacheSetSha256;
      if (exact) await coordinator.verifyNextBoot(durable.intent);
      else {
        await navigator.locks.request(INTENT_KEY, { mode: "exclusive" }, () => {
          const current = readDurable();
          if (current?.state === "armed" && exactIntent(current.intent, durable.intent)) {
            writeDurable(Object.freeze({ intent: durable.intent, state: "tombstoned" }));
          }
        });
        reconciliationFailure = "Armed update intent does not match the exact fresh-boot controller authority.";
      }
    }
    reconciled = true;
  };
  return Object.freeze({
    inspect: async (): Promise<UpdateCapabilityV1> => {
      await reconcileFreshBoot();
      if (reconciliationFailure) return Object.freeze({ state: "failed", reason: reconciliationFailure });
      return adapter.inspect();
    },
    requestAction: async (capability: RuntimeCapabilityV2): Promise<void> => {
      await reconcileFreshBoot();
      return adapter.requestAction(capability);
    },
  });
}
