import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { ManifestRepository } from "../data/manifest-repository";
import type { ReleaseContext } from "../domain/release";

export const FIXTURE_RELEASE_ID = "searise-europe-v1.0.0-20260810-c096aeab4e09";
export const FIXTURE_ORIGIN = "https://fixture.searise.invalid";
export const FIXTURE_ROOT = resolve(
  process.cwd(),
  "../../contracts/release/v1/fixtures/release",
  FIXTURE_RELEASE_ID,
);

export function fixtureBytes(path: string): Uint8Array {
  return readFileSync(resolve(FIXTURE_ROOT, path));
}

export function responseBody(bytes: Uint8Array): ArrayBuffer {
  const copy = new Uint8Array(bytes.byteLength);
  copy.set(bytes);
  return copy.buffer;
}

export async function fixtureReleaseContext(): Promise<ReleaseContext> {
  const manifestBytes = fixtureBytes("manifest.json");
  const repository = new ManifestRepository({
    manifestUrl: `${FIXTURE_ORIGIN}/releases/${FIXTURE_RELEASE_ID}/manifest.json`,
    allowedOrigins: [FIXTURE_ORIGIN],
    expectedDisposition: "synthetic-fixture",
    transport: async () =>
      new Response(responseBody(manifestBytes), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
  });
  return repository.load(FIXTURE_RELEASE_ID, new AbortController().signal);
}

export function fixtureArtifactPath(url: URL): string {
  const prefix = `/releases/${FIXTURE_RELEASE_ID}/`;
  if (!url.pathname.startsWith(prefix)) throw new Error(`unexpected fixture URL ${url.href}`);
  return url.pathname.slice(prefix.length);
}
