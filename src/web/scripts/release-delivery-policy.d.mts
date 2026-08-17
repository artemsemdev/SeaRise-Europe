export interface ReleaseDeliveryArtifact {
  readonly artifactId: string;
  readonly role: string;
  readonly path: string;
  readonly mediaType: string;
  readonly byteSize: number;
  readonly sha256: string;
}

export const RELEASE_DELIVERY_POLICY: Readonly<{
  contractVersion: number;
  defaultCacheControl: string;
  searchIndex: Readonly<{
    mediaType: string;
    role: string;
    identities: Readonly<Record<string, string>>;
  }>;
}>;

export function releaseDeliveryPolicy(
  relativePath: string,
  artifact?: ReleaseDeliveryArtifact,
  actualByteSize?: number,
): Readonly<{
  cacheControl: string;
  contentType: string;
  etag: string | null;
  networkOnly: boolean;
}>;

export function assertVisualPmtilesStatus(status: number): void;
