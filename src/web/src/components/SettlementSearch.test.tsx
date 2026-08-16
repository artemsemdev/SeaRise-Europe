import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import manifest from "../../../../contracts/release/v1/fixtures/release/searise-europe-v1.0.0-20260810-c096aeab4e09/manifest.json";
import { ManifestRepository } from "../data/manifest-repository";
import type { ReleaseContext } from "../domain/release";
import type { SearchWorkerPort, SearchWorkerRequest } from "../search/worker-protocol";
import type { SettlementSearchRecord } from "../search/types";
import { SettlementSearch } from "./SettlementSearch";

const records: readonly SettlementSearchRecord[] = [
  { placeId: "synthetic:3", displayName: "Springfield", searchNames: [], countryCode: "AA", admin1Name: "North", population: 1000, featureCode: "PPL", distanceToCoastMeters: 50000, isCoastal: false, latitude: 50, longitude: 10 },
  { placeId: "synthetic:4", displayName: "Springfield", searchNames: [], countryCode: "BB", admin1Name: "South", population: 500, featureCode: "PPL", distanceToCoastMeters: 100, isCoastal: true, latitude: 50.1, longitude: 10.1 },
];

class FakeWorker implements SearchWorkerPort {
  onmessage: SearchWorkerPort["onmessage"] = null;
  onerror: SearchWorkerPort["onerror"] = null;
  readonly requests: SearchWorkerRequest[] = [];
  terminated = false;

  postMessage(message: SearchWorkerRequest): void {
    this.requests.push(message);
    queueMicrotask(() => {
      if (this.terminated) return;
      if (message.kind === "initialize" || message.kind === "load-shard") {
        this.onmessage?.({ data: {
          kind: "ready",
          token: message.token,
          shardId: message.authority.shardId,
          runtimeVersion: "settlement-browser-worker-v2",
          durationMilliseconds: 1,
        } } as never);
      } else if (message.kind === "query") {
        if (message.query === "technical") {
          this.onmessage?.({ data: {
            kind: "error",
            token: message.token,
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
            readyShards: ["europe-core", "europe-coastal"],
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
    expect(selected).toHaveBeenCalledWith(expect.objectContaining({ placeId: "synthetic:4", latitude: 50.1, longitude: 10.1 }));
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
});
