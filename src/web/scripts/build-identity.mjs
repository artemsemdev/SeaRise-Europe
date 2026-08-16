import { loadEnv } from "vite";
import { validateBuildIdentity } from "../src/build-identity.mjs";

export { assertSameBuildIdentity, validateBuildIdentity } from "../src/build-identity.mjs";

export const buildIdentityFile = "build-identity.json";
const DEFAULT_RELEASE_ID = "searise-europe-v1.0.0-20260810-c096aeab4e09";

export function resolveBuildIdentity({ mode, repositoryRoot, environment = process.env }) {
  const fileEnvironment = loadEnv(mode, repositoryRoot, "SEARISE_");
  const dataReleaseId = environment.SEARISE_DATA_RELEASE_ID
    ?? fileEnvironment.SEARISE_DATA_RELEASE_ID
    ?? DEFAULT_RELEASE_ID;
  return validateBuildIdentity({
    schemaVersion: "1.0.0",
    appBuildId: environment.SEARISE_APP_BUILD_ID
      ?? fileEnvironment.SEARISE_APP_BUILD_ID
      ?? "local-fixture",
    dataReleaseId,
    releaseDisposition: environment.SEARISE_RELEASE_DISPOSITION
      ?? fileEnvironment.SEARISE_RELEASE_DISPOSITION
      ?? "synthetic-fixture",
    manifestPath: `/releases/${dataReleaseId}/manifest.json`,
  });
}

export function privateCandidateBuildIdentity(dataReleaseId) {
  return validateBuildIdentity({
    schemaVersion: "1.0.0",
    appBuildId: "private-local-candidate",
    dataReleaseId,
    releaseDisposition: "private-engineering",
    manifestPath: `/releases/${dataReleaseId}/manifest.json`,
  }, { allowPrivate: true });
}
