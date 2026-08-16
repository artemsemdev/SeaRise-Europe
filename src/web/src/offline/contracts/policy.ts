import type { HorizonYear, ScenarioId } from "../../contracts/generated/release-contract";
import { OFFLINE_CONTRACT_VERSION, exactRecord, type AppReleasePairV1, validateAppReleasePair } from "./keys";
import {
  OfflineContractError,
  assertPersistentEligibility,
  persistenceEligibility,
  sha256Hex,
  validateAppAuthority,
  validateRangeIdentity,
  validateWholeResourceAuthority,
  type AppAuthorityV1,
  type RangeIdentityV1,
  type Sha256Hex,
  type WholeResourceAuthorityV1,
} from "./v1";

function fail(message: string): never { throw new OfflineContractError(message); }
function positiveInteger(value: unknown, name: string): number {
  if (!Number.isSafeInteger(value) || (value as number) <= 0) fail(`${name} must be a positive safe integer.`);
  return value as number;
}
function nonNegativeInteger(value: unknown, name: string): number {
  if (!Number.isSafeInteger(value) || (value as number) < 0) fail(`${name} must be a non-negative safe integer.`);
  return value as number;
}
function boundedString(value: unknown, name: string, maximum = 256): string {
  if (typeof value !== "string" || value.length === 0 || value.length > maximum) fail(`${name} must be 1-${maximum} characters.`);
  return value;
}
function protocolId(value: unknown, name: string): string {
  const result = boundedString(value, name, 128);
  if (!/^[A-Za-z0-9._-]+$/u.test(result)) fail(`${name} must be an opaque ASCII identifier.`);
  return result;
}
function samePair(left: AppReleasePairV1, right: AppReleasePairV1): boolean {
  return left.appBuildId === right.appBuildId && left.dataReleaseId === right.dataReleaseId;
}
function assertSamePair(expected: AppReleasePairV1, actual: AppReleasePairV1): void {
  if (!samePair(expected, actual)) fail("Resource authority belongs to a different app/release pair.");
}

export type OfflineRequirementV1 =
  | Readonly<{ kind: "whole"; authority: WholeResourceAuthorityV1 }>
  | Readonly<{ kind: "range"; identity: RangeIdentityV1 }>;
export type OfflineRequirementV2 = OfflineRequirementV1
  | Readonly<{ kind: "network-only"; identity: string; reason: "visual-pmtiles" }>;
export type InteractionSubjectV1 =
  | Readonly<{ kind: "core" }>
  | Readonly<{ kind: "search"; shards: readonly ("core" | "coastal")[] }>
  | Readonly<{ kind: "assessment" | "map"; scenario: ScenarioId; horizon: HorizonYear }>;
export const OFFLINE_CAPABILITY_CONTRACT_VERSION_V2 = 2 as const;
export interface InteractionRequirementsV1 {
  readonly contractVersion: 1;
  readonly pair: AppReleasePairV1;
  readonly subject: InteractionSubjectV1;
  readonly requirements: readonly OfflineRequirementV1[];
}
export interface InteractionRequirementsV2 {
  readonly contractVersion: typeof OFFLINE_CAPABILITY_CONTRACT_VERSION_V2;
  readonly pair: AppReleasePairV1;
  readonly subject: InteractionSubjectV1;
  readonly requirements: readonly OfflineRequirementV2[];
}
export interface MissingRequirementV1 { readonly kind: "whole" | "range"; readonly identity: string }
export type MissingRequirementV2 = MissingRequirementV1
  | Readonly<{ kind: "network-only"; identity: string }>;

const SCENARIOS = new Set<unknown>(["ssp1-26", "ssp2-45", "ssp5-85"]);
const HORIZONS = new Set<unknown>([2030, 2050, 2100]);
const VISUAL_PMTILES_ID = /^projection-(ssp1-26|ssp2-45|ssp5-85)-(2030|2050|2100)-pmtiles$/u;

function visualPmtilesIdentity(subject: Readonly<{ scenario: ScenarioId; horizon: HorizonYear }>): string {
  return `projection-${subject.scenario}-${subject.horizon}-pmtiles`;
}

function validateNetworkOnlyIdentity(value: unknown): string {
  const identity = protocolId(value, "network-only identity");
  if (!VISUAL_PMTILES_ID.test(identity)) fail("Network-only identity must name an exact visual PMTiles artifact.");
  return identity;
}

function validateSubject(value: unknown): InteractionSubjectV1 {
  if (typeof value !== "object" || value === null || Array.isArray(value)) fail("interaction subject must be an object.");
  const kind = (value as Record<string, unknown>).kind;
  if (kind === "core") {
    exactRecord(value, ["kind"], "core subject");
    return Object.freeze({ kind });
  }
  if (kind === "search") {
    const record = exactRecord(value, ["kind", "shards"], "search subject");
    if (!Array.isArray(record.shards) || record.shards.length === 0 || record.shards.some((item) => item !== "core" && item !== "coastal")) fail("search shards must contain only core or coastal.");
    return Object.freeze({ kind, shards: Object.freeze([...new Set(record.shards as ("core" | "coastal")[])]) });
  }
  if (kind === "assessment" || kind === "map") {
    const record = exactRecord(value, ["kind", "scenario", "horizon"], `${kind} subject`);
    if (!SCENARIOS.has(record.scenario) || !HORIZONS.has(record.horizon)) fail("interaction scenario/horizon is unsupported.");
    return Object.freeze({ kind, scenario: record.scenario as ScenarioId, horizon: record.horizon as HorizonYear });
  }
  return fail("interaction subject kind is unsupported.");
}

