import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useLocation, useParams } from "wouter";
import { api } from "../api";
import MetadataTable from "../components/MetadataTable";
import StatusPill from "../components/StatusPill";
import ThermoPlot from "../components/ThermoPlot";
import type { Artifact, Run, RunDetail } from "../types";

function formatBytes(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
}

function ArtifactCard({
  runId,
  artifact,
  isThumbnail,
  selectingThumbnail,
  onSelectThumbnail,
}: {
  runId: string;
  artifact: Artifact;
  isThumbnail: boolean;
  selectingThumbnail: boolean;
  onSelectThumbnail: () => void;
}) {
  const download = useQuery({
    queryKey: ["artifact-download", artifact.id],
    queryFn: () => api<Artifact>(`/runs/${runId}/artifacts/${artifact.id}/download`),
    enabled: artifact.kind === "image",
    staleTime: 10 * 60_000,
  });
  const requestDownload = async () => {
    const record = await api<Artifact>(`/runs/${runId}/artifacts/${artifact.id}/download`);
    window.location.assign(record.download_url!);
  };
  return (
    <article className="artifact-card" data-thumbnail={isThumbnail}>
      <div className="artifact-preview">{artifact.kind === "image" && download.data?.download_url ? <img src={download.data.download_url} alt={artifact.logical_name} /> : <span>{artifact.kind === "table" ? "▦" : artifact.kind === "log" ? "≡" : "◇"}</span>}</div>
      <div className="artifact-info"><strong title={artifact.path}>{artifact.logical_name}</strong><small>{artifact.path} · {formatBytes(artifact.size)} · v{artifact.version}</small>{artifact.kind === "image" && <button className={`thumbnail-choice${isThumbnail ? " active" : ""}`} disabled={isThumbnail || selectingThumbnail} onClick={onSelectThumbnail}>{isThumbnail ? "★ Thumbnail" : selectingThumbnail ? "Setting…" : "☆ Use as thumbnail"}</button>}</div>
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

export default function RunPage() {
  const { runId = "" } = useParams();
  const queryClient = useQueryClient();
  const [tab, setTab] = useState("overview");
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
    },
  });
  if (detail.isPending) return <div className="center-state"><span className="spinner" />Loading run…</div>;
  if (detail.isError) return <div className="error-panel">This run could not be loaded.</div>;
  const { run, metadata, output, thermo } = detail.data;
  const commit = run.git_commit ? commitReference(run.git_commit) : null;
  const repository = run.git_repository_url ?? "https://github.com/solidsgroup/alamo";
  return (
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
        <section className="panel"><div className="panel-heading"><div><p className="eyebrow">LIVE SERIES</p><h2>Thermodynamics</h2></div></div><ThermoPlot runs={[{ name: run.name, thermo }]} /></section>
      </>}
      {tab === "stdout" && <section className="panel output-panel"><div className="panel-heading"><div><p className="eyebrow">LIVE OUTPUT</p><h2>stdout</h2></div>{output && <span>Updated {new Date(output.updated_at).toLocaleTimeString()}</span>}</div>{output ? <><pre>{output.stdout || "No output has been written yet."}</pre>{output.stdout_truncated && <p className="output-note">Showing the most recent 1 MB.</p>}</> : <div className="empty-panel">No stdout has been posted for this run yet.</div>}</section>}
      {tab === "git diff" && <section className="panel output-panel diff-output"><div className="panel-heading"><div><p className="eyebrow">BUILD PROVENANCE</p><h2>git diff</h2></div></div>{output ? output.git_diff ? <><pre>{output.git_diff}</pre>{output.git_diff_truncated && <p className="output-note">Showing the first 1 MB.</p>}</> : <div className="empty-panel clean-diff"><span>✓</span>Working tree was clean at build time.</div> : <div className="empty-panel">No git diff has been posted for this run yet.</div>}</section>}
      {tab === "thermo" && <section className="panel"><div className="panel-heading"><div><p className="eyebrow">RESULTS EXPLORER</p><h2>thermo.dat</h2></div><span>{thermo.reduce((count, series) => count + series.rows.length, 0).toLocaleString()} rows</span></div><ThermoPlot runs={[{ name: run.name, thermo }]} /></section>}
      {tab === "files" && <section><div className="section-heading"><div><h2>Artifacts</h2><p>Latest version of each posted file. Choose an image to represent this run.</p></div></div>{selectThumbnail.isError && <p className="form-error">Could not set the run thumbnail.</p>}{latestArtifacts.length ? <div className="artifact-grid">{latestArtifacts.map((artifact) => <ArtifactCard key={artifact.id} runId={run.id} artifact={artifact} isThumbnail={artifact.id === run.thumbnail_artifact_id} selectingThumbnail={selectThumbnail.isPending && selectThumbnail.variables === artifact.id} onSelectThumbnail={() => selectThumbnail.mutate(artifact.id)} />)}</div> : <div className="empty-panel panel">No artifacts yet. Upload some with <code>zph put '*.png'</code>.</div>}</section>}
      {tab === "metadata" && <section className="panel"><div className="panel-heading"><div><p className="eyebrow">ALAMO OUTPUT</p><h2>metadata</h2></div><code>{metadata?.digest.slice(0, 12) ?? "not posted"}</code></div>{metadata ? <><MetadataTable records={[{ name: run.name, values: metadata.values }]} /><details className="raw-metadata"><summary>Raw file</summary><pre>{metadata.raw_text}</pre></details></> : <div className="empty-panel">No metadata file has been posted.</div>}</section>}
    </>
  );
}
