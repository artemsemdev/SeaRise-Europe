/* eslint-disable */
/** Generated from contracts/release/v1. Do not edit; run `npm run contracts:generate`. */

export interface SeaRiseEuropeScenarioAndProjectionSemanticsConfigurationV1 {
  $schema: "https://artemsemdev.github.io/SeaRise-Europe/contracts/release/v1/scenario-config.schema.json";
  schemaVersion: "1.0.0";
  dataReleaseId: string;
  dataProvenanceClass: "real-source" | "synthetic-fixture";
  /**
   * @minItems 3
   * @maxItems 3
   */
  scenarios: ["ssp1-26", "ssp2-45", "ssp5-85"];
  /**
   * @minItems 3
   * @maxItems 3
   */
  horizons: [2030, 2050, 2100];
  defaults: {
    scenario: "ssp2-45";
    horizon: 2050;
  };
  /**
   * @minItems 9
   * @maxItems 9
   */
  layerMatrix: [
    Ssp1262030,
    Ssp1262050,
    Ssp1262100,
    Ssp2452030,
    Ssp2452050,
    Ssp2452100,
    Ssp5852030,
    Ssp5852050,
    Ssp5852100
  ];
  /**
   * @minItems 4
   * @maxItems 4
   */
  resultStates: ["ProjectionAvailable", "DataUnavailable", "OutOfScope", "UnsupportedGeography"];
  lookup: {
    sourceLocationFamily: "grid";
    operator: "nearest-source-grid-location";
    maximumDistanceKilometres: 100;
    distanceLimitInclusive: true;
    nativeResolutionDegrees: 1;
    interpolation: "none";
    tideGaugeFallback: "prohibited";
    nodataSubstitution: "prohibited";
    analysisArtifactRole: "projection-analysis-cog";
    visualArtifactScientificInput: false;
  };
  projectionSemantics: {
    modeledQuantity: "regional-relative-sea-level-change";
    units: "m";
    baseline: "1995-2014 mean";
    confidence: "medium";
    quantiles: {
      lower: 0.167;
      median: 0.5;
      upper: 0.833;
    };
  };
  /**
   * @minItems 5
   * @maxItems 5
   */
  prohibitedClaims: ["flooding", "inundation", "terrain-exposure", "flood-probability", "property-risk"];
}
export interface Ssp1262030 {
  scenario: "ssp1-26";
  horizon: 2030;
}
export interface Ssp1262050 {
  scenario: "ssp1-26";
  horizon: 2050;
}
export interface Ssp1262100 {
  scenario: "ssp1-26";
  horizon: 2100;
}
export interface Ssp2452030 {
  scenario: "ssp2-45";
  horizon: 2030;
}
export interface Ssp2452050 {
  scenario: "ssp2-45";
  horizon: 2050;
}
export interface Ssp2452100 {
  scenario: "ssp2-45";
  horizon: 2100;
}
export interface Ssp5852030 {
  scenario: "ssp5-85";
  horizon: 2030;
}
export interface Ssp5852050 {
  scenario: "ssp5-85";
  horizon: 2050;
}
export interface Ssp5852100 {
  scenario: "ssp5-85";
  horizon: 2100;
}
