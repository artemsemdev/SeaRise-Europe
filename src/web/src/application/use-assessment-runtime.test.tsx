import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeAll, describe, expect, it, vi } from "vitest";
import { CogAnalysisArtifactReader } from "../data/cog-analysis-reader";
import { StaticGeographyClassifier } from "../data/geography-classifier";
import type { ReleaseMethodology } from "../data/methodology-repository";
import {
  createBootingProjectionState,
  projectionReducer,
  projectionReleaseIdentity,
  type ProjectionState,
} from "../domain/projection-state";
import { AssessmentEngine } from "../domain/scientific-lookup";
import {
  ReleaseContext,
  TechnicalFailure,
  type Selection,
} from "../domain/release";
import { fixtureReleaseContext } from "../test/release-fixture";
import { createSearchQueryOperation } from "../search/lifecycle";
import { AssessmentController } from "./assessment-controller";
import {
  createBrowserRuntime,
  type AssessmentControllerPort,
  type BrowserRuntimeFactory,
  type BrowserRuntimeScope,
} from "./browser-runtime";
import { useAssessmentRuntime } from "./use-assessment-runtime";

let firstContext: ReleaseContext;
let secondContext: ReleaseContext;

beforeAll(async () => {
  firstContext = await fixtureReleaseContext();
  const manifest = structuredClone(firstContext.manifest);
  (manifest as { dataReleaseId: string }).dataReleaseId =
    "searise-europe-v1.0.1-20260816-aaaaaaaaaaaa";
  secondContext = new ReleaseContext({
    manifest,
    manifestUrl: firstContext.manifestUrl.replace(firstContext.dataReleaseId, manifest.dataReleaseId),
    disposition: firstContext.disposition,
    artifacts: { ...firstContext.artifacts },
    datasets: { ...firstContext.datasets },
  });
});

interface Deferred<T> {
  readonly promise: Promise<T>;
  resolve(value: T): void;
  reject(error: unknown): void;
}

function deferred<T>(): Deferred<T> {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((accept, decline) => {
    resolve = accept;
    reject = decline;
  });
  return { promise, resolve, reject };
}

function readyState(context: ReleaseContext): ProjectionState {
  return projectionReducer(createBootingProjectionState(context.dataReleaseId), {
    type: "release-ready",
    operationToken: 0,
    release: projectionReleaseIdentity(context),
  });
}

class TestController implements AssessmentControllerPort {
  readonly select = vi.fn(async () => undefined);
  readonly retry = vi.fn(async () => true);
  readonly reset = vi.fn(() => undefined);
  readonly handleSearchLifecycle = vi.fn(() => undefined);
  readonly cancelSearch = vi.fn(() => undefined);
  readonly dispose = vi.fn(() => undefined);
  #snapshot: ProjectionState;
  readonly #listeners = new Set<() => void>();

  constructor(context: ReleaseContext) {
    this.#snapshot = readyState(context);
  }

  readonly getSnapshot = (): ProjectionState => this.#snapshot;
  readonly subscribe = (listener: () => void): (() => void) => {
    this.#listeners.add(listener);
    return () => this.#listeners.delete(listener);
  };

  get listenerCount(): number {
    return this.#listeners.size;
  }

