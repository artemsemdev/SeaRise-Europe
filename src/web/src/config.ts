import type { BuildIdentityV1 } from "./build-identity.mjs";

const ID = /^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/u;
const DISPOSITIONS = new Set(["synthetic-fixture", "private-engineering", "public-promoted"]);
const KEYS = ["schemaVersion", "appBuildId", "dataReleaseId", "releaseDisposition", "manifestPath"];

function runtimeBuildIdentity(value: unknown): BuildIdentityV1 {
  if (
    !value || typeof value !== "object" || Array.isArray(value)
    || Object.keys(value).length !== KEYS.length
    || Object.keys(value).some((key) => !KEYS.includes(key))
  ) throw new TypeError("Runtime build identity contains missing or additional properties.");
  const record = value as Record<string, unknown>;
  if (
    record.schemaVersion !== "1.0.0"
    || typeof record.appBuildId !== "string" || !ID.test(record.appBuildId)
    || typeof record.dataReleaseId !== "string" || !ID.test(record.dataReleaseId)
    || typeof record.releaseDisposition !== "string" || !DISPOSITIONS.has(record.releaseDisposition)
    || typeof record.manifestPath !== "string"
    || record.manifestPath !== `/releases/${record.dataReleaseId}/manifest.json`
  ) throw new TypeError("Runtime build identity is invalid or inconsistent.");
  return Object.freeze({
    schemaVersion: "1.0.0",
    appBuildId: record.appBuildId,
    dataReleaseId: record.dataReleaseId,
    releaseDisposition: record.releaseDisposition as BuildIdentityV1["releaseDisposition"],
    manifestPath: record.manifestPath,
  });
}

export const runtimeConfig = runtimeBuildIdentity(
  JSON.parse(__SEARISE_BUILD_IDENTITY_JSON__) as unknown,
);

export function releaseLabel(): string {
  switch (runtimeConfig.releaseDisposition) {
    case "public-promoted":
      return "Public promoted release";
    case "private-engineering":
      return "Private engineering release · local only";
    case "synthetic-fixture":
      return "Synthetic fixture · illustrative only";
  }
}
