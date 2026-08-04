/** Browser-oriented reference reader for the Phase 0 regional fixture. */

export type DomainState =
  | "modeled-exposure-detected"
  | "no-modeled-exposure-detected"
  | "data-unavailable"
  | "out-of-scope"
  | "unsupported-geography";

export interface Cell {
  row: number;
  column: number;
}

export interface LookupResult {
  state: DomainState;
  cell: Cell | null;
}

interface Grid {
  width: number;
  height: number;
  west: number;
  south: number;
  east: number;
  north: number;
  longitude_convention: "minus-180-to-180";
  edge_rule: "west-north-inclusive-east-south-exclusive";
}

interface Layer {
  status: "ready" | "blocked";
  values: Uint8Array | null;
  blockedBy: string[];
}

interface EncodedArray {
  encoding: "base64-uint8-row-major";
  data: string;
  sha256: string;
}

interface FixtureDocument {
  schemaVersion: number;
  fixtureId: string;
  grid: Grid;
  supportMask: EncodedArray;
  coastalMask: EncodedArray;
  layers: Record<
    string,
    { status: "ready"; values: EncodedArray } | { status: "blocked"; blockedBy: string[] }
  >;
}

export class FixtureContractError extends Error {}

export class RegionalFixture {
  private constructor(
    readonly fixtureId: string,
    readonly grid: Grid,
    private readonly supportMask: Uint8Array,
    private readonly coastalMask: Uint8Array,
    private readonly layers: ReadonlyMap<string, Layer>,
  ) {}

  static async parse(value: unknown): Promise<RegionalFixture> {
    const raw = value as FixtureDocument;
    if (!raw || raw.schemaVersion !== 1 || typeof raw.fixtureId !== "string") {
      throw new FixtureContractError("unsupported fixture schemaVersion");
    }
    const grid = raw.grid;
    if (
      !grid ||
      grid.longitude_convention !== "minus-180-to-180" ||
      grid.edge_rule !== "west-north-inclusive-east-south-exclusive"
    ) {
      throw new FixtureContractError("unsupported grid contract");
    }
    if (!Number.isInteger(grid.width) || !Number.isInteger(grid.height)) {
      throw new FixtureContractError("grid dimensions must be integers");
    }

    const cellCount = grid.width * grid.height;
    const support = await decodeArray(raw.supportMask, cellCount, "supportMask");
    const coastal = await decodeArray(raw.coastalMask, cellCount, "coastalMask");
    for (let index = 0; index < cellCount; index += 1) {
      if (![0, 1].includes(support[index]) || ![0, 1].includes(coastal[index])) {
        throw new FixtureContractError("support and coastal masks must contain only 0 or 1");
      }
      if (coastal[index] === 1 && support[index] === 0) {
        throw new FixtureContractError("coastalMask must be a subset of supportMask");
      }
    }

    const layers = new Map<string, Layer>();
    for (const [key, item] of Object.entries(raw.layers)) {
      if (item.status === "blocked") {
        if (!item.blockedBy?.length || "values" in item) {
          throw new FixtureContractError(`blocked layer ${key} needs reasons and no values`);
        }
        layers.set(key, { status: "blocked", values: null, blockedBy: item.blockedBy });
        continue;
      }
      if (item.status !== "ready" || !("values" in item)) {
        throw new FixtureContractError(`layer ${key} has unsupported status`);
      }
      const values = await decodeArray(item.values, cellCount, `layers.${key}.values`);
      if (values.some((cell) => ![0, 1, 255].includes(cell))) {
        throw new FixtureContractError(`layer ${key} contains an invalid class`);
      }
      layers.set(key, { status: "ready", values, blockedBy: [] });
    }
    return new RegionalFixture(raw.fixtureId, grid, support, coastal, layers);
  }

  cell(longitude: number, latitude: number): Cell | null {
    if (longitude < -180 || longitude > 180) {
      throw new FixtureContractError("longitude is outside [-180, 180]");
    }
    const { west, east, south, north, width, height } = this.grid;
    if (!(west <= longitude && longitude < east && south < latitude && latitude <= north)) {
      return null;
    }
    const column = Math.floor((longitude - west) / ((east - west) / width));
    const row = Math.floor((north - latitude) / ((north - south) / height));
    return row === height ? null : { row, column };
  }

  lookup(longitude: number, latitude: number, scenario: string, horizon: number): LookupResult {
    const cell = this.cell(longitude, latitude);
    if (!cell) return { state: "unsupported-geography", cell: null };
    const index = cell.row * this.grid.width + cell.column;
    if (this.supportMask[index] === 0) return { state: "unsupported-geography", cell };
    if (this.coastalMask[index] === 0) return { state: "out-of-scope", cell };

    const layer = this.layers.get(`${scenario}/${horizon}`);
    if (!layer || layer.status === "blocked" || !layer.values) {
      return { state: "data-unavailable", cell };
    }
    const states: Record<number, DomainState> = {
      0: "no-modeled-exposure-detected",
      1: "modeled-exposure-detected",
      255: "data-unavailable",
    };
    return { state: states[layer.values[index]], cell };
  }
}

async function decodeArray(
  raw: EncodedArray,
  expectedLength: number,
  label: string,
): Promise<Uint8Array> {
  if (!raw || raw.encoding !== "base64-uint8-row-major") {
    throw new FixtureContractError(`${label} has unsupported encoding`);
  }
  let values: Uint8Array;
  try {
    values = Uint8Array.from(atob(raw.data), (character) => character.charCodeAt(0));
  } catch {
    throw new FixtureContractError(`${label} is not valid base64`);
  }
  if (values.length !== expectedLength) {
    throw new FixtureContractError(`${label} length does not match the grid`);
  }
  const digest = await crypto.subtle.digest("SHA-256", values.slice().buffer);
  const hex = Array.from(new Uint8Array(digest))
    .map((value) => value.toString(16).padStart(2, "0"))
    .join("");
  if (hex !== raw.sha256) throw new FixtureContractError(`${label} SHA-256 mismatch`);
  return values;
}
