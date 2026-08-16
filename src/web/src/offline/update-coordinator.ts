import { validateAppReleasePair, type AppReleasePairV1 } from "./contracts/keys";
import { validateClientLease, type ClientLeaseV1 } from "./contracts/policy";
import { sha256Hex } from "./contracts/v1";

const TOKEN = /^[A-Za-z0-9._-]{1,128}$/u;
const PROVIDER_TOKEN = /^[A-Za-z0-9._-]{1,96}$/u;
const REVISION = /^[A-Za-z0-9._-]{1,128}$/u;

export interface AcceptedPairIdentityV1 {
  readonly contractVersion: 1;
  readonly pair: AppReleasePairV1;
  readonly precacheSetSha256: string;
  readonly resourcePlanSha256: string;
  readonly receiptSha256: string;
}

export interface PairAuthoritySnapshotV1 {
  readonly contractVersion: 1;
  readonly revision: string;
  readonly active: AcceptedPairIdentityV1;
  readonly previous: AcceptedPairIdentityV1 | null;
}

export type CandidateInspectionV1 =
  | Readonly<{ status: "sealed"; candidate: AcceptedPairIdentityV1 }>
  | Readonly<{ status: "incomplete" | "corrupt" | "mixed" | "stale"; reason: string }>;

export interface AtomicPairTransitionV1 {
  readonly contractVersion: 1;
  readonly before: PairAuthoritySnapshotV1;
  readonly after: PairAuthoritySnapshotV1;
}

export interface ConfirmedUpdateRequestV1 {
  readonly expected: PairAuthoritySnapshotV1;
  readonly candidate: AcceptedPairIdentityV1;
  readonly confirmationToken: string;
}

export interface ConfirmedRollbackRequestV1 {
  readonly expected: PairAuthoritySnapshotV1;
  readonly target: AcceptedPairIdentityV1;
  readonly confirmationToken: string;
}

export interface CleanupRetiredPairRequestV1 {
  readonly protectedSnapshot: PairAuthoritySnapshotV1;
  readonly pair: AppReleasePairV1;
}

export type CleanupFenceResultV1 =
  | Readonly<{ status: "removed" }>
  | Readonly<{ status: "blocked"; leases: readonly ClientLeaseV1[] }>;

export interface UpdateCoordinatorPorts {
  readSnapshot(): Promise<PairAuthoritySnapshotV1>;
  inspectCandidate(pair: AppReleasePairV1): Promise<CandidateInspectionV1>;
  issueConfirmationToken(request: Readonly<{
    action: "update" | "rollback";
    coordinatorGeneration: number;
    expected: PairAuthoritySnapshotV1;
    target: AcceptedPairIdentityV1;
  }>): string;
  activate(request: ConfirmedUpdateRequestV1): Promise<AtomicPairTransitionV1>;
  rollback(request: ConfirmedRollbackRequestV1): Promise<AtomicPairTransitionV1>;
  /** The adapter must test leases and delete under one shared cleanup fence. */
  cleanupRetiredPair(request: CleanupRetiredPairRequestV1): Promise<CleanupFenceResultV1>;
}

export type CleanupStateV1 =
  | Readonly<{ status: "removed"; pair: AppReleasePairV1 }>
  | Readonly<{ status: "blocked"; pair: AppReleasePairV1; leases: readonly ClientLeaseV1[] }>;

export type UpdateCoordinatorFailureCodeV1 =
  | "candidate-incomplete"
  | "candidate-corrupt"
  | "candidate-mixed"
  | "candidate-stale"
  | "authority-stale"
  | "confirmation-rejected"
  | "rollback-unavailable"
  | "transition-failed"
  | "cleanup-failed";

