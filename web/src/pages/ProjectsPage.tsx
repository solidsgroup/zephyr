import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "wouter";
import { api, currentUser } from "../api";
import StatusPill from "../components/StatusPill";
import type { Project, Run } from "../types";

interface Member { id: string; user_id: string; email: string; name: string; role: string }

function ProjectWorkspace({ project }: { project: Project }) {
  const queryClient = useQueryClient();
  const me = useQuery({ queryKey: ["me"], queryFn: currentUser });
  const allRuns = useQuery({ queryKey: ["runs"], queryFn: () => api<Run[]>("/runs") });
  const runs = useQuery({ queryKey: ["project-runs", project.id], queryFn: () => api<Run[]>(`/projects/${project.id}/runs`) });
  const members = useQuery({
    queryKey: ["project-members", project.id],
    queryFn: () => api<Member[]>(`/projects/${project.id}/members`),
    enabled: me.data?.id === project.owner_id,
  });
  const [runId, setRunId] = useState("");
  const [email, setEmail] = useState("");
  const addRun = useMutation({
    mutationFn: () => api(`/projects/${project.id}/runs`, { method: "POST", body: JSON.stringify({ run_id: runId }) }),
    onSuccess: () => { setRunId(""); queryClient.invalidateQueries({ queryKey: ["project-runs", project.id] }); },
  });
  const removeRun = useMutation({
    mutationFn: (id: string) => api(`/projects/${project.id}/runs/${id}`, { method: "DELETE" }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["project-runs", project.id] }),
  });
  const addMember = useMutation({
    mutationFn: () => api(`/projects/${project.id}/members`, { method: "POST", body: JSON.stringify({ email, role: "viewer" }) }),
    onSuccess: () => { setEmail(""); queryClient.invalidateQueries({ queryKey: ["project-members", project.id] }); },
  });
  const removeProject = useMutation({
    mutationFn: () => api(`/projects/${project.id}`, { method: "DELETE" }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["projects"] }),
  });
  const included = new Set((runs.data ?? []).map((run) => run.id));
  const candidates = (allRuns.data ?? []).filter((run) => run.owner_id === me.data?.id && !included.has(run.id));
  const owner = me.data?.id === project.owner_id;
  return (
    <section className="panel project-workspace">
      <div className="panel-heading"><div><p className="eyebrow">{project.visibility.toUpperCase()}</p><h2>{project.name}</h2><p>{project.description || "No description"}</p></div><div className="heading-actions">{project.visibility === "public" && <a className="button" href={`/public/${project.slug}`}>Open public page ↗</a>}{owner && <button className="button button-danger" onClick={() => window.confirm(`Delete project ${project.name}? Runs will remain in Zephyr.`) && removeProject.mutate()}>Delete project</button>}</div></div>
      <div className="project-columns">
        <div><h3>Runs</h3><div className="inline-form"><select value={runId} onChange={(event) => setRunId(event.target.value)}><option value="">Choose an owned run…</option>{candidates.map((run) => <option value={run.id} key={run.id}>{run.name}</option>)}</select><button className="button button-primary" disabled={!runId || addRun.isPending} onClick={() => addRun.mutate()}>Add</button></div>
          <div className="compact-list">{runs.data?.map((run) => <div key={run.id}><StatusPill status={run.effective_status} /><Link href={`/runs/${run.id}`}>{run.name}</Link>{owner && <button className="icon-button danger" onClick={() => removeRun.mutate(run.id)}>×</button>}</div>)}{!runs.data?.length && <p className="muted">No runs in this project.</p>}</div>
        </div>
        <div><h3>Sharing</h3>{owner ? <><div className="inline-form"><input type="email" value={email} onChange={(event) => setEmail(event.target.value)} placeholder="colleague@solids.group" /><button className="button" disabled={!email || addMember.isPending} onClick={() => addMember.mutate()}>Invite</button></div><div className="compact-list">{members.data?.map((member) => <div key={member.id}><span className="avatar small">{member.name[0]}</span><span>{member.email}<small>{member.role}</small></span></div>)}</div></> : <p className="muted">Shared with you by the project owner.</p>}</div>
      </div>
    </section>
  );
}

export default function ProjectsPage() {
  const queryClient = useQueryClient();
  const projects = useQuery({ queryKey: ["projects"], queryFn: () => api<Project[]>("/projects") });
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const [visibility, setVisibility] = useState<Project["visibility"]>("private");
  const create = useMutation({
    mutationFn: () => api<Project>("/projects", { method: "POST", body: JSON.stringify({ name, slug, visibility }) }),
    onSuccess: (project) => { queryClient.invalidateQueries({ queryKey: ["projects"] }); setSelectedId(project.id); setShowCreate(false); setName(""); setSlug(""); },
  });
  const selected = projects.data?.find((project) => project.id === selectedId) ?? projects.data?.[0];
  return (
    <>
      <header className="page-header"><div><p className="eyebrow">ORGANIZE & SHARE</p><h1>Projects</h1><p>Curate related runs and control who can see them.</p></div><button className="button button-primary" onClick={() => setShowCreate(!showCreate)}>New project</button></header>
      {showCreate && <section className="panel create-project"><label>Name<input value={name} onChange={(event) => { setName(event.target.value); if (!slug) setSlug(event.target.value.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "")); }} /></label><label>URL slug<input value={slug} onChange={(event) => setSlug(event.target.value)} /></label><label>Visibility<select value={visibility} onChange={(event) => setVisibility(event.target.value as Project["visibility"])}><option value="private">Private — invited users</option><option value="group">Group — all solids.group users</option><option value="public">Public — anyone with the link</option></select></label><button className="button button-primary" disabled={name.length < 1 || slug.length < 3 || create.isPending} onClick={() => create.mutate()}>Create project</button>{create.isError && <span className="form-error">Could not create this project.</span>}</section>}
      <div className="project-tabs">{projects.data?.map((project) => <button className={selected?.id === project.id ? "active" : ""} key={project.id} onClick={() => setSelectedId(project.id)}><span>{project.name}</span><small>{project.visibility}</small></button>)}</div>
      {selected ? <ProjectWorkspace key={selected.id} project={selected} /> : <div className="panel empty-panel">Create a project to organize and share runs.</div>}
    </>
  );
}
