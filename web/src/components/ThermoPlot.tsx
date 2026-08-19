import Plotly from "plotly.js-basic-dist-min";
import { useEffect, useMemo, useRef, useState } from "react";
import type { ThermoSeries } from "../types";

interface PlotRun {
  name: string;
  thermo: ThermoSeries[];
}

export default function ThermoPlot({ runs }: { runs: PlotRun[] }) {
  const chart = useRef<HTMLDivElement>(null);
  const columns = useMemo(
    () => Array.from(new Set(runs.flatMap(({ thermo }) => thermo.flatMap((series) => series.columns)))),
    [runs],
  );
  const hasRows = runs.some(({ thermo }) => thermo.some((series) => series.rows.length > 0));
  const defaultX = columns.find((column) => /^(time|step|cycle)$/i.test(column)) ?? columns[0];
  const defaultY = columns.find((column) => column !== defaultX) ?? columns[0];
  const [xColumn, setXColumn] = useState(defaultX);
  const [yColumn, setYColumn] = useState(defaultY);
  const traces = runs.flatMap((run) =>
    run.thermo.map((series) => ({
      x: series.rows.map((row) => row.values[xColumn] ?? row.sequence),
      y: series.rows.map((row) => row.values[yColumn]),
      name: runs.length > 1 ? `${run.name} · ${series.segment}` : `segment ${series.segment}`,
      type: "scatter" as const,
      mode: "lines" as const,
      line: { width: 2 },
      connectgaps: false,
    })),
  );
  useEffect(() => {
    if (!chart.current || !columns.length) return;
    const element = chart.current;
    void Plotly.react(
      element,
      traces as Plotly.Data[],
      {
        autosize: true,
        height: 460,
        margin: { l: 60, r: 20, t: 20, b: 55 },
        paper_bgcolor: "transparent",
        plot_bgcolor: "#fbfcfe",
        xaxis: { title: { text: xColumn }, gridcolor: "#e8ecf2" },
        yaxis: { title: { text: yColumn }, gridcolor: "#e8ecf2" },
        legend: { orientation: "h", y: -0.2 },
      },
      { responsive: true, displaylogo: false },
    );
    const resize = new ResizeObserver(() => Plotly.Plots.resize(element));
    resize.observe(element);
    return () => {
      resize.disconnect();
      Plotly.purge(element);
    };
  }, [columns.length, traces, xColumn, yColumn]);
  if (!columns.length || !hasRows) return <div className="empty-panel">No thermo data has been posted yet.</div>;
  return (
    <div>
      <div className="plot-controls">
        <label>x <select value={xColumn} onChange={(event) => setXColumn(event.target.value)}>{columns.map((column) => <option key={column}>{column}</option>)}</select></label>
        <label>y <select value={yColumn} onChange={(event) => setYColumn(event.target.value)}>{columns.map((column) => <option key={column}>{column}</option>)}</select></label>
      </div>
      <div ref={chart} style={{ width: "100%", minHeight: 460 }} />
    </div>
  );
}
