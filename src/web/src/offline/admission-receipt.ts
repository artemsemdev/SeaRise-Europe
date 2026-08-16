import { cacheNamespaces, validateAppReleasePair, type AppReleasePairV1 } from "./contracts/keys";
import {
  persistenceEligibility,
  validateAppAuthority,
  validateRangeIdentity,
  validateWholeResourceAuthority,
  type AppAuthorityV1,
  type RangeIdentityV1,
  type WholeResourceAuthorityV1,
} from "./contracts/v1";
import type {
  WholeResourceAdmissionV1,
  WholeResourceStore,
} from "./whole-resource-cache";
import type {
  RangeAdmissionV1,
  RangeStore,
  VerifiedRangeWrite,
} from "./range-store";

const RECEIPT_DATABASE = "searise-offline:admission-receipts:v1";
const RECEIPT_STORE = "accepted-receipts";
const RECEIPT_DATABASE_VERSION = 1;
const SHA256 = /^[0-9a-f]{64}$/u;
const OPERATION_ID = /^[A-Za-z0-9._-]{1,64}$/u;

export interface AdmissionResourceDigestV1 {
  readonly identitySha256: string;
  readonly byteSize: number;
}

export interface AdmissionPlanIdentityV1 {
  readonly contractVersion: 1;
  readonly pair: AppReleasePairV1;
  readonly resourcePlanSha256: string;
  readonly wholeResourcesSha256: string;
  readonly rangeResourcesSha256: string;
  readonly wholeResources: readonly AdmissionResourceDigestV1[];
  readonly rangeResources: readonly AdmissionResourceDigestV1[];
}

export interface VerifiedAdmissionReceiptV1 {
  readonly contractVersion: 1;
  readonly receiptKind: "verified-resource-admission";
  readonly pair: AppReleasePairV1;
  readonly resourcePlanSha256: string;
  readonly wholeResourcesSha256: string;
  readonly rangeResourcesSha256: string;
  readonly wholeResourceCount: number;
  readonly wholeResourceBytes: number;
  readonly rangeResourceCount: number;
  readonly rangeResourceBytes: number;
}

export interface AcceptedAdmissionGateV1 {
  readonly contractVersion: 1;
  readonly pair: AppReleasePairV1;
  readonly resourcePlanSha256: string;
  readonly receiptSha256: string;
}

export interface AdmissionReceiptStore {
  readonly mode: "persistent" | "memory-only";
  publishLast(
    proof: VerifiedAdmissionProofV1,
    signal: AbortSignal,
  ): Promise<AcceptedAdmissionGateV1>;
  accepted(plan: AdmissionPlanIdentityV1): Promise<AcceptedAdmissionGateV1 | null>;
  deleteIfCurrent(gate: AcceptedAdmissionGateV1): Promise<boolean>;
  close(): void;
}

export interface VerifiedAdmissionProofV1 {
  readonly contractVersion: 1;
  readonly plan: AdmissionPlanIdentityV1;
  readonly operationId: string;
  readonly expectedPreviousReceiptSha256: string | null;
}

export interface CoordinatedAdmissionResultV1 {
  readonly contractVersion: 1;
  readonly gate: AcceptedAdmissionGateV1;
  readonly wholeAdmission: WholeResourceAdmissionV1;
  readonly rangeAdmission: RangeAdmissionV1;
}

export class AdmissionReceiptError extends Error {
  readonly code: "AuthorityRejected" | "IntegrityFailed" | "Conflict" | "Aborted" | "StorageFailed";

  constructor(code: AdmissionReceiptError["code"], message: string, cause?: unknown) {
    super(message, { cause });
    this.name = "AdmissionReceiptError";
    this.code = code;
  }
}

interface StoredReceipt {
  readonly key: string;
  readonly receipt: VerifiedAdmissionReceiptV1;
  readonly receiptSha256: string;
}

interface GateAuthority {
  readonly whole: ReadonlySet<string>;
  readonly ranges: ReadonlySet<string>;
}

const VERIFIED_PLANS = new WeakSet<object>();
const VERIFIED_PROOFS = new WeakSet<object>();
const ACCEPTED_GATES = new WeakMap<object, GateAuthority>();

