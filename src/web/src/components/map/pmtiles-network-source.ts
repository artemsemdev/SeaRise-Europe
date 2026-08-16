import {
  EtagMismatch,
  PMTiles,
  type Cache,
  type Protocol,
  type RangeResponse,
  type Source,
} from "pmtiles";

const PMTILES_MEDIA_TYPE = "application/vnd.pmtiles";
export const MAX_PMTILES_RANGE_BYTES = 512 * 1024;

interface CommonVisualPmtilesAuthority {
  readonly artifactId: string;
  readonly byteSize: number;
  readonly dataReleaseId: string;
  readonly sha256: string;
  readonly url: string;
  readonly visualOnly: true;
}

export type VisualPmtilesAuthority =
  | Readonly<CommonVisualPmtilesAuthority & {
      readonly kind: "projection";
      readonly scenario: "ssp1-26" | "ssp2-45" | "ssp5-85";
      readonly horizon: 2030 | 2050 | 2100;
    }>
  | Readonly<CommonVisualPmtilesAuthority & {
      readonly kind: "support-boundary" | "coastal-boundary";
    }>;

export type PmtilesFetch = (request: Request) => Promise<Response>;

function fail(message: string): never {
  throw new TypeError(message);
}

function exactPmtilesUrl(authority: VisualPmtilesAuthority): string {
  if (!/^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/u.test(authority.dataReleaseId)) {
    fail("PMTiles dataReleaseId is not a canonical release identifier.");
  }
  if (!/^[A-Za-z0-9][A-Za-z0-9._-]{0,255}$/u.test(authority.artifactId)) {
    fail("PMTiles artifactId is not a canonical artifact identifier.");
  }
  if (!Number.isSafeInteger(authority.byteSize) || authority.byteSize <= 0) {
    fail("PMTiles byteSize must be a positive safe integer.");
  }
  if (!/^[0-9a-f]{64}$/u.test(authority.sha256)) {
    fail("PMTiles sha256 must be a lowercase SHA-256 digest.");
  }
  if (authority.visualOnly !== true) fail("PMTiles network delivery is visual-only.");

  let url: URL;
  let decodedPathname: string;
  try {
    url = new URL(authority.url);
    decodedPathname = decodeURIComponent(url.pathname);
  } catch {
    return fail("PMTiles URL must be absolute with canonical path encoding.");
  }
  const releasePrefix = `/releases/${authority.dataReleaseId}/`;
  const relativePath = url.pathname.slice(releasePrefix.length);
  if (
    !new Set(["http:", "https:"]).has(url.protocol) ||
    url.username !== "" ||
    url.password !== "" ||
    url.search !== "" ||
    url.hash !== "" ||
    url.href !== authority.url ||
    !url.pathname.startsWith(releasePrefix) ||
    relativePath.length === 0 ||
    relativePath.startsWith("/") ||
    relativePath.includes("//") ||
    relativePath.split("/").some((part) => part === "." || part === "..") ||
    !relativePath.endsWith(".pmtiles") ||
    decodedPathname !== url.pathname
  ) {
    fail("PMTiles URL must be one canonical file in the exact release path.");
  }
  if (authority.kind === "projection") {
    const expectedArtifactId = `projection-${authority.scenario}-${authority.horizon}-pmtiles`;
    const expectedPath = `layers/${authority.scenario}/${authority.horizon}.pmtiles`;
    if (authority.artifactId !== expectedArtifactId || relativePath !== expectedPath) {
      fail("PMTiles projection identity does not match its exact release URL.");
    }
  } else {
    const boundary = authority.kind === "support-boundary"
      ? { artifactId: "support-boundary-pmtiles", path: "boundaries/europe.pmtiles" }
      : authority.kind === "coastal-boundary"
        ? { artifactId: "coastal-boundary-pmtiles", path: "boundaries/coastal-analysis-zone.pmtiles" }
        : null;
    if (!boundary || authority.artifactId !== boundary.artifactId || relativePath !== boundary.path) {
      fail("PMTiles boundary identity does not match the candidate artifact contract.");
    }
  }
  return url.href;
}

