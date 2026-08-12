import { useEffect, useMemo, useState, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useLocation, useParams } from "wouter";
import { api } from "../api";
import { isVideoContentType, isVisualContentType } from "../artifacts";
import CopyButton from "../components/CopyButton";
import LazyVideo from "../components/LazyVideo";
import MetadataTable from "../components/MetadataTable";
import PathTail from "../components/PathTail";
import StatusPill from "../components/StatusPill";
import ThermoPlot from "../components/ThermoPlot";
import { alamoOutputDirectory, formatSlurmMemory, slurmGpuCount, slurmJobId } from "../slurm";
import type { Artifact, Run, RunCopy, RunDetail } from "../types";

function formatBytes(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 ** 3) return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
  if (bytes < 1024 ** 4) return `${(bytes / 1024 ** 3).toFixed(1)} GB`;
  return `${(bytes / 1024 ** 4).toFixed(1)} TB`;
}

function abbreviatedAge(value: string, now = Date.now()) {
  const seconds = Math.max(0, Math.floor((now - new Date(value).getTime()) / 1000));
  if (seconds < 60) return `${seconds} sec`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes} min`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours} hr`;
  const days = Math.floor(hours / 24);
  if (days < 30) return `${days} days`;
  const months = Math.floor(days / 30);
  if (months < 12) return `${months} mo`;
  return `${Math.floor(days / 365)} yr`;
}

function ArtifactMedia({ artifact, url, fullscreen = false }: { artifact: Artifact; url: string; fullscreen?: boolean }) {
  if (isVideoContentType(artifact.content_type)) {
    if (!fullscreen) return <LazyVideo src={url} label={artifact.logical_name} />;
    return <video src={url} aria-label={artifact.logical_name} controls autoPlay loop playsInline preload="metadata" />;
  }
  return <img src={url} alt={artifact.logical_name} />;
}

export function ArtifactViewer({ artifact, url, onClose }: { artifact: Artifact; url: string; onClose: () => void }) {
  useEffect(() => {
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const closeOnEscape = (event: KeyboardEvent) => event.key === "Escape" && onClose();
    window.addEventListener("keydown", closeOnEscape);
    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener("keydown", closeOnEscape);
    };
  }, [onClose]);
  return (
    <div className="artifact-viewer" role="dialog" aria-modal="true" aria-label={`Preview ${artifact.logical_name}`} onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
      <header><div><strong>{artifact.logical_name}</strong><small>{artifact.path}</small></div><button onClick={onClose} aria-label="Close fullscreen preview">×</button></header>
      <div className="artifact-viewer-media"><ArtifactMedia artifact={artifact} url={url} fullscreen /></div>
    </div>
  );
}

function ArtifactCard({
  runId,
  artifact,
  isThumbnail,
  selectingThumbnail,
  onSelectThumbnail,
  onOpen,
}: {
  runId: string;
  artifact: Artifact;
  isThumbnail: boolean;
  selectingThumbnail: boolean;
  onSelectThumbnail: () => void;
  onOpen: (url: string) => void;
}) {
  const visual = isVisualContentType(artifact.content_type);
  const download = useQuery({
    queryKey: ["artifact-download", artifact.id],
    queryFn: () => api<Artifact>(`/runs/${runId}/artifacts/${artifact.id}/download`),
    enabled: visual,
    staleTime: 10 * 60_000,
  });
  const requestDownload = async () => {
    const record = await api<Artifact>(`/runs/${runId}/artifacts/${artifact.id}/download`);
    window.location.assign(record.download_url!);
  };
  return (
    <article className="artifact-card" data-thumbnail={isThumbnail}>
      <button className="artifact-preview" disabled={!visual || !download.data?.download_url} onClick={() => download.data?.download_url && onOpen(download.data.download_url)} aria-label={visual ? `Open ${artifact.logical_name} fullscreen` : undefined}>
        {visual && download.data?.download_url ? <ArtifactMedia artifact={artifact} url={download.data.download_url} /> : <span>{artifact.kind === "table" ? "▦" : artifact.kind === "log" ? "≡" : "◇"}</span>}
        {visual && download.data?.download_url && <i title="Open fullscreen">⛶</i>}
      </button>
      <div className="artifact-info"><strong title={artifact.path}>{artifact.logical_name}</strong><small>{artifact.path} · {formatBytes(artifact.size)} · v{artifact.version}</small>{visual && <button className={`thumbnail-choice${isThumbnail ? " active" : ""}`} disabled={isThumbnail || selectingThumbnail} onClick={onSelectThumbnail}>{isThumbnail ? "★ Thumbnail" : selectingThumbnail ? "Setting…" : "☆ Use as thumbnail"}</button>}</div>
      <button className="icon-button" title="Download" onClick={requestDownload}>⇩</button>
    </article>
  );
}

