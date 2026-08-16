import { act, renderHook } from "@testing-library/react";
import { beforeAll, describe, expect, it, vi } from "vitest";
import {
  HORIZON_YEARS,
  SCENARIO_IDS,
  type HorizonYear,
  type ScenarioId,
} from "../contracts/generated/release-contract";
import {
  selectionKey,
  type AcceptedProjection,
} from "../domain/projection-state";
import {
  ReleaseContext,
  type Selection,
} from "../domain/release";
import { fixtureReleaseContext } from "../test/release-fixture";
import {
  PROJECTION_URL_PARAMETERS,
  ProjectionUrlController,
  type ProjectionUrlEnvironment,
  type ProjectionUrlEvent,
} from "./projection-url-controller";
import { useProjectionUrl } from "./use-projection-url";

let firstContext: ReleaseContext;
let secondContext: ReleaseContext;

beforeAll(async () => {
  firstContext = await fixtureReleaseContext();
  const manifest = structuredClone(firstContext.manifest);
  (manifest as { dataReleaseId: string }).dataReleaseId =
    "searise-europe-v1.0.1-20260816-bbbbbbbbbbbb";
  secondContext = new ReleaseContext({
    manifest,
    manifestUrl: firstContext.manifestUrl.replace(firstContext.dataReleaseId, manifest.dataReleaseId),
    disposition: firstContext.disposition,
    artifacts: { ...firstContext.artifacts },
    datasets: { ...firstContext.datasets },
  });
});

class FakeUrlEnvironment implements ProjectionUrlEnvironment {
  url: URL;
  readonly replacements: URL[] = [];
  readonly listeners = new Set<() => void>();
  readonly removedListeners: (() => void)[] = [];

  constructor(url = "https://app.example/explore") {
    this.url = new URL(url);
  }

  readonly currentUrl = (): URL => new URL(this.url);
  readonly replaceUrl = (url: URL): void => {
    this.url = new URL(url);
    this.replacements.push(new URL(url));
  };
  readonly subscribePopState = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
      this.removedListeners.push(listener);
    };
  };

  pop(url: string): void {
    this.url = new URL(url);
    for (const listener of [...this.listeners]) listener();
  }
}

function selected(
  context: ReleaseContext,
  overrides: Partial<Pick<Selection, "scenario" | "horizon" | "location">> = {},
): Selection {
  const coordinates = Object.freeze({ latitude: 51.9244, longitude: 4.4777 });
  const location = overrides.location ?? Object.freeze({
    kind: "settlement" as const,
    placeId: "geonames:2747891",
    coordinates,
  });
  return Object.freeze({
    dataReleaseId: context.dataReleaseId,
    scenario: overrides.scenario ?? context.defaults.scenario,
    horizon: overrides.horizon ?? context.defaults.horizon,
    location: Object.freeze({
      ...location,
      coordinates: Object.freeze({ ...location.coordinates }),
    }),
  });
}

function accepted(context: ReleaseContext, selection = selected(context)): AcceptedProjection {
  const dataset = context.dataset(selection.scenario, selection.horizon);
  const analysis = context.artifact(dataset.analysisArtifactId);
  const visual = context.artifact(dataset.visualArtifactId);
  return Object.freeze({
    release: Object.freeze({
      dataReleaseId: context.dataReleaseId,
      methodologyVersion: context.methodologyVersion,
    }),
    selection,
    selectionKey: selectionKey(selection),
    result: Object.freeze({
      dataReleaseId: context.dataReleaseId,
      methodologyVersion: context.methodologyVersion,
      scenario: selection.scenario,
      horizon: selection.horizon,
      analysisArtifactId: analysis.artifactId,
      analysisArtifactSha256: analysis.sha256,
      visualArtifactId: visual.artifactId,
      visualArtifactSha256: visual.sha256,
      visualArtifactUrl: visual.url,
      resultState: "OutOfScope",
      reason: "outside-coastal-scope",
    }),
  });
}

