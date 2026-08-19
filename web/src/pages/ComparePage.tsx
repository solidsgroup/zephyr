import { useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useSearch } from "wouter";
import { api } from "../api";
import MetadataTable from "../components/MetadataTable";
import ThermoPlot from "../components/ThermoPlot";
import type { Run, ThermoSeries } from "../types";

interface ComparisonItem { run: Run; metadata: Record<string, string>; thermo: ThermoSeries[] }

function displayField(value: string) {
  return value.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function displayTime(value: string | null) {
  return value ? new Date(value).toLocaleString() : "";
}

function runProvenance(run: Run) {
  const values: Record<string, string> = {
    "Identity · Name": run.name,
    "Identity · Alamo hash": run.alamo_hash ?? "",
    "Identity · Run ID": run.id,
    "State · Effective status": run.effective_status,
    "State · Declared status": run.status,
    "State · Progress": run.progress === null ? "" : `${run.progress}%`,
    "Execution · Output path": run.output_path ?? "",
    "Execution · Host": run.host ?? "",
    "Execution · Platform": run.platform ?? "",
    "Execution · Command": run.command.join(" "),
    "Execution · Started": displayTime(run.started_at),
    "Execution · Ended": displayTime(run.ended_at),
    "Execution · Last heartbeat": displayTime(run.last_heartbeat),
    "Source · Repository": run.git_repository_url ?? "",
    "Source · Git commit": run.git_commit ?? "",
    "Scheduler · System": run.scheduler_system ?? "",
    "Scheduler · Job ID": run.scheduler_job_id ?? "",
    "Organization · Tags": run.tags.join(", "),
    "Organization · Notes": run.notes,
    "Record · Created": displayTime(run.created_at),
    "Record · Updated": displayTime(run.updated_at),
    "Artifacts · Count": String(run.artifact_count),
  };
  const schedulerLabel = run.scheduler_system?.toLocaleLowerCase() === "slurm" ? "SLURM" : "Scheduler";
  for (const [key, value] of Object.entries(run.scheduler_details)) {
    values[`${schedulerLabel} · ${displayField(key)}`] = String(value);
  }
  return values;
}

function ComparisonSection({
  eyebrow,
  title,
  note,
  defaultOpen = true,
  plot = false,
  children,
}: {
  eyebrow: string;
  title: string;
  note?: string;
  defaultOpen?: boolean;
  plot?: boolean;
  children: ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <details className="panel comparison-section" open={open} onToggle={(event) => setOpen(event.currentTarget.open)}>
      <summary><div><p className="eyebrow">{eyebrow}</p><h2>{title}</h2></div><span>{note}</span><i aria-hidden="true">⌄</i></summary>
      <div className={plot ? "comparison-plot-body" : "comparison-table-body"}>{children}</div>
    </details>
  );
}

export function RunComparison({ ids, embedded = false }: { ids: string[]; embedded?: boolean }) {
  const [hideSimilar, setHideSimilar] = useState(false);
  const comparison = useQuery({
    queryKey: ["comparison", ids],
    queryFn: () => api<{ runs: ComparisonItem[] }>(`/comparisons/runs?${ids.map((id) => `ids=${encodeURIComponent(id)}`).join("&")}`),
    enabled: ids.length >= 2,
  });
  const content = (
    <>
      <header className={embedded ? "run-header" : "page-header"}><div><p className="eyebrow">RESULTS EXPLORER</p><h1>Compare {ids.length} runs</h1><p>Overlay results and expose provenance differences.</p></div><label className="comparison-similarity-toggle"><input type="checkbox" checked={hideSimilar} onChange={(event) => setHideSimilar(event.target.checked)} /><span>Hide similar</span></label></header>
      {ids.length < 2 ? <div className="panel empty-panel">Select two or more runs from the <Link href="/">run browser</Link> to begin.</div> : comparison.isPending ? <div className="center-state"><span className="spinner" />Building comparison…</div> : comparison.isError ? <div className="error-panel">The comparison could not be loaded.</div> : <>
        <ComparisonSection eyebrow="OVERLAY" title="Thermodynamics" note={comparison.data.runs.some((item) => item.thermo.some((series) => series.rows.length)) ? undefined : "No data"} defaultOpen={comparison.data.runs.some((item) => item.thermo.some((series) => series.rows.length))} plot>
          <ThermoPlot runs={comparison.data.runs.map((item) => ({ name: item.run.name, thermo: item.thermo }))} />
        </ComparisonSection>
        <ComparisonSection eyebrow="PROVENANCE" title="Run provenance" note="Differences highlighted">
          <MetadataTable hideSimilar={hideSimilar} records={comparison.data.runs.map((item) => ({ name: item.run.name, values: runProvenance(item.run) }))} />
        </ComparisonSection>
        <ComparisonSection eyebrow="ALAMO METADATA" title="Metadata comparison" note="Differences highlighted">
          <MetadataTable hideSimilar={hideSimilar} records={comparison.data.runs.map((item) => ({ name: item.run.name, values: item.metadata }))} />
        </ComparisonSection>
      </>}
    </>
  );
  return embedded ? <div className="embedded-run-record comparison-view">{content}</div> : content;
}

export default function ComparePage() {
  const params = new URLSearchParams(useSearch());
  const ids = (params.get("ids") ?? "").split(",").filter(Boolean);
  return <RunComparison ids={ids} />;
}
