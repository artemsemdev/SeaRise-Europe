export type Ar6ScopeState = "in-scope" | "out-of-scope" | "unsupported-geography";

export interface Ar6LookupContract {
  lookup: {
    sourceFamily: "native-one-degree-grid";
    locationSelection: "nearest-source-grid-location";
    maximumDistanceKm: number;
    distance: {
      algorithm: "haversine";
      earthMeanRadiusKm: number;
      boundary: "inclusive";
      reportedDistanceDecimalPlaces: number;
    };
    tieBreak: "lowest-source-location-id";
    requiredQuantiles: number[];
    nodataRule: string;
    interpolation: "forbidden";
    extrapolation: "forbidden";
  };
  publicationMetadata: {
    confidence: "medium";
    nativeResolutionDegrees: number;
    methodVersion: string;
    sourceRelease: string;
  };
  resultContract: {
    stableReasonCodes: {
      sourceValueNodata: string;
      sourceGridBeyondMaximumDistance: string;
      outsideCoastalScope: string;
      outsideEuropeSupport: string;
    };
  };
}

export interface Ar6GridLocation {
  locationId: number;
  latitude: number;
  longitude: number;
  lowerMillimetres: number | null;
  centralMillimetres: number | null;
  upperMillimetres: number | null;
}

export interface Ar6GridInterval {
  scenario: "ssp1-26" | "ssp2-45" | "ssp5-85";
  horizon: 2030 | 2050 | 2100;
  baseline: "1995-2014 mean";
  sourceRelease: "20210809";
  memberSha256: string;
  locations: readonly Ar6GridLocation[];
}

export interface Ar6ResolvedSource {
  locationId: number;
  latitude: number;
  longitude: number;
  family: "grid";
  distanceKilometres: number;
}

interface ResultIdentity {
  scenario: Ar6GridInterval["scenario"];
  horizon: Ar6GridInterval["horizon"];
  baseline: Ar6GridInterval["baseline"];
  confidence: "medium";
  nativeResolutionDegrees: number;
  methodVersion: string;
  sourceRelease: "20210809";
  memberSha256: string;
}

export type Ar6ProjectionLookupResult =
  | (ResultIdentity & {
      state: "ProjectionAvailable";
      reasonCode: "projection-available";
      source: Ar6ResolvedSource;
      lowerMillimetres: number;
      centralMillimetres: number;
      upperMillimetres: number;
      lowerMetres: number;
      centralMetres: number;
      upperMetres: number;
    })
  | (ResultIdentity & {
      state: "DataUnavailable";
      reasonCode: string;
      source: Ar6ResolvedSource;
    })
  | (ResultIdentity & {
      state: "OutOfScope" | "UnsupportedGeography";
      reasonCode: string;
      source: null;
    });

export class Ar6LookupContractError extends Error {}

function validateContract(contract: Ar6LookupContract): void {
  const lookup = contract.lookup;
  const distance = lookup.distance;
  const metadata = contract.publicationMetadata;
  if (
    lookup.sourceFamily !== "native-one-degree-grid" ||
    lookup.locationSelection !== "nearest-source-grid-location" ||
    lookup.tieBreak !== "lowest-source-location-id" ||
    lookup.nodataRule !==
      "resolve-nearest-location-first-then-fail-if-any-required-quantile-is-fill" ||
    lookup.interpolation !== "forbidden" ||
    lookup.extrapolation !== "forbidden"
  ) {
    throw new Ar6LookupContractError("AR6 lookup semantics changed");
  }
  if (
    lookup.maximumDistanceKm !== 100 ||
    distance.algorithm !== "haversine" ||
    distance.earthMeanRadiusKm !== 6371.0088 ||
    distance.boundary !== "inclusive" ||
    distance.reportedDistanceDecimalPlaces !== 6
  ) {
    throw new Ar6LookupContractError("AR6 lookup distance contract changed");
  }
  if (JSON.stringify(lookup.requiredQuantiles) !== JSON.stringify([0.167, 0.5, 0.833])) {
    throw new Ar6LookupContractError("AR6 lookup quantiles changed");
  }
  if (
    metadata.confidence !== "medium" ||
    metadata.nativeResolutionDegrees !== 1 ||
    metadata.methodVersion !== "ar6-regional-projection-v1" ||
    metadata.sourceRelease !== "20210809"
  ) {
    throw new Ar6LookupContractError("AR6 publication metadata changed");
  }
}

