import { validateAppReleasePair, type AppReleasePairV1 } from "./contracts/keys";
import {
  OFFLINE_WORKER_PROTOCOL,
  validateOfflineWorkerToClientMessage,
  validateWorkerLeaseChallenge,
  type ClientLeaseV1,
  type WorkerClientObservationV1,
} from "./contracts/policy";
import type { ClientLeaseIdentityV1, ClientLeaseStorePort } from "./client-lease-controller";

export const WORKER_AUTHORITY_TIMEOUT_MS = 10_000;

export interface ClientCensusPort {
  observe(pair: AppReleasePairV1, signal: AbortSignal): Promise<readonly WorkerClientObservationV1[]>;
}

interface WorkerPort {
  postMessage(message: unknown, transfer: Transferable[]): void;
}

interface WorkerMessageEventLike {
  readonly data: unknown;
  readonly source: unknown;
  readonly ports: readonly MessagePort[];
}

interface WorkerContainerPort {
  addEventListener(type: "message", listener: (event: WorkerMessageEventLike) => void): void;
}

export interface WorkerClientAuthority extends ClientLeaseStorePort, ClientCensusPort {
  attachObservation(provider: () => Readonly<
    { state: "inactive" } | { state: "active"; pair: AppReleasePairV1; leaseId: string }
  >): void;
}

function samePair(left: AppReleasePairV1, right: AppReleasePairV1): boolean {
  return left.appBuildId === right.appBuildId && left.dataReleaseId === right.dataReleaseId;
}

function exactIdentity(identity: ClientLeaseIdentityV1): ClientLeaseIdentityV1 {
  const pair = validateAppReleasePair(identity.pair);
  if (!/^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/u.test(identity.leaseId)) {
    throw new TypeError("Client lease identity is invalid.");
  }
  return Object.freeze({ pair, leaseId: identity.leaseId });
}