function InlineRunTitle({ run }: { run: Run }) {
  const queryClient = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(run.name);
  useEffect(() => setName(run.name), [run.name]);
  const update = useMutation({
    mutationFn: (nextName: string) => api<Run>(`/runs/${run.id}`, {
      method: "PATCH",
      body: JSON.stringify({ name: nextName }),
    }),
    onSuccess: () => {
      setEditing(false);
      queryClient.invalidateQueries({ queryKey: ["run", run.id] });
      queryClient.invalidateQueries({ queryKey: ["runs"] });
      queryClient.invalidateQueries({ queryKey: ["project-layout"] });
    },
  });
  const save = () => {
    const nextName = name.trim();
    if (!nextName) {
      setName(run.name);
      setEditing(false);
    } else if (nextName === run.name) {
      setEditing(false);
    } else if (!update.isPending) {
      update.mutate(nextName);
    }
  };
  if (editing) {
    return <input className="run-title-input" autoFocus value={name} maxLength={240} aria-label="Run name" onChange={(event) => setName(event.target.value)} onBlur={save} onKeyDown={(event) => {
      if (event.key === "Enter") event.currentTarget.blur();
      if (event.key === "Escape") {
        setName(run.name);
        setEditing(false);
      }
    }} />;
  }
  return <button className="editable-run-title" title="Click to rename" onClick={() => setEditing(true)}><h1>{run.name}</h1><span>✎</span></button>;
}

function RunMenu({ run }: { run: Run }) {
  const queryClient = useQueryClient();
  const [, navigate] = useLocation();
  const [tags, setTags] = useState(run.tags.join(", "));
  const [notes, setNotes] = useState(run.notes);
  const update = useMutation({
    mutationFn: () => api<Run>(`/runs/${run.id}`, {
      method: "PATCH",
      body: JSON.stringify({ tags: tags.split(",").map((tag) => tag.trim()).filter(Boolean), notes }),
    }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["run", run.id] });
      queryClient.invalidateQueries({ queryKey: ["runs"] });
      queryClient.invalidateQueries({ queryKey: ["project-layout"] });
    },
  });
  const remove = useMutation({
    mutationFn: () => api(`/runs/${run.id}`, { method: "DELETE" }),
    onSuccess: () => navigate("/"),
  });
  return (
    <details className="run-menu">
      <summary aria-label="Run settings" title="Run settings">•••</summary>
      <div className="run-menu-popover">
        <strong>Run settings</strong>
        <label>Tags<input value={tags} onChange={(event) => setTags(event.target.value)} placeholder="shock, convergence, paper-1" /></label>
        <label>Notes<textarea value={notes} onChange={(event) => setNotes(event.target.value)} rows={3} /></label>
        <div className="run-menu-actions"><button className="button button-danger button-quiet" disabled={remove.isPending} onClick={() => window.confirm(`Delete ${run.name}?`) && remove.mutate()}>Delete</button><button className="button button-primary" disabled={update.isPending} onClick={() => update.mutate()}>{update.isPending ? "Saving…" : "Save"}</button></div>
      </div>
    </details>
  );
}

function commitReference(value: string) {
  const clean = value.replace(/-dirty$/, "");
  return clean.match(/-g([0-9a-f]+)$/i)?.[1] ?? clean;
}

export function SlurmDetails({ run }: { run: Run }) {
  if (run.scheduler_system !== "slurm" && !run.scheduler_job_id?.startsWith("SLURM_JOB_ID=")) return null;
  const details = run.scheduler_details;
  type SlurmRow = { label: string; value: string | null | undefined; code?: boolean; copy?: boolean; wide?: boolean };
  const rows: SlurmRow[] = [
    { label: "Output directory", value: alamoOutputDirectory(run), code: true, copy: true, wide: true },
    { label: "Job name", value: details.job_name ?? run.name },
    { label: "Job ID", value: slurmJobId(run), code: true },
    { label: "Cluster", value: details.cluster },
    { label: "Partition", value: details.partition },
    { label: "QoS", value: details.qos },
    { label: "Account", value: details.account },
    { label: "Node list", value: details.node_list, code: true },
    { label: "Nodes", value: details.node_count },
    { label: "Tasks", value: details.task_count },
    { label: "Tasks per node", value: details.tasks_per_node },
    { label: "CPUs per task", value: details.cpus_per_task },
    { label: "GPUs", value: slurmGpuCount(run) },
    { label: "GPU IDs", value: details.job_gpu_ids, code: true },
    { label: "Memory per node", value: formatSlurmMemory(details.memory_per_node) },
    { label: "Memory per CPU", value: formatSlurmMemory(details.memory_per_cpu) },
    { label: "Constraints", value: details.constraints },
    { label: "Submit directory", value: details.submit_directory, code: true, copy: true, wide: true },
    { label: "plot_file", value: details.plot_file, code: true, wide: true },
  ];
  const visibleRows = rows.filter((row): row is SlurmRow & { value: string } => Boolean(row.value));
  return (
    <section className="panel slurm-detail-panel">
      <div className="panel-heading"><h2>SLURM</h2></div>
      <table className="slurm-detail-table"><tbody>{visibleRows.map((row) => (
        <tr key={row.label} data-wide={row.wide || undefined} data-path={row.copy || undefined}>
          <th>{row.label}</th>
          <td>{row.code ? <code title={row.value}>{row.copy ? <PathTail value={row.value} /> : row.value}</code> : <span>{row.value}</span>}{row.copy && <CopyButton value={row.value} label={row.label.toLowerCase()} />}</td>
        </tr>
      ))}</tbody></table>
    </section>
  );
}