function validateOfflineRequirement(
  value: unknown,
  pair: AppReleasePairV1,
  allowNetworkOnly: false,
): OfflineRequirementV1;
function validateOfflineRequirement(
  value: unknown,
  pair: AppReleasePairV1,
  allowNetworkOnly: true,
): OfflineRequirementV2;
function validateOfflineRequirement(
  value: unknown,
  pair: AppReleasePairV1,
  allowNetworkOnly: boolean,
): OfflineRequirementV2 {
  if (typeof value !== "object" || value === null || Array.isArray(value)) fail("requirement must be an object.");
  const kind = (value as Record<string, unknown>).kind;
  if (kind === "whole") {
    const authority = validateWholeResourceAuthority(exactRecord(value, ["kind", "authority"], "whole requirement").authority);
    assertSamePair(pair, authority.pair);
    return Object.freeze({ kind, authority });
  }
  if (kind === "range") {
    const identity = validateRangeIdentity(exactRecord(value, ["kind", "identity"], "range requirement").identity);
    assertSamePair(pair, identity.authority.pair);
    return Object.freeze({ kind, identity });
  }
  if (kind === "network-only" && allowNetworkOnly) {
    const networkOnly = exactRecord(value, ["kind", "identity", "reason"], "network-only requirement");
    if (networkOnly.reason !== "visual-pmtiles") fail("Network-only requirement reason is unsupported.");
    return Object.freeze({ kind, identity: validateNetworkOnlyIdentity(networkOnly.identity), reason: networkOnly.reason });
  }
  return fail("requirement kind is unsupported.");
}

export function validateInteractionRequirements(value: unknown): InteractionRequirementsV1 {
  const record = exactRecord(value, ["contractVersion", "pair", "subject", "requirements"], "interaction requirements");
  if (record.contractVersion !== OFFLINE_CONTRACT_VERSION || !Array.isArray(record.requirements)) fail("Interaction requirements version or list is invalid.");
  const pair = validateAppReleasePair(record.pair);
  const subject = validateSubject(record.subject);
  const requirements = record.requirements.map((requirement) => validateOfflineRequirement(requirement, pair, false));
  return Object.freeze({ contractVersion: OFFLINE_CONTRACT_VERSION, pair, subject, requirements: Object.freeze(requirements) });
}

export function validateInteractionRequirementsV2(value: unknown): InteractionRequirementsV2 {
  const record = exactRecord(value, ["contractVersion", "pair", "subject", "requirements"], "v2 interaction requirements");
  if (record.contractVersion !== OFFLINE_CAPABILITY_CONTRACT_VERSION_V2 || !Array.isArray(record.requirements)) fail("Interaction requirements version or list is invalid.");
  const pair = validateAppReleasePair(record.pair);
  const subject = validateSubject(record.subject);
  const requirements = record.requirements.map((requirement) => validateOfflineRequirement(requirement, pair, true));
  const networkOnly = requirements.filter((requirement) => requirement.kind === "network-only");
  if (subject.kind === "map") {
    if (networkOnly.length !== 1 || networkOnly[0]?.identity !== visualPmtilesIdentity(subject)) {
      fail("Map requirements must contain exactly one matching visual PMTiles network-only resource.");
    }
  } else if (networkOnly.length !== 0) {
    fail("Only map interactions may require a network-only visual PMTiles resource.");
  }
  return Object.freeze({ contractVersion: OFFLINE_CAPABILITY_CONTRACT_VERSION_V2, pair, subject, requirements: Object.freeze(requirements) });
}

function validateMissing(value: unknown): MissingRequirementV1 {
  const record = exactRecord(value, ["kind", "identity"], "missing requirement");
  if (record.kind !== "whole" && record.kind !== "range") fail("Missing requirement kind is unsupported.");
  return Object.freeze({ kind: record.kind, identity: protocolId(record.identity, "missing identity") });
}
function validateMissingList(value: unknown): readonly MissingRequirementV1[] {
  if (!Array.isArray(value)) fail("missing requirements must be an array.");
  return Object.freeze(value.map(validateMissing));
}

function validateMissingV2(value: unknown): MissingRequirementV2 {
  const record = exactRecord(value, ["kind", "identity"], "v2 missing requirement");
  if (record.kind === "network-only") {
    return Object.freeze({ kind: record.kind, identity: validateNetworkOnlyIdentity(record.identity) });
  }
  return validateMissing(record);
}
function validateMissingListV2(value: unknown): readonly MissingRequirementV2[] {
  if (!Array.isArray(value)) fail("missing requirements must be an array.");
  return Object.freeze(value.map(validateMissingV2));
}