function noStorePolicy(response: Response): string {
  const value = response.headers.get("cache-control") ?? "";
  const directives: string[] = [];
  let start = 0;
  let quoted = false;
  let escaped = false;
  for (let index = 0; index <= value.length; index += 1) {
    const character = value[index];
    if (escaped) {
      escaped = false;
    } else if (quoted && character === "\\") {
      escaped = true;
    } else if (character === '"') {
      quoted = !quoted;
    } else if ((character === "," && !quoted) || index === value.length) {
      directives.push(value.slice(start, index).trim());
      start = index + 1;
    }
  }
  if (quoted || escaped) fail("PMTiles response has malformed Cache-Control.");
  const normalized = directives.map((directive) => directive.toLowerCase());
  if (!normalized.includes("no-store") || normalized.some((directive) => directive.startsWith("no-store="))) {
    fail("PMTiles response must declare Cache-Control: no-store.");
  }
  return value;
}

function responseEtag(response: Response): string | undefined {
  const value = response.headers.get("etag");
  return value && !value.startsWith("W/") ? value : undefined;
}

function safeDecimal(value: string | null, name: string, allowZero = false): number {
  if (value === null) fail(`PMTiles response is missing ${name}.`);
  if (!/^[0-9]+$/u.test(value)) fail(`PMTiles response ${name} must contain decimal digits only.`);
  const parsed = Number(value);
  if (!Number.isSafeInteger(parsed) || parsed < (allowZero ? 0 : 1)) {
    fail(`PMTiles response ${name} must be a ${allowZero ? "non-negative" : "positive"} safe integer.`);
  }
  return parsed;
}

function contentLength(response: Response): number {
  return safeDecimal(response.headers.get("content-length"), "Content-Length");
}

/**
 * PMTiles' supported Source boundary with no browser HTTP-cache admission.
 * It performs byte delivery only; decoded header/directory caching is supplied
 * separately by PMTiles' bounded in-memory Cache implementation.
 */
export class NetworkOnlyPmtilesSource implements Source {
  readonly #authority: VisualPmtilesAuthority;
  readonly #url: string;
  readonly #headers: Headers;
  readonly #fetch: PmtilesFetch;
  readonly #expectedEtag: string;

  constructor(
    authority: VisualPmtilesAuthority,
    options: Readonly<{ headers?: HeadersInit; fetch?: PmtilesFetch }> = {},
  ) {
    this.#url = exactPmtilesUrl(authority);
    this.#authority = Object.freeze({ ...authority, url: this.#url });
    this.#expectedEtag = `"sha256-${authority.sha256}"`;
    this.#headers = new Headers(options.headers);
    if (this.#headers.has("range")) fail("PMTiles callers cannot override the authoritative Range header.");
    this.#headers.set("accept", PMTILES_MEDIA_TYPE);
    this.#fetch = options.fetch ?? ((request) => globalThis.fetch(request));
  }

  getKey(): string {
    return this.#url;
  }

  sameAuthority(other: NetworkOnlyPmtilesSource): boolean {
    return this.#authority.kind === other.#authority.kind &&
      this.#authority.artifactId === other.#authority.artifactId &&
      this.#authority.dataReleaseId === other.#authority.dataReleaseId &&
      this.#authority.byteSize === other.#authority.byteSize &&
      this.#authority.sha256 === other.#authority.sha256 &&
      this.#authority.url === other.#authority.url &&
      (this.#authority.kind !== "projection" || (
        other.#authority.kind === "projection" &&
        this.#authority.scenario === other.#authority.scenario &&
        this.#authority.horizon === other.#authority.horizon
      ));
  }

  async #request(start: number, end: number, signal: AbortSignal): Promise<Response> {
    const headers = new Headers(this.#headers);
    headers.set("range", `bytes=${start}-${end}`);
    const request = new Request(this.#url, {
      method: "GET",
      headers,
      signal,
      cache: "no-store",
      credentials: "omit",
      redirect: "error",
      referrerPolicy: "no-referrer",
    });
    const response = await this.#fetch(request);
    if (response.redirected || (response.url !== "" && response.url !== this.#url)) {
      fail("PMTiles response escaped its exact release URL.");
    }
    noStorePolicy(response);
    if (response.status === 416) return response;
    if (response.status !== 200 && response.status !== 206) return response;
    const mediaType = response.headers.get("content-type")?.split(";", 1)[0].trim().toLowerCase();
    if (mediaType !== PMTILES_MEDIA_TYPE) fail("PMTiles response has an unexpected media type.");
    return response;
  }

