export const runtimeConfig = Object.freeze({
  appBuildId: __APP_BUILD_ID__,
  dataReleaseId: __DATA_RELEASE_ID__,
  releaseDisposition: __RELEASE_DISPOSITION__,
  manifestUrl: __MANIFEST_URL__,
});

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
