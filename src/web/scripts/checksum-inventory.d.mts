interface ChecksumManifest {
  readonly artifacts: readonly {
    readonly path: string;
    readonly sha256: string;
  }[];
}

export const CHECKSUM_SELF_REFERENCE_EXCLUSIONS: readonly string[];
export function parseChecksumText(text: string): Map<string, string>;
export function checksumInventory(manifest: ChecksumManifest): Map<string, string>;
export function assertChecksumInventory(
  manifest: ChecksumManifest,
  checksumText: string,
): Map<string, string>;
export function canonicalChecksumText(manifest: ChecksumManifest): string;
