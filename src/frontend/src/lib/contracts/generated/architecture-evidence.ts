/* eslint-disable */
/** Generated from contracts/release/v1. Do not edit; run `npm run contracts:generate`. */

export type SeaRiseEuropePublicArchitectureEvidenceV1 = {
  $schema: "https://artemsemdev.github.io/SeaRise-Europe/contracts/release/v1/architecture-evidence.schema.json";
  schemaVersion: "1.0.0";
  dataReleaseId: string;
  dataProvenanceClass: "real-source" | "synthetic-fixture";
  codeRevision: string;
  generatedAt: string;
  verificationArtifacts?: VerificationArtifacts;
  runtime: {
    applicationApiCalls: 0;
    /**
     * @minItems 3
     * @maxItems 3
     */
    prohibitedRoutes: ["/assess", "/geocode", "/config"];
    scientificLookupArtifact: "projection-analysis-cog";
  };
  privacy: {
    searchSentToProjectServer: false;
    coordinatesSentToProjectServer: false;
  };
  /**
   * @minItems 1
   */
  measurements: [
    {
      name: string;
      status: "passed" | "failed" | "pending";
      observed: number | null;
      threshold: number;
      unit: string;
      evidencePath: string;
    },
    ...{
      name: string;
      status: "passed" | "failed" | "pending";
      observed: number | null;
      threshold: number;
      unit: string;
      evidencePath: string;
    }[]
  ];
} & (
  | {
      dataProvenanceClass: "real-source";
      verificationArtifacts: VerificationArtifacts;
      [k: string]: unknown;
    }
  | {
      dataProvenanceClass: "synthetic-fixture";
      [k: string]: unknown;
    }
);
/**
 * @minItems 3
 * @maxItems 3
 */
export type VerificationArtifacts = [
  string & "supply-chain/receipts/cryptographic-verification.json",
  string & "supply-chain/receipts/public-readback.json",
  string & "supply-chain/retention-receipt.json"
];
