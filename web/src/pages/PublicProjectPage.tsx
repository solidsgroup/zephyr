import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "wouter";
import { publicApi } from "../api";
import { isVideoContentType, isVisualContentType } from "../artifacts";
import LazyVideo from "../components/LazyVideo";
import MetadataTable from "../components/MetadataTable";
import StatusPill from "../components/StatusPill";
import ThermoPlot from "../components/ThermoPlot";
import type { Artifact, MetadataRecord, Project, Run, ThermoSeries } from "../types";

interface PublicProject { project: Project; runs: Run[] }
interface PublicRun { project: Project; run: Run; metadata: MetadataRecord | null; thermo: ThermoSeries[]; artifacts: Artifact[] }

function PublicRunView({ slug, runId }: { slug: string; runId: string }) {
  const detail = useQuery({ queryKey: ["public-run", slug, runId], queryFn: () => publicApi<PublicRun>(`/projects/${slug}/runs/${runId}`) });
  if (detail.isPending) return <div className="center-state"><span className="spinner" />Loading public run…</div>;
  if (detail.isError) return <div className="error-panel">This run is not publicly available.</div>;
  const { project, run, metadata, thermo, artifacts } = detail.data;
  return <>
    <div className="breadcrumbs"><Link href={`/public/${slug}`}>{project.name}</Link><span>/</span><span>{run.name}</span></div>
    <header className="run-header"><div><div className="run-title-row"><h1>{run.name}</h1><StatusPill status={run.effective_status} /></div><p>Public reproducibility record · <code>{run.alamo_hash ?? run.id}</code></p></div></header>
    <section className="panel"><div className="panel-heading"><div><p className="eyebrow">THERMODYNAMICS</p><h2>Results</h2></div></div><ThermoPlot runs={[{ name: run.name, thermo }]} /></section>
    {metadata && <section className="panel"><div className="panel-heading"><div><p className="eyebrow">PROVENANCE</p><h2>Metadata</h2></div></div><MetadataTable records={[{ name: run.name, values: metadata.values }]} /></section>}
    <section><div className="section-heading"><div><h2>Artifacts</h2><p>Published files associated with this simulation.</p></div></div><div className="artifact-grid">{artifacts.map((artifact) => <a className="artifact-card public-artifact" key={artifact.id} href={artifact.download_url ?? "#"}><div className="artifact-preview">{artifact.download_url && isVideoContentType(artifact.content_type) ? <LazyVideo src={artifact.download_url} label={artifact.logical_name} /> : artifact.download_url && isVisualContentType(artifact.content_type) ? <img loading="lazy" src={artifact.download_url} alt={artifact.logical_name} /> : <span>◇</span>}</div><div className="artifact-info"><strong>{artifact.logical_name}</strong><small>{artifact.path}</small></div><span>⇩</span></a>)}</div></section>
  </>;
}

export default function PublicProjectPage() {
  const { slug = "", "*": rest = "" } = useParams();
  const match = rest.match(/^runs\/([0-9a-f-]+)$/);
  if (match) return <div className="public-shell"><PublicRunView slug={slug} runId={match[1]} /></div>;
  return <PublicProjectIndex slug={slug} />;
}

function PublicProjectIndex({ slug }: { slug: string }) {
  const project = useQuery({ queryKey: ["public-project", slug], queryFn: () => publicApi<PublicProject>(`/projects/${slug}`) });
  if (project.isPending) return <div className="center-state"><span className="spinner" />Loading public project…</div>;
  if (project.isError) return <div className="public-shell"><div className="error-panel">This project is not publicly available.</div></div>;
  return <div className="public-shell">
    <header className="public-header"><Link className="brand" href="/"><span className="brand-mark">Z</span><span><strong>Zephyr</strong><small>Public project</small></span></Link><a className="button" href="/">Sign in</a></header>
    <section className="public-hero"><p className="eyebrow">Public Alamo collection</p><h1>{project.data.project.name}</h1><p>{project.data.project.description}</p></section>
    <section className="panel table-panel"><div className="table-scroll"><table className="data-table"><thead><tr><th>Run</th><th>Status</th><th>Code</th><th>Updated</th></tr></thead><tbody>{project.data.runs.map((run) => <tr key={run.id}><td><div className="run-name"><Link href={`/public/${slug}/runs/${run.id}`}>{run.name}</Link></div></td><td><StatusPill status={run.effective_status} /></td><td><code>{run.git_commit?.slice(0, 9) ?? "—"}</code></td><td>{new Date(run.updated_at).toLocaleString()}</td></tr>)}</tbody></table></div></section>
  </div>;
}
