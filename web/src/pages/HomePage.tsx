import { useMemo, type CSSProperties } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "wouter";
import { api } from "../api";
import { isVideoContentType } from "../artifacts";
import LazyVideo from "../components/LazyVideo";
import { ArtifactStack } from "../components/RunBrowser";
import StatusPill from "../components/StatusPill";
import type { ProjectDashboard, Run } from "../types";

function relativeAge(value: string) {
  const seconds = Math.max(0, Math.floor((Date.now() - new Date(value).getTime()) / 1000));
  if (seconds < 60) return "just now";
  if (seconds < 3600) return `${Math.floor(seconds / 60)} min ago`;
  if (seconds < 86_400) return `${Math.floor(seconds / 3600)} hr ago`;
  if (seconds < 604_800) return `${Math.floor(seconds / 86_400)} days ago`;
  return new Date(value).toLocaleDateString();
}

function projectInitials(name: string) {
  const words = name.trim().split(/\s+/).filter(Boolean);
  return (words.length > 1 ? `${words[0][0]}${words[1][0]}` : words[0]?.slice(0, 2) || "Z").toLocaleUpperCase();
}

function projectHue(project: ProjectDashboard) {
  const hues = [216, 258, 184, 28, 332];
  const index = [...project.slug].reduce((total, character) => total + character.charCodeAt(0), 0) % hues.length;
  return hues[index];
}

function ProjectPreviews({ project }: { project: ProjectDashboard }) {
  const previews = project.artifact_previews ?? [];
  if (!previews.length) {
    return <div className="dashboard-project-previews empty" aria-label="No project previews"><span>◇</span></div>;
  }
  return (
    <div className="dashboard-project-previews" data-count={previews.length}>
      {previews.map((artifact) => (
        <div className="dashboard-project-preview" title={artifact.logical_name} key={artifact.id}>
          {isVideoContentType(artifact.content_type)
            ? <LazyVideo src={artifact.download_url!} label={artifact.logical_name} />
            : <img loading="lazy" src={artifact.download_url!} alt={artifact.logical_name} />}
        </div>
      ))}
    </div>
  );
}