  async getBytes(
    offset: number,
    length: number,
    passedSignal?: AbortSignal,
    etag?: string,
  ): Promise<RangeResponse> {
    if (
      !Number.isSafeInteger(offset) || offset < 0 ||
      !Number.isSafeInteger(length) || length <= 0 || length > MAX_PMTILES_RANGE_BYTES ||
      !Number.isSafeInteger(offset + length - 1)
    ) {
      fail(`PMTiles ranges must be positive safe intervals of at most ${MAX_PMTILES_RANGE_BYTES} bytes.`);
    }

    const controller = passedSignal ? undefined : new AbortController();
    const signal = passedSignal ?? controller!.signal;
    const start = offset;
    let end = offset + length - 1;
    let shortArchiveTotal: number | undefined;
    let response = await this.#request(start, end, signal);

    // Preserve PMTiles' supported short-archive retry without relaxing no-store.
    if (offset === 0 && response.status === 416) {
      const match = /^bytes \*\/([0-9]+)$/u.exec(response.headers.get("content-range") ?? "");
      const total = safeDecimal(match?.[1] ?? null, "416 Content-Range total");
      if (
        !Number.isSafeInteger(total) || total <= 0 || total > length ||
        total !== this.#authority.byteSize || responseEtag(response) !== this.#expectedEtag
      ) {
        fail("PMTiles 416 response has no valid short-archive length.");
      }
      shortArchiveTotal = total;
      end = total - 1;
      response = await this.#request(0, end, signal);
    }

    if (response.status !== 200 && response.status !== 206) {
      fail(`PMTiles server returned HTTP ${response.status}.`);
    }
    const newEtag = responseEtag(response);
    if (
      newEtag !== this.#expectedEtag ||
      (etag !== undefined && (etag !== this.#expectedEtag || newEtag !== etag))
    ) {
      throw new EtagMismatch(
        `PMTiles ETag must equal manifest authority ${this.#expectedEtag}.`,
      );
    }

    const declaredLength = contentLength(response);
    if (response.status === 206) {
      const match = /^bytes ([0-9]+)-([0-9]+)\/([0-9]+)$/u.exec(response.headers.get("content-range") ?? "");
      const responseStart = match ? safeDecimal(match[1], "Content-Range start", true) : undefined;
      const responseEnd = match ? safeDecimal(match[2], "Content-Range end", true) : undefined;
      const responseTotal = match ? safeDecimal(match[3], "Content-Range total") : undefined;
      if (
        !match || responseStart !== start || responseEnd !== end ||
        responseTotal !== this.#authority.byteSize ||
        (shortArchiveTotal !== undefined && responseTotal !== shortArchiveTotal) ||
        declaredLength !== end - start + 1 ||
        response.headers.get("accept-ranges")?.toLowerCase() !== "bytes"
      ) {
        fail("PMTiles server returned a range outside the exact requested interval.");
      }
    } else if (
      response.status !== 200 || start !== 0 ||
      declaredLength !== this.#authority.byteSize || declaredLength > end + 1
    ) {
      fail("PMTiles server did not preserve bounded HTTP byte serving.");
    }

    const data = await response.arrayBuffer();
    if (data.byteLength !== declaredLength) fail("PMTiles response length does not match its body.");
    return {
      data,
      etag: newEtag,
      cacheControl: noStorePolicy(response),
    };
  }
}

export function registerNetworkOnlyPmtiles(
  protocol: Pick<Protocol, "add" | "get">,
  cache: Cache,
  authority: VisualPmtilesAuthority,
): PMTiles {
  // Construct first so forged metadata cannot bypass validation through an
  // already-registered URL.
  const source = new NetworkOnlyPmtilesSource(authority);
  const existing = protocol.get(source.getKey());
  if (existing) {
    if (
      !(existing.source instanceof NetworkOnlyPmtilesSource) ||
      !existing.source.sameAuthority(source)
    ) {
      fail("PMTiles URL is already registered under a different visual authority.");
    }
    return existing;
  }
  const archive = new PMTiles(source, cache);
  protocol.add(archive);
  return archive;
}