export type DataCapabilityV1 =
  | Readonly<{ state: "online-complete"; pair: AppReleasePairV1 }>
  | Readonly<{ state: "available-offline"; pair: AppReleasePairV1; resourceCount: number; byteCount: number }>
  | Readonly<{ state: "connection-required"; pair: AppReleasePairV1; missing: readonly MissingRequirementV1[]; retryable: true }>
  | Readonly<{ state: "degraded-storage"; pair: AppReleasePairV1; reason: "quota" | "evicted" | "persistence-denied"; networkUsable: boolean }>;
export type DataCapabilityV2 =
  | Exclude<DataCapabilityV1, { state: "connection-required" }>
  | Readonly<{ state: "connection-required"; pair: AppReleasePairV1; missing: readonly MissingRequirementV2[]; retryable: true }>;
export type UpdateCapabilityV1 =
  | Readonly<{ state: "current" }>
  | Readonly<{ state: "update-available" | "installing" | "ready-to-activate"; candidate: AppReleasePairV1 }>
  | Readonly<{ state: "activation-blocked" | "failed"; reason: string }>;
export interface RuntimeCapabilityV1 { readonly contractVersion: 1; readonly data: DataCapabilityV1; readonly update: UpdateCapabilityV1 }
export interface RuntimeCapabilityV2 { readonly contractVersion: typeof OFFLINE_CAPABILITY_CONTRACT_VERSION_V2; readonly subject: InteractionSubjectV1; readonly data: DataCapabilityV2; readonly update: UpdateCapabilityV1 }

export function validateDataCapability(value: unknown): DataCapabilityV1 {
  if (typeof value !== "object" || value === null || Array.isArray(value)) fail("data capability must be an object.");
  const state = (value as Record<string, unknown>).state;
  if (state === "online-complete") {
    return Object.freeze({ state, pair: validateAppReleasePair(exactRecord(value, ["state", "pair"], "online capability").pair) });
  }
  if (state === "available-offline") {
    const record = exactRecord(value, ["state", "pair", "resourceCount", "byteCount"], "offline capability");
    return Object.freeze({ state, pair: validateAppReleasePair(record.pair), resourceCount: positiveInteger(record.resourceCount, "resourceCount"), byteCount: positiveInteger(record.byteCount, "byteCount") });
  }
  if (state === "connection-required") {
    const record = exactRecord(value, ["state", "pair", "missing", "retryable"], "connection-required capability");
    const missing = validateMissingList(record.missing);
    if (missing.length === 0 || record.retryable !== true) fail("Connection-required capability must be retryable and identify missing resources.");
    return Object.freeze({ state, pair: validateAppReleasePair(record.pair), missing, retryable: true });
  }
  if (state === "degraded-storage") {
    const record = exactRecord(value, ["state", "pair", "reason", "networkUsable"], "degraded storage capability");
    if (!new Set(["quota", "evicted", "persistence-denied"]).has(record.reason as string) || typeof record.networkUsable !== "boolean") fail("Degraded storage capability is invalid.");
    return Object.freeze({ state, pair: validateAppReleasePair(record.pair), reason: record.reason as "quota" | "evicted" | "persistence-denied", networkUsable: record.networkUsable });
  }
  return fail("data capability state is unsupported.");
}

export function validateDataCapabilityV2(value: unknown): DataCapabilityV2 {
  if (typeof value !== "object" || value === null || Array.isArray(value)) fail("data capability must be an object.");
  if ((value as Record<string, unknown>).state !== "connection-required") return validateDataCapability(value);
  const record = exactRecord(value, ["state", "pair", "missing", "retryable"], "v2 connection-required capability");
  const missing = validateMissingListV2(record.missing);
  if (missing.length === 0 || record.retryable !== true) fail("Connection-required capability must be retryable and identify missing resources.");
  return Object.freeze({ state: "connection-required", pair: validateAppReleasePair(record.pair), missing, retryable: true });
}

export function validateUpdateCapability(value: unknown): UpdateCapabilityV1 {
  if (typeof value !== "object" || value === null || Array.isArray(value)) fail("update capability must be an object.");
  const state = (value as Record<string, unknown>).state;
  if (state === "current") {
    exactRecord(value, ["state"], "current update capability");
    return Object.freeze({ state });
  }
  if (state === "update-available" || state === "installing" || state === "ready-to-activate") {
    return Object.freeze({ state, candidate: validateAppReleasePair(exactRecord(value, ["state", "candidate"], `${state} capability`).candidate) });
  }
  if (state === "activation-blocked" || state === "failed") {
    return Object.freeze({ state, reason: boundedString(exactRecord(value, ["state", "reason"], `${state} capability`).reason, "reason", 512) });
  }
  return fail("update capability state is unsupported.");
}

export function validateRuntimeCapability(value: unknown): RuntimeCapabilityV1 {
  const record = exactRecord(value, ["contractVersion", "data", "update"], "runtime capability");
  if (record.contractVersion !== OFFLINE_CONTRACT_VERSION) fail("Unsupported offline contract version.");
  const data = validateDataCapability(record.data);
  const update = validateUpdateCapability(record.update);
  if ("candidate" in update && samePair(data.pair, update.candidate)) fail("An update candidate must differ from the current data pair.");
  return Object.freeze({ contractVersion: OFFLINE_CONTRACT_VERSION, data, update });
}

