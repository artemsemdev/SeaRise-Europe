import type { ResolvedArtifact } from "../domain/release";
import { TechnicalFailure } from "../domain/release";
import type { ArtifactTransport } from "../data/artifact-integrity";
import type {
  CogRangeTransport,
} from "../data/cog-analysis-reader";
import type { CogRangeArtifactIdentityV1 } from "./range-integrity-catalog";
import {
  coordinateVerifiedAdmission,
  createAdmissionPlanIdentity,
  type AcceptedAdmissionGateV1,
  type AdmissionPlanIdentityV1,
  type AdmissionReceiptStore,
} from "./admission-receipt";
import {
  assertVerifiedReleaseResourcePlan,
  type ReleaseResourceRouteV1,
  type VerifiedReleaseResourcePlanV1,
} from "./release-resource-plan";
import type { RangeIdentityV1, WholeResourceAuthorityV1 } from "./contracts/v1";
import {
  OFFLINE_CAPABILITY_CONTRACT_VERSION_V2,
  validateInteractionRequirementsV2,
  validateRuntimeCapabilityV2,
  type InteractionRequirementsV2,
  type InteractionSubjectV1,
  type MissingRequirementV2,
  type OfflineRequirementV2,
  type RuntimeCapabilityV2,
  type UpdateCapabilityV1,
} from "./contracts/policy";
import type { RangeStore, VerifiedRangeWrite } from "./range-store";
import {
  WholeResourceCacheError,
  type WholeResourceReadResult,
  type WholeResourceStore,
} from "./whole-resource-cache";

export interface AcceptedResourceSnapshotV1 {
  readonly contractVersion: 1;
  readonly plan: AdmissionPlanIdentityV1;
  readonly gate: AcceptedAdmissionGateV1;
}

export interface VerifiedResourceRouterOptionsV1 {
  readonly releasePlan: VerifiedReleaseResourcePlanV1;
  readonly wholeStore: WholeResourceStore;
  readonly rangeStore: RangeStore;
  readonly receiptStore: AdmissionReceiptStore;
  readonly subtle: SubtleCrypto;
  readonly fetchRange: typeof fetch;
  readonly clientLease?: Readonly<{ close(): Promise<void>; assertActive(): void }>;
}

export interface RuntimeCapabilityInspectionV1 {
  /**
   * Evidence that the exact current interaction completed against its
   * authoritative network resources. Generic connectivity signals such as
   * navigator.onLine are deliberately insufficient.
   */
  readonly authoritativeNetworkUsable?: boolean;
  readonly storageDegraded?: "quota" | "evicted" | "persistence-denied";
  readonly update?: UpdateCapabilityV1;
  readonly signal?: AbortSignal;
}

function technical(
  code: "SchemaInvalid" | "FetchFailed" | "RangeUnsupported" | "IntegrityFailed" | "UnsupportedBrowser" | "Aborted",
  message: string,
  recoverable = false,
): TechnicalFailure {
  return new TechnicalFailure({ kind: "technical-error", code, message, recoverable });
}

function abortIfNeeded(signal: AbortSignal): void {
  if (signal.aborted) throw technical("Aborted", "Verified resource admission was cancelled.", true);
}

function sameRangeIdentity(left: RangeIdentityV1, right: RangeIdentityV1): boolean {
  return left.authority.artifactId === right.authority.artifactId &&
    left.authority.canonicalUrl === right.authority.canonicalUrl &&
    left.authority.path === right.authority.path &&
    left.authority.mediaType === right.authority.mediaType &&
    left.authority.totalByteSize === right.authority.totalByteSize &&
    left.authority.artifactSha256 === right.authority.artifactSha256 &&
    left.authority.etag === right.authority.etag &&
    left.authority.pair.appBuildId === right.authority.pair.appBuildId &&
    left.authority.pair.dataReleaseId === right.authority.pair.dataReleaseId &&
    left.interval.start === right.interval.start &&
    left.interval.endExclusive === right.interval.endExclusive &&
    left.authorizedIntervalSha256 === right.authorizedIntervalSha256;
}

