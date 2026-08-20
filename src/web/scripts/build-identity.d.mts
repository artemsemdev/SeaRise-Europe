import type { BuildIdentityV1 } from "../src/build-identity.mjs";

export { assertSameBuildIdentity, validateBuildIdentity } from "../src/build-identity.mjs";
export const buildIdentityFile: "build-identity.json";
export function resolveBuildIdentity(input: {
  readonly mode: string;
  readonly repositoryRoot: string;
  readonly environment?: Record<string, string | undefined>;
}): BuildIdentityV1;
export function privateCandidateBuildIdentity(dataReleaseId: string): BuildIdentityV1;