export function createWorkerClientAuthority(
  worker: WorkerPort,
  container: WorkerContainerPort,
  options: Readonly<{
    randomUUID?: () => string;
    setTimer?: (callback: () => void, milliseconds: number) => number;
    clearTimer?: (id: number) => void;
    createChannel?: () => MessageChannel;
  }> = {},
): WorkerClientAuthority {
  const randomUUID = options.randomUUID ?? (() => crypto.randomUUID());
  const setTimer = options.setTimer ?? ((callback, milliseconds) => globalThis.setTimeout(callback, milliseconds) as unknown as number);
  const clearTimer = options.clearTimer ?? ((id) => globalThis.clearTimeout(id));
  const createChannel = options.createChannel ?? (() => new MessageChannel());
  let observation: () => Readonly<
    { state: "inactive" } | { state: "active"; pair: AppReleasePairV1; leaseId: string }
  > = () => Object.freeze({ state: "inactive" });

  const request = <T>(message: Readonly<Record<string, unknown>>, signal?: AbortSignal): Promise<T> => {
    if (signal?.aborted) return Promise.reject(new DOMException("Worker authority request was aborted.", "AbortError"));
    const channel = createChannel();
    return new Promise<T>((resolve, reject) => {
      let settled = false;
      const finish = (operation: () => void): void => {
        if (settled) return;
        settled = true;
        if (signal) signal.removeEventListener("abort", abort);
        clearTimer(timeout);
        channel.port1.close();
        operation();
      };
      const abort = () => finish(() => reject(new DOMException("Worker authority request was aborted.", "AbortError")));
      const timeout = setTimer(
        () => finish(() => reject(new TypeError("The verified service worker did not answer the authority request."))),
        WORKER_AUTHORITY_TIMEOUT_MS,
      );
      signal?.addEventListener("abort", abort, { once: true });
      channel.port1.onmessage = ({ data }) => finish(() => {
        try { resolve(validateOfflineWorkerToClientMessage(data) as T); }
        catch (error) { reject(error); }
      });
      try { worker.postMessage(message, [channel.port2]); }
      catch (error) { finish(() => reject(error)); }
    });
  };

  const leaseRequest = async (
    type: "acquire-lease" | "heartbeat-lease",
    input: ClientLeaseIdentityV1,
  ): Promise<ClientLeaseV1> => {
    const identity = exactIdentity(input);
    const messageToken = `lease-${randomUUID()}`;
    const response = await request<ReturnType<typeof validateOfflineWorkerToClientMessage>>({
      protocol: OFFLINE_WORKER_PROTOCOL, type, messageToken,
      leaseId: identity.leaseId, pair: identity.pair,
    });
    if (response.messageToken !== messageToken) throw new TypeError("Worker lease response token disagrees.");
    if (response.type === "lease-refused") throw new TypeError(`Worker lease request was refused: ${response.reason}.`);
    if (response.type !== "lease-state" || response.lease.leaseId !== identity.leaseId ||
        !samePair(response.lease.pair, identity.pair)) throw new TypeError("Worker lease response authority disagrees.");
    return response.lease;
  };

  container.addEventListener("message", (event) => {
    if (event.source !== worker || event.ports.length !== 1) return;
    let challenge;
    try { challenge = validateWorkerLeaseChallenge(event.data); }
    catch { return; }
    let snapshot: ReturnType<typeof observation>;
    try { snapshot = observation(); }
    catch { snapshot = Object.freeze({ state: "inactive" as const }); }
    event.ports[0]!.postMessage(snapshot.state === "active" ? {
      protocol: OFFLINE_WORKER_PROTOCOL,
      type: "lease-challenge-response",
      messageToken: challenge.messageToken,
      state: "active",
      pair: snapshot.pair,
      leaseId: snapshot.leaseId,
    } : {
      protocol: OFFLINE_WORKER_PROTOCOL,
      type: "lease-challenge-response",
      messageToken: challenge.messageToken,
      state: "inactive",
    });
  });

  const authority: WorkerClientAuthority = {
    activateClientLease: (identity: ClientLeaseIdentityV1) => leaseRequest("acquire-lease", identity),
    acquireLease: (identity: ClientLeaseIdentityV1) => leaseRequest("heartbeat-lease", identity),
    releaseLease: async (input: ClientLeaseIdentityV1) => {
      const identity = exactIdentity(input);
      const messageToken = `lease-${randomUUID()}`;
      const response = await request<ReturnType<typeof validateOfflineWorkerToClientMessage>>({
        protocol: OFFLINE_WORKER_PROTOCOL,
        type: "release-lease",
        messageToken,
        leaseId: identity.leaseId,
        pair: identity.pair,
      });
      if (response.messageToken !== messageToken) throw new TypeError("Worker lease release token disagrees.");
      if (response.type === "lease-refused") throw new TypeError(`Worker lease release was refused: ${response.reason}.`);
      if (response.type !== "lease-released" || response.leaseId !== identity.leaseId ||
          !samePair(response.pair, identity.pair)) throw new TypeError("Worker lease release authority disagrees.");
    },
    observe: async (pairInput: AppReleasePairV1, signal: AbortSignal) => {
      const targetPair = validateAppReleasePair(pairInput);
      const messageToken = `census-${randomUUID()}`;
      const response = await request<ReturnType<typeof validateOfflineWorkerToClientMessage>>({
        protocol: OFFLINE_WORKER_PROTOCOL,
        type: "request-client-census",
        messageToken,
        targetPair,
      }, signal);
      if (response.messageToken !== messageToken) throw new TypeError("Worker census response token disagrees.");
      if (response.type === "census-refused") throw new TypeError(`Worker client census was refused: ${response.reason}.`);
      if (response.type !== "client-census" || !samePair(response.targetPair, targetPair)) {
        throw new TypeError("Worker census authority disagrees.");
      }
      return response.observations;
    },
    attachObservation: (provider: () => Readonly<
      { state: "inactive" } | { state: "active"; pair: AppReleasePairV1; leaseId: string }
    >) => { observation = provider; },
  };
  return Object.freeze(authority);
}
