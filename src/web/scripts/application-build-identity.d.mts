import type { BuildIdentityV1 } from "./build-identity.mjs";

export const applicationBuildIdentityFile: "assets/application-build-identity.js";
export const applicationBuildIdentityMarker: "__SEARISE_APPLICATION_BUILD_IDENTITY_V1__";
export function serializeApplicationBuildIdentity(value: unknown): string;
export function extractApplicationBuildIdentity(source: string): BuildIdentityV1;
export function applicationBuildIdentityPlugin(identity: BuildIdentityV1): import("vite").Plugin;
export function validateApplicationBuildIdentity(options: {
  dist: string;
  expectedIdentity: BuildIdentityV1;
}): BuildIdentityV1;
