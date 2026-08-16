export interface PrivateMeasurementOutputOptions {
  readonly outputPath: string;
  readonly candidateRoot: string;
  readonly distRoot: string;
}

export function assertPrivateMeasurementOutput(
  options: PrivateMeasurementOutputOptions,
): string;
