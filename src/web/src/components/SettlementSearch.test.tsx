import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ReleaseContext } from "../domain/release";
import type { SearchWorkerPort, SearchWorkerRequest } from "../search/worker-protocol";
import type { SettlementSearchRecord } from "../search/types";
import type { SearchLifecycleEvent } from "../domain/projection-search";
import { fixtureReleaseContext } from "../test/release-fixture";
import { SettlementSearch } from "./SettlementSearch";

const records: readonly SettlementSearchRecord[] = [
  { placeId: "geonames:900000003", displayName: "Springfield", searchNames: [], countryCode: "AA", admin1Name: "North", population: 1000, featureCode: "PPL", distanceToCoastMeters: 50000, isCoastal: false, latitude: 50, longitude: 10 },
  { placeId: "geonames:900000004", displayName: "Springfield", searchNames: [], countryCode: "BB", admin1Name: "South", population: 500, featureCode: "PPL", distanceToCoastMeters: 100, isCoastal: true, latitude: 50.1, longitude: 10.1 },
];

class FakeWorker implements SearchWorkerPort {
  onmessage: SearchWorkerPort["onmessage"] = null;
  onerror: SearchWorkerPort["onerror"] = null;
  readonly requests: SearchWorkerRequest[] = [];
  terminated = false;
  holdQueries = false;
  failCoastalAfterQuery = false;

  postMessage(message: SearchWorkerRequest): void {
    this.requests.push(message);
    queueMicrotask(() => {
      if (this.terminated) return;
      if (message.kind === "load-shard" && this.failCoastalAfterQuery) {
        window.setTimeout(() => this.onmessage?.({ data: {
          kind: "error",
          token: message.token,
          operation: "load-shard",
          error: { kind: "technical-error", code: "IntegrityFailed", message: "Coastal identity mismatch.", recoverable: false },
        } } as never), 10);
      } else if (message.kind === "initialize" || message.kind === "load-shard") {
        this.onmessage?.({ data: {
          kind: "ready",
          token: message.token,
          shardId: message.authority.shardId,
          runtimeVersion: "settlement-browser-worker-v2",
          durationMilliseconds: 1,
        } } as never);
      } else if (message.kind === "query") {
        if (this.holdQueries) return;
        if (message.query === "technical") {
          this.onmessage?.({ data: {
            kind: "error",
            token: message.token,
            operation: "query",
            error: { kind: "technical-error", code: "DecodeFailed", message: "Synthetic index failure.", recoverable: false },
          } } as never);
        } else {
          this.onmessage?.({ data: {
            kind: "results",
            token: message.token,
            results: message.query.toLowerCase().startsWith("spring")
              ? records.map((record) => ({ record, matchTier: 0 as const, editDistance: 0, shardId: "europe-core" as const }))
              : [],
            durationMilliseconds: 2,
            readyShards: this.failCoastalAfterQuery
              ? ["europe-core"]
              : ["europe-core", "europe-coastal"],
          } } as never);
        }
      }
    });
  }

  terminate(): void {
    this.terminated = true;
  }

  respond(token: number, queryResults: readonly SettlementSearchRecord[]): void {
    this.onmessage?.({ data: {
      kind: "results",
      token,
      results: queryResults.map((record) => ({
        record, matchTier: 0 as const, editDistance: 0, shardId: "europe-core" as const,
      })),
      durationMilliseconds: 2,
      readyShards: ["europe-core", "europe-coastal"],
    } } as never);
  }
}

let context: ReleaseContext;

function lastMatching<T>(items: readonly T[], predicate: (item: T) => boolean): T | undefined {
  return [...items].reverse().find(predicate);
}

function withoutArtifact(artifactId: string): ReleaseContext {
  const artifacts = { ...context.artifacts };
  delete artifacts[artifactId];
  return new ReleaseContext({
    manifest: context.manifest,
    manifestUrl: context.manifestUrl,
    disposition: context.disposition,
    artifacts,
    datasets: { ...context.datasets },
  });
}

function replacementContext(): ReleaseContext {
  const manifest = structuredClone(context.manifest);
  (manifest as { dataReleaseId: string }).dataReleaseId =
    "searise-europe-v1.0.1-20260816-aaaaaaaaaaaa";
  return new ReleaseContext({
    manifest,
    manifestUrl: context.manifestUrl.replace(context.dataReleaseId, manifest.dataReleaseId),
    disposition: context.disposition,
    artifacts: { ...context.artifacts },
    datasets: { ...context.datasets },
  });
}

