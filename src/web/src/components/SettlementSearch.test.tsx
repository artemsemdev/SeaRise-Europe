import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import manifest from "../../../../contracts/release/v1/fixtures/release/searise-europe-v1.0.0-20260810-c096aeab4e09/manifest.json";
import { ManifestRepository } from "../data/manifest-repository";
import { ReleaseContext } from "../domain/release";
import type { SearchWorkerPort, SearchWorkerRequest } from "../search/worker-protocol";
import type { SettlementSearchRecord } from "../search/types";
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
}

let context: ReleaseContext;

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

beforeEach(async () => {
  const manifestUrl = `https://fixture.invalid/releases/${manifest.dataReleaseId}/manifest.json`;
  context = await new ManifestRepository({
    manifestUrl,
    allowedOrigins: ["https://fixture.invalid"],
    expectedDisposition: "synthetic-fixture",
    transport: async () => new Response(JSON.stringify(manifest), { headers: { "content-type": "application/json" } }),
  }).load(manifest.dataReleaseId, new AbortController().signal);
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("settlement search combobox", () => {
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

  it("clears old results immediately so Enter and Explore cannot select a stale query", async () => {
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
    expect(screen.getByRole("button", { name: /explore/i })).toBeDisabled();
    await user.keyboard("{Enter}");
    await user.click(screen.getByRole("button", { name: /explore/i }));
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
    expect(screen.getByRole("button", { name: /explore/i })).toBeDisabled();
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
    expect(screen.getByRole("status")).toHaveAttribute("data-search-readiness", "core-ready");
    expect(screen.getByRole("button", { name: /explore/i })).toBeEnabled();
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
});
