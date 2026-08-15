import {
  HORIZON_YEARS,
  SCENARIO_IDS,
  type DataReleaseId,
  type HorizonYear,
  type ScenarioId,
} from "../contracts/generated/release-contract";
import {
  TechnicalFailure,
  validateCoordinates,
  type Selection,
  type SelectedLocation,
} from "./release";

function invalid(message: string): never {
  throw new TechnicalFailure({
    kind: "technical-error",
    code: "SchemaInvalid",
    message,
    recoverable: false,
  });
}

function isScenario(value: string): value is ScenarioId {
  return (SCENARIO_IDS as readonly string[]).includes(value);
}

function isHorizon(value: number): value is HorizonYear {
  return (HORIZON_YEARS as readonly number[]).includes(value);
}

function parseLocation(params: URLSearchParams): SelectedLocation | undefined {
  const latitude = params.get("lat");
  const longitude = params.get("lon");
  const placeId = params.get("place");
  if (latitude === null && longitude === null && placeId === null) return undefined;
  if (latitude === null || longitude === null) invalid("URL location requires both lat and lon.");
  if (latitude.trim() === "" || longitude.trim() === "") invalid("URL coordinates cannot be empty.");
  const coordinates = validateCoordinates({ latitude: Number(latitude), longitude: Number(longitude) });
  if (placeId !== null) {
    if (!/^[a-z0-9][a-z0-9._:-]{0,127}$/i.test(placeId)) invalid("URL place ID is invalid.");
    return Object.freeze({ kind: "settlement", placeId, coordinates });
  }
  return Object.freeze({ kind: "coordinate", coordinates });
}

export function parseUrlSelection(
  url: URL,
  pinnedReleaseId: DataReleaseId,
  defaults: Readonly<{ scenario: ScenarioId; horizon: HorizonYear }>,
): Selection | undefined {
  const release = url.searchParams.get("release") ?? pinnedReleaseId;
  if (release !== pinnedReleaseId) {
    throw new TechnicalFailure({
      kind: "technical-error",
      code: "ReleaseIdentityMismatch",
      message: "The shared URL names a different release than this application build.",
      recoverable: false,
    });
  }
  const scenarioValue = url.searchParams.get("scenario") ?? defaults.scenario;
  const horizonValue = Number(url.searchParams.get("horizon") ?? defaults.horizon);
  if (!isScenario(scenarioValue)) invalid("URL scenario is unsupported.");
  if (!isHorizon(horizonValue)) invalid("URL horizon is unsupported.");
  const location = parseLocation(url.searchParams);
  if (!location) return undefined;
  return Object.freeze({
    dataReleaseId: pinnedReleaseId,
    scenario: scenarioValue,
    horizon: horizonValue,
    location,
  });
}

export function writeUrlSelection(url: URL, selection: Selection): URL {
  const next = new URL(url);
  next.searchParams.set("release", selection.dataReleaseId);
  next.searchParams.set("scenario", selection.scenario);
  next.searchParams.set("horizon", String(selection.horizon));
  const coordinateText = (value: number) => (Object.is(value, -0) ? "-0" : String(value));
  next.searchParams.set("lat", coordinateText(selection.location.coordinates.latitude));
  next.searchParams.set("lon", coordinateText(selection.location.coordinates.longitude));
  if (selection.location.kind === "settlement") {
    next.searchParams.set("place", selection.location.placeId);
  } else {
    next.searchParams.delete("place");
  }
  return next;
}
