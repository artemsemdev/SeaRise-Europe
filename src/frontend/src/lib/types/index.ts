export interface GeocodingCandidate {
  rank: number;
  label: string;
  country: string;
  latitude: number;
  longitude: number;
  displayContext: string;
}

export interface SelectedLocation {
  label: string;
  displayContext: string;
  latitude: number;
  longitude: number;
}

export type ResultState =
  | "ModeledExposureDetected"
  | "NoModeledExposureDetected"
  | "DataUnavailable"
  | "OutOfScope"
  | "UnsupportedGeography";

export interface LegendColorStop {
  value: number;
  color: string;
  label: string;
}

export interface AssessmentResult {
  requestId: string;
  resultState: ResultState;
  location: { latitude: number; longitude: number };
  scenario: { id: string; displayName: string };
  horizon: { year: number; displayLabel: string };
  methodologyVersion: string;
  layerTileUrlTemplate: string | null;
  legendSpec: { colorStops: LegendColorStop[] } | null;
  generatedAt: string;
}

export interface GeocodingError {
  code: string;
  message: string;
}

export interface AssessmentError {
  code: string;
  message: string;
}

export interface ScenarioConfig {
  id: string;
  displayName: string;
  description: string;
  sortOrder: number;
}

export interface HorizonConfig {
  year: number;
  displayLabel: string;
  sortOrder: number;
}

export interface ConfigData {
  requestId: string;
  scenarios: ScenarioConfig[];
  horizons: HorizonConfig[];
  defaults: {
    scenarioId: string;
    horizonYear: number;
  };
}

export interface MethodologySource {
  name: string;
  provider: string;
  url: string;
}

export interface InterpretationGuidance {
  modeledExposureDetected: string;
  noModeledExposureDetected: string;
}

export interface MethodologyData {
  requestId: string;
  methodologyVersion: string;
  seaLevelProjectionSource: MethodologySource;
  elevationSource: MethodologySource;
  whatItDoes: string;
  whatItDoesNotAccountFor: string[];
  resolutionNote: string;
  interpretationGuidance: InterpretationGuidance;
  updatedAt: string;
}