export function validateRuntimeCapabilityV2(value: unknown): RuntimeCapabilityV2 {
  const record = exactRecord(value, ["contractVersion", "subject", "data", "update"], "v2 runtime capability");
  if (record.contractVersion !== OFFLINE_CAPABILITY_CONTRACT_VERSION_V2) fail("Unsupported offline capability contract version.");
  const subject = validateSubject(record.subject);
  const data = validateDataCapabilityV2(record.data);
  const update = validateUpdateCapability(record.update);
  if ("candidate" in update && samePair(data.pair, update.candidate)) fail("An update candidate must differ from the current data pair.");
  const networkOnlyMissing = data.state === "connection-required"
    ? data.missing.filter((requirement) => requirement.kind === "network-only")
    : [];
  if (subject.kind === "map") {
    if (data.state === "available-offline") fail("A map capability cannot be available offline because visual PMTiles is network-only.");
    if (
      data.state === "connection-required"
      && (networkOnlyMissing.length !== 1 || networkOnlyMissing[0]?.identity !== visualPmtilesIdentity(subject))
    ) {
      fail("A connection-required map capability must identify its matching network-only visual PMTiles resource.");
    }
  } else if (networkOnlyMissing.length !== 0) {
    fail("Only map capabilities may report a missing network-only visual PMTiles resource.");
  }
  return Object.freeze({ contractVersion: OFFLINE_CAPABILITY_CONTRACT_VERSION_V2, subject, data, update });
}

export interface StorageBudgetV1 {
  readonly contractVersion: 1; readonly policyId: string;
  readonly maxTotalBytes: number; readonly maxWholeResourceBytes: number; readonly maxRangeBytes: number;
  readonly maxWholeEntries: number; readonly maxRangeEntries: number;
  readonly highWatermarkBytes: number; readonly lowWatermarkBytes: number; readonly minQuotaReserveBytes: number;
  readonly maxQuotaFraction: number; readonly leaseTtlMs: number; readonly heartbeatMs: number;
  readonly retainedCompletePairs: 2; readonly eviction: "unleased-lru";
}

export function validateStorageBudget(value: unknown): StorageBudgetV1 {
  const keys = ["contractVersion", "policyId", "maxTotalBytes", "maxWholeResourceBytes", "maxRangeBytes", "maxWholeEntries", "maxRangeEntries", "highWatermarkBytes", "lowWatermarkBytes", "minQuotaReserveBytes", "maxQuotaFraction", "leaseTtlMs", "heartbeatMs", "retainedCompletePairs", "eviction"];
  const record = exactRecord(value, keys, "storage budget");
  if (record.contractVersion !== OFFLINE_CONTRACT_VERSION) fail("Unsupported offline contract version.");
  const result: StorageBudgetV1 = {
    contractVersion: OFFLINE_CONTRACT_VERSION, policyId: protocolId(record.policyId, "policyId"),
    maxTotalBytes: positiveInteger(record.maxTotalBytes, "maxTotalBytes"),
    maxWholeResourceBytes: positiveInteger(record.maxWholeResourceBytes, "maxWholeResourceBytes"),
    maxRangeBytes: positiveInteger(record.maxRangeBytes, "maxRangeBytes"),
    maxWholeEntries: positiveInteger(record.maxWholeEntries, "maxWholeEntries"),
    maxRangeEntries: positiveInteger(record.maxRangeEntries, "maxRangeEntries"),
    highWatermarkBytes: positiveInteger(record.highWatermarkBytes, "highWatermarkBytes"),
    lowWatermarkBytes: positiveInteger(record.lowWatermarkBytes, "lowWatermarkBytes"),
    minQuotaReserveBytes: nonNegativeInteger(record.minQuotaReserveBytes, "minQuotaReserveBytes"),
    maxQuotaFraction: typeof record.maxQuotaFraction === "number" ? record.maxQuotaFraction : Number.NaN,
    leaseTtlMs: positiveInteger(record.leaseTtlMs, "leaseTtlMs"), heartbeatMs: positiveInteger(record.heartbeatMs, "heartbeatMs"),
    retainedCompletePairs: record.retainedCompletePairs as 2, eviction: record.eviction as "unleased-lru",
  };
  if (result.maxWholeResourceBytes + result.maxRangeBytes > result.maxTotalBytes) fail("Whole and range budgets exceed maxTotalBytes.");
  if (!(result.lowWatermarkBytes < result.highWatermarkBytes && result.highWatermarkBytes <= result.maxTotalBytes)) fail("Storage watermarks must satisfy low < high <= total.");
  if (!(result.maxQuotaFraction > 0 && result.maxQuotaFraction <= 1)) fail("maxQuotaFraction must be in (0, 1].");
  if (result.heartbeatMs * 2 >= result.leaseTtlMs) fail("leaseTtlMs must exceed two heartbeat intervals.");
  if (record.retainedCompletePairs !== 2 || record.eviction !== "unleased-lru") fail("Storage must retain two complete pairs and evict only unleased LRU entries.");
  return Object.freeze(result);
}

