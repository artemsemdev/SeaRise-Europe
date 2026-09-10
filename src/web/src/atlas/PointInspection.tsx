import { useEffect, useState } from "react";
import { ArrowClockwise, Info } from "@phosphor-icons/react";
import type { AtlasDataSource } from "./data-source";
import { parseInspection, type Inspection, type Point, type PointResult, type Protection, type Year } from "./model";

function resultLabel(result: PointResult): string {
  if (result.status === "unknown") return "No usable data";
  if (result.status === "zero") return "No flooding modeled";
  return `${result.depthMeters! < 0.1 ? "<0.1" : result.depthMeters!.toFixed(1)} m depth`;
}

export function PointInspection({ dataSource, point, protection, year }: { dataSource: AtlasDataSource; point: Point; protection: Protection; year: Year }) {
  const [data, setData] = useState<{ key: string; source: AtlasDataSource; value: Inspection } | null>(null);
  const [failure, setFailure] = useState<{ key: string; source: AtlasDataSource; message: string } | null>(null);
  const [retry, setRetry] = useState(0);
  const [lon, lat] = point;
  const key = `${lon},${lat},${protection},${retry}`;
  useEffect(() => {
    const controller = new AbortController();
    dataSource.inspect({ coordinates: [lon, lat], protection, signal: controller.signal })
      .then((value: unknown) => {
        const parsed = parseInspection(value);
        if (parsed.protection !== protection || Math.abs(parsed.coordinates[0] - lon) > 0.000001 || Math.abs(parsed.coordinates[1] - lat) > 0.000001) throw new Error("The result does not match this point.");
        if (!controller.signal.aborted) { setData({ key, source: dataSource, value: parsed }); setFailure(null); }
      })
      .catch((error: unknown) => { if (!controller.signal.aborted) setFailure({ key, source: dataSource, message: error instanceof Error ? error.message : "This point could not be checked." }); });
    return () => controller.abort();
  }, [key, lat, lon, protection, retry, dataSource]);
  const current = data?.key === key && data.source === dataSource ? data.value : null;
  const error = failure?.key === key && failure.source === dataSource ? failure.message : null;
  const result = current?.results.find((item) => item.year === year);
  return <div className="point-inspection" data-testid="point-inspection" data-state={error ? "error" : result?.status ?? "loading"}>
    <div className="point-summary" role="status">
      <span className="point-kicker">Point result · One 25 m model cell · {year}</span>
      <strong>{error ?? (result ? resultLabel(result) : "Checking this point…")}</strong>
      {result?.status === "flooded" && <span>Modeled flooding at high tide</span>}
      {result?.status === "unknown" && <span>Unknown does not mean dry.</span>}
      {result?.status === "zero" && <span>A model result for this point, not a safety assessment.</span>}
    </div>
    {error && <button className="text-button" type="button" onClick={() => setRetry((value) => value + 1)}><ArrowClockwise size={18} />Retry point check</button>}
    <div className="panel-details">
      {current && <dl className="point-years" aria-label="Selected point across years">{current.results.map((item) => <div key={item.year} className={year === item.year ? "is-selected" : ""}><dt>{item.year}</dt><dd>{resultLabel(item)}</dd></div>)}</dl>}
      <p className="point-context"><Info size={16} />One 25 m model cell, not the whole city or a property assessment.</p>
      <p className="point-coordinates">{lat.toFixed(5)}° N · {Math.abs(lon).toFixed(5)}° {lon < 0 ? "W" : "E"}</p>
    </div>
  </div>;
}
