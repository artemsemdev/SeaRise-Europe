import { validateAppReleasePair, type AppReleasePairV1 } from "./contracts/keys";
import { sha256Hex } from "./contracts/v1";

const OPAQUE_ID = /^[A-Za-z0-9._-]{1,128}$/u;
const PROVIDER_TOKEN = /^[A-Za-z0-9._-]{1,96}$/u;
const BOOT_ID = /^[A-Za-z0-9._-]{1,64}$/u;
const INSTANCE_ID = /^[A-Za-z0-9_-]{16,40}$/u;
const UPDATE_READY_MESSAGE = "Update ready. Close all SeaRise tabs and reopen to use it." as const;
const ROLLBACK_MESSAGE = "Application rollback requires a verified static deployment or Git-history restoration." as const;

export interface AcceptedPairIdentityV1 {
  readonly contractVersion: 1;
  readonly pair: AppReleasePairV1;
  readonly precacheSetSha256: string;
  readonly resourcePlanSha256: string;
  readonly receiptSha256: string;
}

export interface ControllerBootProofV1 {
  readonly contractVersion: 1;
  readonly bootId: string;
  readonly controller: AcceptedPairIdentityV1;
}

export type WaitingCandidateInspectionV1 =
  | Readonly<{ status: "sealed"; candidate: AcceptedPairIdentityV1 }>
  | Readonly<{ status: "incomplete" | "corrupt" | "mixed" | "stale"; reason: string }>;

export interface CloseAndReopenIntentV1 {
  readonly contractVersion: 1;
  readonly transitionId: string;
  readonly confirmationGeneration: number;
  readonly sourceBootId: string;
  readonly sourceController: AcceptedPairIdentityV1;
  readonly candidate: AcceptedPairIdentityV1;
  readonly message: typeof UPDATE_READY_MESSAGE;
}

export type IntentConsumptionResultV1 = "consumed" | "missing" | "already-consumed" | "not-armed";
export type IntentArmResultV1 = "armed" | "missing" | "mismatch";
export type IntentTombstoneResultV1 = "tombstoned" | "missing" | "mismatch";

export interface DurablePortPermitV1 {
  readonly coordinatorGeneration: number;
  readonly deadlineMs: number;
  /** A durable adapter must abort its transaction and settle when this signal is aborted. */
  readonly signal: AbortSignal;
}

/** Durable methods are non-reentrant and must settle promptly after permit abort. */
export interface StaticUpdateCoordinatorPorts {
  readControllerBoot(): Promise<ControllerBootProofV1>;
  inspectWaitingCandidate(pair: AppReleasePairV1): Promise<WaitingCandidateInspectionV1>;
  issueConfirmationToken(request: Readonly<{
    coordinatorGeneration: number;
    boot: ControllerBootProofV1;
    candidate: AcceptedPairIdentityV1;
  }>): string;
  /** Persist a non-consumable PENDING intent for this exact source boot. */
  recordPendingTransitionIntent(intent: CloseAndReopenIntentV1, permit: DurablePortPermitV1): Promise<void>;
  /**
   * Atomically change this exact PENDING intent to ARMED. The durable transaction
   * must observe and remain bound to the permit signal until commit. Rejection,
   * abort, `missing`, or `mismatch` must guarantee that no ARMED write committed.
   */
  armTransitionIntent(intent: CloseAndReopenIntentV1, permit: DurablePortPermitV1): Promise<IntentArmResultV1>;
  /** Conditionally remove only this exact PENDING intent; never remove a newer or ARMED intent. */
  discardPendingTransitionIntent(intent: CloseAndReopenIntentV1, permit: DurablePortPermitV1): Promise<void>;
  /** Atomically tombstone this exact PENDING or ARMED intent. Tombstoned IDs can never arm or consume. */
  tombstoneTransitionIntent(intent: CloseAndReopenIntentV1, permit: DurablePortPermitV1): Promise<IntentTombstoneResultV1>;
  /** Atomically consume only the exact ARMED intent once. */
  consumeTransitionIntent(
    intent: CloseAndReopenIntentV1,
    boot: ControllerBootProofV1,
    permit: DurablePortPermitV1,
  ): Promise<IntentConsumptionResultV1>;
}