export type PairLifecycleStateV1 = "staging" | "bootstrap-complete" | "core-complete" | "active" | "previous" | "cleanup-pending" | "corrupt";
export interface PairLifecycleV1 { readonly contractVersion: 1; readonly pair: AppReleasePairV1; readonly state: PairLifecycleStateV1; readonly completenessReceiptSha256: Sha256Hex | null }
export interface RollbackRequestV1 { readonly contractVersion: 1; readonly currentPair: AppReleasePairV1; readonly targetPair: AppReleasePairV1; readonly confirmationToken: string }
const LIFECYCLE = new Set<PairLifecycleStateV1>(["staging", "bootstrap-complete", "core-complete", "active", "previous", "cleanup-pending", "corrupt"]);
const RECEIPT_REQUIRED = new Set<PairLifecycleStateV1>(["bootstrap-complete", "core-complete", "active", "previous"]);

export function validatePairLifecycle(value: unknown): PairLifecycleV1 {
  const record = exactRecord(value, ["contractVersion", "pair", "state", "completenessReceiptSha256"], "pair lifecycle");
  if (record.contractVersion !== OFFLINE_CONTRACT_VERSION || !LIFECYCLE.has(record.state as PairLifecycleStateV1)) fail("Pair lifecycle version or state is unsupported.");
  const state = record.state as PairLifecycleStateV1;
  const receipt = record.completenessReceiptSha256 === null ? null : sha256Hex(record.completenessReceiptSha256, "completenessReceiptSha256");
  if (state === "staging" && receipt !== null) fail("A staging pair cannot have a completeness receipt.");
  if (RECEIPT_REQUIRED.has(state) && receipt === null) fail("Complete, active, and previous states require a completeness receipt.");
  return Object.freeze({ contractVersion: OFFLINE_CONTRACT_VERSION, pair: validateAppReleasePair(record.pair), state, completenessReceiptSha256: receipt });
}

export function validateRollbackRequest(value: unknown): RollbackRequestV1 {
  const record = exactRecord(value, ["contractVersion", "currentPair", "targetPair", "confirmationToken"], "rollback request");
  if (record.contractVersion !== OFFLINE_CONTRACT_VERSION) fail("Unsupported offline contract version.");
  const currentPair = validateAppReleasePair(record.currentPair);
  const targetPair = validateAppReleasePair(record.targetPair);
  if (samePair(currentPair, targetPair)) fail("Rollback target must differ from the current pair.");
  return Object.freeze({ contractVersion: OFFLINE_CONTRACT_VERSION, currentPair, targetPair, confirmationToken: protocolId(record.confirmationToken, "confirmationToken") });
}

export interface ClientLeaseV1 { readonly contractVersion: 1; readonly leaseId: string; readonly pair: AppReleasePairV1; readonly expiresAtEpochMs: number; readonly state: "active" }
export function validateClientLease(value: unknown): ClientLeaseV1 {
  const record = exactRecord(value, ["contractVersion", "leaseId", "pair", "expiresAtEpochMs", "state"], "client lease");
  if (record.contractVersion !== OFFLINE_CONTRACT_VERSION || record.state !== "active") fail("Client lease version or state is unsupported.");
  return Object.freeze({ contractVersion: OFFLINE_CONTRACT_VERSION, leaseId: protocolId(record.leaseId, "leaseId"), pair: validateAppReleasePair(record.pair), expiresAtEpochMs: positiveInteger(record.expiresAtEpochMs, "expiresAtEpochMs"), state: "active" });
}

export type OfflineTechnicalErrorV1 =
  | Readonly<{ kind: "technical-error"; code: "ConnectionRequired"; recoverable: true; pair: AppReleasePairV1; missing: readonly MissingRequirementV1[]; message: "This result is not available offline yet. Reconnect to load the selected data." }>
  | Readonly<{ kind: "technical-error"; code: "StorageLimitReached"; recoverable: true; pair: AppReleasePairV1; message: "Offline storage is full. Reconnect to continue without saving more data." }>;
export type OfflineTechnicalErrorV2 =
  | Readonly<{ kind: "technical-error"; code: "ConnectionRequired"; recoverable: true; pair: AppReleasePairV1; missing: readonly MissingRequirementV2[]; message: "This result is not available offline yet. Reconnect to load the selected data." }>
  | Extract<OfflineTechnicalErrorV1, { code: "StorageLimitReached" }>;