const copyAction = {
  get: "get",
  put: "put",
  sync: "sync",
};

export function CopyLocations({ copies }: { copies: RunCopy[] }) {
  return (
    <section className="panel copy-locations-panel">
      <div className="panel-heading">
        <div><p className="eyebrow">STORAGE INVENTORY</p><h2>Copies</h2></div>
        <span>{copies.length} known {copies.length === 1 ? "location" : "locations"}</span>
      </div>
      {copies.length ? <div className="copy-location-table">
        <div className="copy-location-header"><span>Site</span><span>Path</span><span>Contents</span><span>Last update</span></div>
        {copies.map((copy) => <article className="copy-location-row" key={copy.id}>
          <div className="copy-site"><strong>{copy.site}</strong>{copy.host !== copy.site && <small>{copy.host}</small>}</div>
          <div className="copy-path"><code><PathTail value={copy.path} /></code><CopyButton value={copy.path} label="path" compact /></div>
          <div className="copy-contents">
            <strong>{copy.file_count.toLocaleString()} files</strong>
            {copy.total_size_bytes !== null && <small>{formatBytes(copy.total_size_bytes)}</small>}
            {(copy.has_cell_data || copy.has_node_data) && <span className="simulation-copy-badge">Data</span>}
          </div>
          <div className="copy-updated"><strong title={new Date(copy.updated_at).toLocaleString()}>{abbreviatedAge(copy.updated_at)}</strong><small>via zph {copyAction[copy.last_action]}</small></div>
        </article>)}
      </div> : <div className="copy-location-empty">No inventoried copies yet. Run <code>zph sync PATH</code> where a copy is stored.</div>}
    </section>
  );
}