function samePair(left: AppReleasePairV1, right: AppReleasePairV1): boolean {
  return left.appBuildId === right.appBuildId && left.dataReleaseId === right.dataReleaseId;
}

function abortFailure(): AdmissionReceiptError {
  return new AdmissionReceiptError("Aborted", "Coordinated resource admission was cancelled before receipt publication.");
}

function requireSignal(signal: AbortSignal): void {
  if (signal.aborted) throw abortFailure();
}

function operationId(value: string): string {
  if (!OPERATION_ID.test(value)) {
    throw new AdmissionReceiptError("AuthorityRejected", "Admission operation identity is invalid.");
  }
  return value;
}

function sha256(value: unknown, name: string): string {
  if (typeof value !== "string" || !SHA256.test(value)) {
    throw new AdmissionReceiptError("IntegrityFailed", `${name} is not a lowercase SHA-256 digest.`);
  }
  return value;
}

function positiveSafeInteger(value: unknown, name: string): number {
  if (!Number.isSafeInteger(value) || (value as number) < 0) {
    throw new AdmissionReceiptError("IntegrityFailed", `${name} must be a non-negative safe integer.`);
  }
  return value as number;
}

function exactKeys(value: object, expected: readonly string[], name: string): void {
  const keys = Object.keys(value);
  const allowed = new Set(expected);
  if (keys.length !== allowed.size || keys.some((key) => !allowed.has(key))) {
    throw new AdmissionReceiptError("IntegrityFailed", `${name} contains missing or additional fields.`);
  }
}

function hexadecimal(bytes: ArrayBuffer): string {
  return Array.from(new Uint8Array(bytes), (value) => value.toString(16).padStart(2, "0")).join("");
}

async function digestJson(value: unknown, subtle: SubtleCrypto): Promise<string> {
  const bytes = new TextEncoder().encode(JSON.stringify(value));
  return hexadecimal(await subtle.digest("SHA-256", bytes));
}

function normalizedWhole(authority: WholeResourceAuthorityV1): object {
  const value = validateWholeResourceAuthority(authority);
  if (value.authorityKind !== "release-artifact") {
    throw new AdmissionReceiptError("AuthorityRejected", "Coordinated release admission cannot contain app assets.");
  }
  if (value.path.endsWith(".pmtiles") || value.mediaType === "application/vnd.pmtiles") {
    throw new AdmissionReceiptError("AuthorityRejected", "PMTiles cannot enter an admission receipt or resource store.");
  }
  return {
    contractVersion: value.contractVersion,
    authorityKind: value.authorityKind,
    pair: value.pair,
    artifactId: value.artifactId,
    role: value.role,
    canonicalUrl: value.canonicalUrl,
    path: value.path,
    mediaType: value.mediaType,
    byteSize: value.byteSize,
    sha256: value.sha256,
    etag: value.etag,
  };
}

function normalizedRange(identity: RangeIdentityV1): object {
  const value = validateRangeIdentity(identity);
  if (
    value.authority.role !== "projection-analysis-cog" ||
    value.authority.path.endsWith(".pmtiles") ||
    value.authority.mediaType === "application/vnd.pmtiles"
  ) {
    throw new AdmissionReceiptError("AuthorityRejected", "Only exact scientific COG chunks may enter a range admission receipt.");
  }
  return {
    contractVersion: value.contractVersion,
    authority: value.authority,
    interval: value.interval,
    authorizedIntervalSha256: value.authorizedIntervalSha256,
  };
}

export async function wholeResourceIdentitySha256(
  authority: WholeResourceAuthorityV1,
  subtle: SubtleCrypto,
): Promise<string> {
  return digestJson(normalizedWhole(authority), subtle);
}

export async function rangeIdentitySha256(
  identity: RangeIdentityV1,
  subtle: SubtleCrypto,
): Promise<string> {
  return digestJson(normalizedRange(identity), subtle);
}

function resourceDigest(identitySha256: string, byteSize: number): AdmissionResourceDigestV1 {
  return Object.freeze({
    identitySha256: sha256(identitySha256, "resource identity"),
    byteSize: positiveSafeInteger(byteSize, "resource byteSize"),
  });
}

