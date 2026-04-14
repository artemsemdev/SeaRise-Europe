import { describe, it, expect } from "vitest";
import type { MethodologyData } from "@/lib/types";

// Captured from a live `GET /v1/config/methodology` response on 2026-04-13.
// If the real API ever drifts from this shape, the TypeScript assignment
// below will fail to compile (or the runtime assertions below will trip),
// which is the whole point of this guard: MethodologyPanel was silently
// broken for months because the type and the API had diverged.
const LIVE_RESPONSE_FIXTURE = {
  requestId: "req_c630599d3b1e",
  methodologyVersion: "v1.0",
  seaLevelProjectionSource: {
    name: "IPCC AR6 sea-level projections",
    provider: "NASA Sea Level Change Team",
    url: "https://sealevel.nasa.gov/ipcc-ar6-sea-level-projection-tool",
  },
  elevationSource: {
    name: "Copernicus DEM (Digital Surface Model, GLO-30)",
    provider: "Copernicus / DLR",
    url: "https://dataspace.copernicus.eu/explore-data/data-collections/copernicus-contributing-missions/collections-description/COP-DEM",
  },
  whatItDoes:
    "This methodology combines IPCC AR6 mean sea-level rise projections with Copernicus DEM surface elevation to identify locations in the coastal analysis zone where projected mean sea-level rise reaches or exceeds terrain elevation under the selected scenario and time horizon.",
  whatItDoesNotAccountFor: [
    "Flood defenses or adaptation infrastructure",
    "Hydrodynamic flow behavior or detailed water pathways",
    "Storm surge or tidal variability",
    "Land subsidence or uplift",
    "Local drainage systems or pumping infrastructure",
  ],
  resolutionNote:
    "Results are derived from approximately 30-meter resolution datasets. Results cannot distinguish conditions within a single city block and are not suitable for site-specific engineering or property-level decisions.",
  interpretationGuidance: {
    modeledExposureDetected:
      "The selected point falls within a zone where modeled sea-level rise reaches or exceeds the terrain elevation under the selected scenario and time horizon.",
    noModeledExposureDetected:
      "The selected point does not fall within a modeled exposure zone under the selected scenario and time horizon. This does not constitute a safety determination.",
  },
  updatedAt: "2026-04-03T00:00:00Z",
};

function isNonEmptyString(value: unknown): value is string {
  return typeof value === "string" && value.length > 0;
}

function assertMethodologyData(raw: unknown): asserts raw is MethodologyData {
  if (!raw || typeof raw !== "object") {
    throw new Error("methodology response is not an object");
  }
  const r = raw as Record<string, unknown>;

  for (const field of [
    "requestId",
    "methodologyVersion",
    "whatItDoes",
    "resolutionNote",
    "updatedAt",
  ]) {
    if (!isNonEmptyString(r[field])) {
      throw new Error(`methodology.${field} must be a non-empty string`);
    }
  }

  for (const srcField of ["seaLevelProjectionSource", "elevationSource"]) {
    const src = r[srcField] as Record<string, unknown> | undefined;
    if (!src || typeof src !== "object") {
      throw new Error(`methodology.${srcField} must be an object`);
    }
    for (const sub of ["name", "provider", "url"]) {
      if (!isNonEmptyString(src[sub])) {
        throw new Error(`methodology.${srcField}.${sub} must be a non-empty string`);
      }
    }
  }

  if (!Array.isArray(r.whatItDoesNotAccountFor) || r.whatItDoesNotAccountFor.length === 0) {
    throw new Error("methodology.whatItDoesNotAccountFor must be a non-empty array");
  }
  for (const item of r.whatItDoesNotAccountFor) {
    if (!isNonEmptyString(item)) {
      throw new Error("methodology.whatItDoesNotAccountFor entries must be non-empty strings");
    }
  }

  const guidance = r.interpretationGuidance as Record<string, unknown> | undefined;
  if (!guidance || typeof guidance !== "object") {
    throw new Error("methodology.interpretationGuidance must be an object");
  }
  for (const key of ["modeledExposureDetected", "noModeledExposureDetected"]) {
    if (!isNonEmptyString(guidance[key])) {
      throw new Error(`methodology.interpretationGuidance.${key} must be a non-empty string`);
    }
  }
}

describe("methodology API contract", () => {
  it("captured fixture is structurally a MethodologyData", () => {
    assertMethodologyData(LIVE_RESPONSE_FIXTURE);
    // Compile-time guard: this assignment only type-checks if the fixture's
    // shape still matches MethodologyData. Renaming any field in the type
    // without updating the fixture (or the API) will fail `tsc --noEmit`.
    const typed: MethodologyData = LIVE_RESPONSE_FIXTURE;
    expect(typed.methodologyVersion).toBe("v1.0");
    expect(typed.whatItDoesNotAccountFor).toHaveLength(5);
  });

  it("rejects a response missing whatItDoesNotAccountFor", () => {
    const broken = { ...LIVE_RESPONSE_FIXTURE } as Record<string, unknown>;
    delete broken.whatItDoesNotAccountFor;
    expect(() => assertMethodologyData(broken)).toThrow(/whatItDoesNotAccountFor/);
  });

  it("rejects a response missing interpretationGuidance", () => {
    const broken = { ...LIVE_RESPONSE_FIXTURE } as Record<string, unknown>;
    delete broken.interpretationGuidance;
    expect(() => assertMethodologyData(broken)).toThrow(/interpretationGuidance/);
  });

  it("rejects a source entry missing a url", () => {
    const broken = {
      ...LIVE_RESPONSE_FIXTURE,
      seaLevelProjectionSource: {
        name: "x",
        provider: "y",
      },
    };
    expect(() => assertMethodologyData(broken)).toThrow(/seaLevelProjectionSource\.url/);
  });

  it("rejects the legacy shape that shipped in the broken version of the frontend", () => {
    // The old type had `models[]` / `limitations[]` / `dataUpdated`; the real
    // API never spoke this. If someone re-introduces that shape, this fails.
    const legacy = {
      requestId: "req_x",
      models: [{ id: "a", name: "a" }],
      limitations: [],
      dataUpdated: "2026-01-01",
    };
    expect(() => assertMethodologyData(legacy)).toThrow();
  });
});
