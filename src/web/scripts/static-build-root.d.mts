export const STATIC_BUILD_ROOT_ENV: "SEARISE_WEB_DIST_ROOT";
export const LIFECYCLE_BUILD_ENV: "SEARISE_LIFECYCLE_BUILD";
export const LIFECYCLE_ROOT_ENV: "SEARISE_LIFECYCLE_ROOT";
export const LIFECYCLE_ROOT_TOKEN_ENV: "SEARISE_LIFECYCLE_ROOT_TOKEN";

export function createOwnedLifecycleRoot(): Readonly<{ root: string; token: string }>;
export function validateOwnedLifecycleRoot(value: Readonly<{ root: string; token: string | undefined }>): string;

export function resolveStaticBuildRoot(options: Readonly<{
  webRoot: string;
  environment?: Readonly<Record<string, string | undefined>>;
}>): string;