async function resourceSet(
  resources: readonly Readonly<{ identitySha256: string; byteSize: number }>[] ,
  subtle: SubtleCrypto,
): Promise<Readonly<{ entries: readonly AdmissionResourceDigestV1[]; sha256: string }>> {
  const entries = resources
    .map(({ identitySha256, byteSize }) => resourceDigest(identitySha256, byteSize))
    .sort((left, right) => left.identitySha256.localeCompare(right.identitySha256));
  if (new Set(entries.map((entry) => entry.identitySha256)).size !== entries.length) {
    throw new AdmissionReceiptError("AuthorityRejected", "An admission plan cannot contain duplicate resource identities.");
  }
  return Object.freeze({ entries: Object.freeze(entries), sha256: await digestJson(entries, subtle) });
}

export async function createAdmissionPlanIdentity(input: Readonly<{
  pair: AppReleasePairV1;
  wholeResources: readonly WholeResourceAuthorityV1[];
  rangeResources: readonly RangeIdentityV1[];
  subtle: SubtleCrypto;
}>): Promise<AdmissionPlanIdentityV1> {
  const pair = validateAppReleasePair(input.pair);
  const whole = await resourceSet(await Promise.all(input.wholeResources.map(async (authority) => {
    const validated = validateWholeResourceAuthority(authority);
    if (!samePair(pair, validated.pair)) {
      throw new AdmissionReceiptError("AuthorityRejected", "Whole resource belongs to another app/release pair.");
    }
    return { identitySha256: await wholeResourceIdentitySha256(validated, input.subtle), byteSize: validated.byteSize };
  })), input.subtle);
  const ranges = await resourceSet(await Promise.all(input.rangeResources.map(async (identity) => {
    const validated = validateRangeIdentity(identity);
    if (!samePair(pair, validated.authority.pair)) {
      throw new AdmissionReceiptError("AuthorityRejected", "Range resource belongs to another app/release pair.");
    }
    return {
      identitySha256: await rangeIdentitySha256(validated, input.subtle),
      byteSize: validated.interval.endExclusive - validated.interval.start,
    };
  })), input.subtle);
  const resourcePlanSha256 = await digestJson({
    contractVersion: 1,
    pair,
    wholeResourcesSha256: whole.sha256,
    rangeResourcesSha256: ranges.sha256,
  }, input.subtle);
  const plan = Object.freeze({
    contractVersion: 1 as const,
    pair,
    resourcePlanSha256,
    wholeResourcesSha256: whole.sha256,
    rangeResourcesSha256: ranges.sha256,
    wholeResources: whole.entries,
    rangeResources: ranges.entries,
  });
  VERIFIED_PLANS.add(plan);
  return plan;
}

function checkedPlan(plan: AdmissionPlanIdentityV1, pair: AppReleasePairV1): AdmissionPlanIdentityV1 {
  if (!VERIFIED_PLANS.has(plan) || !samePair(plan.pair, pair)) {
    throw new AdmissionReceiptError("AuthorityRejected", "Admission plan identity was not verified for this app/release pair.");
  }
  return plan;
}

function receiptFor(
  plan: AdmissionPlanIdentityV1,
): VerifiedAdmissionReceiptV1 {
  return Object.freeze({
    contractVersion: 1,
    receiptKind: "verified-resource-admission",
    pair: plan.pair,
    resourcePlanSha256: plan.resourcePlanSha256,
    wholeResourcesSha256: plan.wholeResourcesSha256,
    rangeResourcesSha256: plan.rangeResourcesSha256,
    wholeResourceCount: plan.wholeResources.length,
    wholeResourceBytes: plan.wholeResources.reduce((sum, resource) => sum + resource.byteSize, 0),
    rangeResourceCount: plan.rangeResources.length,
    rangeResourceBytes: plan.rangeResources.reduce((sum, resource) => sum + resource.byteSize, 0),
  });
}

