import type { AtlasDataSource } from "./data-source";
import { createFixtureAtlasDataSource } from "./fixture-data-source";
import { createRealLocalAtlasDataSource, type HttpAtlasDataSourceOptions } from "./http-data-source";

export const DEFAULT_ATLAS_EDITION = "synthetic-fixture" as const;

export type AtlasDataSourceOptions =
  | Readonly<{ edition: "synthetic-fixture" }>
  | (Readonly<{ edition: "real-local" }> & HttpAtlasDataSourceOptions);

export function createAtlasDataSource(
  options: AtlasDataSourceOptions = { edition: DEFAULT_ATLAS_EDITION },
): AtlasDataSource {
  return options.edition === "real-local"
    ? createRealLocalAtlasDataSource(options)
    : createFixtureAtlasDataSource();
}
