import { ReleaseContext, TechnicalFailure, type ResolvedArtifact } from "../domain/release";

export type ArtifactTransport = (
  input: URL,
  init: Readonly<{ signal: AbortSignal; headers: Readonly<Record<string, string>> }>,
) => Promise<Response>;

function technical(
  code: "FetchFailed" | "IntegrityFailed" | "UnsupportedBrowser" | "Aborted",
  message: string,
  recoverable = false,
): TechnicalFailure {
  return new TechnicalFailure({ kind: "technical-error", code, message, recoverable });
}

export function defaultArtifactTransport(
  input: URL,
  init: Parameters<ArtifactTransport>[1],
): Promise<Response> {
  return fetch(input, {
    signal: init.signal,
    headers: init.headers,
    credentials: "omit",
    referrerPolicy: "no-referrer",
  });
}

function hexadecimal(bytes: ArrayBuffer): string {
  return Array.from(new Uint8Array(bytes), (value) => value.toString(16).padStart(2, "0")).join("");
}

export async function sha256Hex(bytes: ArrayBuffer): Promise<string> {
  if (!globalThis.crypto?.subtle) {
    throw technical("UnsupportedBrowser", "SHA-256 verification is unavailable in this browser.");
  }
  return hexadecimal(await globalThis.crypto.subtle.digest("SHA-256", bytes));
}

export async function verifiedArtifactBytes(
  artifact: ResolvedArtifact,
  signal: AbortSignal,
  transport: ArtifactTransport = defaultArtifactTransport,
): Promise<ArrayBuffer> {
  let response: Response;
  try {
    response = await transport(new URL(artifact.url), {
      signal,
      headers: Object.freeze({ Accept: artifact.mediaType }),
    });
  } catch (error) {
    if (signal.aborted || (error instanceof DOMException && error.name === "AbortError")) {
      throw technical("Aborted", `Artifact read for ${artifact.artifactId} was cancelled.`, true);
    }
    if (error instanceof TechnicalFailure) throw error;
    throw technical("FetchFailed", `Artifact ${artifact.artifactId} is unavailable.`, true);
  }
  if (!response.ok) {
    throw technical("FetchFailed", `Artifact ${artifact.artifactId} returned HTTP ${response.status}.`, true);
  }
  let bytes: ArrayBuffer;
  try {
    bytes = await response.arrayBuffer();
  } catch (error) {
    if (signal.aborted || (error instanceof DOMException && error.name === "AbortError")) {
      throw technical("Aborted", `Artifact read for ${artifact.artifactId} was cancelled.`, true);
    }
    throw technical("FetchFailed", `Artifact body for ${artifact.artifactId} is unavailable.`, true);
  }
  if (bytes.byteLength !== artifact.byteSize) {
    throw technical("IntegrityFailed", `Artifact ${artifact.artifactId} has the wrong byte size.`);
  }
  if ((await sha256Hex(bytes)) !== artifact.sha256) {
    throw technical("IntegrityFailed", `Artifact ${artifact.artifactId} failed SHA-256 verification.`);
  }
  return bytes;
}

export interface SharedArtifactResource<T> {
  readonly controller: AbortController;
  readonly pending: Promise<T>;
  consumers: number;
  readonly settled: boolean;
}

export function createSharedArtifactResource<T>(
  load: (signal: AbortSignal) => Promise<T>,
): SharedArtifactResource<T> {
  const controller = new AbortController();
  let settled = false;
  const pending = Promise.resolve()
    .then(() => load(controller.signal))
    .finally(() => {
      settled = true;
    });
  return {
    controller,
    consumers: 0,
    pending,
    get settled() {
      return settled;
    },
  };
}

export async function waitForSharedArtifact<T>(
  resource: SharedArtifactResource<T>,
  signal: AbortSignal,
  message: string,
  onOrphaned?: () => void,
): Promise<T> {
  if (signal.aborted) throw technical("Aborted", message, true);
  resource.consumers += 1;
  let listener: (() => void) | undefined;
  const aborted = new Promise<never>((_, reject) => {
    listener = () => reject(technical("Aborted", message, true));
    signal.addEventListener("abort", listener, { once: true });
  });
  try {
    return await Promise.race([resource.pending, aborted]);
  } finally {
    if (listener) signal.removeEventListener("abort", listener);
    resource.consumers -= 1;
    if (resource.consumers === 0 && !resource.settled) {
      onOrphaned?.();
      resource.controller.abort("all consumers cancelled");
    }
  }
}

export function artifactCacheIdentity(
  context: ReleaseContext,
  artifacts: readonly ResolvedArtifact[],
): string {
  return JSON.stringify([
    context.dataReleaseId,
    context.manifest.dataProvenanceClass,
    ...artifacts.map((artifact) => [
      artifact.artifactId,
      artifact.role,
      artifact.mediaType,
      artifact.path,
      artifact.url,
      artifact.byteSize,
      artifact.sha256,
      artifact.dataReleaseId,
      artifact.dataProvenanceClass,
    ]),
  ]);
}

export async function waitForCaller<T>(
  pending: Promise<T>,
  signal: AbortSignal,
  message: string,
): Promise<T> {
  if (signal.aborted) throw technical("Aborted", message, true);
  let listener: (() => void) | undefined;
  const aborted = new Promise<never>((_, reject) => {
    listener = () => reject(technical("Aborted", message, true));
    signal.addEventListener("abort", listener, { once: true });
  });
  try {
    return await Promise.race([pending, aborted]);
  } finally {
    if (listener) signal.removeEventListener("abort", listener);
  }
}