beforeEach(async () => {
  context = await fixtureReleaseContext();
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("settlement search combobox", () => {
  it("uses the approved European-settlement prompt without synthetic control names", () => {
    render(<SettlementSearch release={context} onSelect={vi.fn()} workerFactory={() => new FakeWorker()} />);
    const input = screen.getByRole("combobox", { name: /find a city/i });
    expect(input).toHaveAttribute("placeholder", "Try Rotterdam, Porto, or Galway");
    expect(input).not.toHaveAttribute("placeholder", expect.stringMatching(/Border City/i));
  });

  it("emits immutable query lifecycle and only hands off a current frozen result", async () => {
    const worker = new FakeWorker();
    const lifecycle: SearchLifecycleEvent[] = [];
    const selected = vi.fn();
    const user = userEvent.setup();
    render(<SettlementSearch
      release={context}
      onSelect={selected}
      onSearchLifecycle={(event) => lifecycle.push(event)}
      workerFactory={() => worker}
      clearToken={0}
    />);

    const input = screen.getByRole("combobox", { name: /find a city/i });
    await user.type(input, "Spring");
    expect(await screen.findAllByRole("option")).toHaveLength(2);
    const started = lastMatching(lifecycle,
      (event) => event.type === "search-started" && event.operation.normalizedQuery === "spring",
    );
    expect(started).toMatchObject({
      type: "search-started",
      operation: { dataReleaseId: context.dataReleaseId, normalizedQuery: "spring" },
    });
    expect(lifecycle.at(-1)).toMatchObject({
      type: "search-completed",
      queryKey: started?.type === "search-started" ? started.operation.queryKey : "missing",
      searchToken: started?.type === "search-started" ? started.operation.searchToken : -1,
    });

    await user.keyboard("{Enter}");
    const handedOff = selected.mock.calls[0][0] as SettlementSearchRecord;
    expect(Object.isFrozen(handedOff)).toBe(true);
    expect(Object.isFrozen(handedOff.searchNames)).toBe(true);
  });

  it("emits cancel on clear and ignores stale worker completion correlation", async () => {
    const worker = new FakeWorker();
    worker.holdQueries = true;
    const lifecycle: SearchLifecycleEvent[] = [];
    const selected = vi.fn();
    const user = userEvent.setup();
    const { rerender } = render(<SettlementSearch
      release={context}
      onSelect={selected}
      onSearchLifecycle={(event) => lifecycle.push(event)}
      workerFactory={() => worker}
      clearToken={0}
    />);
    const input = screen.getByRole("combobox", { name: /find a city/i });
    await user.type(input, "A");
    const firstRequest = lastMatching(worker.requests,
      (request): request is Extract<SearchWorkerRequest, { kind: "query" }> => request.kind === "query",
    )!;
    await user.type(input, "b");
    const currentRequest = lastMatching(worker.requests,
      (request): request is Extract<SearchWorkerRequest, { kind: "query" }> => request.kind === "query",
    )!;
    expect(currentRequest.token).not.toBe(firstRequest.token);

    act(() => worker.respond(firstRequest.token, records));
    expect(screen.queryAllByRole("option")).toHaveLength(0);
    expect(lifecycle.filter(({ type }) => type === "search-completed")).toHaveLength(0);

    act(() => worker.respond(currentRequest.token, records));
    expect(await screen.findAllByRole("option")).toHaveLength(2);
    expect(lifecycle.filter(({ type }) => type === "search-completed")).toHaveLength(1);

    worker.holdQueries = true;
    await user.type(input, "c");
    const pendingStart = lastMatching(lifecycle, ({ type }) => type === "search-started");
    rerender(<SettlementSearch
      release={context}
      onSelect={selected}
      onSearchLifecycle={(event) => lifecycle.push(event)}
      workerFactory={() => worker}
      clearToken={1}
    />);
    await waitFor(() => expect(screen.getByRole("combobox", { name: /find a city/i })).toHaveValue(""));
    expect(lastMatching(lifecycle, ({ type }) => type === "search-cancelled")).toMatchObject({
      type: "search-cancelled",
      queryKey: pendingStart?.type === "search-started" ? pendingStart.operation.queryKey : "missing",
      searchToken: pendingStart?.type === "search-started" ? pendingStart.operation.searchToken : -1,
    });
    expect(selected).not.toHaveBeenCalled();
  });

  it("clears prior-release text and results while disposing its pending lifecycle", async () => {
    const first = new FakeWorker();
    const second = new FakeWorker();
    const factory = vi.fn().mockReturnValueOnce(first).mockReturnValueOnce(second);
    const lifecycle: SearchLifecycleEvent[] = [];
    const selected = vi.fn();
    const user = userEvent.setup();
    const { rerender } = render(<SettlementSearch
      release={context}
      onSelect={selected}
      onSearchLifecycle={(event) => lifecycle.push(event)}
      workerFactory={factory}
    />);
    const input = screen.getByRole("combobox", { name: /find a city/i });
    await user.type(input, "Spring");
    expect(await screen.findAllByRole("option")).toHaveLength(2);

    first.holdQueries = true;
    await user.type(input, "x");
    const pending = lastMatching(lifecycle, ({ type }) => type === "search-started");
    expect(input).toHaveValue("Springx");

    rerender(<SettlementSearch
      release={replacementContext()}
      onSelect={selected}
      onSearchLifecycle={(event) => lifecycle.push(event)}
      workerFactory={factory}
    />);
    expect(screen.getByRole("combobox", { name: /find a city/i })).toHaveValue("");
    expect(screen.queryAllByRole("option")).toHaveLength(0);
    await waitFor(() => expect(first.terminated).toBe(true));
    expect(lastMatching(lifecycle, ({ type }) => type === "search-cancelled")).toMatchObject({
      type: "search-cancelled",
      queryKey: pending?.type === "search-started" ? pending.operation.queryKey : "missing",
      searchToken: pending?.type === "search-started" ? pending.operation.searchToken : -1,
    });

    const oldQuery = first.requests.find(
      (request): request is Extract<SearchWorkerRequest, { kind: "query" }> => request.kind === "query",
    );
    if (oldQuery) act(() => first.respond(oldQuery.token, records));
    await user.keyboard("{Enter}");
    expect(screen.queryAllByRole("option")).toHaveLength(0);
    expect(selected).not.toHaveBeenCalled();
  });

  it("supports active-descendant keyboard selection without moving focus or persisting the query", async () => {
    const worker = new FakeWorker();
    const selected = vi.fn();
    const storage = vi.spyOn(Storage.prototype, "setItem");
    const user = userEvent.setup();
    render(<SettlementSearch release={context} onSelect={selected} workerFactory={() => worker} />);

    const input = screen.getByRole("combobox", { name: /find a city/i });
    await user.click(input);
    await user.type(input, "Spring");
    expect(await screen.findByRole("listbox", { name: /settlement results/i })).toBeVisible();
    expect(screen.getAllByRole("option")).toHaveLength(2);
    expect(screen.getByText("North, AA")).toBeVisible();
    expect(input).toHaveAttribute("aria-expanded", "true");

    await user.keyboard("{ArrowDown}{Enter}");
    expect(selected).toHaveBeenCalledWith(expect.objectContaining({ placeId: "geonames:900000004", latitude: 50.1, longitude: 10.1 }));
    expect(input).toHaveFocus();
    expect(input).toHaveValue("Springfield");
    expect(storage).not.toHaveBeenCalled();
    expect(worker.requests.filter(({ kind }) => kind === "query").every((request) => "query" in request)).toBe(true);
  });

  it("distinguishes a technical index failure from no matching settlement", async () => {
    const worker = new FakeWorker();
    const user = userEvent.setup();
    render(<SettlementSearch release={context} onSelect={vi.fn()} workerFactory={() => worker} />);
    const input = screen.getByRole("combobox", { name: /find a city/i });
    await user.type(input, "technical");
    expect(await screen.findByText(/technical failure, not a no-match result/i)).toBeVisible();
    expect(screen.getByText(/no scientific outcome was produced/i)).toBeVisible();
    expect(screen.queryByText(/try another spelling/i)).not.toBeInTheDocument();
  });

  it("uses the approved settlement-only no-match guidance", async () => {
    const worker = new FakeWorker();
    const user = userEvent.setup();
    render(<SettlementSearch release={context} onSelect={vi.fn()} workerFactory={() => worker} />);
    await user.type(screen.getByRole("combobox", { name: /find a city/i }), "Unknown place");
    expect(await screen.findByText(
      "No matching places found. Check the spelling or try a nearby city, town, or village.",
    )).toBeVisible();
    expect(document.querySelector(".search-shell .status")).toHaveTextContent(
      /No matching places found in the loaded index.*try a nearby city, town, or village/i,
    );
  });

  it("clears old results immediately so Enter and Fly there cannot select a stale query", async () => {
    const worker = new FakeWorker();
    const selected = vi.fn();
    const user = userEvent.setup();
    render(<SettlementSearch release={context} onSelect={selected} workerFactory={() => worker} />);
    const input = screen.getByRole("combobox", { name: /find a city/i });
    await user.type(input, "Spring");
    expect(await screen.findAllByRole("option")).toHaveLength(2);

    worker.holdQueries = true;
    await user.type(input, "x");
    expect(screen.queryAllByRole("option")).toHaveLength(0);
    expect(screen.getByRole("button", { name: /fly there/i })).toBeDisabled();
    await user.keyboard("{Enter}");
    await user.click(screen.getByRole("button", { name: /fly there/i }));
    expect(selected).not.toHaveBeenCalled();
  });

  it("removes old options when the current query fails", async () => {
    const worker = new FakeWorker();
    const selected = vi.fn();
    const user = userEvent.setup();
    render(<SettlementSearch release={context} onSelect={selected} workerFactory={() => worker} />);
    const input = screen.getByRole("combobox", { name: /find a city/i });
    await user.type(input, "Spring");
    expect(await screen.findAllByRole("option")).toHaveLength(2);
    await user.clear(input);
    await user.type(input, "technical");
    expect(await screen.findByText(/technical failure, not a no-match result/i)).toBeVisible();
    expect(screen.queryAllByRole("option")).toHaveLength(0);
    expect(screen.getByRole("button", { name: /fly there/i })).toBeDisabled();
    await user.keyboard("{Enter}");
    expect(selected).not.toHaveBeenCalled();
  });

  it("keeps an older coastal-load failure visible after a newer core query result", async () => {
    const worker = new FakeWorker();
    worker.failCoastalAfterQuery = true;
    const user = userEvent.setup();
    render(<SettlementSearch release={context} onSelect={vi.fn()} workerFactory={() => worker} />);
    const input = screen.getByRole("combobox", { name: /find a city/i });
    await user.type(input, "Spring");
    expect(await screen.findAllByRole("option")).toHaveLength(2);
    expect(await screen.findByText(/coastal index has a technical failure/i)).toBeVisible();
    expect(document.querySelector(".search-shell .status")).toHaveAttribute("data-search-readiness", "core-ready");
    expect(screen.getByRole("button", { name: /fly there/i })).toBeEnabled();
  });

  it("fails closed when the pinned release omits the core search shard", async () => {
    const user = userEvent.setup();
    render(<SettlementSearch
      release={withoutArtifact("settlements-europe-core")}
      onSelect={vi.fn()}
      workerFactory={() => new FakeWorker()}
    />);
    await user.type(screen.getByRole("combobox", { name: /find a city/i }), "Athens");
    expect(await screen.findByText(/technical failure, not a no-match result/i)).toBeVisible();
    expect(screen.queryAllByRole("option")).toHaveLength(0);
  });

  it("keeps core search useful when the pinned release omits the coastal shard", async () => {
    const worker = new FakeWorker();
    const user = userEvent.setup();
    render(<SettlementSearch
      release={withoutArtifact("settlements-europe-coastal")}
      onSelect={vi.fn()}
      workerFactory={() => worker}
    />);
    await user.type(screen.getByRole("combobox", { name: /find a city/i }), "Spring");
    expect(await screen.findAllByRole("option")).toHaveLength(2);
    expect(await screen.findByText(/coastal index has a technical failure/i)).toBeVisible();
    expect(worker.requests.some(({ kind }) => kind === "load-shard")).toBe(false);
    expect(worker.requests.some(({ kind }) => kind === "query")).toBe(true);
  });

  it("leaves ready state after a worker crash and restarts without a hanging query", async () => {
    const first = new FakeWorker();
    const replacement = new FakeWorker();
    const factory = vi.fn()
      .mockReturnValueOnce(first)
      .mockReturnValueOnce(replacement);
    const user = userEvent.setup();
    render(<SettlementSearch release={context} onSelect={vi.fn()} workerFactory={factory} />);
    const input = screen.getByRole("combobox", { name: /find a city/i });

    await user.type(input, "Spring");
    expect(await screen.findAllByRole("option")).toHaveLength(2);
    expect(document.querySelector(".search-shell .status")).toHaveAttribute("data-search-readiness", "all-ready");

    act(() => first.onerror?.({} as ErrorEvent));
    expect(first.terminated).toBe(true);
    expect(document.querySelector(".search-shell .status")).toHaveAttribute("data-search-readiness", "idle");
    expect(await screen.findByText(/technical failure, not a no-match result/i)).toBeVisible();
    expect(screen.queryAllByRole("option")).toHaveLength(0);

    await user.clear(input);
    await user.type(input, "Spring");
    expect(await screen.findAllByRole("option")).toHaveLength(2);
    expect(factory).toHaveBeenCalledTimes(2);
    expect(document.querySelector(".search-shell .status")).toHaveAttribute("data-search-readiness", "all-ready");
    expect(screen.queryByText(/technical failure, not a no-match result/i)).not.toBeInTheDocument();
  });
});
