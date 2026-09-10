import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { PointInspection } from "./PointInspection";
import { fakeDataSource } from "./ui-test-data";
import { SYNTHETIC_ATLAS_PLACES, syntheticAtlasInspection } from "./synthetic-fixture";
import type { AtlasInspectionV1 } from "./browser-data-contract";

afterEach(() => { cleanup(); vi.restoreAllMocks(); });
const point = SYNTHETIC_ATLAS_PLACES[1].coordinates;

// These component responses exercise all three display states independently
// of the spatial fixture, which correctly has no raster coverage in Rotterdam.
function pointDataSource() {
  const source = fakeDataSource();
  source.inspect.mockImplementation(async ({ coordinates, protection }) => ({
    coordinates, protection, cellSizeMeters: 25,
    results: [
      { year: 2030, status: "unknown", depthMeters: null },
      { year: 2050, status: "zero", depthMeters: 0 },
      protection === "protected"
        ? { year: 2100, status: "zero", depthMeters: 0 }
        : { year: 2100, status: "flooded", depthMeters: 0.3 },
    ],
  }));
  return source;
}

describe("atlas point results", () => {
  it("keeps unknown, valid zero, and positive depths distinct across three years", async () => {
    const source = pointDataSource();
    const { rerender } = render(<PointInspection dataSource={source} point={point} protection="unprotected" year={2030} />);
    await waitFor(() => expect(screen.getByTestId("point-inspection")).toHaveAttribute("data-state", "unknown"));
    expect(screen.getByRole("status")).toHaveTextContent("No usable data");
    expect(screen.getByRole("status")).toHaveTextContent("Unknown does not mean dry.");
    rerender(<PointInspection dataSource={source} point={point} protection="unprotected" year={2050} />);
    expect(screen.getByRole("status")).toHaveTextContent("No flooding modeled");
    rerender(<PointInspection dataSource={source} point={point} protection="unprotected" year={2100} />);
    expect(screen.getByRole("status")).toHaveTextContent("0.3 m depth");
    expect(source.inspect).toHaveBeenCalledTimes(1);
    expect(screen.getByLabelText("Selected point across years").children).toHaveLength(3);
  });

  it("rejects a result for the wrong point and retries the same request", async () => {
    const source = pointDataSource();
    source.inspect.mockResolvedValueOnce(syntheticAtlasInspection("fixture:venice", "unprotected")!);
    render(<PointInspection dataSource={source} point={point} protection="unprotected" year={2050} />);
    await screen.findByText("The result does not match this point.");
    fireEvent.click(screen.getByRole("button", { name: "Retry point check" }));
    await waitFor(() => expect(screen.getByTestId("point-inspection")).toHaveAttribute("data-state", "zero"));
    expect(source.inspect.mock.calls.map(([request]) => request.coordinates)).toEqual([point, point]);
    expect(source.inspect.mock.calls.map(([request]) => request.protection)).toEqual(["unprotected", "unprotected"]);
  });

  it("aborts the prior defense request and ignores its late completion", async () => {
    const source = pointDataSource();
    let completeOld!: (value: AtlasInspectionV1) => void;
    source.inspect.mockImplementationOnce(() => new Promise((resolve) => { completeOld = resolve; }));
    const { rerender } = render(<PointInspection dataSource={source} point={point} protection="unprotected" year={2100} />);
    const signal = source.inspect.mock.calls[0][0].signal;
    rerender(<PointInspection dataSource={source} point={point} protection="protected" year={2100} />);
    expect(signal?.aborted).toBe(true);
    await waitFor(() => expect(screen.getByTestId("point-inspection")).toHaveAttribute("data-state", "zero"));
    await act(async () => completeOld(syntheticAtlasInspection("fixture:rotterdam", "unprotected")!));
    expect(screen.getByRole("status")).toHaveTextContent("No flooding modeled");
  });
});
