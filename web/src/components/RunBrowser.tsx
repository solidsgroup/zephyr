import { useMemo, useState, type CSSProperties, type MouseEvent } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useLocation } from "wouter";
import { api } from "../api";
import type { Run } from "../types";
import StatusPill from "./StatusPill";

function age(value: string | null) {
  if (!value) return "No heartbeat";
  const seconds = Math.max(0, (Date.now() - new Date(value).getTime()) / 1000);
  if (seconds < 60) return `${Math.round(seconds)}s ago`;
  if (seconds < 3600) return `${Math.round(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.round(seconds / 3600)}h ago`;
  return `${Math.round(seconds / 86400)}d ago`;
}

function artifactGlyph(kind: string) {
  if (kind === "table") return "▦";
  if (kind === "log") return "≡";
  if (kind === "checkpoint") return "◫";
  return "◇";
}

export function ArtifactStack({ run }: { run: Run }) {
  if (!run.artifact_previews.length) {
    return <span className="run-preview-empty" aria-label="No artifacts">Z</span>;
  }
  return (
    <div className="run-preview-stack" aria-label={`${run.artifact_count} artifacts`}>
      {run.artifact_previews.map((artifact, index) => (
        <div
          className={`run-preview-card${artifact.id === run.thumbnail_artifact_id ? " selected" : ""}`}
          key={artifact.id}
          style={{ "--stack-index": index } as CSSProperties}
          title={artifact.logical_name}
        >
          {artifact.kind === "image" && artifact.download_url
            ? <img loading="lazy" src={artifact.download_url} alt={artifact.logical_name} />
            : <span>{artifactGlyph(artifact.kind)}</span>}
        </div>
      ))}
      {run.artifact_count > run.artifact_previews.length && <small>+{run.artifact_count - run.artifact_previews.length}</small>}
    </div>
  );
}

export default function RunBrowser({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [location, navigate] = useLocation();
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("");
  const [selected, setSelected] = useState<Record<string, boolean>>({});
  const runs = useQuery({
    queryKey: ["runs"],
    queryFn: () => api<Run[]>("/runs"),
    refetchInterval: 15_000,
  });
  const data = useMemo(() => (runs.data ?? []).filter((run) =>
    (!status || run.effective_status === status) &&
    (!search || `${run.name} ${run.alamo_hash ?? ""} ${run.host ?? ""}`.toLowerCase().includes(search.toLowerCase())),
  ), [runs.data, search, status]);
  const selectedIds = Object.keys(selected).filter((id) => selected[id]);

  function chooseRun(event: MouseEvent<HTMLAnchorElement>, run: Run) {
    if (event.ctrlKey || event.metaKey) {
      event.preventDefault();
      setSelected((current) => ({ ...current, [run.id]: !current[run.id] }));
      return;
    }
    setSelected({ [run.id]: true });
    onClose();
  }

  return (
    <aside className="run-browser" data-open={open} aria-label="Run browser">
      <header className="run-browser-header">
        <div>
          <p className="eyebrow">Alamo workspace</p>
          <h2>Runs <span>{runs.data?.length ?? 0}</span></h2>
        </div>
        <div className="run-browser-actions">
          <button className={runs.isFetching ? "refreshing" : ""} title="Refresh runs" aria-label="Refresh runs" onClick={() => runs.refetch()}>↻</button>
          <button className="run-browser-close" title="Close run browser" aria-label="Close run browser" onClick={onClose}>×</button>
        </div>
      </header>
      <div className="run-browser-filters">
        <label className="run-search">
          <span>⌕</span>
          <input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search runs" aria-label="Search runs" />
        </label>
        <select value={status} onChange={(event) => setStatus(event.target.value)} aria-label="Filter run status">
          <option value="">All statuses</option>
          <option>running</option>
          <option>completed</option>
          <option>failed</option>
          <option>interrupted</option>
          <option>unreachable</option>
        </select>
      </div>
      <div className="run-browser-list" aria-label="Runs">
        {runs.isPending ? <div className="run-browser-state"><span className="spinner" />Loading runs…</div> :
          runs.isError ? <div className="run-browser-state error-text">Could not load runs.</div> :
          data.map((run) => {
            const active = location === `/runs/${run.id}`;
            const chosen = Boolean(selected[run.id]);
            return (
              <div className="run-browser-item" data-active={active} data-selected={chosen} key={run.id}>
                <Link
                  href={`/runs/${run.id}`}
                  onClickCapture={(event) => chooseRun(event, run)}
                  aria-current={active ? "page" : undefined}
                  aria-label={`${run.name}${chosen ? ", selected for comparison" : ""}`}
                >
                  <div className="run-artifact-slot"><ArtifactStack run={run} /></div>
                  <div className="run-browser-copy">
                    <div><strong title={run.name}>{run.name}</strong><StatusPill status={run.effective_status} /></div>
                    <small>{run.host ?? "Unknown host"}<span>·</span>{age(run.last_heartbeat)}</small>
                    {run.progress != null && <span className="run-browser-progress"><i style={{ width: `${run.progress}%` }} /></span>}
                  </div>
                </Link>
              </div>
            );
          })}
        {!runs.isPending && !runs.isError && !data.length && <div className="run-browser-state">No runs match this view.</div>}
      </div>
      <footer className="run-browser-footer">
        {selectedIds.length >= 2 ?
          <button className="button button-primary" onClick={() => navigate(`/compare?ids=${selectedIds.join(",")}`)}>Compare {selectedIds.length} runs</button> :
          <span>{selectedIds.length === 1 ? "Ctrl/Cmd-click another run to compare" : "Ctrl/Cmd-click to select multiple runs"}</span>}
      </footer>
    </aside>
  );
}