function concatenate(parts: readonly ArrayBuffer[]): ArrayBuffer {
  const length = parts.reduce((sum, part) => sum + part.byteLength, 0);
  const output = new Uint8Array(length);
  let offset = 0;
  for (const part of parts) {
    output.set(new Uint8Array(part), offset);
    offset += part.byteLength;
  }
  return output.buffer;
}

function wholeIdentity(authority: WholeResourceAuthorityV1): string {
  switch (authority.authorityKind) {
    case "release-artifact": return authority.artifactId;
    case "app-asset": return authority.resourceId;
    case "release-manifest": return "release-manifest";
  }
}

function rangeIdentity(identity: RangeIdentityV1): string {
  return `${identity.authority.artifactId}.${identity.interval.start}-${identity.interval.endExclusive}`;
}

export class VerifiedResourceRouter {
  readonly #releasePlan: VerifiedReleaseResourcePlanV1;
  readonly #wholeStore: WholeResourceStore;
  readonly #rangeStore: RangeStore;
  readonly #receiptStore: AdmissionReceiptStore;
  readonly #subtle: SubtleCrypto;
  readonly #fetchRange: typeof fetch;
  readonly #clientLease: Readonly<{ close(): Promise<void>; assertActive(): void }> | undefined;
  readonly #cogResponseCacheControl: string;
  readonly #whole: readonly WholeResourceAuthorityV1[];
  readonly #assessmentSupport: readonly WholeResourceAuthorityV1[];
  readonly #ranges: readonly RangeIdentityV1[];
  readonly #wholeByUrl: ReadonlyMap<string, WholeResourceAuthorityV1>;
  readonly #rangesByArtifact: ReadonlyMap<string, readonly RangeIdentityV1[]>;
  #active: AcceptedResourceSnapshotV1 | undefined;
  #activeResources: Readonly<{
    whole: readonly WholeResourceAuthorityV1[];
    ranges: readonly RangeIdentityV1[];
  }> | undefined;
  #admissionTail: Promise<void> = Promise.resolve();
  readonly #pendingOperations = new Set<Promise<unknown>>();
  #closed = false;

  readonly artifactTransport: ArtifactTransport;
  readonly cogRangeTransport: CogRangeTransport;

  constructor(options: VerifiedResourceRouterOptionsV1) {
    this.#releasePlan = assertVerifiedReleaseResourcePlan(options.releasePlan);
    this.#wholeStore = options.wholeStore;
    this.#rangeStore = options.rangeStore;
    this.#receiptStore = options.receiptStore;
    this.#subtle = options.subtle;
    this.#fetchRange = options.fetchRange;
    this.#clientLease = options.clientLease;
    this.#cogResponseCacheControl = this.#releasePlan.persistence.mode === "memory-only"
      ? "private, no-store"
      : "public, max-age=31536000, immutable";
    const expectedMode = this.#releasePlan.persistence.mode;
    if (
      this.#wholeStore.mode !== expectedMode ||
      this.#rangeStore.mode !== expectedMode ||
      this.#receiptStore.mode !== expectedMode
    ) {
      throw technical("SchemaInvalid", "Resource stores do not match the verified release persistence mode.");
    }
    if (expectedMode === "persistent" && !this.#clientLease) {
      throw technical("SchemaInvalid", "Persistent resource routing requires an active client lease controller.");
    }
    if (expectedMode === "memory-only" && this.#clientLease) {
      throw technical("SchemaInvalid", "Memory-only Candidate routing cannot install a persistent client lease.");
    }
    try {
      this.#clientLease?.assertActive();
    } catch {
      throw technical("UnsupportedBrowser", "The persistent client lease is unavailable.", true);
    }

    this.#whole = Object.freeze(this.#releasePlan.routes.flatMap((route) =>
      route.kind === "complete-resource" ? [route.authority] : []));
    this.#assessmentSupport = Object.freeze(this.#whole.filter((authority) =>
      authority.authorityKind === "release-artifact" &&
      (authority.role === "source-grid-identity" || authority.role === "range-integrity-index")));
    if (this.#assessmentSupport.length !== 2) {
      throw technical("SchemaInvalid", "Assessment routing requires the exact source-grid and range-integrity support pair.");
    }
    this.#ranges = Object.freeze(this.#releasePlan.routes.flatMap((route) =>
      route.kind === "analysis-cog-ranges" ? route.ranges : []));
    this.#wholeByUrl = new Map(this.#whole.map((authority) => [authority.canonicalUrl, authority]));
    const rangesByArtifact = new Map<string, RangeIdentityV1[]>();
    for (const identity of this.#ranges) {
      const values = rangesByArtifact.get(identity.authority.artifactId) ?? [];
      values.push(identity);
      rangesByArtifact.set(identity.authority.artifactId, values);
    }
    this.#rangesByArtifact = new Map([...rangesByArtifact].map(([key, values]) => [
      key,
      Object.freeze(values.sort((left, right) => left.interval.start - right.interval.start)),
    ]));

    this.artifactTransport = async (input, init) => this.#runWhileOpen(async () => {
      abortIfNeeded(init.signal);
      const authority = this.#wholeByUrl.get(input.href);
      if (!authority || Object.keys(init.headers).some((name) => name.toLowerCase() !== "accept") ||
          init.headers.Accept !== authority.mediaType) {
        throw technical("IntegrityFailed", "Whole-resource request does not match the accepted release route.");
      }
      const snapshot = await this.#admitResources([authority], [], init.signal);
      const result = await this.#wholeStore.readAccepted(authority, snapshot.gate);
      if (result.state !== "hit") {
        const resourceId = authority.authorityKind === "release-artifact"
          ? authority.artifactId
          : authority.authorityKind === "app-asset" ? authority.resourceId : "release-manifest";
        throw technical("IntegrityFailed", `Accepted resource ${resourceId} is unavailable.`);
      }
      abortIfNeeded(init.signal);
      return result.response.clone();
    });

    this.cogRangeTransport = Object.freeze({
      validateDelivery: async (
        artifact: ResolvedArtifact,
        identity: CogRangeArtifactIdentityV1,
        signal: AbortSignal,
      ) => this.#runWhileOpen(async () => {
        abortIfNeeded(signal);
        this.#assertCogAuthority(artifact, identity);
      }),
      readExpandedRange: async (
        artifact: ResolvedArtifact,
        identity: CogRangeArtifactIdentityV1,
        start: number,
        endExclusive: number,
        signal: AbortSignal,
      ) => this.#runWhileOpen(async () => {
        abortIfNeeded(signal);
        const ranges = this.#assertCogAuthority(artifact, identity).filter((range) =>
          range.interval.endExclusive > start && range.interval.start < endExclusive);
        if (
          ranges.length === 0 || ranges[0].interval.start > start ||
          ranges.at(-1)!.interval.endExclusive < endExclusive ||
          ranges.some((range, index) => index > 0 && ranges[index - 1].interval.endExclusive !== range.interval.start)
        ) {
          throw technical("IntegrityFailed", `Accepted COG ranges do not cover ${start}-${endExclusive}.`);
        }
        const snapshot = await this.#admitResources(this.#assessmentSupport, ranges, signal);
        const parts: ArrayBuffer[] = [];
        for (const range of ranges) {
          const request = {
            start: Math.max(start, range.interval.start),
            endExclusive: Math.min(endExclusive, range.interval.endExclusive),
          };
          const bytes = await this.#rangeStore.readAccepted(range, snapshot.gate, request);
          if (!bytes) throw technical("IntegrityFailed", `Accepted COG range ${range.authority.artifactId} is unavailable.`);
          parts.push(bytes);
          abortIfNeeded(signal);
        }
        return concatenate(parts);
      }),
    });
  }

  #assertOpenAndLeased(): void {
    if (this.#closed) {
      throw technical("UnsupportedBrowser", "The verified resource router is closed.");
    }
    try {
      this.#clientLease?.assertActive();
    } catch {
      throw technical("UnsupportedBrowser", "The persistent client lease is unavailable.", true);
    }
  }

  #runWhileOpen<T>(operation: () => Promise<T>): Promise<T> {
    this.#assertOpenAndLeased();
    const pending = Promise.resolve().then(async () => {
      this.#assertOpenAndLeased();
      return operation();
    });
    this.#pendingOperations.add(pending);
    void pending.finally(() => this.#pendingOperations.delete(pending)).catch(() => undefined);
    return pending;
  }

  interactionRequirements(subject: InteractionSubjectV1): InteractionRequirementsV2 {
    const routes = this.#routesForSubject(subject);
    return validateInteractionRequirementsV2({
      contractVersion: OFFLINE_CAPABILITY_CONTRACT_VERSION_V2,
      pair: this.#releasePlan.pair,
      subject,
      requirements: routes.flatMap((route): readonly OfflineRequirementV2[] => {
        switch (route.kind) {
          case "complete-resource": return [{ kind: "whole" as const, authority: route.authority }];
          case "analysis-cog-ranges": return route.ranges.map((identity) => ({ kind: "range" as const, identity }));
          case "network-only": return route.reason === "visual-pmtiles"
            ? [{ kind: "network-only" as const, identity: route.identity.artifactId, reason: route.reason }]
            : [];
        }
      }),
    });
  }

  async inspectCapability(
    subject: InteractionSubjectV1,
    options: RuntimeCapabilityInspectionV1 = {},
  ): Promise<RuntimeCapabilityV2> {
    const requirements = this.interactionRequirements(subject);
    const update = options.update ?? Object.freeze({ state: "current" as const });
    const signal = options.signal ?? new AbortController().signal;
    abortIfNeeded(signal);

    const degradedReason = options.storageDegraded ?? (
      this.#releasePlan.persistence.mode === "memory-only" ? "persistence-denied" : undefined
    );
    if (degradedReason) {
      return validateRuntimeCapabilityV2({
        contractVersion: OFFLINE_CAPABILITY_CONTRACT_VERSION_V2,
        subject: requirements.subject,
        data: {
          state: "degraded-storage",
          pair: requirements.pair,
          reason: degradedReason,
          networkUsable: options.authoritativeNetworkUsable === true,
        },
        update,
      });
    }

    const requiredWhole = requirements.requirements.flatMap((requirement) =>
      requirement.kind === "whole" ? [requirement.authority] : []);
    const requiredRanges = requirements.requirements.flatMap((requirement) =>
      requirement.kind === "range" ? [requirement.identity] : []);
    const networkOnly = requirements.requirements.flatMap((requirement) =>
      requirement.kind === "network-only" ? [requirement] : []);
    const missing: MissingRequirementV2[] = networkOnly.map((requirement) => Object.freeze({
      kind: "network-only" as const,
      identity: requirement.identity,
    }));
    let resourceCount = 0;
    let byteCount = 0;

    for (const authority of requiredWhole) {
      abortIfNeeded(signal);
      let result: WholeResourceReadResult | null = null;
      if (this.#active?.gate) {
        try {
          result = await this.#wholeStore.readAccepted(authority, this.#active.gate);
        } catch {
          // The active gate may belong to a different exact interaction.
        }
      }
      if (!result || result.state !== "hit") {
        const plan = await this.#admissionPlan([authority], []);
        const gate = await this.#receiptStore.accepted(plan);
        if (gate) result = await this.#wholeStore.readAccepted(authority, gate);
      }
      if (result?.state === "hit") {
        resourceCount += 1;
        byteCount += result.byteLength;
      } else {
        missing.push(Object.freeze({ kind: "whole", identity: wholeIdentity(authority) }));
      }
    }
    const activeGate = this.#active?.gate ?? null;
    for (const identity of requiredRanges) {
      abortIfNeeded(signal);
      let bytes: ArrayBuffer | null = null;
      if (activeGate) {
        try {
          bytes = await this.#rangeStore.readAccepted(identity, activeGate);
        } catch {
          // A valid gate for another exact subject is not evidence for this
          // range. Treat it as missing instead of widening authority.
        }
      }
      if (bytes) {
        resourceCount += 1;
        byteCount += bytes.byteLength;
      } else {
        missing.push(Object.freeze({ kind: "range", identity: rangeIdentity(identity) }));
      }
    }

    const data = missing.length === 0
      ? { state: "available-offline" as const, pair: requirements.pair, resourceCount, byteCount }
      : options.authoritativeNetworkUsable === true
        ? { state: "online-complete" as const, pair: requirements.pair }
        : {
            state: "connection-required" as const,
            pair: requirements.pair,
            missing: Object.freeze(missing),
            retryable: true as const,
          };
    return validateRuntimeCapabilityV2({
      contractVersion: OFFLINE_CAPABILITY_CONTRACT_VERSION_V2,
      subject: requirements.subject,
      data,
      update,
    });
  }

  #routesForSubject(subject: InteractionSubjectV1): readonly ReleaseResourceRouteV1[] {
    if (subject.kind === "core") {
      return this.#releasePlan.routes.filter((route) => route.kind === "complete-resource" &&
        route.authority.authorityKind === "release-artifact" &&
        ["methodology", "source-attribution", "support-boundary", "coastal-boundary"]
          .includes(route.authority.role));
    }
    if (subject.kind === "search") {
      const paths = new Set(subject.shards.map((shard) => `search/europe-${shard}.codepoint-trie.json.br`));
      return this.#releasePlan.routes.filter((route) => route.kind === "complete-resource" &&
        route.authority.authorityKind === "release-artifact" && paths.has(route.authority.path));
    }
    const artifactId = `projection-${subject.scenario}-${subject.horizon}-${subject.kind === "map" ? "pmtiles" : "cog"}`;
    if (subject.kind === "map") {
      return this.#releasePlan.routes.filter((route) =>
        route.kind === "network-only" && route.identity.artifactId === artifactId);
    }
    const activeRangeIds = new Set((this.#activeResources?.ranges ?? [])
      .filter((identity) => identity.authority.artifactId === artifactId)
      .map(rangeIdentity));
    const hasCurrentRanges = activeRangeIds.size > 0;
    return this.#releasePlan.routes.flatMap((route): readonly ReleaseResourceRouteV1[] => {
      if (route.kind === "complete-resource" && route.authority.authorityKind === "release-artifact" &&
          ["support-boundary", "coastal-boundary", "source-grid-identity", "range-integrity-index"]
            .includes(route.authority.role)) return [route];
      if (route.kind !== "analysis-cog-ranges" || route.identity.artifactId !== artifactId) return [];
      return [{
        ...route,
        ranges: hasCurrentRanges
          ? Object.freeze(route.ranges.filter((identity) => activeRangeIds.has(rangeIdentity(identity))))
          : route.ranges,
      }];
    });
  }

  async #admissionPlan(
    whole: readonly WholeResourceAuthorityV1[],
    ranges: readonly RangeIdentityV1[],
  ): Promise<AdmissionPlanIdentityV1> {
    return createAdmissionPlanIdentity({
      releasePlan: this.#releasePlan,
      wholeResources: whole,
      rangeResources: ranges,
      subtle: this.#subtle,
    });
  }

  #assertCogAuthority(
    artifact: ResolvedArtifact,
    identity: CogRangeArtifactIdentityV1,
  ): readonly RangeIdentityV1[] {
    const ranges = this.#rangesByArtifact.get(artifact.artifactId);
    if (!ranges ||
        artifact.url !== ranges[0].authority.canonicalUrl ||
        artifact.path !== ranges[0].authority.path ||
        artifact.mediaType !== ranges[0].authority.mediaType ||
        artifact.byteSize !== ranges[0].authority.totalByteSize ||
        artifact.sha256 !== ranges[0].authority.artifactSha256 ||
        identity.artifactId !== artifact.artifactId ||
        identity.byteSize !== artifact.byteSize ||
        identity.sha256 !== artifact.sha256 ||
        identity.chunks.length !== ranges.length ||
        identity.chunks.some((chunk, index) =>
          chunk.start !== ranges[index].interval.start ||
          chunk.endExclusive !== ranges[index].interval.endExclusive ||
          chunk.sha256 !== ranges[index].authorizedIntervalSha256)) {
      throw technical("IntegrityFailed", "COG reader authority does not match the exact accepted resource plan.");
    }
    return ranges;
  }

  async #readAcceptedRanges(
    gate: AcceptedAdmissionGateV1 | null,
    identities: readonly RangeIdentityV1[],
    signal: AbortSignal,
  ): Promise<Readonly<{ writes: readonly VerifiedRangeWrite[]; missing: readonly RangeIdentityV1[] }>> {
    const writes: VerifiedRangeWrite[] = [];
    const missing: RangeIdentityV1[] = [];
    for (const identity of identities) {
      abortIfNeeded(signal);
      if (!gate) {
        missing.push(identity);
        continue;
      }
      try {
        const bytes = await this.#rangeStore.readAccepted(identity, gate);
        if (bytes) writes.push(Object.freeze({ identity, bytes }));
        else missing.push(identity);
      } catch {
        throw technical(
          "IntegrityFailed",
          `Accepted COG range ${identity.authority.artifactId} failed verification.`,
          false,
        );
      }
    }
    return Object.freeze({ writes: Object.freeze(writes), missing: Object.freeze(missing) });
  }

  async #fetchMissingRanges(
    missing: readonly RangeIdentityV1[],
    signal: AbortSignal,
  ): Promise<readonly VerifiedRangeWrite[]> {
    const byArtifact = new Map<string, RangeIdentityV1[]>();
    for (const identity of missing) {
      const values = byArtifact.get(identity.authority.artifactId) ?? [];
      values.push(identity);
      byArtifact.set(identity.authority.artifactId, values);
    }
    const writes: VerifiedRangeWrite[] = [];
    for (const identities of byArtifact.values()) {
      abortIfNeeded(signal);
      const authority = identities[0].authority;
      let head: Response;
      try {
        head = await this.#fetchRange(authority.canonicalUrl, {
          method: "HEAD",
          cache: "no-store",
          credentials: "omit",
          redirect: "error",
          referrerPolicy: "no-referrer",
          signal,
          headers: { Accept: authority.mediaType },
        });
      } catch (error) {
        if (signal.aborted || (error instanceof DOMException && error.name === "AbortError")) {
          throw technical("Aborted", `COG admission for ${authority.artifactId} was cancelled.`, true);
        }
        throw technical("FetchFailed", `COG delivery metadata for ${authority.artifactId} is unavailable.`, true);
      }
      if (head.status !== 200) throw technical("FetchFailed", `COG delivery metadata returned HTTP ${head.status}.`, true);
      if (
        head.redirected || (head.url !== "" && head.url !== authority.canonicalUrl) ||
        head.headers.get("accept-ranges") !== "bytes" ||
        head.headers.get("content-length") !== String(authority.totalByteSize) ||
        head.headers.get("content-type") !== authority.mediaType ||
        head.headers.get("etag") !== authority.etag ||
        head.headers.get("cache-control") !== this.#cogResponseCacheControl
      ) {
        throw technical("RangeUnsupported", `COG HEAD identity for ${authority.artifactId} is inexact.`, true);
      }
      for (const identity of identities) {
        abortIfNeeded(signal);
        const start = identity.interval.start;
        const end = identity.interval.endExclusive - 1;
        let response: Response;
        try {
          response = await this.#fetchRange(authority.canonicalUrl, {
            method: "GET",
            cache: "no-store",
            credentials: "omit",
            redirect: "error",
            referrerPolicy: "no-referrer",
            signal,
            headers: {
              Accept: authority.mediaType,
              Range: `bytes=${start}-${end}`,
              "If-Match": authority.etag,
            },
          });
        } catch (error) {
          if (signal.aborted || (error instanceof DOMException && error.name === "AbortError")) {
            throw technical("Aborted", `COG range admission for ${authority.artifactId} was cancelled.`, true);
          }
          throw technical("FetchFailed", `COG range for ${authority.artifactId} is unavailable.`, true);
        }
        const expectedLength = identity.interval.endExclusive - start;
        if (!response.ok) throw technical("FetchFailed", `COG range returned HTTP ${response.status}.`, true);
        if (
          response.redirected || (response.url !== "" && response.url !== authority.canonicalUrl) ||
          response.status !== 206 ||
          response.headers.get("accept-ranges") !== "bytes" ||
          response.headers.get("content-length") !== String(expectedLength) ||
          response.headers.get("content-range") !== `bytes ${start}-${end}/${authority.totalByteSize}` ||
          response.headers.get("content-type") !== authority.mediaType ||
          response.headers.get("etag") !== authority.etag ||
          response.headers.get("cache-control") !== this.#cogResponseCacheControl
        ) {
          throw technical("RangeUnsupported", `COG range identity for ${authority.artifactId} is inexact.`, true);
        }
        let bytes: ArrayBuffer;
        try {
          bytes = await response.arrayBuffer();
        } catch (error) {
          if (signal.aborted || (error instanceof DOMException && error.name === "AbortError")) {
            throw technical("Aborted", `COG range admission for ${authority.artifactId} was cancelled.`, true);
          }
          throw technical("FetchFailed", `COG range body for ${authority.artifactId} is unavailable.`, true);
        }
        abortIfNeeded(signal);
        if (bytes.byteLength !== expectedLength) {
          throw technical("IntegrityFailed", `COG range for ${authority.artifactId} has the wrong length.`);
        }
        writes.push(Object.freeze({ identity, bytes }));
      }
    }
    return Object.freeze(writes);
  }

  async restoreAssessmentSupport(): Promise<AcceptedResourceSnapshotV1 | null> {
    return this.#runWhileOpen(async () => {
      const plan = await this.#admissionPlan(this.#assessmentSupport, []);
      const gate = await this.#receiptStore.accepted(plan);
      if (!gate) return null;
      const snapshot = Object.freeze({ contractVersion: 1 as const, plan, gate });
      this.#active = snapshot;
      this.#activeResources = Object.freeze({ whole: this.#assessmentSupport, ranges: Object.freeze([]) });
      return snapshot;
    });
  }

  async #coordinateResources(
    requiredWhole: readonly WholeResourceAuthorityV1[],
    requiredRanges: readonly RangeIdentityV1[],
    signal: AbortSignal,
  ): Promise<AcceptedResourceSnapshotV1> {
    abortIfNeeded(signal);
    const plan = await this.#admissionPlan(requiredWhole, requiredRanges);
    const previous = await this.#receiptStore.accepted(plan);
    const accepted = await this.#readAcceptedRanges(previous, requiredRanges, signal);
    if (previous && accepted.missing.length === 0) {
      let wholeComplete = true;
      for (const authority of requiredWhole) {
        const result = await this.#wholeStore.readAccepted(authority, previous);
        if (result.state === "corrupt") {
          throw technical("IntegrityFailed", "An accepted whole resource failed verification.");
        }
        if (result.state !== "hit") { wholeComplete = false; break; }
      }
      if (wholeComplete) {
        const snapshot = Object.freeze({ contractVersion: 1 as const, plan, gate: previous });
        this.#active = snapshot;
        this.#activeResources = Object.freeze({ whole: requiredWhole, ranges: requiredRanges });
        return snapshot;
      }
    }
    const downloaded = await this.#fetchMissingRanges(accepted.missing, signal);
    const writes = [...accepted.writes, ...downloaded].sort((left, right) =>
      left.identity.authority.artifactId.localeCompare(right.identity.authority.artifactId) ||
      left.identity.interval.start - right.identity.interval.start);
    if (writes.length !== requiredRanges.length || writes.some((write, index) =>
      !sameRangeIdentity(write.identity, [...requiredRanges].sort((left, right) =>
        left.authority.artifactId.localeCompare(right.authority.artifactId) ||
        left.interval.start - right.interval.start)[index]))) {
      throw technical("IntegrityFailed", "COG admission did not resolve the exact release range set.");
    }
    const result = await coordinateVerifiedAdmission({
      plan,
      wholeResources: requiredWhole,
      rangeWrites: writes,
      wholeStore: this.#wholeStore,
      rangeStore: this.#rangeStore,
      receiptStore: this.#receiptStore,
      subtle: this.#subtle,
      signal,
    });
    const snapshot = Object.freeze({ contractVersion: 1 as const, plan, gate: result.gate });
    this.#active = snapshot;
    this.#activeResources = Object.freeze({ whole: requiredWhole, ranges: requiredRanges });
    return snapshot;
  }

  async #admitResources(
    requiredWhole: readonly WholeResourceAuthorityV1[],
    requiredRanges: readonly RangeIdentityV1[],
    signal: AbortSignal,
  ): Promise<AcceptedResourceSnapshotV1> {
    const previousTurn = this.#admissionTail;
    let releaseTurn!: () => void;
    this.#admissionTail = new Promise<void>((resolve) => { releaseTurn = resolve; });
    try {
      await previousTurn;
      abortIfNeeded(signal);
      return await this.#coordinateResources(requiredWhole, requiredRanges, signal);
    } catch (error) {
      if (error instanceof TechnicalFailure) throw error;
      if (error instanceof WholeResourceCacheError) {
        if (error.code === "Aborted") {
          throw technical("Aborted", "Verified resource admission was cancelled.", true);
        }
        if (["AuthorityRejected", "ResponseRejected", "IntegrityFailed"].includes(error.code)) {
          throw technical("IntegrityFailed", error.message);
        }
        throw technical("FetchFailed", error.message, true);
      }
      if (signal.aborted || (error instanceof DOMException && error.name === "AbortError") ||
          (error instanceof Error && /Aborted/u.test(error.name))) {
        throw technical("Aborted", "Verified resource admission was cancelled.", true);
      }
      if (error instanceof Error && /Quota/u.test(`${error.name} ${error.message}`)) {
        throw technical("UnsupportedBrowser", "Browser storage quota cannot admit the exact resource plan.", true);
      }
      const message = error instanceof Error ? error.message : "Verified resource admission failed.";
      if (error instanceof Error && /Integrity|Authority|Conflict|Schema/u.test(`${error.name} ${message}`)) {
        throw technical("IntegrityFailed", message);
      }
      throw technical("FetchFailed", message, true);
    } finally {
      releaseTurn();
    }
  }

  /** Installs only the two exact whole resources required before an assessment. COG chunks remain lazy. */
  async prepareAssessmentSupport(signal: AbortSignal): Promise<AcceptedResourceSnapshotV1> {
    return this.#runWhileOpen(() => this.#admitResources(this.#assessmentSupport, [], signal));
  }

  current(): AcceptedResourceSnapshotV1 | null {
    return this.#active ?? null;
  }

  close(): void {
    if (this.#closed) return;
    this.#closed = true;
    const closeStores = (): void => {
      this.#receiptStore.close();
      this.#rangeStore.close();
      this.#wholeStore.close();
    };
    if (!this.#clientLease && this.#pendingOperations.size === 0) {
      closeStores();
      return;
    }
    const pending = [...this.#pendingOperations];
    void Promise.allSettled(pending)
      .then(() => this.#clientLease?.close())
      .catch(() => undefined)
      .finally(closeStores);
  }

}
