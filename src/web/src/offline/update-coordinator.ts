import { validateAppReleasePair, type AppReleasePairV1 } from "./contracts/keys";
import { sha256Hex } from "./contracts/v1";

const OPAQUE_ID = /^[A-Za-z0-9._-]{1,128}$/u;
const PROVIDER_TOKEN = /^[A-Za-z0-9._-]{1,96}$/u;
const BOOT_ID = /^[A-Za-z0-9._-]{1,64}$/u;
const INSTANCE_ID = /^[A-Za-z0-9_-]{16,32}$/u;
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

export type IntentConsumptionResultV1 = "consumed" | "missing" | "already-consumed";

export interface StaticUpdateCoordinatorPorts {
  readControllerBoot(): Promise<ControllerBootProofV1>;
  inspectWaitingCandidate(pair: AppReleasePairV1): Promise<WaitingCandidateInspectionV1>;
  issueConfirmationToken(request: Readonly<{
    coordinatorGeneration: number;
    boot: ControllerBootProofV1;
    candidate: AcceptedPairIdentityV1;
  }>): string;
  /** Return a collision-resistant identifier minted once for this coordinator instance. */
  issueCoordinatorInstanceId(): string;
  /** Persist only the latest unconsumed intent for this exact source boot. */
  recordTransitionIntent(intent: CloseAndReopenIntentV1): Promise<void>;
  /** Conditionally remove only this exact intent; never remove a newer intent. */
  revokeTransitionIntent(intent: CloseAndReopenIntentV1): Promise<void>;
  /** Consume the intent once; this record is not controller or rollback authority. */
  consumeTransitionIntent(
    intent: CloseAndReopenIntentV1,
    boot: ControllerBootProofV1,
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
    phase: "failed";
    operation: "prepare-update" | "confirm-update" | "verify-next-boot";
    code: StaticUpdateFailureCodeV1;
    message: string;
    boot: ControllerBootProofV1;
    currentUsable: true;
  }>;

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