export function connectionRequired(pair: AppReleasePairV1, missing: readonly MissingRequirementV1[]): OfflineTechnicalErrorV1 {
  if (missing.length === 0) fail("ConnectionRequired must identify at least one missing resource.");
  return Object.freeze({ kind: "technical-error", code: "ConnectionRequired", recoverable: true, pair: validateAppReleasePair(pair), missing: Object.freeze(missing.map(validateMissing)), message: "This result is not available offline yet. Reconnect to load the selected data." });
}
export function connectionRequiredV2(pair: AppReleasePairV1, missing: readonly MissingRequirementV2[]): OfflineTechnicalErrorV2 {
  if (missing.length === 0) fail("ConnectionRequired must identify at least one missing resource.");
  return Object.freeze({ kind: "technical-error", code: "ConnectionRequired", recoverable: true, pair: validateAppReleasePair(pair), missing: Object.freeze(missing.map(validateMissingV2)), message: "This result is not available offline yet. Reconnect to load the selected data." });
}
export function storageLimitReached(pair: AppReleasePairV1): OfflineTechnicalErrorV1 {
  return Object.freeze({ kind: "technical-error", code: "StorageLimitReached", recoverable: true, pair: validateAppReleasePair(pair), message: "Offline storage is full. Reconnect to continue without saving more data." });
}
export function validateOfflineTechnicalError(value: unknown): OfflineTechnicalErrorV1 {
  if (typeof value !== "object" || value === null || Array.isArray(value)) fail("offline technical error must be an object.");
  const code = (value as Record<string, unknown>).code;
  if (code === "ConnectionRequired") {
    const record = exactRecord(value, ["kind", "code", "recoverable", "pair", "missing", "message"], "connection-required error");
    if (record.kind !== "technical-error" || record.recoverable !== true || record.message !== "This result is not available offline yet. Reconnect to load the selected data.") fail("ConnectionRequired fields are invalid.");
    return connectionRequired(validateAppReleasePair(record.pair), validateMissingList(record.missing));
  }
  if (code === "StorageLimitReached") {
    const record = exactRecord(value, ["kind", "code", "recoverable", "pair", "message"], "storage-limit error");
    if (record.kind !== "technical-error" || record.recoverable !== true || record.message !== "Offline storage is full. Reconnect to continue without saving more data.") fail("StorageLimitReached fields are invalid.");
    return storageLimitReached(validateAppReleasePair(record.pair));
  }
  return fail("offline technical error code is unsupported.");
}

export function validateOfflineTechnicalErrorV2(value: unknown): OfflineTechnicalErrorV2 {
  if (typeof value !== "object" || value === null || Array.isArray(value)) fail("offline technical error must be an object.");
  const code = (value as Record<string, unknown>).code;
  if (code === "ConnectionRequired") {
    const record = exactRecord(value, ["kind", "code", "recoverable", "pair", "missing", "message"], "v2 connection-required error");
    if (record.kind !== "technical-error" || record.recoverable !== true || record.message !== "This result is not available offline yet. Reconnect to load the selected data.") fail("ConnectionRequired fields are invalid.");
    return connectionRequiredV2(validateAppReleasePair(record.pair), validateMissingListV2(record.missing));
  }
  if (code === "StorageLimitReached") return validateOfflineTechnicalError(value);
  return fail("offline technical error code is unsupported.");
}

export const OFFLINE_WORKER_PROTOCOL_V1 = "searise-offline-worker-v1" as const;
export const OFFLINE_WORKER_PROTOCOL = OFFLINE_WORKER_PROTOCOL_V1;
export const OFFLINE_WORKER_PROTOCOL_V2 = "searise-offline-worker-v2" as const;
export type ClientToOfflineWorkerV1 =
  | Readonly<{ protocol: typeof OFFLINE_WORKER_PROTOCOL; type: "inspect-identity"; messageToken: string; pair: AppReleasePairV1 }>
  | Readonly<{ protocol: typeof OFFLINE_WORKER_PROTOCOL; type: "acquire-lease" | "heartbeat-lease" | "release-lease"; messageToken: string; leaseId: string; pair: AppReleasePairV1 }>
  | Readonly<{ protocol: typeof OFFLINE_WORKER_PROTOCOL; type: "query-capability"; messageToken: string; requirements: InteractionRequirementsV1 }>
  | Readonly<{ protocol: typeof OFFLINE_WORKER_PROTOCOL; type: "prepare-update"; messageToken: string; currentPair: AppReleasePairV1; candidate: AppAuthorityV1 }>
  | Readonly<{ protocol: typeof OFFLINE_WORKER_PROTOCOL; type: "activate-update"; messageToken: string; candidatePair: AppReleasePairV1; confirmationToken: string }>
  | Readonly<{ protocol: typeof OFFLINE_WORKER_PROTOCOL; type: "request-cleanup"; messageToken: string; pair: AppReleasePairV1 }>
  | Readonly<{ protocol: typeof OFFLINE_WORKER_PROTOCOL; type: "request-rollback"; messageToken: string; currentPair: AppReleasePairV1; targetPair: AppReleasePairV1; confirmationToken: string }>;