export type StaticUpdateFailureCodeV1 =
  | "candidate-incomplete"
  | "candidate-corrupt"
  | "candidate-mixed"
  | "candidate-stale"
  | "confirmation-rejected"
  | "controller-mismatch"
  | "intent-stale"
  | "preparation-failed"
  | "intent-record-failed";

export type StaticUpdateCoordinatorStateV1 =
  | Readonly<{ phase: "current"; boot: ControllerBootProofV1; currentUsable: true }>
  | Readonly<{ phase: "preparing"; boot: ControllerBootProofV1; currentUsable: true }>
  | Readonly<{
    phase: "waiting-candidate-verified";
    boot: ControllerBootProofV1;
    candidate: AcceptedPairIdentityV1;
    confirmationToken: string;
    currentUsable: true;
  }>
  | Readonly<{
    phase: "mutation-busy";
    operation: "initialize" | "prepare-update" | "confirm-update" | "verify-next-boot" | "rollback";
    boot: ControllerBootProofV1;
    code: "durable-mutation-busy";
    message: string;
    retryable: true;
    currentUsable: true;
  }>
  | Readonly<{
    phase: "adapter-stalled";
    operation: "confirm-update" | "verify-next-boot" | "rollback";
    boot: ControllerBootProofV1;
    code: "durable-adapter-stalled";
    message: string;
    retryable: false;
    currentUsable: true;
  }>
  | Readonly<{
    phase: "recording-close-and-reopen-intent";
    boot: ControllerBootProofV1;
    candidate: AcceptedPairIdentityV1;
    currentUsable: true;
  }>
  | Readonly<{
    phase: "close-and-reopen-required";
    boot: ControllerBootProofV1;
    intent: CloseAndReopenIntentV1;
    message: typeof UPDATE_READY_MESSAGE;
    currentUsable: true;
  }>
  | Readonly<{
    phase: "controller-verified-activation";
    boot: ControllerBootProofV1;
    intent: CloseAndReopenIntentV1;
    currentUsable: true;
  }>
  | Readonly<{
    phase: "deployment-required";
    operation: "rollback";
    boot: ControllerBootProofV1;
    code: "rollback-unavailable";
    message: typeof ROLLBACK_MESSAGE;
    currentUsable: true;
  }>
  | Readonly<{
    phase: "rollback-failed";
    operation: "rollback";
    boot: ControllerBootProofV1;
    code: "intent-tombstone-failed";
    intent: CloseAndReopenIntentV1;
    durableIntentState: "pending" | "armed";
    message: string;
    currentUsable: true;
  }>
  | Readonly<{
    phase: "failed";
    operation: "prepare-update" | "confirm-update" | "verify-next-boot";
    code: StaticUpdateFailureCodeV1;
    message: string;
    boot: ControllerBootProofV1;
    currentUsable: true;
  }>;

export interface StaticUpdateCoordinatorOptions {
  /** Deterministic test seam. Production callers must use the secure default. */
  readonly instanceId?: string;
  /** Bounded durable adapter deadline. Production default is 5 seconds. */
  readonly durablePortTimeoutMs?: number;
}

const claimedCoordinatorInstanceIds = new Set<string>();

function samePair(left: AppReleasePairV1, right: AppReleasePairV1): boolean {
  return left.appBuildId === right.appBuildId && left.dataReleaseId === right.dataReleaseId;
}

function sameIdentity(left: AcceptedPairIdentityV1, right: AcceptedPairIdentityV1): boolean {
  return samePair(left.pair, right.pair) &&
    left.precacheSetSha256 === right.precacheSetSha256 &&
    left.resourcePlanSha256 === right.resourcePlanSha256 &&
    left.receiptSha256 === right.receiptSha256;
}

function opaque(value: unknown, name: string, pattern = OPAQUE_ID): string {
  if (typeof value !== "string" || !pattern.test(value)) throw new TypeError(`${name} is invalid.`);
  return value;
}

function boundedMessage(value: unknown, fallback: string): string {
  if (value instanceof Error && value.message) return value.message.slice(0, 512);
  if (typeof value === "string" && value) return value.slice(0, 512);
  return fallback;
}