  constructor(ports: StaticUpdateCoordinatorPorts) {
    this.#ports = ports;
    this.#instanceId = opaque(
      ports.issueCoordinatorInstanceId(),
      "coordinator instance id",
      INSTANCE_ID,
    );
  }

  state(): StaticUpdateCoordinatorStateV1 | null { return this.#state; }

  async initialize(): Promise<StaticUpdateCoordinatorStateV1> {
    const boot = await this.#readAndPinLaunchBoot();
    if (!this.#isLaunchBoot(boot)) throw new Error("Controller authority changed within one page boot.");
    return this.#set(Object.freeze({ phase: "current", boot, currentUsable: true }));
  }

  async prepareUpdate(pairInput: AppReleasePairV1): Promise<StaticUpdateCoordinatorStateV1> {
    if (this.#state?.phase === "recording-close-and-reopen-intent") return this.#state;
    const fallback = this.#bootFromState();
    const operation = ++this.#sequence;
    this.#pendingGeneration = null;
    if (fallback) this.#state = Object.freeze({ phase: "preparing", boot: fallback, currentUsable: true });

    let boot: ControllerBootProofV1;
    try { boot = await this.#readAndPinLaunchBoot(); }
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
    try { current = await this.#readAndPinLaunchBoot(); }
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
    const pending = this.#state;
    if (!pending || pending.phase !== "waiting-candidate-verified") return this.#currentOr(null);
    const pendingGeneration = this.#pendingGeneration;
    let token: string;
    try { token = opaque(tokenInput, "confirmation token"); }
    catch {
      return this.#set(failed("confirm-update", "confirmation-rejected", pending.boot, "Confirmation token is invalid."));
    }
    if (pendingGeneration === null || pendingGeneration !== this.#sequence || token !== pending.confirmationToken) {
      return this.#set(failed("confirm-update", "confirmation-rejected", pending.boot, "Confirmation token does not authorize this waiting candidate."));
    }

    this.#pendingGeneration = null;
    const operation = ++this.#sequence;
    this.#state = Object.freeze({
      phase: "recording-close-and-reopen-intent", boot: pending.boot,
      candidate: pending.candidate, currentUsable: true,
    });
    const intent = validateCloseAndReopenIntent({
      contractVersion: 1,
      transitionId: `${pending.boot.bootId}.${this.#instanceId}.g${pendingGeneration}`,
      confirmationGeneration: pendingGeneration,
      sourceBootId: pending.boot.bootId,
      sourceController: pending.boot.controller,
      candidate: pending.candidate,
      message: UPDATE_READY_MESSAGE,
    });
    try {
      await this.#ports.recordTransitionIntent(intent);
      if (operation !== this.#sequence) {
        try { await this.#ports.revokeTransitionIntent(intent); }
        catch (error) {
          return this.#set(failed(
            "confirm-update", "intent-record-failed", pending.boot,
            boundedMessage(error, "Cancelled transition intent could not be revoked."),
          ));
        }
        return this.#currentOr(pending.boot);
      }
      return this.#set(Object.freeze({
        phase: "close-and-reopen-required", boot: pending.boot, intent,
        message: UPDATE_READY_MESSAGE, currentUsable: true,
      }));
    } catch (error) {
      try { await this.#ports.revokeTransitionIntent(intent); }
      catch (revokeError) {
        return this.#set(failed(
          "confirm-update", "intent-record-failed", pending.boot,
          boundedMessage(revokeError, "Failed transition intent could not be revoked."),
        ));
      }
      return this.#set(failed(
        "confirm-update", "intent-record-failed", pending.boot,
        boundedMessage(error, "Close-and-reopen intent could not be recorded."),
      ));
    }
  }

  async verifyNextBoot(intentInput: CloseAndReopenIntentV1): Promise<StaticUpdateCoordinatorStateV1> {
    const operation = ++this.#sequence;
    this.#pendingGeneration = null;
    const fallback = this.#bootFromState();
    let boot: ControllerBootProofV1;
    try { boot = await this.#readAndPinLaunchBoot(); }
    catch (error) {
      if (!fallback) throw error;
      return this.#set(failed("verify-next-boot", "preparation-failed", fallback, boundedMessage(error, "Controller proof is unavailable.")));
    }
    if (operation !== this.#sequence) return this.#currentOr(boot);
    let intent: CloseAndReopenIntentV1;
    try { intent = validateCloseAndReopenIntent(intentInput); }
    catch (error) {
      return this.#set(failed("verify-next-boot", "intent-stale", boot, boundedMessage(error, "Transition intent is invalid.")));
    }
    if (
      !this.#isLaunchBoot(boot) ||
      this.#launchBoot?.bootId === intent.sourceBootId ||
      boot.bootId === intent.sourceBootId ||
      !sameIdentity(boot.controller, intent.candidate)
    ) {
      return this.#set(failed(
        "verify-next-boot", "controller-mismatch", boot,
        "Fresh boot is not controlled by the exact confirmed app/release candidate.",
      ));
    }
    try {
      const consumed = await this.#ports.consumeTransitionIntent(intent, boot);
      if (operation !== this.#sequence) return this.#currentOr(boot);
      if (consumed !== "consumed") {
        return this.#set(failed("verify-next-boot", "intent-stale", boot, "Transition intent is missing or was already consumed."));
      }
      return this.#set(Object.freeze({
        phase: "controller-verified-activation", boot, intent, currentUsable: true,
      }));
    } catch (error) {
      return this.#set(failed(
        "verify-next-boot", "intent-stale", boot,
        boundedMessage(error, "Transition intent could not be consumed."),
      ));
    }
  }

  async requestRollback(): Promise<StaticUpdateCoordinatorStateV1> {
    ++this.#sequence;
    this.#pendingGeneration = null;
    const boot = this.#bootFromState() ?? validateControllerBootProof(await this.#ports.readControllerBoot());
    return this.#set(Object.freeze({
      phase: "deployment-required", operation: "rollback", boot,
      code: "rollback-unavailable", message: ROLLBACK_MESSAGE, currentUsable: true,
    }));
  }

  async #preparationFailure(
    operation: number,
    fallback: ControllerBootProofV1 | null,
    error: unknown,
    defaultMessage: string,
  ): Promise<StaticUpdateCoordinatorStateV1> {
    const boot = await this.#safeBoot(fallback);
    if (operation !== this.#sequence) return this.#currentOr(boot);
    return this.#set(failed("prepare-update", "preparation-failed", boot, boundedMessage(error, defaultMessage)));
  }

  async #safeBoot(fallback: ControllerBootProofV1 | null): Promise<ControllerBootProofV1> {
    try { return await this.#readAndPinLaunchBoot(); }
    catch (error) {
      if (fallback) return fallback;
      throw error;
    }
  }

  #bootFromState(): ControllerBootProofV1 | null {
    return this.#state && "boot" in this.#state ? this.#state.boot : null;
  }

  async #readAndPinLaunchBoot(): Promise<ControllerBootProofV1> {
    const boot = validateControllerBootProof(await this.#ports.readControllerBoot());
    this.#launchBoot ??= boot;
    return boot;
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