  publish(snapshot: ProjectionState): void {
    this.#snapshot = snapshot;
    for (const listener of this.#listeners) listener();
  }
}

function methodology(context: ReleaseContext): ReleaseMethodology {
  return Object.freeze({
    dataReleaseId: context.dataReleaseId,
    methodologyVersion: context.methodologyVersion,
    disposition: context.disposition,
  }) as ReleaseMethodology;
}

interface RuntimeRecord {
  readonly scope: BrowserRuntimeScope;
  readonly controller: TestController;
  readonly methodology: Deferred<ReleaseMethodology>;
  readonly signals: AbortSignal[];
}

function runtimeRecord(context: ReleaseContext): RuntimeRecord {
  const controller = new TestController(context);
  const pending = deferred<ReleaseMethodology>();
  const signals: AbortSignal[] = [];
  return {
    controller,
    methodology: pending,
    signals,
    scope: {
      context,
      controller,
      methodology: {
        load: (_context, signal) => {
          signals.push(signal);
          return pending.promise;
        },
      },
    },
  };
}

function selected(context: ReleaseContext): Selection {
  return {
    dataReleaseId: context.dataReleaseId,
    scenario: "ssp2-45",
    horizon: 2050,
    location: {
      kind: "coordinate",
      coordinates: { latitude: 51.9, longitude: 4.5 },
    },
  };
}

describe("static browser runtime adapter", () => {
  it("wires the production runtime from the real static scientific classes", () => {
    const runtime = createBrowserRuntime(firstContext);

    expect(runtime.context).toBe(firstContext);
    expect(runtime.geography).toBeInstanceOf(StaticGeographyClassifier);
    expect(runtime.analysis).toBeInstanceOf(CogAnalysisArtifactReader);
    expect(runtime.assessment).toBeInstanceOf(AssessmentEngine);
    expect(runtime.controller).toBeInstanceOf(AssessmentController);
    expect(runtime.controller.getSnapshot()).toMatchObject({
      phase: "ready",
      release: { dataReleaseId: firstContext.dataReleaseId },
    });
    runtime.controller.dispose();
  });

  it("constructs once per context, keeps snapshots stable, and exposes every controller command", async () => {
    const records: RuntimeRecord[] = [];
    const factory: BrowserRuntimeFactory = vi.fn((context) => {
      const record = runtimeRecord(context);
      records.push(record);
      return record.scope;
    });
    const { result, rerender, unmount } = renderHook(
      ({ context }) => useAssessmentRuntime(context, factory),
      { initialProps: { context: firstContext as ReleaseContext | null } },
    );

    await waitFor(() => expect(result.current.projection?.phase).toBe("ready"));
    const stableSnapshot = result.current.projection;
    const stableCommands = {
      select: result.current.select,
      retry: result.current.retry,
      reset: result.current.reset,
      handleSearchLifecycle: result.current.handleSearchLifecycle,
      cancelSearch: result.current.cancelSearch,
    };
    rerender({ context: firstContext });

    expect(factory).toHaveBeenCalledOnce();
    expect(result.current.projection).toBe(stableSnapshot);
    expect(result.current.select).toBe(stableCommands.select);
    expect(result.current.retry).toBe(stableCommands.retry);
    expect(result.current.reset).toBe(stableCommands.reset);
    expect(result.current.handleSearchLifecycle).toBe(stableCommands.handleSearchLifecycle);
    expect(result.current.cancelSearch).toBe(stableCommands.cancelSearch);

    const selection = selected(firstContext);
    await act(async () => {
      await result.current.select(selection);
      expect(await result.current.retry()).toBe(true);
      result.current.handleSearchLifecycle({
        type: "search-started",
        operation: createSearchQueryOperation(firstContext.dataReleaseId, "Athens", 1)!,
      });
      result.current.cancelSearch();
      result.current.reset();
    });
    expect(records[0].controller.select).toHaveBeenCalledWith(selection);
    expect(records[0].controller.retry).toHaveBeenCalledOnce();
    expect(records[0].controller.reset).toHaveBeenCalledOnce();
    expect(records[0].controller.handleSearchLifecycle).toHaveBeenCalledOnce();
    expect(records[0].controller.cancelSearch).toHaveBeenCalledOnce();

    unmount();
    expect(records[0].signals[0].aborted).toBe(true);
    expect(records[0].controller.dispose).toHaveBeenCalledOnce();
    expect(records[0].controller.listenerCount).toBe(0);
    act(() => records[0].controller.publish(readyState(firstContext)));
  });

  it("replaces and disposes the exact release scope without accepting stale methodology", async () => {
    const records: RuntimeRecord[] = [];
    const factory: BrowserRuntimeFactory = (context) => {
      const record = runtimeRecord(context);
      records.push(record);
      return record.scope;
    };
    const { result, rerender } = renderHook(
      ({ context }) => useAssessmentRuntime(context, factory),
      { initialProps: { context: firstContext as ReleaseContext | null } },
    );
    await waitFor(() => expect(result.current.projection?.phase).toBe("ready"));

    rerender({ context: secondContext });
    await waitFor(() => {
      expect(result.current.projection).toMatchObject({
        phase: "ready",
        release: { dataReleaseId: secondContext.dataReleaseId },
      });
    });
    expect(records[0].signals[0].aborted).toBe(true);
    expect(records[0].controller.dispose).toHaveBeenCalledOnce();
    expect(records[0].controller.listenerCount).toBe(0);
    act(() => records[0].controller.publish(readyState(firstContext)));
    expect(result.current.projection).toMatchObject({
      release: { dataReleaseId: secondContext.dataReleaseId },
    });
    expect(result.current.methodology).toEqual({
      phase: "loading",
      dataReleaseId: secondContext.dataReleaseId,
    });

    await act(async () => records[0].methodology.resolve(methodology(firstContext)));
    expect(result.current.methodology.phase).toBe("loading");

    const currentMethodology = methodology(secondContext);
    await act(async () => records[1].methodology.resolve(currentMethodology));
    expect(result.current.methodology).toEqual({
      phase: "ready",
      dataReleaseId: secondContext.dataReleaseId,
      methodology: currentMethodology,
    });
  });

  it("reports methodology delivery failure as technical state, never as an ADR-024 outcome", async () => {
    const record = runtimeRecord(firstContext);
    const factory: BrowserRuntimeFactory = () => record.scope;
    const { result } = renderHook(() => useAssessmentRuntime(firstContext, factory));
    await waitFor(() => expect(result.current.methodology.phase).toBe("loading"));

    await act(async () => record.methodology.reject(new TechnicalFailure({
      kind: "technical-error",
      code: "IntegrityFailed",
      message: "Methodology hash mismatch.",
      recoverable: false,
    })));

    expect(result.current.methodology).toMatchObject({
      phase: "technical-error",
      dataReleaseId: firstContext.dataReleaseId,
      error: { kind: "technical-error", code: "IntegrityFailed" },
    });
    expect(JSON.stringify(result.current.methodology)).not.toContain("resultState");
  });

  it("rejects a methodology object from another immutable release", async () => {
    const record = runtimeRecord(firstContext);
    const factory: BrowserRuntimeFactory = () => record.scope;
    const { result } = renderHook(() => useAssessmentRuntime(firstContext, factory));
    await waitFor(() => expect(result.current.projection?.phase).toBe("ready"));

    await act(async () => record.methodology.resolve(methodology(secondContext)));

    expect(result.current.methodology).toMatchObject({
      phase: "technical-error",
      dataReleaseId: firstContext.dataReleaseId,
      error: { kind: "technical-error", code: "ReleaseIdentityMismatch" },
    });
  });

  it("stays idle without constructing a runtime and fails commands explicitly", async () => {
    const factory: BrowserRuntimeFactory = vi.fn();
    const { result } = renderHook(() => useAssessmentRuntime(null, factory));

    expect(result.current.projection).toBeNull();
    expect(result.current.methodology).toEqual({ phase: "idle" });
    expect(factory).not.toHaveBeenCalled();
    await expect(result.current.select(selected(firstContext))).rejects.toThrow("not ready");
    await expect(result.current.retry()).rejects.toThrow("not ready");
    expect(() => result.current.reset()).toThrow("not ready");
  });
});
