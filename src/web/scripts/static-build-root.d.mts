export const STATIC_BUILD_ROOT_ENV: "SEARISE_WEB_DIST_ROOT";
export const LIFECYCLE_BUILD_ENV: "SEARISE_LIFECYCLE_BUILD";
export const LIFECYCLE_ROOT_ENV: "SEARISE_LIFECYCLE_ROOT";

export function resolveStaticBuildRoot(options: Readonly<{
  webRoot: string;
  environment?: Readonly<Record<string, string | undefined>>;
}>): string;
