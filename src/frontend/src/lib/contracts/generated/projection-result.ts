/* eslint-disable */
/** Generated from contracts/release/v1. Do not edit; run `npm run contracts:generate`. */

export type SeaRiseEuropeProjectionResultV1 = ProjectionAvailable | DataUnavailable | OutOfScope | UnsupportedGeography;
export type ProjectionAvailable = Base & {
  state?: "ProjectionAvailable";
  reasonCode?: "projection-available";
  geography: "InEuropeAndCoastalZone";
  projection: Projection;
  source: SelectedSourceIdentity;
  [k: string]: unknown;
};
export type ReleaseAuthority = {
  [k: string]: unknown;
} & {
  automatedValidation: "pending" | "passed" | "failed";
  releaseDisposition: "pending-owner" | "approved" | "rejected" | "blocked";
  dataProvenanceClass: "real-source" | "synthetic-fixture";
  statusDisclosureRequired: boolean;
};
export type SelectedSourceIdentity = SourceIdentity & {
  distanceKilometres?: number;
  [k: string]: unknown;
};
export type DataUnavailable = Base & {
  [k: string]: unknown;
};
export type OutOfScope = Base & {
  state?: "OutOfScope";
  reasonCode?: "outside-coastal-scope";
  geography: "InEuropeOutsideCoastalZone";
  source: null;
  [k: string]: unknown;
};
export type UnsupportedGeography = Base & {
  state?: "UnsupportedGeography";
  reasonCode?: "outside-europe-support";
  geography: "OutsideEurope";
  source: null;
  [k: string]: unknown;
};

export interface Base {
  $schema: "https://artemsemdev.github.io/SeaRise-Europe/contracts/release/v1/projection-result.schema.json";
  schemaVersion: "1.0.0";
  dataReleaseId: string;
  methodologyVersion: "ar6-regional-projection-v1";
  state: "ProjectionAvailable" | "DataUnavailable" | "OutOfScope" | "UnsupportedGeography";
  reasonCode: string;
  selection: Selection;
  releaseAuthority: ReleaseAuthority;
  [k: string]: unknown;
}
export interface Selection {
  location: Coordinates;
  scenario: "ssp1-26" | "ssp2-45" | "ssp5-85";
  horizon: 2030 | 2050 | 2100;
}
export interface Coordinates {
  latitude: number;
  longitude: number;
}
export interface Projection {
  lowerMillimetres: number;
  medianMillimetres: number;
  upperMillimetres: number;
  storedUnits: "mm";
  scaleToMetres: 0.001;
  baseline: "1995-2014 mean";
  confidence: "medium";
  /**
   * @minItems 3
   * @maxItems 3
   */
  quantiles: [0.167, 0.5, 0.833];
}
export interface SourceIdentity {
  sourceRelease: "20210809";
  memberSha256: string;
  locationId: number;
  location: Coordinates;
  distanceKilometres: number;
  nativeResolutionDegrees: 1;
  locationFamily: "grid";
  lookupOperator: "nearest-source-grid-location";
}
