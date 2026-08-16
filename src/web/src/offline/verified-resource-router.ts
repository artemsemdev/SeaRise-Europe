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
  type VerifiedReleaseResourcePlanV1,
} from "./release-resource-plan";
import type { RangeIdentityV1, WholeResourceAuthorityV1 } from "./contracts/v1";
import type { RangeStore, VerifiedRangeWrite } from "./range-store";
import type { WholeResourceStore } from "./whole-resource-cache";

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

function exactNoStore(value: string | null): boolean {
  return value?.split(",").map((part) => part.trim().toLowerCase()).includes("no-store") === true;
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

export class VerifiedResourceRouter {
  readonly #releasePlan: VerifiedReleaseResourcePlanV1;
  readonly #wholeStore: WholeResourceStore;
  readonly #rangeStore: RangeStore;
  readonly #receiptStore: AdmissionReceiptStore;
  readonly #subtle: SubtleCrypto;
  readonly #fetchRange: typeof fetch;
  readonly #whole: readonly WholeResourceAuthorityV1[];
  readonly #assessmentSupport: readonly WholeResourceAuthorityV1[];
  readonly #ranges: readonly RangeIdentityV1[];
  readonly #wholeByUrl: ReadonlyMap<string, WholeResourceAuthorityV1>;
  readonly #rangesByArtifact: ReadonlyMap<string, readonly RangeIdentityV1[]>;
  #active: AcceptedResourceSnapshotV1 | undefined;
  #admissionTail: Promise<void> = Promise.resolve();

  readonly artifactTransport: ArtifactTransport;
  readonly cogRangeTransport: CogRangeTransport;

  constructor(options: VerifiedResourceRouterOptionsV1) {
    this.#releasePlan = assertVerifiedReleaseResourcePlan(options.releasePlan);
    this.#wholeStore = options.wholeStore;
    this.#rangeStore = options.rangeStore;
    this.#receiptStore = options.receiptStore;
    this.#subtle = options.subtle;
    this.#fetchRange = options.fetchRange;
    const expectedMode = this.#releasePlan.persistence.mode;
    if (
      this.#wholeStore.mode !== expectedMode ||
      this.#rangeStore.mode !== expectedMode ||
      this.#receiptStore.mode !== expectedMode
    ) {
      throw technical("SchemaInvalid", "Resource stores do not match the verified release persistence mode.");
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

    this.artifactTransport = async (input, init) => {
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
    };

    this.cogRangeTransport = Object.freeze({
      validateDelivery: async (
        artifact: ResolvedArtifact,
        identity: CogRangeArtifactIdentityV1,
        signal: AbortSignal,
      ) => {
        abortIfNeeded(signal);
        this.#assertCogAuthority(artifact, identity);
      },
      readExpandedRange: async (
        artifact: ResolvedArtifact,
        identity: CogRangeArtifactIdentityV1,
        start: number,
        endExclusive: number,
        signal: AbortSignal,
      ) => {
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
      },
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
        !exactNoStore(head.headers.get("cache-control"))
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
          !exactNoStore(response.headers.get("cache-control"))
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
    const plan = await this.#admissionPlan(this.#assessmentSupport, []);
    const gate = await this.#receiptStore.accepted(plan);
    if (!gate) return null;
    const snapshot = Object.freeze({ contractVersion: 1 as const, plan, gate });
    this.#active = snapshot;
    return snapshot;
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
    return this.#admitResources(this.#assessmentSupport, [], signal);
  }

  current(): AcceptedResourceSnapshotV1 | null {
    return this.#active ?? null;
  }

  close(): void {
    this.#receiptStore.close();
    this.#rangeStore.close();
    this.#wholeStore.close();
  }

}
