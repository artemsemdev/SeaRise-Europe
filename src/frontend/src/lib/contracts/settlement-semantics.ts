export interface SettlementSearchShardDocument {
  readonly recordCount: number;
  readonly documents: readonly unknown[];
}

export function validateSettlementSearchShardSemantics(
  document: SettlementSearchShardDocument,
): void {
  if (document.recordCount !== document.documents.length) {
    throw new TypeError(
      "search shard recordCount differs from documents length",
    );
  }
}