export function RunRecord({ runId, embedded = false }: { runId: string; embedded?: boolean }) {
  const queryClient = useQueryClient();
  const [tab, setTab] = useState("overview");
  const [viewer, setViewer] = useState<{ artifact: Artifact; url: string } | null>(null);
  const detail = useQuery({ queryKey: ["run", runId], queryFn: () => api<RunDetail>(`/runs/${runId}`), refetchInterval: 15_000 });
  const artifacts = useQuery({ queryKey: ["artifacts", runId], queryFn: () => api<Artifact[]>(`/runs/${runId}/artifacts`) });
  const latestArtifacts = useMemo(() => {
    const paths = new Set<string>();
    return (artifacts.data ?? []).filter((artifact) => !paths.has(artifact.path) && Boolean(paths.add(artifact.path)));
  }, [artifacts.data]);
  const selectThumbnail = useMutation({
    mutationFn: (artifactId: string) => api<Run>(`/runs/${runId}/artifacts/${artifactId}/thumbnail`, { method: "PUT" }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["run", runId] });
      queryClient.invalidateQueries({ queryKey: ["runs"] });
      queryClient.invalidateQueries({ queryKey: ["project-layout"] });
    },
  });
  const frame = (content: ReactNode) => embedded ? <div className="embedded-run-record">{content}</div> : content;
  if (detail.isPending) return frame(<div className="center-state"><span className="spinner" />Loading run…</div>);
  if (detail.isError) return frame(<div className="error-panel">This run could not be loaded.</div>);
  const { run, metadata, output, copies = [], thermo } = detail.data;
  const commit = run.git_commit ? commitReference(run.git_commit) : null;
  const repository = run.git_repository_url ?? "https://github.com/solidsgroup/alamo";
  return frame(
    <>
      <header className="run-header">
        <div><p className="eyebrow">RUN DETAIL</p><div className="run-title-row"><InlineRunTitle run={run} /><StatusPill status={run.effective_status} /></div>{run.host && <p>Running on <strong>{run.host}</strong></p>}</div>
        <div className="heading-actions"><Link className="button" href={`/compare?ids=${run.id}`}>Compare</Link><RunMenu key={run.id} run={run} /></div>
      </header>
      <nav className="tabs">{["overview", "stdout", "git diff", "thermo", "files", "metadata"].map((item) => <button key={item} className={tab === item ? "active" : ""} onClick={() => setTab(item)}>{item}{item === "files" && <span>{latestArtifacts.length}</span>}</button>)}</nav>
      {tab === "overview" && <>
        <section className="panel metric-grid">
          <div><small>Progress</small><strong>{run.progress == null ? "—" : `${run.progress}%`}</strong></div>
          <div><small>Started</small><strong>{run.started_at ? new Date(run.started_at).toLocaleString() : "—"}</strong></div>
          <div><small>Last heartbeat</small><strong>{run.last_heartbeat ? new Date(run.last_heartbeat).toLocaleString() : "—"}</strong></div>
          <div><small>Code revision</small><strong>{commit ? <a className="commit-link" href={`${repository}/commit/${encodeURIComponent(commit)}`} target="_blank" rel="noreferrer"><code>{run.git_commit!.slice(0, 12)}</code><span>↗</span></a> : "—"}</strong></div>
        </section>
        <SlurmDetails run={run} />
        <CopyLocations copies={copies} />
        <section className="panel"><div className="panel-heading"><div><p className="eyebrow">LIVE SERIES</p><h2>Thermodynamics</h2></div></div><ThermoPlot runs={[{ name: run.name, thermo }]} /></section>
      </>}
      {tab === "stdout" && <section className="panel output-panel"><div className="panel-heading"><div><p className="eyebrow">LIVE OUTPUT</p><h2>stdout</h2></div>{output && <span>Updated {new Date(output.updated_at).toLocaleTimeString()}</span>}</div>{output ? <><pre>{output.stdout || "No output has been written yet."}</pre>{output.stdout_truncated && <p className="output-note">Showing the most recent 1 MB.</p>}</> : <div className="empty-panel">No stdout has been posted for this run yet.</div>}</section>}
      {tab === "git diff" && <section className="panel output-panel diff-output"><div className="panel-heading"><div><p className="eyebrow">BUILD PROVENANCE</p><h2>git diff</h2></div></div>{output ? output.git_diff ? <><pre>{output.git_diff}</pre>{output.git_diff_truncated && <p className="output-note">Showing the first 1 MB.</p>}</> : <div className="empty-panel clean-diff"><span>✓</span>Working tree was clean at build time.</div> : <div className="empty-panel">No git diff has been posted for this run yet.</div>}</section>}
      {tab === "thermo" && <section className="panel"><div className="panel-heading"><div><p className="eyebrow">RESULTS EXPLORER</p><h2>thermo.dat</h2></div><span>{thermo.reduce((count, series) => count + series.rows.length, 0).toLocaleString()} rows</span></div><ThermoPlot runs={[{ name: run.name, thermo }]} /></section>}
      {tab === "files" && <section><div className="section-heading"><div><h2>Artifacts</h2><p>Latest version of each posted file. Click an image or video for a fullscreen view.</p></div></div>{selectThumbnail.isError && <p className="form-error">Could not set the run thumbnail.</p>}{latestArtifacts.length ? <div className="artifact-grid">{latestArtifacts.map((artifact) => <ArtifactCard key={artifact.id} runId={run.id} artifact={artifact} isThumbnail={artifact.id === run.thumbnail_artifact_id} selectingThumbnail={selectThumbnail.isPending && selectThumbnail.variables === artifact.id} onSelectThumbnail={() => selectThumbnail.mutate(artifact.id)} onOpen={(url) => setViewer({ artifact, url })} />)}</div> : <div className="empty-panel panel">No artifacts yet. Upload some with <code>zph put '*.png'</code>.</div>}</section>}
      {tab === "metadata" && <section className="panel"><div className="panel-heading"><div><p className="eyebrow">Alamo output</p><h2>metadata</h2></div><code>{metadata?.digest.slice(0, 12) ?? "not posted"}</code></div>{metadata ? <><MetadataTable records={[{ name: run.name, values: metadata.values }]} /><details className="raw-metadata"><summary>Raw file</summary><pre>{metadata.raw_text}</pre></details></> : <div className="empty-panel">No metadata file has been posted.</div>}</section>}
      {viewer && <ArtifactViewer artifact={viewer.artifact} url={viewer.url} onClose={() => setViewer(null)} />}
    </>,
  );
}

export default function RunPage() {
  const { runId = "" } = useParams();
  return <RunRecord runId={runId} />;
}