export default function HomePage() {
  const projects = useQuery({
    queryKey: ["projects", "dashboard"],
    queryFn: ({ signal }) => api<ProjectDashboard[]>("/projects/dashboard", { signal }),
    refetchInterval: 30_000,
  });
  const activeJobs = useQuery({
    queryKey: ["runs", "dashboard-active"],
    queryFn: async ({ signal }) => {
      const [running, starting] = await Promise.all([
        api<Run[]>("/runs?status=running&limit=1000&include_scheduler_metadata=true", { signal }),
        api<Run[]>("/runs?status=starting&limit=1000&include_scheduler_metadata=true", { signal }),
      ]);
      return [...running, ...starting].sort((left, right) => right.updated_at.localeCompare(left.updated_at));
    },
    refetchInterval: 15_000,
  });
  const uncategorized = useQuery({
    queryKey: ["runs", "dashboard-uncategorized"],
    queryFn: ({ signal }) => api<Run[]>("/runs?uncategorized=true&limit=8", { signal }),
    refetchInterval: 30_000,
  });
  const sortedProjects = useMemo(
    () => [...(projects.data ?? [])].sort((left, right) => right.last_modified_at.localeCompare(left.last_modified_at)),
    [projects.data],
  );
  const jobs = activeJobs.data ?? [];
  const runningCount = jobs.filter((run) => run.effective_status === "running").length;
  const startingCount = jobs.filter((run) => run.effective_status === "starting").length;
  const clusters = new Set(jobs.map((run) => run.scheduler_details.cluster ?? run.host).filter(Boolean)).size;

  return (
    <div className="dashboard-page">
      <header className="dashboard-heading">
        <div><p className="eyebrow">WORKSPACE</p><h1>Dashboard</h1><p>Projects, active simulations, and runs that still need organizing.</p></div>
        <Link className="button" href="/projects">Manage projects</Link>
      </header>
      <div className="dashboard-layout">
        <main className="dashboard-projects">
          <div className="dashboard-section-heading">
            <div><h2>Recent projects</h2><p>Sorted by the latest project or run activity.</p></div>
            <span>{sortedProjects.length} {sortedProjects.length === 1 ? "project" : "projects"}</span>
          </div>
          {projects.isPending ? <div className="dashboard-state"><span className="spinner" />Loading projects…</div> : projects.isError ? <div className="dashboard-state error-text">Projects could not be loaded.</div> : sortedProjects.length ? <div className="dashboard-project-grid">
            {sortedProjects.map((project) => (
              <Link
                className="dashboard-project-tile"
                href={`/projects/${encodeURIComponent(project.slug)}`}
                key={project.id}
                style={{ "--project-accent": projectHue(project) } as CSSProperties}
              >
                <div className="dashboard-project-top">
                  <span className="dashboard-project-mark">{projectInitials(project.name)}</span>
                  <span className="dashboard-visibility">{project.visibility}</span>
                </div>
                <div className="dashboard-project-copy"><h3>{project.name}</h3></div>
                <ProjectPreviews project={project} />
                <div className="dashboard-project-stats">
                  <span><strong>{project.run_count}</strong>{project.run_count === 1 ? "run" : "runs"}</span>
                  {project.active_run_count > 0 && <span className="dashboard-project-active"><i />{project.active_run_count} active</span>}
                  <small title={new Date(project.last_modified_at).toLocaleString()}>Updated {relativeAge(project.last_modified_at)}</small>
                </div>
              </Link>
            ))}
          </div> : <div className="dashboard-project-empty"><span>⌁</span><h2>No projects yet</h2><p>Create a project to group related simulations and results.</p><Link className="button button-primary" href="/projects">Create a project</Link></div>}
        </main>
        <aside className="dashboard-side">
          <section className="panel dashboard-jobs-panel">
            <div className="dashboard-panel-heading"><div><p className="eyebrow">LIVE</p><h2>Running jobs</h2></div><Link href="/jobs">Open jobs ↗</Link></div>
            {activeJobs.isPending ? <div className="dashboard-side-state"><span className="spinner" />Checking jobs…</div> : activeJobs.isError ? <div className="dashboard-side-state error-text">Jobs unavailable.</div> : <>
              <div className="dashboard-job-summary">
                <div><strong>{jobs.length}</strong><span>active</span></div>
                <div><strong>{runningCount}</strong><span>running</span></div>
                <div><strong>{startingCount}</strong><span>starting</span></div>
                <div><strong>{clusters}</strong><span>{clusters === 1 ? "site" : "sites"}</span></div>
              </div>
              {jobs.length ? <div className="dashboard-job-list">{jobs.slice(0, 6).map((run) => (
                <Link href={`/runs/${run.id}`} key={run.id}>
                  <StatusPill status={run.effective_status} />
                  <span><strong>{run.scheduler_details.job_name ?? run.name}</strong><small>{run.scheduler_details.cluster ?? run.host ?? "Unknown host"}{run.scheduler_job_id ? ` · ${run.scheduler_job_id.replace("SLURM_JOB_ID=", "")}` : ""}</small></span>
                  <i>{run.progress == null ? "—" : `${run.progress}%`}</i>
                </Link>
              ))}</div> : <div className="dashboard-side-empty"><span>✓</span>No simulations are running.</div>}
            </>}
          </section>
          <section className="panel dashboard-uncategorized-panel">
            <div className="dashboard-panel-heading"><div><p className="eyebrow">INBOX</p><h2>Uncategorized runs</h2></div><Link href="/runs">Open runs ↗</Link></div>
            {uncategorized.isPending ? <div className="dashboard-side-state"><span className="spinner" />Loading runs…</div> : uncategorized.isError ? <div className="dashboard-side-state error-text">Runs unavailable.</div> : uncategorized.data?.length ? <div className="dashboard-run-list">{uncategorized.data.map((run) => (
              <Link href={`/runs/${run.id}`} key={run.id}>
                <span className="dashboard-run-preview"><ArtifactStack run={run} /></span>
                <span><strong>{run.name}</strong><small><StatusPill status={run.effective_status} />Updated {relativeAge(run.updated_at)}</small></span>
              </Link>
            ))}</div> : <div className="dashboard-side-empty"><span>✓</span>Every run is in a project.</div>}
          </section>
        </aside>
      </div>
    </div>
  );
}