function validateReceipt(value: unknown): VerifiedAdmissionReceiptV1 {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new AdmissionReceiptError("IntegrityFailed", "Stored admission receipt is not an object.");
  }
  exactKeys(value, [
    "contractVersion", "receiptKind", "pair", "resourcePlanSha256", "wholeResourcesSha256",
    "rangeResourcesSha256", "wholeResourceCount", "wholeResourceBytes", "rangeResourceCount",
    "rangeResourceBytes",
  ], "admission receipt");
  const record = value as Record<string, unknown>;
  if (record.contractVersion !== 1 || record.receiptKind !== "verified-resource-admission") {
    throw new AdmissionReceiptError("IntegrityFailed", "Stored admission receipt version or kind is invalid.");
  }
  return Object.freeze({
    contractVersion: 1,
    receiptKind: "verified-resource-admission",
    pair: validateAppReleasePair(record.pair),
    resourcePlanSha256: sha256(record.resourcePlanSha256, "resource plan"),
    wholeResourcesSha256: sha256(record.wholeResourcesSha256, "whole resource set"),
    rangeResourcesSha256: sha256(record.rangeResourcesSha256, "range resource set"),
    wholeResourceCount: positiveSafeInteger(record.wholeResourceCount, "wholeResourceCount"),
    wholeResourceBytes: positiveSafeInteger(record.wholeResourceBytes, "wholeResourceBytes"),
    rangeResourceCount: positiveSafeInteger(record.rangeResourceCount, "rangeResourceCount"),
    rangeResourceBytes: positiveSafeInteger(record.rangeResourceBytes, "rangeResourceBytes"),
  });
}

function receiptMatchesPlan(receipt: VerifiedAdmissionReceiptV1, plan: AdmissionPlanIdentityV1): boolean {
  return samePair(receipt.pair, plan.pair) &&
    receipt.resourcePlanSha256 === plan.resourcePlanSha256 &&
    receipt.wholeResourcesSha256 === plan.wholeResourcesSha256 &&
    receipt.rangeResourcesSha256 === plan.rangeResourcesSha256 &&
    receipt.wholeResourceCount === plan.wholeResources.length &&
    receipt.wholeResourceBytes === plan.wholeResources.reduce((sum, resource) => sum + resource.byteSize, 0) &&
    receipt.rangeResourceCount === plan.rangeResources.length &&
    receipt.rangeResourceBytes === plan.rangeResources.reduce((sum, resource) => sum + resource.byteSize, 0);
}

function receiptKey(plan: AdmissionPlanIdentityV1): string {
  return receiptKeyFor(plan.pair, plan.resourcePlanSha256);
}

function receiptKeyFor(pair: AppReleasePairV1, resourcePlanSha256: string): string {
  return JSON.stringify([cacheNamespaces(pair).pairKey, resourcePlanSha256]);
}

async function validateStored(
  stored: StoredReceipt | undefined,
  plan: AdmissionPlanIdentityV1,
  subtle: SubtleCrypto,
): Promise<AcceptedAdmissionGateV1 | null> {
  if (!stored) return null;
  try {
    if (typeof stored !== "object") return null;
    exactKeys(stored, ["key", "receipt", "receiptSha256"], "stored admission receipt");
    if (stored.key !== receiptKey(plan)) return null;
    const receipt = validateReceipt(stored.receipt);
    const actualSha256 = await digestJson(receipt, subtle);
    if (sha256(stored.receiptSha256, "stored receipt") !== actualSha256 || !receiptMatchesPlan(receipt, plan)) {
      return null;
    }
    const gate = Object.freeze({
      contractVersion: 1 as const,
      pair: plan.pair,
      resourcePlanSha256: plan.resourcePlanSha256,
      receiptSha256: actualSha256,
    });
    ACCEPTED_GATES.set(gate, {
      whole: new Set(plan.wholeResources.map((resource) => resource.identitySha256)),
      ranges: new Set(plan.rangeResources.map((resource) => resource.identitySha256)),
    });
    return gate;
  } catch {
    return null;
  }
}

export async function assertAcceptedWholeResource(
  gate: AcceptedAdmissionGateV1,
  authority: WholeResourceAuthorityV1,
  subtle: SubtleCrypto,
): Promise<void> {
  const accepted = ACCEPTED_GATES.get(gate);
  const validated = validateWholeResourceAuthority(authority);
  if (!accepted || !samePair(gate.pair, validated.pair) ||
      !accepted.whole.has(await wholeResourceIdentitySha256(validated, subtle))) {
    throw new AdmissionReceiptError("AuthorityRejected", "Whole resource is not covered by the current accepted receipt.");
  }
}