function generation(value: unknown): number {
  if (!Number.isSafeInteger(value) || (value as number) <= 0) {
    throw new TypeError("Confirmation generation is invalid.");
  }
  return value as number;
}

function secureCoordinatorInstanceId(): string {
  const cryptoProvider = globalThis.crypto;
  if (!cryptoProvider) throw new Error("Secure coordinator entropy is unavailable.");
  if (typeof cryptoProvider.randomUUID === "function") return cryptoProvider.randomUUID();
  const bytes = cryptoProvider.getRandomValues(new Uint8Array(16));
  return Array.from(bytes, (value) => value.toString(16).padStart(2, "0")).join("");
}

function claimCoordinatorInstanceId(value: unknown): string {
  const instanceId = opaque(value, "coordinator instance id", INSTANCE_ID);
  if (claimedCoordinatorInstanceIds.has(instanceId)) {
    throw new Error("Coordinator instance id is already active in this JavaScript realm.");
  }
  claimedCoordinatorInstanceIds.add(instanceId);
  return instanceId;
}

export function validateAcceptedPairIdentity(value: AcceptedPairIdentityV1): AcceptedPairIdentityV1 {
  if (!value || typeof value !== "object" || value.contractVersion !== 1) {
    throw new TypeError("Accepted pair identity is invalid.");
  }
  return Object.freeze({
    contractVersion: 1,
    pair: validateAppReleasePair(value.pair),
    precacheSetSha256: sha256Hex(value.precacheSetSha256, "precacheSetSha256"),
    resourcePlanSha256: sha256Hex(value.resourcePlanSha256, "resourcePlanSha256"),
    receiptSha256: sha256Hex(value.receiptSha256, "receiptSha256"),
  });
}

export function validateControllerBootProof(value: ControllerBootProofV1): ControllerBootProofV1 {
  if (!value || typeof value !== "object" || value.contractVersion !== 1) {
    throw new TypeError("Controller boot proof is invalid.");
  }
  return Object.freeze({
    contractVersion: 1,
    bootId: opaque(value.bootId, "bootId", BOOT_ID),
    controller: validateAcceptedPairIdentity(value.controller),
  });
}

export function validateCloseAndReopenIntent(value: CloseAndReopenIntentV1): CloseAndReopenIntentV1 {
  if (!value || typeof value !== "object" || value.contractVersion !== 1 || value.message !== UPDATE_READY_MESSAGE) {
    throw new TypeError("Close-and-reopen transition intent is invalid.");
  }
  const confirmationGeneration = generation(value.confirmationGeneration);
  const sourceBootId = opaque(value.sourceBootId, "sourceBootId", BOOT_ID);
  const transitionId = opaque(value.transitionId, "transitionId");
  const transitionPrefix = `${sourceBootId}.`;
  const transitionSuffix = `.g${confirmationGeneration}`;
  if (!transitionId.startsWith(transitionPrefix) || !transitionId.endsWith(transitionSuffix)) {
    throw new TypeError("Transition identity does not match its source boot and generation.");
  }
  opaque(
    transitionId.slice(transitionPrefix.length, -transitionSuffix.length),
    "coordinator instance id",
    INSTANCE_ID,
  );
  const sourceController = validateAcceptedPairIdentity(value.sourceController);
  const candidate = validateAcceptedPairIdentity(value.candidate);
  if (sameIdentity(sourceController, candidate)) throw new TypeError("Transition candidate is already active.");
  return Object.freeze({
    contractVersion: 1,
    transitionId,
    confirmationGeneration,
    sourceBootId,
    sourceController,
    candidate,
    message: UPDATE_READY_MESSAGE,
  });
}

function validateInspection(
  value: WaitingCandidateInspectionV1,
  requested: AppReleasePairV1,
): WaitingCandidateInspectionV1 {
  if (!value || typeof value !== "object") throw new TypeError("Waiting-candidate inspection is invalid.");
  if (value.status === "sealed") {
    const candidate = validateAcceptedPairIdentity(value.candidate);
    if (!samePair(candidate.pair, requested)) throw new TypeError("Waiting candidate contains a mixed pair.");
    return Object.freeze({ status: "sealed", candidate });
  }
  if (!new Set(["incomplete", "corrupt", "mixed", "stale"]).has(value.status)) {
    throw new TypeError("Waiting-candidate status is unsupported.");
  }
  return Object.freeze({ status: value.status, reason: boundedMessage(value.reason, `Candidate is ${value.status}.`) });
}

