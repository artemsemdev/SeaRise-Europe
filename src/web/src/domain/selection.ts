import type { HorizonYear, ScenarioId } from "../contracts/generated/release-contract";
import {
  validateCoordinates,
  type Coordinates,
  type ReleaseContext,
  type Selection,
} from "./release";

export type SelectionCommand = (selection: Selection) => void;

/**
 * The single selection command used by map, search, and URL adapters.
 * It only records user intent; scientific assessment is performed elsewhere.
 */
export function createCoordinateSelection(
  context: ReleaseContext,
  scenario: ScenarioId,
  horizon: HorizonYear,
  coordinates: Coordinates,
): Selection {
  context.dataset(scenario, horizon);
  return Object.freeze({
    dataReleaseId: context.dataReleaseId,
    scenario,
    horizon,
    location: Object.freeze({
      kind: "coordinate" as const,
      coordinates: validateCoordinates(coordinates),
    }),
  });
}