export async function assertAcceptedRangeResource(
  gate: AcceptedAdmissionGateV1,
  identity: RangeIdentityV1,
  subtle: SubtleCrypto,
): Promise<void> {
  const accepted = ACCEPTED_GATES.get(gate);
  const validated = validateRangeIdentity(identity);
  if (!accepted || !samePair(gate.pair, validated.authority.pair) ||
      !accepted.ranges.has(await rangeIdentitySha256(validated, subtle))) {
    throw new AdmissionReceiptError("AuthorityRejected", "Range resource is not covered by the current accepted receipt.");
  }
}

abstract class BaseReceiptStore implements AdmissionReceiptStore {
  abstract readonly mode: "persistent" | "memory-only";
  readonly pair: AppReleasePairV1;
  readonly subtle: SubtleCrypto;

  constructor(pair: AppReleasePairV1, subtle: SubtleCrypto) {
    this.pair = validateAppReleasePair(pair);
    this.subtle = subtle;
  }

  abstract readStored(key: string): Promise<StoredReceipt | undefined>;
  abstract publishStored(stored: StoredReceipt, expectedPrevious: string | null, signal: AbortSignal): Promise<void>;
  abstract deleteStored(key: string, receiptSha256: string): Promise<boolean>;
  abstract close(): void;

  async publishLast(proof: VerifiedAdmissionProofV1, signal: AbortSignal): Promise<AcceptedAdmissionGateV1> {
    if (!VERIFIED_PROOFS.has(proof)) {
      throw new AdmissionReceiptError("AuthorityRejected", "Admission receipt proof was not minted after exact resource readback.");
    }
    const plan = checkedPlan(proof.plan, this.pair);
    requireSignal(signal);
    const receipt = receiptFor(plan);
    const receiptSha256 = await digestJson(receipt, this.subtle);
    requireSignal(signal);
    await this.publishStored(Object.freeze({
      key: receiptKey(plan),
      receipt,
      receiptSha256,
    }), proof.expectedPreviousReceiptSha256, signal);
    const gate = await validateStored(await this.readStored(receiptKey(plan)), plan, this.subtle);
    if (!gate || gate.receiptSha256 !== receiptSha256) {
      await this.deleteStored(receiptKey(plan), receiptSha256).catch(() => false);
      throw new AdmissionReceiptError("StorageFailed", "Published admission receipt failed exact readback.");
    }
    return gate;
  }

  async accepted(planInput: AdmissionPlanIdentityV1): Promise<AcceptedAdmissionGateV1 | null> {
    const plan = checkedPlan(planInput, this.pair);
    return validateStored(await this.readStored(receiptKey(plan)), plan, this.subtle);
  }

  async deleteIfCurrent(gate: AcceptedAdmissionGateV1): Promise<boolean> {
    if (!ACCEPTED_GATES.has(gate) || !samePair(gate.pair, this.pair)) {
      throw new AdmissionReceiptError("AuthorityRejected", "Admission gate was not issued by a verified receipt store.");
    }
    return this.deleteStored(receiptKeyFor(this.pair, gate.resourcePlanSha256), gate.receiptSha256);
  }
}

class MemoryAdmissionReceiptStore extends BaseReceiptStore {
  readonly mode = "memory-only" as const;
  readonly #stored = new Map<string, StoredReceipt>();