function projectionUrl(
  context: ReleaseContext,
  scenario: ScenarioId = context.defaults.scenario,
  horizon: HorizonYear = context.defaults.horizon,
): string {
  const url = new URL("https://app.example/explore?campaign=kept#map");
  url.searchParams.set("release", context.dataReleaseId);
  url.searchParams.set("scenario", scenario);
  url.searchParams.set("horizon", String(horizon));
  url.searchParams.set("lat", "51.9244");
  url.searchParams.set("lon", "4.4777");
  return url.href;
}

describe("release-scoped projection URL controller", () => {
  it("loads one validated settlement selection with exact pinned defaults", () => {
    const environment = new FakeUrlEnvironment(
      `https://app.example/explore?release=${firstContext.dataReleaseId}&lat=51.9&lon=4.5&place=geonames%3A2747891`,
    );
    const observer = vi.fn<(event: ProjectionUrlEvent) => void>();
    const controller = new ProjectionUrlController(firstContext, environment, observer);

    controller.start();

    expect(observer).toHaveBeenCalledOnce();
    expect(observer).toHaveBeenCalledWith({
      type: "selection",
      source: "initial",
      selection: {
        dataReleaseId: firstContext.dataReleaseId,
        scenario: "ssp2-45",
        horizon: 2050,
        location: {
          kind: "settlement",
          placeId: "geonames:2747891",
          coordinates: { latitude: 51.9, longitude: 4.5 },
        },
      },
    });
  });

  it("accepts coordinate reloads for every one of the nine scenario/horizon combinations", () => {
    for (const scenario of SCENARIO_IDS) {
      for (const horizon of HORIZON_YEARS) {
        const environment = new FakeUrlEnvironment(projectionUrl(firstContext, scenario, horizon));
        const events: ProjectionUrlEvent[] = [];
        const controller = new ProjectionUrlController(firstContext, environment, (event) => events.push(event));

        controller.start();

        expect(events).toEqual([{
          type: "selection",
          source: "initial",
          selection: {
            dataReleaseId: firstContext.dataReleaseId,
            scenario,
            horizon,
            location: {
              kind: "coordinate",
              coordinates: { latitude: 51.9244, longitude: 4.4777 },
            },
          },
        }]);
        controller.dispose();
      }
    }
  });

  it.each([
    ["missing longitude", "?lat=51.9"],
    ["empty latitude", "?lat=&lon=4.5"],
    ["non-finite coordinate", "?lat=Infinity&lon=4.5"],
    ["out-of-range coordinate", "?lat=91&lon=4.5"],
    ["invalid settlement identity", "?lat=51.9&lon=4.5&place=%2FUsers%2Fexample%2Funpublished-input.tar"],
    ["unsupported scenario", "?scenario=ssp9-99&lat=51.9&lon=4.5"],
    ["unsupported horizon", "?horizon=2051&lat=51.9&lon=4.5"],
  ])("surfaces %s as a technical error, never a scientific outcome", (_label, search) => {
    const environment = new FakeUrlEnvironment(`https://app.example/explore${search}`);
    const events: ProjectionUrlEvent[] = [];
    new ProjectionUrlController(firstContext, environment, (event) => events.push(event)).start();

    expect(events).toHaveLength(1);
    expect(events[0]).toMatchObject({
      type: "technical-error",
      source: "initial",
      error: { kind: "technical-error", code: "SchemaInvalid", recoverable: false },
    });
    expect(JSON.stringify(events[0])).not.toContain("resultState");
  });

  it("surfaces a shared URL from another release as ReleaseIdentityMismatch", () => {
    const environment = new FakeUrlEnvironment(projectionUrl(secondContext));
    const events: ProjectionUrlEvent[] = [];
    new ProjectionUrlController(firstContext, environment, (event) => events.push(event)).start();

    expect(events).toEqual([expect.objectContaining({
      type: "technical-error",
      source: "initial",
      error: expect.objectContaining({ code: "ReleaseIdentityMismatch" }),
    })]);
  });

  it("publishes only an explicitly shared accepted selection and preserves unrelated URL state", () => {
    const environment = new FakeUrlEnvironment("https://app.example/explore?campaign=kept#method");
    const events: ProjectionUrlEvent[] = [];
    const controller = new ProjectionUrlController(firstContext, environment, (event) => events.push(event));
    controller.start();
    const projection = Object.freeze({
      ...accepted(firstContext),
      result: Object.freeze({
        ...accepted(firstContext).result,
        analysisArtifactId: "Rotterdam private address",
        visualArtifactUrl: "/Users/example/unpublished-input.tar",
      }),
      rawSearchText: "Rotterdam private address",
      localPath: "/Users/example/unpublished-input.tar",
    }) as AcceptedProjection & {
      readonly rawSearchText: string;
      readonly localPath: string;
    };

    expect(environment.replacements).toHaveLength(0);
    expect(controller.share(projection)).toBe(true);

    expect(environment.replacements).toHaveLength(1);
    expect(environment.url.pathname).toBe("/explore");
    expect(environment.url.hash).toBe("#method");
    expect(environment.url.searchParams.get("campaign")).toBe("kept");
    expect([...environment.url.searchParams.keys()].sort()).toEqual([
      "campaign", ...PROJECTION_URL_PARAMETERS,
    ].sort());
    expect(environment.url.href).not.toContain("Rotterdam");
    expect(environment.url.href).not.toContain("unpublished-input");
    expect(environment.url.href).not.toContain("Users");
    expect(events).toEqual([{ type: "clear", source: "initial" }]);
  });

  it("refuses to publish raw search text or local paths disguised as settlement identity", () => {
    const environment = new FakeUrlEnvironment();
    const events: ProjectionUrlEvent[] = [];
    const controller = new ProjectionUrlController(firstContext, environment, (event) => events.push(event));
    controller.start();
    const unsafeSelection = selected(firstContext, {
      location: {
        kind: "settlement",
        placeId: "/Users/example/unpublished-input.tar?query=Rotterdam address",
        coordinates: { latitude: 51.9, longitude: 4.5 },
      },
    });

    expect(controller.share(accepted(firstContext, unsafeSelection))).toBe(false);

    expect(environment.replacements).toHaveLength(0);
    expect(environment.url.href).not.toContain("unpublished-input");
    expect(environment.url.href).not.toContain("Rotterdam");
    expect(events.at(-1)).toMatchObject({
      type: "technical-error",
      source: "share",
      error: { code: "SchemaInvalid" },
    });
  });

  it("rejects mutable, inconsistent, mixed-result, and replacement-release tuples without publication", () => {
    const environment = new FakeUrlEnvironment();
    const events: ProjectionUrlEvent[] = [];
    const controller = new ProjectionUrlController(firstContext, environment, (event) => events.push(event));
    controller.start();
    const mutable = { ...accepted(firstContext) } as AcceptedProjection;
    const inconsistent = Object.freeze({
      ...accepted(firstContext),
      selectionKey: "selection-v1:tampered",
    });
    const mixedResult = Object.freeze({
      ...accepted(firstContext),
      result: Object.freeze({
        ...accepted(firstContext).result,
        scenario: "ssp5-85" as const,
      }),
    });

    expect(controller.share(mutable)).toBe(false);
    expect(controller.share(inconsistent)).toBe(false);
    expect(controller.share(mixedResult)).toBe(false);
    expect(controller.share(accepted(secondContext))).toBe(false);
    expect(environment.replacements).toHaveLength(0);
    expect(events.slice(1).map((event) => event.type)).toEqual([
      "technical-error", "technical-error", "technical-error", "technical-error",
    ]);
    expect(events.slice(1).map((event) =>
      event.type === "technical-error" ? event.error.code : null,
    )).toEqual([
      "SchemaInvalid",
      "ReleaseIdentityMismatch",
      "ReleaseIdentityMismatch",
      "ReleaseIdentityMismatch",
    ]);
  });

  it("reset clears only projection parameters while preserving path, hash, and unrelated parameters", () => {
    const url = new URL(projectionUrl(firstContext));
    url.searchParams.append("place", "geonames:2747891");
    url.searchParams.append("campaign", "also-kept");
    const environment = new FakeUrlEnvironment(url.href);
    const events: ProjectionUrlEvent[] = [];
    const controller = new ProjectionUrlController(firstContext, environment, (event) => events.push(event));
    controller.start();

    controller.reset();

    expect(environment.url.pathname).toBe("/explore");
    expect(environment.url.hash).toBe("#map");
    expect(environment.url.searchParams.getAll("campaign")).toEqual(["kept", "also-kept"]);
    for (const parameter of PROJECTION_URL_PARAMETERS) {
      expect(environment.url.searchParams.has(parameter)).toBe(false);
    }
    expect(events.at(-1)).toEqual({ type: "clear", source: "reset" });
  });

  it("validates popstate navigation and treats an empty projection URL as clear", () => {
    const environment = new FakeUrlEnvironment();
    const events: ProjectionUrlEvent[] = [];
    const controller = new ProjectionUrlController(firstContext, environment, (event) => events.push(event));
    controller.start();

    environment.pop(projectionUrl(firstContext, "ssp5-85", 2100));
    environment.pop("https://app.example/explore?campaign=kept#map");

    expect(events).toHaveLength(3);
    expect(events[1]).toMatchObject({
      type: "selection",
      source: "popstate",
      selection: { scenario: "ssp5-85", horizon: 2100 },
    });
    expect(events[2]).toEqual({ type: "clear", source: "popstate" });
  });
});