function boundConfirmationToken(providerToken: unknown, value: number): string {
  const provider = opaque(providerToken, "provider confirmation token", PROVIDER_TOKEN);
  return opaque(`g${generation(value)}.${provider}`, "bound confirmation token");
}

function failed(
  operation: Extract<StaticUpdateCoordinatorStateV1, { phase: "failed" }>["operation"],
  code: StaticUpdateFailureCodeV1,
  boot: ControllerBootProofV1,
  message: string,
): StaticUpdateCoordinatorStateV1 {
  return Object.freeze({ phase: "failed", operation, code, message, boot, currentUsable: true });
}

/**
 * Coordinates user intent only. It cannot activate a worker, swap browser
 * storage authority, reload the page, or perform application rollback.
 */
export class StaticHostUpdateCoordinator {
  readonly #ports: StaticUpdateCoordinatorPorts;
  readonly #instanceId: string;
  #state: StaticUpdateCoordinatorStateV1 | null = null;
  #launchBoot: ControllerBootProofV1 | null = null;
  #sequence = 0;
  #pendingGeneration: number | null = null;
  #operationAbortController: AbortController | null = null;
  #durableIntent: Readonly<{ intent: CloseAndReopenIntentV1; state: "pending" | "armed" }> | null = null;
  #durableMutationActive = false;
  #adapterStalled = false;
  readonly #durablePortTimeoutMs: number;

  constructor(ports: StaticUpdateCoordinatorPorts, options: StaticUpdateCoordinatorOptions = {}) {
    this.#ports = ports;
    this.#instanceId = claimCoordinatorInstanceId(options.instanceId ?? secureCoordinatorInstanceId());
    const timeout = options.durablePortTimeoutMs ?? 5_000;
    if (!Number.isSafeInteger(timeout) || timeout < 10 || timeout > 60_000) {
      throw new TypeError("Durable port timeout is invalid.");
    }
    this.#durablePortTimeoutMs = timeout;
  }