  async readStored(key: string): Promise<StoredReceipt | undefined> { return this.#stored.get(key); }

  async publishStored(stored: StoredReceipt, expectedPrevious: string | null, signal: AbortSignal): Promise<void> {
    requireSignal(signal);
    const current = this.#stored.get(stored.key)?.receiptSha256 ?? null;
    if (current !== expectedPrevious) {
      throw new AdmissionReceiptError("Conflict", "Accepted receipt changed during coordinated admission.");
    }
    this.#stored.set(stored.key, stored);
  }

  async deleteStored(key: string, receiptSha256: string): Promise<boolean> {
    if (this.#stored.get(key)?.receiptSha256 !== receiptSha256) return false;
    this.#stored.delete(key);
    return true;
  }

  close(): void { this.#stored.clear(); }
}

function request<T>(value: IDBRequest<T>): Promise<T> {
  return new Promise((resolve, reject) => {
    value.onsuccess = () => resolve(value.result);
    value.onerror = () => reject(value.error);
  });
}

function completed(transaction: IDBTransaction): Promise<void> {
  return new Promise((resolve, reject) => {
    transaction.oncomplete = () => resolve();
    transaction.onabort = transaction.onerror = () => reject(
      transaction.error ?? new DOMException("Admission receipt transaction aborted.", "AbortError"),
    );
  });
}

class IndexedDbAdmissionReceiptStore extends BaseReceiptStore {
  readonly mode = "persistent" as const;
  readonly #idb: IDBFactory;
  #database: Promise<IDBDatabase> | null = null;

  constructor(pair: AppReleasePairV1, subtle: SubtleCrypto, indexedDB: IDBFactory) {
    super(pair, subtle);
    this.#idb = indexedDB;
  }

  #open(): Promise<IDBDatabase> {
    if (!this.#database) this.#database = new Promise((resolve, reject) => {
      const open = this.#idb.open(RECEIPT_DATABASE, RECEIPT_DATABASE_VERSION);
      open.onupgradeneeded = () => {
        if (!open.result.objectStoreNames.contains(RECEIPT_STORE)) {
          open.result.createObjectStore(RECEIPT_STORE, { keyPath: "key" });
        }
      };
      open.onsuccess = () => { open.result.onversionchange = () => open.result.close(); resolve(open.result); };
      open.onerror = () => reject(open.error ?? new AdmissionReceiptError("StorageFailed", "Admission receipt database open failed."));
      open.onblocked = () => reject(new AdmissionReceiptError("StorageFailed", "Admission receipt database open was blocked."));
    });
    return this.#database;
  }

  async readStored(key: string): Promise<StoredReceipt | undefined> {
    const database = await this.#open();
    const transaction = database.transaction(RECEIPT_STORE, "readonly");
    const done = completed(transaction);
    const stored = await request(transaction.objectStore(RECEIPT_STORE).get(key)) as StoredReceipt | undefined;
    await done;
    return stored;
  }

  async publishStored(stored: StoredReceipt, expectedPrevious: string | null, signal: AbortSignal): Promise<void> {
    requireSignal(signal);
    const database = await this.#open();
    const transaction = database.transaction(RECEIPT_STORE, "readwrite");
    const done = completed(transaction);
    const abort = () => {
      try { transaction.abort(); } catch { /* The receipt already committed and is authoritative. */ }
    };
    signal.addEventListener("abort", abort, { once: true });
    try {
      const store = transaction.objectStore(RECEIPT_STORE);
      const current = await request(store.get(stored.key)) as StoredReceipt | undefined;
      if ((current?.receiptSha256 ?? null) !== expectedPrevious) {
        transaction.abort();
        await done.catch(() => undefined);
        throw new AdmissionReceiptError("Conflict", "Accepted receipt changed during coordinated admission.");
      }
      requireSignal(signal);
      store.put(stored);
      await done;
    } catch (error) {
      if (error instanceof AdmissionReceiptError) throw error;
      if (signal.aborted) throw abortFailure();
      throw new AdmissionReceiptError("StorageFailed", "Admission receipt publication failed.", error);
    } finally {
      signal.removeEventListener("abort", abort);
    }
  }

  async deleteStored(key: string, receiptSha256: string): Promise<boolean> {
    const database = await this.#open();
    const transaction = database.transaction(RECEIPT_STORE, "readwrite");
    const done = completed(transaction);
    const store = transaction.objectStore(RECEIPT_STORE);
    const current = await request(store.get(key)) as StoredReceipt | undefined;
    if (current?.receiptSha256 !== receiptSha256) {
      transaction.abort();
      await done.catch(() => undefined);
      return false;
    }
    store.delete(current.key);
    await done;
    return true;
  }

  close(): void {
    if (this.#database) void this.#database.then((database) => database.close());
    this.#database = null;
  }
}

function samePlan(left: AdmissionPlanIdentityV1, right: AdmissionPlanIdentityV1): boolean {
  return samePair(left.pair, right.pair) &&
    left.resourcePlanSha256 === right.resourcePlanSha256 &&
    left.wholeResourcesSha256 === right.wholeResourcesSha256 &&
    left.rangeResourcesSha256 === right.rangeResourcesSha256;
}

/**
 * Coordinates physical admission primitives but claims only receipt-gated
 * logical atomicity. Conditional rollback is best-effort; crash leftovers are
 * unreceipted and therefore unavailable through authoritative read methods.
 */
export async function coordinateVerifiedAdmission(input: Readonly<{
  plan: AdmissionPlanIdentityV1;
  operationId: string;
  expectedPreviousReceiptSha256: string | null;
  wholeResources: readonly WholeResourceAuthorityV1[];
  rangeWrites: readonly VerifiedRangeWrite[];
  wholeStore: WholeResourceStore;
  rangeStore: RangeStore;
  receiptStore: AdmissionReceiptStore;
  subtle: SubtleCrypto;
  signal: AbortSignal;
}>): Promise<CoordinatedAdmissionResultV1> {
  const plan = checkedPlan(input.plan, input.plan.pair);
  const operation = operationId(input.operationId);
  requireSignal(input.signal);
  const actualPlan = await createAdmissionPlanIdentity({
    pair: plan.pair,
    wholeResources: input.wholeResources,
    rangeResources: input.rangeWrites.map((write) => write.identity),
    subtle: input.subtle,
  });
  if (!samePlan(plan, actualPlan)) {
    throw new AdmissionReceiptError("AuthorityRejected", "Admission resources do not match the exact verified resource-plan identity.");
  }

  let rangeAdmission: RangeAdmissionV1 | undefined;
  let wholeAdmission: WholeResourceAdmissionV1 | undefined;
  let published = false;
  try {
    rangeAdmission = await input.rangeStore.admitVerifiedBatch(input.rangeWrites, {
      operationId: operation,
      signal: input.signal,
    });
    requireSignal(input.signal);
    wholeAdmission = await input.wholeStore.fetchAndAdmitBatch(input.wholeResources, {
      operationId: operation,
      signal: input.signal,
    });
    requireSignal(input.signal);

    for (const authority of input.wholeResources) {
      const read = await input.wholeStore.read(authority);
      if (read.state !== "hit") {
        throw new AdmissionReceiptError("IntegrityFailed", "A whole resource failed exact post-admission readback.");
      }
      requireSignal(input.signal);
    }
    for (const { identity } of input.rangeWrites) {
      const bytes = await input.rangeStore.readExactOrContaining(identity);
      if (!bytes || bytes.byteLength !== identity.interval.endExclusive - identity.interval.start) {
        throw new AdmissionReceiptError("IntegrityFailed", "A range resource failed exact post-admission readback.");
      }
      requireSignal(input.signal);
    }

    const proof = Object.freeze({
      contractVersion: 1 as const,
      plan,
      operationId: operation,
      expectedPreviousReceiptSha256: input.expectedPreviousReceiptSha256,
    });
    VERIFIED_PROOFS.add(proof);
    const gate = await input.receiptStore.publishLast(proof, input.signal);
    published = true;
    return Object.freeze({
      contractVersion: 1,
      gate,
      wholeAdmission,
      rangeAdmission,
    });
  } catch (error) {
    if (!published) {
      await Promise.allSettled([
        ...(wholeAdmission ? [input.wholeStore.rollbackAdmission(wholeAdmission)] : []),
        ...(rangeAdmission ? [input.rangeStore.rollbackAdmission(rangeAdmission)] : []),
      ]);
    }
    throw error;
  }
}

export function createAdmissionReceiptStore(
  authorityInput: AppAuthorityV1,
  subtle: SubtleCrypto,
  options: Readonly<{ indexedDB?: IDBFactory; localCandidate?: boolean }> = {},
): AdmissionReceiptStore {
  const authority = validateAppAuthority(authorityInput);
  const pair = validateAppReleasePair({
    contractVersion: 1,
    appBuildId: authority.appBuildId,
    dataReleaseId: authority.dataReleaseId,
  });
  const eligibility = persistenceEligibility(authority, options.localCandidate === true);
  if (eligibility.mode === "memory-only") return new MemoryAdmissionReceiptStore(pair, subtle);
  if (!options.indexedDB) {
    throw new AdmissionReceiptError("StorageFailed", "IndexedDB is unavailable for persistent admission receipts.");
  }
  return new IndexedDbAdmissionReceiptStore(pair, subtle, options.indexedDB);
}
