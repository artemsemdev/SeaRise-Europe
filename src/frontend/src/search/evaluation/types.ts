export interface SearchDocument {
  placeId: string;
  displayName: string;
  searchNames: string[];
  countryCode: string;
  admin1Name: string | null;
  population: number | null;
  featureCode: string;
  distanceToCoastMeters: number;
  isCoastal: boolean;
}

export interface CandidateDocument {
  ordinal: number;
  record: SearchDocument;
  terms: string;
}

export interface EngineDescriptor {
  engineId: "minisearch" | "flexsearch" | "searise-codepoint-trie";
  packageVersion: "7.2.0" | "0.8.212" | "1.0.0";
  serializationVersion: "minisearch-json-v1" | "flexsearch-export-v1" | "codepoint-trie-json-v1";
}

export interface EvaluationIdentity {
  evaluationId: string;
  shardId: string;
}

export interface CandidateAdapter {
  readonly descriptor: EngineDescriptor;
  build(documents: readonly CandidateDocument[], identity: EvaluationIdentity): unknown;
  serialize(index: unknown): Uint8Array;
  deserialize(bytes: Uint8Array, documents: readonly CandidateDocument[], identity: EvaluationIdentity): unknown;
  search(index: unknown, query: string, limit: number): number[];
}
