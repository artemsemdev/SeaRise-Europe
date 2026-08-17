const ID = /^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/u;
const DISPOSITIONS = new Set(["synthetic-fixture", "private-engineering", "public-promoted"]);
const KEYS = ["schemaVersion", "appBuildId", "dataReleaseId", "releaseDisposition", "manifestPath"];

export function validateBuildIdentity(value, options = {}) {
  if (
    !value || typeof value !== "object" || Array.isArray(value)
    || Object.keys(value).length !== KEYS.length
    || Object.keys(value).some((key) => !KEYS.includes(key))
  ) {
    throw new TypeError("Build identity contains missing or additional properties.");
  }
  if (
    value.schemaVersion !== "1.0.0"
    || !ID.test(value.appBuildId)
    || !ID.test(value.dataReleaseId)
    || !DISPOSITIONS.has(value.releaseDisposition)
  ) {
    throw new TypeError("Build identity values are invalid.");
  }
  if (value.releaseDisposition === "private-engineering" && options.allowPrivate !== true) {
    throw new TypeError("Private engineering identity is restricted to explicit local Candidate mode.");
  }
  const manifestPath = `/releases/${value.dataReleaseId}/manifest.json`;
  if (value.manifestPath !== manifestPath) {
    throw new TypeError("Build identity manifest path is inconsistent.");
  }
  return Object.freeze({
    schemaVersion: "1.0.0",
    appBuildId: value.appBuildId,
    dataReleaseId: value.dataReleaseId,
    releaseDisposition: value.releaseDisposition,
    manifestPath,
  });
}

export function assertSameBuildIdentity(expected, actual, label = "build consumer", options = {}) {
  const left = validateBuildIdentity(expected, options);
  const right = validateBuildIdentity(actual, options);
  if (JSON.stringify(left) !== JSON.stringify(right)) {
    throw new TypeError(`${label} identity mismatch.`);
  }
  return right;
}
