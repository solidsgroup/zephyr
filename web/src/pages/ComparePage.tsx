import { useQuery } from "@tanstack/react-query";
import { Link, useSearch } from "wouter";
import { api } from "../api";
import MetadataTable from "../components/MetadataTable";
import ThermoPlot from "../components/ThermoPlot";
import type { Run, ThermoSeries } from "../types";

interface ComparisonItem { run: Run; metadata: Record<string, string>; thermo: ThermoSeries[] }

export function RunComparison({ ids, embedded = false }: { ids: string[]; embedded?: boolean }) {
  const comparison = useQuery({
    queryKey: ["comparison", ids],
    queryFn: () => api<{ runs: ComparisonItem[] }>(`/comparisons/runs?${ids.map((id) => `ids=${encodeURIComponent(id)}`).join("&")}`),
    enabled: ids.length >= 2,
  });
  return (
    <>
      <header className={embedded ? "run-header" : "page-header"}><div><p className="eyebrow">RESULTS EXPLORER</p><h1>Compare {ids.length} runs</h1><p>Overlay thermo series and expose provenance differences.</p></div></header>
      {ids.length < 2 ? <div className="panel empty-panel">Select two or more runs from the <Link href="/">run browser</Link> to begin.</div> : comparison.isPending ? <div className="center-state"><span className="spinner" />Building comparison…</div> : comparison.isError ? <div className="error-panel">The comparison could not be loaded.</div> : <>
        <section className="panel"><div className="panel-heading"><div><p className="eyebrow">OVERLAY</p><h2>Thermodynamics</h2></div></div><ThermoPlot runs={comparison.data.runs.map((item) => ({ name: item.run.name, thermo: item.thermo }))} /></section>
        <section className="panel"><div className="panel-heading"><div><p className="eyebrow">PROVENANCE</p><h2>Metadata comparison</h2></div><span>Differences highlighted</span></div><MetadataTable records={comparison.data.runs.map((item) => ({ name: item.run.name, values: item.metadata }))} /></section>
      </>}
    </>
  );
}

export default function ComparePage() {
  const params = new URLSearchParams(useSearch());
  const ids = (params.get("ids") ?? "").split(",").filter(Boolean);
  return <RunComparison ids={ids} />;
}
