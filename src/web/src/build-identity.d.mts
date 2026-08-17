export interface BuildIdentityV1 {
  readonly schemaVersion: "1.0.0";
  readonly appBuildId: string;
  readonly dataReleaseId: string;
  readonly releaseDisposition: "synthetic-fixture" | "private-engineering" | "public-promoted";
  readonly manifestPath: string;
}

export interface BuildIdentityValidationOptions {
  readonly allowPrivate?: boolean;
}

export function validateBuildIdentity(
  value: unknown,
  options?: BuildIdentityValidationOptions,
): BuildIdentityV1;
export function assertSameBuildIdentity(
  expected: unknown,
  actual: unknown,
  label?: string,
  options?: BuildIdentityValidationOptions,
): BuildIdentityV1;
