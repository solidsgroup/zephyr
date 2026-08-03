import { useMemo, useState } from "react";
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

function EditRun({ run }: { run: Run }) {
  const queryClient = useQueryClient();
  const [, navigate] = useLocation();
  const [name, setName] = useState(run.name);
  const [tags, setTags] = useState(run.tags.join(", "));
  const [notes, setNotes] = useState(run.notes);
  const update = useMutation({
    mutationFn: () => api<Run>(`/runs/${run.id}`, {
      method: "PATCH",
      body: JSON.stringify({ name, tags: tags.split(",").map((tag) => tag.trim()).filter(Boolean), notes }),
    }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["run", run.id] }),
  });
  const remove = useMutation({
    mutationFn: () => api(`/runs/${run.id}`, { method: "DELETE" }),
    onSuccess: () => navigate("/"),
  });
  return (
    <section className="panel edit-panel">
      <h2>Organization</h2>
      <label>Name<input value={name} onChange={(event) => setName(event.target.value)} /></label>
      <label>Tags<input value={tags} onChange={(event) => setTags(event.target.value)} placeholder="shock, convergence, paper-1" /></label>
      <label>Notes<textarea value={notes} onChange={(event) => setNotes(event.target.value)} rows={4} /></label>
      <button className="button button-primary" disabled={update.isPending} onClick={() => update.mutate()}>{update.isPending ? "Saving…" : "Save changes"}</button>
      <div className="danger-zone"><strong>Delete this run</strong><p>Removes its catalog, telemetry, and artifact links. This cannot be undone.</p><button className="button button-danger" disabled={remove.isPending} onClick={() => window.confirm(`Delete ${run.name}?`) && remove.mutate()}>Delete run</button></div>
    </section>
  );
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
  const { run, metadata, thermo } = detail.data;
  return (
    <>
      <div className="breadcrumbs"><Link href="/">Runs</Link><span>/</span><span>{run.name}</span></div>
      <header className="run-header">
        <div><div className="run-title-row"><h1>{run.name}</h1><StatusPill status={run.effective_status} /></div><p><code>{run.alamo_hash ?? run.id}</code>{run.host && <> on <strong>{run.host}</strong></>}</p></div>
        <Link className="button" href={`/compare?ids=${run.id}`}>Add to comparison</Link>
      </header>
      <nav className="tabs">{["overview", "thermo", "files", "metadata"].map((item) => <button key={item} className={tab === item ? "active" : ""} onClick={() => setTab(item)}>{item}{item === "files" && <span>{latestArtifacts.length}</span>}</button>)}</nav>
      {tab === "overview" && <div className="two-column">
        <div>
          <section className="panel metric-grid">
            <div><small>Progress</small><strong>{run.progress == null ? "—" : `${run.progress}%`}</strong></div>
            <div><small>Started</small><strong>{run.started_at ? new Date(run.started_at).toLocaleString() : "—"}</strong></div>
            <div><small>Last heartbeat</small><strong>{run.last_heartbeat ? new Date(run.last_heartbeat).toLocaleString() : "—"}</strong></div>
            <div><small>Code revision</small><strong><code>{run.git_commit?.slice(0, 12) ?? "—"}</code></strong></div>
          </section>
          <section className="panel"><div className="panel-heading"><div><p className="eyebrow">LIVE SERIES</p><h2>Thermodynamics</h2></div></div><ThermoPlot runs={[{ name: run.name, thermo }]} /></section>
        </div>
        <EditRun run={run} />
      </div>}
      {tab === "thermo" && <section className="panel"><div className="panel-heading"><div><p className="eyebrow">RESULTS EXPLORER</p><h2>thermo.dat</h2></div><span>{thermo.reduce((count, series) => count + series.rows.length, 0).toLocaleString()} rows</span></div><ThermoPlot runs={[{ name: run.name, thermo }]} /></section>}
      {tab === "files" && <section><div className="section-heading"><div><h2>Artifacts</h2><p>Latest version of each posted file. Choose an image to represent this run.</p></div></div>{selectThumbnail.isError && <p className="form-error">Could not set the run thumbnail.</p>}{latestArtifacts.length ? <div className="artifact-grid">{latestArtifacts.map((artifact) => <ArtifactCard key={artifact.id} runId={run.id} artifact={artifact} isThumbnail={artifact.id === run.thumbnail_artifact_id} selectingThumbnail={selectThumbnail.isPending && selectThumbnail.variables === artifact.id} onSelectThumbnail={() => selectThumbnail.mutate(artifact.id)} />)}</div> : <div className="empty-panel panel">No artifacts yet. Upload some with <code>zph put '*.png'</code>.</div>}</section>}
      {tab === "metadata" && <section className="panel"><div className="panel-heading"><div><p className="eyebrow">ALAMO OUTPUT</p><h2>metadata</h2></div><code>{metadata?.digest.slice(0, 12) ?? "not posted"}</code></div>{metadata ? <><MetadataTable records={[{ name: run.name, values: metadata.values }]} /><details className="raw-metadata"><summary>Raw file</summary><pre>{metadata.raw_text}</pre></details></> : <div className="empty-panel">No metadata file has been posted.</div>}</section>}
    </>
  );
}