export type OfflineWorkerToClientV1 =
  | Readonly<{ protocol: typeof OFFLINE_WORKER_PROTOCOL; type: "worker-identity"; messageToken: string; pair: AppReleasePairV1; precacheSetSha256: Sha256Hex }>
  | Readonly<{ protocol: typeof OFFLINE_WORKER_PROTOCOL; type: "activation-deferred"; messageToken: string; candidatePair: AppReleasePairV1; reason: "update-coordinator-not-installed" }>
  | Readonly<{ protocol: typeof OFFLINE_WORKER_PROTOCOL; type: "lease-state"; messageToken: string; lease: ClientLeaseV1 }>
  | Readonly<{ protocol: typeof OFFLINE_WORKER_PROTOCOL; type: "capability"; messageToken: string; capability: RuntimeCapabilityV1 }>
  | Readonly<{ protocol: typeof OFFLINE_WORKER_PROTOCOL; type: "update-state"; messageToken: string | null; update: UpdateCapabilityV1 }>
  | Readonly<{ protocol: typeof OFFLINE_WORKER_PROTOCOL; type: "cleanup-result"; messageToken: string; pair: AppReleasePairV1; deletedPairs: readonly AppReleasePairV1[]; freedBytes: number }>
  | Readonly<{ protocol: typeof OFFLINE_WORKER_PROTOCOL; type: "technical-error"; messageToken: string | null; error: OfflineTechnicalErrorV1 }>;
export type ClientToOfflineWorkerV2 = Readonly<{
  protocol: typeof OFFLINE_WORKER_PROTOCOL_V2;
  type: "query-capability";
  messageToken: string;
  requirements: InteractionRequirementsV2;
}>;
export type OfflineWorkerToClientV2 =
  | Readonly<{ protocol: typeof OFFLINE_WORKER_PROTOCOL_V2; type: "capability"; messageToken: string; capability: RuntimeCapabilityV2 }>
  | Readonly<{ protocol: typeof OFFLINE_WORKER_PROTOCOL_V2; type: "technical-error"; messageToken: string | null; error: OfflineTechnicalErrorV2 }>;

export function validateClientToOfflineWorkerMessage(value: unknown): ClientToOfflineWorkerV1 {
  if (typeof value !== "object" || value === null || Array.isArray(value)) fail("worker message must be an object.");
  const source = value as Record<string, unknown>;
  if (source.protocol !== OFFLINE_WORKER_PROTOCOL) fail("Offline worker protocol version is unsupported.");
  const messageToken = protocolId(source.messageToken, "messageToken");
  const type = source.type;
  if (type === "inspect-identity") {
    const record = exactRecord(value, ["protocol", "type", "messageToken", "pair"], "identity message");
    return Object.freeze({ protocol: OFFLINE_WORKER_PROTOCOL, type, messageToken, pair: validateAppReleasePair(record.pair) });
  }
  if (type === "acquire-lease" || type === "heartbeat-lease" || type === "release-lease") {
    const record = exactRecord(value, ["protocol", "type", "messageToken", "leaseId", "pair"], `${type} message`);
    return Object.freeze({ protocol: OFFLINE_WORKER_PROTOCOL, type, messageToken, leaseId: protocolId(record.leaseId, "leaseId"), pair: validateAppReleasePair(record.pair) });
  }
  if (type === "query-capability") {
    return Object.freeze({ protocol: OFFLINE_WORKER_PROTOCOL, type, messageToken, requirements: validateInteractionRequirements(exactRecord(value, ["protocol", "type", "messageToken", "requirements"], "capability message").requirements) });
  }
  if (type === "prepare-update") {
    const record = exactRecord(value, ["protocol", "type", "messageToken", "currentPair", "candidate"], "prepare update message");
    const currentPair = validateAppReleasePair(record.currentPair);
    const candidate = validateAppAuthority(record.candidate);
    assertPersistentEligibility(persistenceEligibility(candidate));
    if (samePair(currentPair, candidate)) fail("An update candidate must differ from the current pair.");
    return Object.freeze({ protocol: OFFLINE_WORKER_PROTOCOL, type, messageToken, currentPair, candidate });
  }
  if (type === "activate-update") {
    const record = exactRecord(value, ["protocol", "type", "messageToken", "candidatePair", "confirmationToken"], "activate update message");
    return Object.freeze({ protocol: OFFLINE_WORKER_PROTOCOL, type, messageToken, candidatePair: validateAppReleasePair(record.candidatePair), confirmationToken: protocolId(record.confirmationToken, "confirmationToken") });
  }
  if (type === "request-cleanup") {
    const record = exactRecord(value, ["protocol", "type", "messageToken", "pair"], "cleanup message");
    return Object.freeze({ protocol: OFFLINE_WORKER_PROTOCOL, type, messageToken, pair: validateAppReleasePair(record.pair) });
  }
  if (type === "request-rollback") {
    const record = exactRecord(value, ["protocol", "type", "messageToken", "currentPair", "targetPair", "confirmationToken"], "rollback message");
    const rollback = validateRollbackRequest({ contractVersion: 1, currentPair: record.currentPair, targetPair: record.targetPair, confirmationToken: record.confirmationToken });
    return Object.freeze({ protocol: OFFLINE_WORKER_PROTOCOL, type, messageToken, currentPair: rollback.currentPair, targetPair: rollback.targetPair, confirmationToken: rollback.confirmationToken });
  }
  return fail("worker message type is unsupported.");
}