describe("React projection URL ownership", () => {
  it("replaces the release session, ignores stale listeners, and publishes only current-release navigation", () => {
    const environment = new FakeUrlEnvironment(projectionUrl(firstContext));
    const observer = vi.fn<(event: ProjectionUrlEvent) => void>();
    const { rerender } = renderHook(
      ({ context }) => useProjectionUrl(context, observer, environment),
      { initialProps: { context: firstContext as ReleaseContext | null } },
    );
    expect(observer).toHaveBeenLastCalledWith(expect.objectContaining({
      type: "selection",
      selection: expect.objectContaining({ dataReleaseId: firstContext.dataReleaseId }),
    }));
    const staleListener = [...environment.listeners][0];

    environment.url = new URL(projectionUrl(secondContext));
    rerender({ context: secondContext });

    expect(environment.listeners.size).toBe(1);
    expect(observer).toHaveBeenLastCalledWith(expect.objectContaining({
      type: "selection",
      selection: expect.objectContaining({ dataReleaseId: secondContext.dataReleaseId }),
    }));
    const callsAfterReplacement = observer.mock.calls.length;
    act(() => staleListener());
    expect(observer).toHaveBeenCalledTimes(callsAfterReplacement);
  });

  it("removes the popstate listener on unmount and ignores later callbacks", () => {
    const environment = new FakeUrlEnvironment(projectionUrl(firstContext));
    const observer = vi.fn<(event: ProjectionUrlEvent) => void>();
    const { unmount } = renderHook(() => useProjectionUrl(firstContext, observer, environment));
    const listener = [...environment.listeners][0];
    const callsBeforeUnmount = observer.mock.calls.length;

    unmount();
    act(() => listener());

    expect(environment.listeners.size).toBe(0);
    expect(environment.removedListeners).toContain(listener);
    expect(observer).toHaveBeenCalledTimes(callsBeforeUnmount);
  });

  it("exposes typed share/reset commands and fails explicitly without a release", () => {
    const environment = new FakeUrlEnvironment();
    const observer = vi.fn<(event: ProjectionUrlEvent) => void>();
    const { result, rerender } = renderHook(
      ({ context }) => useProjectionUrl(context, observer, environment),
      { initialProps: { context: firstContext as ReleaseContext | null } },
    );

    act(() => expect(result.current.share(accepted(firstContext))).toBe(true));
    act(() => result.current.reset());
    expect(environment.replacements).toHaveLength(2);

    rerender({ context: null });
    expect(() => result.current.share(accepted(firstContext))).toThrow("not ready");
    expect(() => result.current.reset()).toThrow("not ready");
  });
});