export type UpdateCoordinatorStateV1 =
  | Readonly<{ phase: "current"; snapshot: PairAuthoritySnapshotV1; cleanup: null }>
  | Readonly<{
    phase: "preparing";
    action: "update" | "rollback";
    snapshot: PairAuthoritySnapshotV1;
  }>
  | Readonly<{
    phase: "awaiting-confirmation";
    action: "update" | "rollback";
    snapshot: PairAuthoritySnapshotV1;
    target: AcceptedPairIdentityV1;
    confirmationToken: string;
  }>
  | Readonly<{
    phase: "transitioning";
    action: "update" | "rollback";
    snapshot: PairAuthoritySnapshotV1;
    target: AcceptedPairIdentityV1;
  }>
  | Readonly<{
    phase: "activated" | "rolled-back";
    snapshot: PairAuthoritySnapshotV1;
    cleanup: CleanupStateV1 | null;
    reloadAllowed: true;
  }>
  | Readonly<{
    phase: "failed";
    operation: "prepare-update" | "prepare-rollback" | "activate-update" | "rollback" | "cleanup";
    code: UpdateCoordinatorFailureCodeV1;
    message: string;
    recoverable: true;
    currentUsable: true;
    snapshot: PairAuthoritySnapshotV1;
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

function boundedMessage(value: unknown, fallback: string): string {
  if (value instanceof Error && value.message) return value.message.slice(0, 512);
  if (typeof value === "string" && value) return value.slice(0, 512);
  return fallback;
}

function opaque(value: unknown, name: string, pattern: RegExp): string {
  if (typeof value !== "string" || !pattern.test(value)) throw new TypeError(`${name} is invalid.`);
  return value;
}

function boundConfirmationToken(providerToken: unknown, generation: number): string {
  if (!Number.isSafeInteger(generation) || generation <= 0) {
    throw new TypeError("Coordinator confirmation generation is invalid.");
  }
  const provider = opaque(providerToken, "provider confirmation token", PROVIDER_TOKEN);
  return opaque(`g${generation}.${provider}`, "bound confirmation token", TOKEN);
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

export function validatePairAuthoritySnapshot(value: PairAuthoritySnapshotV1): PairAuthoritySnapshotV1 {
  if (!value || typeof value !== "object" || value.contractVersion !== 1) {
    throw new TypeError("Pair authority snapshot is invalid.");
  }
  const active = validateAcceptedPairIdentity(value.active);
  const previous = value.previous === null ? null : validateAcceptedPairIdentity(value.previous);
  if (previous && samePair(active.pair, previous.pair)) {
    throw new TypeError("Active and previous authority must be different exact pairs.");
  }
  return Object.freeze({
    contractVersion: 1,
    revision: opaque(value.revision, "snapshot revision", REVISION),
    active,
    previous,
  });
}

function sameSnapshot(left: PairAuthoritySnapshotV1, right: PairAuthoritySnapshotV1): boolean {
  return left.revision === right.revision && sameIdentity(left.active, right.active) &&
    (left.previous === null ? right.previous === null : right.previous !== null && sameIdentity(left.previous, right.previous));
}

function failure(
  operation: Extract<UpdateCoordinatorStateV1, { phase: "failed" }>["operation"],
  code: UpdateCoordinatorFailureCodeV1,
  snapshot: PairAuthoritySnapshotV1,
  message: string,
): UpdateCoordinatorStateV1 {
  return Object.freeze({
    phase: "failed", operation, code, message, recoverable: true, currentUsable: true, snapshot,
  });
}

function validateInspection(value: CandidateInspectionV1, requested: AppReleasePairV1): CandidateInspectionV1 {
  if (!value || typeof value !== "object") throw new TypeError("Candidate inspection is invalid.");
  if (value.status === "sealed") {
    const candidate = validateAcceptedPairIdentity(value.candidate);
    if (!samePair(candidate.pair, requested)) throw new TypeError("Candidate inspection returned a mixed pair.");
    return Object.freeze({ status: "sealed", candidate });
  }
  if (!new Set(["incomplete", "corrupt", "mixed", "stale"]).has(value.status)) {
    throw new TypeError("Candidate inspection status is unsupported.");
  }
  return Object.freeze({ status: value.status, reason: boundedMessage(value.reason, `Candidate is ${value.status}.`) });
}

function validateTransition(
  value: AtomicPairTransitionV1,
  expected: PairAuthoritySnapshotV1,
  nextActive: AcceptedPairIdentityV1,
): PairAuthoritySnapshotV1 {
  if (!value || value.contractVersion !== 1) throw new TypeError("Atomic transition receipt is invalid.");
  const before = validatePairAuthoritySnapshot(value.before);
  const after = validatePairAuthoritySnapshot(value.after);
  if (!sameSnapshot(before, expected) || after.revision === expected.revision ||
      !sameIdentity(after.active, nextActive) || after.previous === null ||
      !sameIdentity(after.previous, expected.active)) {
    throw new TypeError("Atomic transition did not preserve the exact active/previous authority contract.");
  }
  return after;
}

function validateCleanup(
  value: CleanupFenceResultV1,
  target: AppReleasePairV1,
): CleanupStateV1 {
  if (value.status === "removed") return Object.freeze({ status: "removed", pair: target });
  if (value.status !== "blocked" || !Array.isArray(value.leases) || value.leases.length === 0) {
    throw new TypeError("Cleanup fence result is invalid.");
  }
  const leases = value.leases.map(validateClientLease);
  if (leases.some((lease) => !samePair(lease.pair, target))) {
    throw new TypeError("Cleanup fence reported a lease for another pair.");
  }
  return Object.freeze({ status: "blocked", pair: target, leases: Object.freeze(leases) });
}

/**
 * Pure orchestration around injected persistence and lease-fence ports. This
 * module never calls browser lifecycle APIs; only a confirmed atomic receipt
 * exposes `reloadAllowed: true` to the adapter.
 */
export class ExplicitUpdateCoordinator {
  readonly #ports: UpdateCoordinatorPorts;
  #state: UpdateCoordinatorStateV1 | null = null;
  #sequence = 0;
  #pendingGeneration: number | null = null;

  constructor(ports: UpdateCoordinatorPorts) { this.#ports = ports; }

  state(): UpdateCoordinatorStateV1 | null { return this.#state; }

  async initialize(): Promise<UpdateCoordinatorStateV1> {
    const snapshot = validatePairAuthoritySnapshot(await this.#ports.readSnapshot());
    return this.#set(Object.freeze({ phase: "current", snapshot, cleanup: null }));
  }

  async prepareUpdate(pairInput: AppReleasePairV1): Promise<UpdateCoordinatorStateV1> {
    if (this.#state?.phase === "transitioning") return this.#state;
    const fallback = this.#state && "snapshot" in this.#state ? this.#state.snapshot : null;
    const operation = this.#beginPreparation("update", fallback);
    let expected: PairAuthoritySnapshotV1;
    try {
      expected = validatePairAuthoritySnapshot(await this.#ports.readSnapshot());
    } catch (error) {
      return await this.#preparationFailure(operation, "prepare-update", fallback, error, "Update authority could not be read.");
    }
    if (operation !== this.#sequence) return this.#currentOr(expected);

    let requested: AppReleasePairV1;
    try { requested = validateAppReleasePair(pairInput); }
    catch (error) {
      return this.#set(failure("prepare-update", "candidate-corrupt", expected, boundedMessage(error, "Candidate pair is invalid.")));
    }
    if (samePair(requested, expected.active.pair) ||
        (expected.previous && samePair(requested, expected.previous.pair))) {
      return this.#set(failure("prepare-update", "candidate-stale", expected, "Update candidate is already retained by the current authority."));
    }

    let rawInspection: CandidateInspectionV1;
    try { rawInspection = await this.#ports.inspectCandidate(requested); }
    catch (error) {
      return await this.#preparationFailure(operation, "prepare-update", expected, error, "Candidate inspection port failed.");
    }
    if (operation !== this.#sequence) return this.#currentOr(expected);

    let inspected: CandidateInspectionV1;
    try { inspected = validateInspection(rawInspection, requested); }
    catch (error) {
      return this.#set(failure("prepare-update", "candidate-corrupt", expected, boundedMessage(error, "Candidate evidence is corrupt.")));
    }
    let current: PairAuthoritySnapshotV1;
    try { current = validatePairAuthoritySnapshot(await this.#ports.readSnapshot()); }
    catch (error) {
      return await this.#preparationFailure(operation, "prepare-update", expected, error, "Update authority could not be confirmed.");
    }
    if (operation !== this.#sequence) return this.#currentOr(expected);
    if (!sameSnapshot(current, expected)) {
      return this.#set(failure("prepare-update", "authority-stale", current, "Pair authority changed while the candidate was inspected."));
    }
    if (inspected.status !== "sealed") {
      return this.#set(failure("prepare-update", `candidate-${inspected.status}`, expected, inspected.reason));
    }
    try {
      const confirmationToken = boundConfirmationToken(this.#ports.issueConfirmationToken({
        action: "update", coordinatorGeneration: operation, expected, target: inspected.candidate,
      }), operation);
      this.#pendingGeneration = operation;
      return this.#set(Object.freeze({
        phase: "awaiting-confirmation", action: "update", snapshot: expected,
        target: inspected.candidate, confirmationToken,
      }));
    } catch (error) {
      return await this.#preparationFailure(operation, "prepare-update", expected, error, "Update confirmation could not be issued.");
    }
  }

  async prepareRollback(): Promise<UpdateCoordinatorStateV1> {
    if (this.#state?.phase === "transitioning") return this.#state;
    const fallback = this.#state && "snapshot" in this.#state ? this.#state.snapshot : null;
    const operation = this.#beginPreparation("rollback", fallback);
    try {
      const expected = validatePairAuthoritySnapshot(await this.#ports.readSnapshot());
      if (operation !== this.#sequence) return this.#currentOr(expected);
      if (!expected.previous) {
        return this.#set(failure("prepare-rollback", "rollback-unavailable", expected, "No exact previous pair is retained for rollback."));
      }
      const confirmationToken = boundConfirmationToken(this.#ports.issueConfirmationToken({
        action: "rollback", coordinatorGeneration: operation, expected, target: expected.previous,
      }), operation);
      this.#pendingGeneration = operation;
      return this.#set(Object.freeze({
        phase: "awaiting-confirmation", action: "rollback", snapshot: expected,
        target: expected.previous, confirmationToken,
      }));
    } catch (error) {
      return await this.#preparationFailure(
        operation, "prepare-rollback", fallback, error, "Rollback authority could not be prepared.",
      );
    }
  }

  async confirm(tokenInput: string): Promise<UpdateCoordinatorStateV1> {
    const pending = this.#state;
    if (!pending || pending.phase !== "awaiting-confirmation") return this.#currentOr(null);
    const pendingGeneration = this.#pendingGeneration;
    let token: string;
    try { token = opaque(tokenInput, "confirmation token", TOKEN); } catch {
      return this.#set(failure(
        pending.action === "update" ? "activate-update" : "rollback",
        "confirmation-rejected", pending.snapshot, "Confirmation token is invalid.",
      ));
    }
    if (pendingGeneration === null || pendingGeneration !== this.#sequence || token !== pending.confirmationToken) {
      return this.#set(failure(
        pending.action === "update" ? "activate-update" : "rollback",
        "confirmation-rejected", pending.snapshot, "Confirmation token does not authorize this exact transition.",
      ));
    }
    this.#pendingGeneration = null;
    ++this.#sequence;
    this.#state = Object.freeze({
      phase: "transitioning", action: pending.action, snapshot: pending.snapshot, target: pending.target,
    });
    let current: PairAuthoritySnapshotV1;
    try {
      current = validatePairAuthoritySnapshot(await this.#ports.readSnapshot());
    } catch (error) {
      const currentAfterFailure = await this.#safeSnapshot(pending.snapshot);
      return this.#set(failure(
        pending.action === "update" ? "activate-update" : "rollback",
        "transition-failed", currentAfterFailure, boundedMessage(error, "Pair authority could not be confirmed."),
      ));
    }
    if (!sameSnapshot(current, pending.snapshot)) {
      return this.#set(failure(
        pending.action === "update" ? "activate-update" : "rollback",
        "authority-stale", current, "Pair authority changed after confirmation was offered.",
      ));
    }
    try {
      const receipt = pending.action === "update"
        ? await this.#ports.activate({ expected: pending.snapshot, candidate: pending.target, confirmationToken: token })
        : await this.#ports.rollback({ expected: pending.snapshot, target: pending.target, confirmationToken: token });
      const after = validateTransition(receipt, pending.snapshot, pending.target);
      if (pending.action === "rollback") {
        return this.#set(Object.freeze({ phase: "rolled-back", snapshot: after, cleanup: null, reloadAllowed: true }));
      }
      return await this.#finishActivation(pending.snapshot, after);
    } catch (error) {
      const currentAfterFailure = await this.#safeSnapshot(pending.snapshot);
      return this.#set(failure(
        pending.action === "update" ? "activate-update" : "rollback",
        "transition-failed", currentAfterFailure, boundedMessage(error, "Atomic pair transition failed."),
      ));
    }
  }

  async #finishActivation(
    before: PairAuthoritySnapshotV1,
    after: PairAuthoritySnapshotV1,
  ): Promise<UpdateCoordinatorStateV1> {
    if (!before.previous) {
      return this.#set(Object.freeze({ phase: "activated", snapshot: after, cleanup: null, reloadAllowed: true }));
    }
    try {
      const cleanup = validateCleanup(await this.#ports.cleanupRetiredPair({
        protectedSnapshot: after,
        pair: before.previous.pair,
      }), before.previous.pair);
      return this.#set(Object.freeze({ phase: "activated", snapshot: after, cleanup, reloadAllowed: true }));
    } catch (error) {
      return this.#set(failure("cleanup", "cleanup-failed", after, boundedMessage(error, "Retired-pair cleanup failed.")));
    }
  }

  async #safeSnapshot(fallback: PairAuthoritySnapshotV1 | null): Promise<PairAuthoritySnapshotV1> {
    try { return validatePairAuthoritySnapshot(await this.#ports.readSnapshot()); }
    catch (error) {
      if (fallback) return fallback;
      throw error;
    }
  }

  #beginPreparation(
    action: "update" | "rollback",
    snapshot: PairAuthoritySnapshotV1 | null,
  ): number {
    const generation = ++this.#sequence;
    this.#pendingGeneration = null;
    if (snapshot) this.#state = Object.freeze({ phase: "preparing", action, snapshot });
    return generation;
  }

  async #preparationFailure(
    generation: number,
    operation: "prepare-update" | "prepare-rollback",
    fallback: PairAuthoritySnapshotV1 | null,
    error: unknown,
    defaultMessage: string,
  ): Promise<UpdateCoordinatorStateV1> {
    const current = await this.#safeSnapshot(fallback);
    if (generation !== this.#sequence) return this.#currentOr(current);
    return this.#set(failure(
      operation, "transition-failed", current, boundedMessage(error, defaultMessage),
    ));
  }

  #currentOr(fallback: PairAuthoritySnapshotV1 | null): UpdateCoordinatorStateV1 {
    if (this.#state) return this.#state;
    if (!fallback) throw new Error("Update coordinator is not initialized.");
    return Object.freeze({ phase: "current", snapshot: fallback, cleanup: null });
  }

  #set<T extends UpdateCoordinatorStateV1>(state: T): T {
    this.#state = state;
    if (state.phase !== "awaiting-confirmation") this.#pendingGeneration = null;
    return state;
  }
}
