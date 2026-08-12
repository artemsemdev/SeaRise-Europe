export interface SettlementSearchShardDocument {
  readonly recordCount: number;
  readonly documents?: readonly unknown[];
  readonly records?: readonly unknown[];
}

export function validateSettlementSearchShardSemantics(
  document: SettlementSearchShardDocument,
): void {
  const records = document.documents ?? document.records;
  if (!records || document.recordCount !== records.length) {
    throw new TypeError(
      "search shard recordCount differs from records length",
    );
  }
}