  state(): StaticUpdateCoordinatorStateV1 | null { return this.#state; }

  async initialize(): Promise<StaticUpdateCoordinatorStateV1> {
    const blocked = this.#busyOrStalled("initialize");
    if (blocked) return blocked;
    if (this.#state?.phase === "recording-close-and-reopen-intent" || this.#durableIntent) {
      return this.#currentOr(null);
    }
    const operation = this.#beginOperation();
    let boot: ControllerBootProofV1;
    try { boot = await this.#readBootFor(operation); }
    catch (error) {
      if (!this.#isCurrentOperation(operation)) return this.#currentOr(null);
      throw error;
    }
    if (!this.#isCurrentOperation(operation)) return this.#currentOr(boot);
    if (!this.#isLaunchBoot(boot)) throw new Error("Controller authority changed within one page boot.");
    return this.#commit(operation, Object.freeze({ phase: "current", boot, currentUsable: true }), boot);
  }

  async prepareUpdate(pairInput: AppReleasePairV1): Promise<StaticUpdateCoordinatorStateV1> {
    const blocked = this.#busyOrStalled("prepare-update");
    if (blocked) return blocked;
    if (this.#state?.phase === "recording-close-and-reopen-intent" || this.#durableIntent) {
      return this.#currentOr(null);
    }
    const fallback = this.#bootFromState();
    const operation = this.#beginOperation();
    if (fallback) this.#state = Object.freeze({ phase: "preparing", boot: fallback, currentUsable: true });

    let boot: ControllerBootProofV1;
    try { boot = await this.#readBootFor(operation); }
    catch (error) {
      return await this.#preparationFailure(operation, fallback, error, "Controller authority could not be read.");
    }
    if (operation !== this.#sequence) return this.#currentOr(boot);

    let requested: AppReleasePairV1;
    try { requested = validateAppReleasePair(pairInput); }
    catch (error) {
      return this.#set(failed("prepare-update", "candidate-corrupt", boot, boundedMessage(error, "Candidate pair is invalid.")));
    }
    if (samePair(requested, boot.controller.pair)) {
      return this.#set(failed("prepare-update", "candidate-stale", boot, "Waiting candidate is already the controlling pair."));
    }

    let rawInspection: WaitingCandidateInspectionV1;
    try { rawInspection = await this.#ports.inspectWaitingCandidate(requested); }
    catch (error) {
      return await this.#preparationFailure(operation, boot, error, "Waiting-candidate inspection failed.");
    }
    if (operation !== this.#sequence) return this.#currentOr(boot);

    let inspection: WaitingCandidateInspectionV1;
    try { inspection = validateInspection(rawInspection, requested); }
    catch (error) {
      return this.#set(failed("prepare-update", "candidate-corrupt", boot, boundedMessage(error, "Candidate evidence is corrupt.")));
    }
    if (inspection.status !== "sealed") {
      return this.#set(failed("prepare-update", `candidate-${inspection.status}`, boot, inspection.reason));
    }

    let current: ControllerBootProofV1;
    try { current = await this.#readBootFor(operation); }
    catch (error) {
      return await this.#preparationFailure(operation, boot, error, "Controller authority could not be confirmed.");
    }
    if (operation !== this.#sequence) return this.#currentOr(boot);
    if (!this.#isLaunchBoot(current) || current.bootId !== boot.bootId || !sameIdentity(current.controller, boot.controller)) {
      return this.#set(failed("prepare-update", "preparation-failed", current, "Controller authority changed during candidate inspection."));
    }

    try {
      const confirmationToken = boundConfirmationToken(this.#ports.issueConfirmationToken({
        coordinatorGeneration: operation, boot, candidate: inspection.candidate,
      }), operation);
      this.#pendingGeneration = operation;
      return this.#set(Object.freeze({
        phase: "waiting-candidate-verified", boot, candidate: inspection.candidate,
        confirmationToken, currentUsable: true,
      }));
    } catch (error) {
      return await this.#preparationFailure(operation, boot, error, "Update confirmation could not be issued.");
    }
  }

  async confirmUpdate(tokenInput: string): Promise<StaticUpdateCoordinatorStateV1> {
    const blocked = this.#busyOrStalled("confirm-update");
    if (blocked) return blocked;
    const pending = this.#state;
    if (!pending || pending.phase !== "waiting-candidate-verified") return this.#currentOr(null);
    const pendingGeneration = this.#pendingGeneration;
    let token: string;
    try { token = opaque(tokenInput, "confirmation token"); }
    catch {
      const operation = this.#beginOperation();
      return this.#commit(
        operation,
        failed("confirm-update", "confirmation-rejected", pending.boot, "Confirmation token is invalid."),
        pending.boot,
      );
    }
    if (pendingGeneration === null || pendingGeneration !== this.#sequence || token !== pending.confirmationToken) {
      const operation = this.#beginOperation();
      return this.#commit(
        operation,
        failed("confirm-update", "confirmation-rejected", pending.boot, "Confirmation token does not authorize this waiting candidate."),
        pending.boot,
      );
    }

    const operation = this.#beginOperation();
    this.#commit(operation, Object.freeze({
      phase: "recording-close-and-reopen-intent", boot: pending.boot,
      candidate: pending.candidate, currentUsable: true,
    }), pending.boot);
    const intent = validateCloseAndReopenIntent({
      contractVersion: 1,
      transitionId: `${pending.boot.bootId}.${this.#instanceId}.g${pendingGeneration}`,
      confirmationGeneration: pendingGeneration,
      sourceBootId: pending.boot.bootId,
      sourceController: pending.boot.controller,
      candidate: pending.candidate,
      message: UPDATE_READY_MESSAGE,
    });
    return await this.#withDurableMutation(async () => {
      if (!this.#isCurrentOperation(operation)) return this.#currentOr(pending.boot);
      this.#durableIntent = Object.freeze({ intent, state: "pending" });
      try {
        await this.#callDurable(operation, "confirm-update", pending.boot, async (permit) =>
          await this.#ports.recordPendingTransitionIntent(intent, permit));
        if (!this.#isCurrentOperation(operation)) {
          try {
            await this.#callDurable(operation, "confirm-update", pending.boot, async (permit) =>
              await this.#ports.discardPendingTransitionIntent(intent, permit));
            if (this.#durableIntent?.intent.transitionId === intent.transitionId && this.#durableIntent.state === "pending") {
              this.#durableIntent = null;
            }
          } catch {
            // PENDING evidence is non-consumable; the superseding mutation decides its disposition.
          }
          return this.#currentOr(pending.boot);
        }
        const armed = await this.#callDurable(operation, "confirm-update", pending.boot, async (permit) =>
          await this.#ports.armTransitionIntent(intent, permit));
        if (armed === "armed") this.#durableIntent = Object.freeze({ intent, state: "armed" });
        if (!this.#isCurrentOperation(operation)) return this.#currentOr(pending.boot);
        if (armed !== "armed") {
          return this.#commit(operation, failed(
            "confirm-update", "intent-record-failed", pending.boot,
            "Pending transition intent could not be armed exactly once.",
          ), pending.boot);
        }
        return this.#commit(operation, Object.freeze({
          phase: "close-and-reopen-required", boot: pending.boot, intent,
          message: UPDATE_READY_MESSAGE, currentUsable: true,
        }), pending.boot);
      } catch (error) {
        try {
          await this.#callDurable(operation, "confirm-update", pending.boot, async (permit) =>
            await this.#ports.discardPendingTransitionIntent(intent, permit));
          if (this.#durableIntent?.intent.transitionId === intent.transitionId && this.#durableIntent.state === "pending") {
            this.#durableIntent = null;
          }
        } catch (discardError) {
          if (!this.#isCurrentOperation(operation)) return this.#currentOr(pending.boot);
          return this.#commit(operation, failed(
            "confirm-update", "intent-record-failed", pending.boot,
            boundedMessage(discardError, "Failed pending transition intent could not be discarded."),
          ), pending.boot);
        }
        if (!this.#isCurrentOperation(operation)) return this.#currentOr(pending.boot);
        return this.#commit(operation, failed(
          "confirm-update", "intent-record-failed", pending.boot,
          boundedMessage(error, "Close-and-reopen intent could not be recorded."),
        ), pending.boot);
      }
    });
  }

  async verifyNextBoot(intentInput: CloseAndReopenIntentV1): Promise<StaticUpdateCoordinatorStateV1> {
    const blocked = this.#busyOrStalled("verify-next-boot");
    if (blocked) return blocked;
    if (this.#state?.phase === "recording-close-and-reopen-intent") {
      return this.#currentOr(null);
    }
    const operation = this.#beginOperation();
    const fallback = this.#bootFromState();
    let boot: ControllerBootProofV1;
    try { boot = await this.#readBootFor(operation); }
    catch (error) {
      if (!this.#isCurrentOperation(operation)) return this.#currentOr(fallback);
      if (!fallback) throw error;
      return this.#commit(
        operation,
        failed("verify-next-boot", "preparation-failed", fallback, boundedMessage(error, "Controller proof is unavailable.")),
        fallback,
      );
    }
    if (operation !== this.#sequence) return this.#currentOr(boot);
    let intent: CloseAndReopenIntentV1;
    try { intent = validateCloseAndReopenIntent(intentInput); }
    catch (error) {
      return this.#commit(
        operation,
        failed("verify-next-boot", "intent-stale", boot, boundedMessage(error, "Transition intent is invalid.")),
        boot,
      );
    }
    if (
      !this.#isLaunchBoot(boot) ||
      this.#launchBoot?.bootId === intent.sourceBootId ||
      boot.bootId === intent.sourceBootId ||
      !sameIdentity(boot.controller, intent.candidate)
    ) {
      return this.#commit(operation, failed(
        "verify-next-boot", "controller-mismatch", boot,
        "Fresh boot is not controlled by the exact confirmed app/release candidate.",
      ), boot);
    }
    try {
      const consumed = await this.#withDurableMutation(async () =>
        await this.#callDurable(operation, "verify-next-boot", boot, async (permit) =>
          await this.#ports.consumeTransitionIntent(intent, boot, permit)));
      if (operation !== this.#sequence) return this.#currentOr(boot);
      if (consumed !== "consumed") {
        return this.#commit(
          operation,
          failed("verify-next-boot", "intent-stale", boot, "Transition intent is missing or was already consumed."),
          boot,
        );
      }
      return this.#commit(operation, Object.freeze({
        phase: "controller-verified-activation", boot, intent, currentUsable: true,
      }), boot);
    } catch (error) {
      if (!this.#isCurrentOperation(operation)) return this.#currentOr(boot);
      return this.#commit(operation, failed(
        "verify-next-boot", "intent-stale", boot,
        boundedMessage(error, "Transition intent could not be consumed."),
      ), boot);
    }
  }

  async requestRollback(): Promise<StaticUpdateCoordinatorStateV1> {
    const blocked = this.#busyOrStalled("rollback");
    if (blocked) return blocked;
    const operation = this.#beginOperation();
    const fallback = this.#bootFromState();
    let boot = fallback;
    if (!boot) {
      try { boot = await this.#readBootFor(operation); }
      catch (error) {
        if (!this.#isCurrentOperation(operation)) return this.#currentOr(null);
        throw error;
      }
      if (!this.#isCurrentOperation(operation)) return this.#currentOr(boot);
    }
    return await this.#withDurableMutation(async () => {
      if (!this.#isCurrentOperation(operation)) return this.#currentOr(boot);
      const durable = this.#durableIntent;
      if (durable) {
        let tombstoned: IntentTombstoneResultV1;
        try {
          tombstoned = await this.#callDurable(operation, "rollback", boot, async (permit) =>
            await this.#ports.tombstoneTransitionIntent(durable.intent, permit));
        }
        catch (error) {
          if (!this.#isCurrentOperation(operation)) return this.#currentOr(boot);
          return this.#set(Object.freeze({
            phase: "rollback-failed", operation: "rollback", boot,
            code: "intent-tombstone-failed", intent: durable.intent,
            durableIntentState: durable.state,
            message: boundedMessage(error, "Durable update intent could not be tombstoned."),
            currentUsable: true,
          }));
        }
        if (tombstoned !== "mismatch") this.#durableIntent = null;
        if (!this.#isCurrentOperation(operation)) return this.#currentOr(boot);
        if (tombstoned === "mismatch") {
          return this.#set(Object.freeze({
            phase: "rollback-failed", operation: "rollback", boot,
            code: "intent-tombstone-failed", intent: durable.intent,
            durableIntentState: durable.state,
            message: "Durable update intent did not match the rollback target.",
            currentUsable: true,
          }));
        }
      }
      return this.#commit(operation, Object.freeze({
        phase: "deployment-required", operation: "rollback", boot,
        code: "rollback-unavailable", message: ROLLBACK_MESSAGE, currentUsable: true,
      }), boot);
    });
  }

  async #preparationFailure(
    operation: number,
    fallback: ControllerBootProofV1 | null,
    error: unknown,
    defaultMessage: string,
  ): Promise<StaticUpdateCoordinatorStateV1> {
    const boot = await this.#safeBoot(operation, fallback);
    if (operation !== this.#sequence) return this.#currentOr(boot);
    return this.#set(failed("prepare-update", "preparation-failed", boot, boundedMessage(error, defaultMessage)));
  }

  async #safeBoot(operation: number, fallback: ControllerBootProofV1 | null): Promise<ControllerBootProofV1> {
    try { return await this.#readBootFor(operation); }
    catch (error) {
      if (fallback) return fallback;
      throw error;
    }
  }

  #bootFromState(): ControllerBootProofV1 | null {
    return this.#state && "boot" in this.#state ? this.#state.boot : null;
  }

  async #readBootFor(operation: number): Promise<ControllerBootProofV1> {
    const boot = validateControllerBootProof(await this.#ports.readControllerBoot());
    if (this.#isCurrentOperation(operation)) this.#launchBoot ??= boot;
    return boot;
  }

  #beginOperation(): number {
    this.#operationAbortController?.abort();
    this.#operationAbortController = new AbortController();
    this.#pendingGeneration = null;
    return ++this.#sequence;
  }

  #operationSignal(operation: number): AbortSignal {
    if (!this.#isCurrentOperation(operation) || !this.#operationAbortController) {
      throw new Error("Coordinator operation is no longer current.");
    }
    return this.#operationAbortController.signal;
  }

  async #withDurableMutation<T>(mutation: () => Promise<T>): Promise<T> {
    if (this.#durableMutationActive) throw new Error("Durable mutation is already active.");
    this.#durableMutationActive = true;
    try { return await mutation(); }
    finally { this.#durableMutationActive = false; }
  }

  async #callDurable<T>(
    operation: number,
    operationName: "confirm-update" | "verify-next-boot" | "rollback",
    boot: ControllerBootProofV1,
    call: (permit: DurablePortPermitV1) => Promise<T>,
  ): Promise<T> {
    const operationSignal = this.#operationSignal(operation);
    const controller = new AbortController();
    const abort = () => controller.abort();
    if (operationSignal.aborted) controller.abort();
    else operationSignal.addEventListener("abort", abort, { once: true });
    let deadlineExceeded = false;
    const timer = setTimeout(() => {
      deadlineExceeded = true;
      controller.abort();
      this.#adapterStalled = true;
      if (this.#isCurrentOperation(operation)) {
        this.#set(Object.freeze({
          phase: "adapter-stalled", operation: operationName, boot,
          code: "durable-adapter-stalled",
          message: "Durable adapter exceeded its deadline and has not acknowledged abort.",
          retryable: false, currentUsable: true,
        }));
      }
    }, this.#durablePortTimeoutMs);
    try {
      const result = await call({
        coordinatorGeneration: operation,
        deadlineMs: this.#durablePortTimeoutMs,
        signal: controller.signal,
      });
      if (deadlineExceeded) throw new Error("Durable adapter settled only after its deadline.");
      return result;
    } catch (error) {
      if (deadlineExceeded) throw new Error("Durable adapter acknowledged abort after its deadline.");
      throw error;
    } finally {
      clearTimeout(timer);
      operationSignal.removeEventListener("abort", abort);
      if (deadlineExceeded) this.#adapterStalled = false;
    }
  }

  #busyOrStalled(
    operation: "initialize" | "prepare-update" | "confirm-update" | "verify-next-boot" | "rollback",
  ): StaticUpdateCoordinatorStateV1 | null {
    if (!this.#durableMutationActive) return null;
    if (this.#adapterStalled && this.#state?.phase === "adapter-stalled") return this.#state;
    const boot = this.#bootFromState() ?? this.#launchBoot;
    if (!boot) throw new Error("Durable mutation is active without controller authority.");
    return Object.freeze({
      phase: "mutation-busy", operation, boot,
      code: "durable-mutation-busy",
      message: "A durable update operation is in progress. Retry after it settles.",
      retryable: true, currentUsable: true,
    });
  }

  #isCurrentOperation(operation: number): boolean {
    return operation === this.#sequence;
  }

  #commit<T extends StaticUpdateCoordinatorStateV1>(
    operation: number,
    state: T,
    fallback: ControllerBootProofV1,
  ): StaticUpdateCoordinatorStateV1 {
    if (!this.#isCurrentOperation(operation)) return this.#currentOr(fallback);
    return this.#set(state);
  }

  #isLaunchBoot(boot: ControllerBootProofV1): boolean {
    return this.#launchBoot !== null &&
      boot.bootId === this.#launchBoot.bootId &&
      sameIdentity(boot.controller, this.#launchBoot.controller);
  }

  #currentOr(fallback: ControllerBootProofV1 | null): StaticUpdateCoordinatorStateV1 {
    if (this.#state) return this.#state;
    if (!fallback) throw new Error("Static update coordinator is not initialized.");
    return Object.freeze({ phase: "current", boot: fallback, currentUsable: true });
  }

  #set<T extends StaticUpdateCoordinatorStateV1>(state: T): T {
    this.#state = state;
    if (state.phase !== "waiting-candidate-verified") this.#pendingGeneration = null;
    return state;
  }
}

export { ROLLBACK_MESSAGE, UPDATE_READY_MESSAGE };