function nullableId(value: unknown): string | null { return value === null ? null : protocolId(value, "messageToken"); }
export function validateOfflineWorkerToClientMessage(value: unknown): OfflineWorkerToClientV1 {
  if (typeof value !== "object" || value === null || Array.isArray(value)) fail("worker response must be an object.");
  const source = value as Record<string, unknown>;
  if (source.protocol !== OFFLINE_WORKER_PROTOCOL) fail("Offline worker protocol version is unsupported.");
  const type = source.type;
  if (type === "worker-identity") {
    const record = exactRecord(value, ["protocol", "type", "messageToken", "pair", "precacheSetSha256"], "worker identity response");
    return Object.freeze({ protocol: OFFLINE_WORKER_PROTOCOL, type, messageToken: protocolId(record.messageToken, "messageToken"), pair: validateAppReleasePair(record.pair), precacheSetSha256: sha256Hex(record.precacheSetSha256, "precacheSetSha256") });
  }
  if (type === "activation-deferred") {
    const record = exactRecord(value, ["protocol", "type", "messageToken", "candidatePair", "reason"], "activation deferred response");
    if (record.reason !== "update-coordinator-not-installed") fail("Activation deferral reason is unsupported.");
    return Object.freeze({ protocol: OFFLINE_WORKER_PROTOCOL, type, messageToken: protocolId(record.messageToken, "messageToken"), candidatePair: validateAppReleasePair(record.candidatePair), reason: record.reason });
  }
  if (type === "lease-state") {
    const record = exactRecord(value, ["protocol", "type", "messageToken", "lease"], "lease-state response");
    return Object.freeze({ protocol: OFFLINE_WORKER_PROTOCOL, type, messageToken: protocolId(record.messageToken, "messageToken"), lease: validateClientLease(record.lease) });
  }
  if (type === "capability") {
    const record = exactRecord(value, ["protocol", "type", "messageToken", "capability"], "capability response");
    return Object.freeze({ protocol: OFFLINE_WORKER_PROTOCOL, type, messageToken: protocolId(record.messageToken, "messageToken"), capability: validateRuntimeCapability(record.capability) });
  }
  if (type === "update-state") {
    const record = exactRecord(value, ["protocol", "type", "messageToken", "update"], "update-state response");
    return Object.freeze({ protocol: OFFLINE_WORKER_PROTOCOL, type, messageToken: nullableId(record.messageToken), update: validateUpdateCapability(record.update) });
  }
  if (type === "cleanup-result") {
    const record = exactRecord(value, ["protocol", "type", "messageToken", "pair", "deletedPairs", "freedBytes"], "cleanup response");
    if (!Array.isArray(record.deletedPairs)) fail("deletedPairs must be an array.");
    const pair = validateAppReleasePair(record.pair);
    const deletedPairs = Object.freeze(record.deletedPairs.map(validateAppReleasePair));
    if (deletedPairs.some((deleted) => samePair(pair, deleted))) fail("Cleanup cannot delete the protected pair.");
    return Object.freeze({ protocol: OFFLINE_WORKER_PROTOCOL, type, messageToken: protocolId(record.messageToken, "messageToken"), pair, deletedPairs, freedBytes: nonNegativeInteger(record.freedBytes, "freedBytes") });
  }
  if (type === "technical-error") {
    const record = exactRecord(value, ["protocol", "type", "messageToken", "error"], "technical-error response");
    return Object.freeze({ protocol: OFFLINE_WORKER_PROTOCOL, type, messageToken: nullableId(record.messageToken), error: validateOfflineTechnicalError(record.error) });
  }
  return fail("worker response type is unsupported.");
}

export function validateClientToOfflineWorkerV2Message(value: unknown): ClientToOfflineWorkerV2 {
  const record = exactRecord(value, ["protocol", "type", "messageToken", "requirements"], "v2 capability message");
  if (record.protocol !== OFFLINE_WORKER_PROTOCOL_V2 || record.type !== "query-capability") {
    fail("Offline worker protocol version or message type is unsupported.");
  }
  return Object.freeze({
    protocol: OFFLINE_WORKER_PROTOCOL_V2,
    type: "query-capability",
    messageToken: protocolId(record.messageToken, "messageToken"),
    requirements: validateInteractionRequirementsV2(record.requirements),
  });
}

export function validateOfflineWorkerToClientV2Message(value: unknown): OfflineWorkerToClientV2 {
  if (typeof value !== "object" || value === null || Array.isArray(value)) fail("v2 worker response must be an object.");
  const source = value as Record<string, unknown>;
  if (source.protocol !== OFFLINE_WORKER_PROTOCOL_V2) fail("Offline worker protocol version is unsupported.");
  if (source.type === "capability") {
    const record = exactRecord(value, ["protocol", "type", "messageToken", "capability"], "v2 capability response");
    return Object.freeze({
      protocol: OFFLINE_WORKER_PROTOCOL_V2,
      type: "capability",
      messageToken: protocolId(record.messageToken, "messageToken"),
      capability: validateRuntimeCapabilityV2(record.capability),
    });
  }
  if (source.type === "technical-error") {
    const record = exactRecord(value, ["protocol", "type", "messageToken", "error"], "v2 technical-error response");
    return Object.freeze({
      protocol: OFFLINE_WORKER_PROTOCOL_V2,
      type: "technical-error",
      messageToken: nullableId(record.messageToken),
      error: validateOfflineTechnicalErrorV2(record.error),
    });
  }
  return fail("v2 worker response type is unsupported.");
}