function resultIdentity(
  interval: Ar6GridInterval,
  contract: Ar6LookupContract,
): ResultIdentity {
  return {
    scenario: interval.scenario,
    horizon: interval.horizon,
    baseline: interval.baseline,
    confidence: contract.publicationMetadata.confidence,
    nativeResolutionDegrees: contract.publicationMetadata.nativeResolutionDegrees,
    methodVersion: contract.publicationMetadata.methodVersion,
    sourceRelease: interval.sourceRelease,
    memberSha256: interval.memberSha256,
  };
}

function haversineKilometres(
  queryLatitude: number,
  queryLongitude: number,
  sourceLatitude: number,
  sourceLongitude: number,
  radiusKilometres: number,
): number {
  const radians = Math.PI / 180;
  const queryLatitudeRadians = queryLatitude * radians;
  const sourceLatitudeRadians = sourceLatitude * radians;
  const latitudeDelta = sourceLatitudeRadians - queryLatitudeRadians;
  const rawLongitudeDelta = (sourceLongitude - queryLongitude) * radians;
  const longitudeDelta =
    ((((rawLongitudeDelta + Math.PI) % (2 * Math.PI)) + 2 * Math.PI) %
      (2 * Math.PI)) -
    Math.PI;
  const haversine =
    Math.sin(latitudeDelta / 2) ** 2 +
    Math.cos(queryLatitudeRadians) *
      Math.cos(sourceLatitudeRadians) *
      Math.sin(longitudeDelta / 2) ** 2;
  return (
    2 *
    radiusKilometres *
    Math.atan2(Math.sqrt(haversine), Math.sqrt(Math.max(0, 1 - haversine)))
  );
}

function rounded(value: number, decimalPlaces: number): number {
  const factor = 10 ** decimalPlaces;
  return Math.round(value * factor) / factor;
}

export function lookupAr6Projection(
  interval: Ar6GridInterval,
  latitude: number,
  longitude: number,
  scope: Ar6ScopeState,
  contract: Ar6LookupContract,
): Ar6ProjectionLookupResult {
  if (!Number.isFinite(latitude) || latitude < -90 || latitude > 90) {
    throw new RangeError("Latitude must be finite and between -90 and 90");
  }
  if (!Number.isFinite(longitude) || longitude < -180 || longitude > 180) {
    throw new RangeError("Longitude must be finite and between -180 and 180");
  }
  validateContract(contract);
  const identity = resultIdentity(interval, contract);
  const reasons = contract.resultContract.stableReasonCodes;
  if (scope === "unsupported-geography") {
    return {
      ...identity,
      state: "UnsupportedGeography",
      reasonCode: reasons.outsideEuropeSupport,
      source: null,
    };
  }
  if (scope === "out-of-scope") {
    return {
      ...identity,
      state: "OutOfScope",
      reasonCode: reasons.outsideCoastalScope,
      source: null,
    };
  }
  if (interval.locations.length === 0) {
    throw new Ar6LookupContractError("AR6 lookup grid is empty");
  }

  let selected: Ar6GridLocation | null = null;
  let selectedDistance = Number.POSITIVE_INFINITY;
  for (const candidate of interval.locations) {
    const distance = haversineKilometres(
      latitude,
      longitude,
      candidate.latitude,
      candidate.longitude,
      contract.lookup.distance.earthMeanRadiusKm,
    );
    if (
      distance < selectedDistance ||
      (distance === selectedDistance &&
        (selected === null || candidate.locationId < selected.locationId))
    ) {
      selected = candidate;
      selectedDistance = distance;
    }
  }
  if (selected === null) {
    throw new Ar6LookupContractError("AR6 lookup grid has no source location");
  }
  const source: Ar6ResolvedSource = {
    locationId: selected.locationId,
    latitude: selected.latitude,
    longitude: selected.longitude,
    family: "grid",
    distanceKilometres: rounded(
      selectedDistance,
      contract.lookup.distance.reportedDistanceDecimalPlaces,
    ),
  };
  if (selectedDistance > contract.lookup.maximumDistanceKm) {
    return {
      ...identity,
      state: "DataUnavailable",
      reasonCode: reasons.sourceGridBeyondMaximumDistance,
      source,
    };
  }
  const { lowerMillimetres, centralMillimetres, upperMillimetres } = selected;
  if (
    lowerMillimetres === null ||
    centralMillimetres === null ||
    upperMillimetres === null
  ) {
    return {
      ...identity,
      state: "DataUnavailable",
      reasonCode: reasons.sourceValueNodata,
      source,
    };
  }
  return {
    ...identity,
    state: "ProjectionAvailable",
    reasonCode: "projection-available",
    source,
    lowerMillimetres,
    centralMillimetres,
    upperMillimetres,
    lowerMetres: lowerMillimetres / 1000,
    centralMetres: centralMillimetres / 1000,
    upperMetres: upperMillimetres / 1000,
  };
}
