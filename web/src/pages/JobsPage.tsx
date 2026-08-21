import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "wouter";
import { api } from "../api";
import CopyButton from "../components/CopyButton";
import PathTail from "../components/PathTail";
import StatusPill from "../components/StatusPill";
import { alamoOutputDirectory, slurmGpuCount, slurmJobId } from "../slurm";
import type { Run, RunDetail } from "../types";

const ACTIVE_STATUSES = new Set(["starting", "running"]);

function timestamp(value: string | null) {
  if (!value) return "Not reported";
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
    second: "2-digit",
  }).format(new Date(value));
}

function duration(start: string | null, end: string | null, now: number) {
  if (!start) return "Unknown runtime";
  let seconds = Math.max(0, Math.floor(((end ? new Date(end).getTime() : now) - new Date(start).getTime()) / 1000));
  const days = Math.floor(seconds / 86_400);
  seconds %= 86_400;
  const hours = Math.floor(seconds / 3_600);
  seconds %= 3_600;
  const minutes = Math.floor(seconds / 60);
  seconds %= 60;
  if (days) return `${days}d ${hours}h ${minutes}m`;
  if (hours) return `${hours}h ${minutes}m ${seconds}s`;
  if (minutes) return `${minutes}m ${seconds}s`;
  return `${seconds}s`;
}

function ResourceCounts({ run }: { run: Run }) {
  const details = run.scheduler_details;
  const nodes = details.node_count ?? "—";
  const tasks = details.task_count ?? "—";
  const gpus = slurmGpuCount(run) ?? "—";
  return (
    <div className="job-resource-counts">
      <span aria-label={`${nodes} ${nodes === "1" ? "node" : "nodes"}`}><b>{nodes}</b> {nodes === "1" ? "node" : "nodes"}</span>
      <span aria-label={`${tasks} ${tasks === "1" ? "task" : "tasks"}`}><b>{tasks}</b> {tasks === "1" ? "task" : "tasks"}</span>
      <span aria-label={`${gpus} GPUs`}><b>{gpus}</b> GPUs</span>
    </div>
  );
}

function JobRow({ run, now, isNew = false }: { run: Run; now: number; isNew?: boolean }) {
  const [stdoutOpen, setStdoutOpen] = useState(false);
  const details = run.scheduler_details;
  const active = ACTIVE_STATUSES.has(run.effective_status);
  const start = run.started_at ?? run.created_at;
  const end = active ? null : (run.ended_at ?? run.updated_at);
  const output = alamoOutputDirectory(run);
  const detail = useQuery({
    queryKey: ["run", run.id],
    queryFn: () => api<RunDetail>(`/runs/${run.id}`),
    enabled: stdoutOpen,
    refetchInterval: stdoutOpen && active ? 5_000 : false,
  });
  const stdoutLabel = `${stdoutOpen ? "Hide" : "Show"} stdout for ${details.job_name ?? run.name}`;
  return (
    <article className="job-record" data-new={isNew}>
      <div className="job-row">
        <div className="job-identity">
          <div className="job-state-line"><StatusPill status={run.effective_status} /><Link href={`/runs/${run.id}`}>{run.name}</Link></div>
          <small>{run.host ?? details.cluster ?? "—"}</small>
        </div>
        <div className="job-slurm">
          <strong title={details.job_name ?? run.name}>{details.job_name ?? run.name}</strong>
          <small><code>{slurmJobId(run) ?? "—"}</code><span>·</span>{details.partition ?? "—"}{details.qos ? ` · ${details.qos}` : ""}</small>
        </div>
        <div className="job-allocation">
          <ResourceCounts run={run} />
          <small title={details.node_list}>{details.node_list ?? run.host ?? "Node list unavailable"}</small>
          {details.constraints && <small>Constraint: {details.constraints}</small>}
        </div>
        <div className="job-timing">
          <strong>{active ? duration(start, null, now) : `Ran ${duration(start, end, now)}`}</strong>
          <small>{active ? `Started ${timestamp(start)}` : `Stopped ${timestamp(end)}`}</small>
        </div>
        <div className="job-output">
          <div className="job-output-line">
            <code>{output ? <PathTail value={output} /> : "Output path unavailable"}</code>
            {output && <CopyButton compact value={output} label="output directory" />}
            <button type="button" aria-expanded={stdoutOpen} aria-label={stdoutLabel} onClick={() => setStdoutOpen((open) => !open)}><span>▤</span> stdout</button>
          </div>
        </div>
      </div>
      {stdoutOpen && (
        <section className="job-stdout" aria-live="polite">
          <div><strong>Live stdout</strong>{detail.data?.output && <small>Updated {timestamp(detail.data.output.updated_at)}</small>}<Link href={`/runs/${run.id}`}>Open full run →</Link></div>
          {detail.isPending && <p>Loading current stdout…</p>}
          {detail.isError && <p>Current stdout could not be loaded.</p>}
          {detail.data && (detail.data.output ? <><pre>{detail.data.output.stdout || "No output has been written yet."}</pre>{detail.data.output.stdout_truncated && <small>Showing the most recent 1 MB.</small>}</> : <p>No stdout has been posted for this run yet.</p>)}
        </section>
      )}
    </article>
  );
}

function JobTable({ jobs, now, newJobIds }: { jobs: Run[]; now: number; newJobIds?: Set<string> }) {
  return (
    <>
      <div className="job-column-head"><span>Run</span><span>SLURM job</span><span>Resources</span><span>Runtime</span><span>Output / log</span></div>
      <div className="job-list">
        {jobs.map((run) => <JobRow key={run.id} run={run} now={now} isNew={newJobIds?.has(run.id)} />)}
      </div>
    </>
  );
}

export default function JobsPage() {
  const [now, setNow] = useState(Date.now());
  const [newJobIds, setNewJobIds] = useState<Set<string>>(new Set());
  const knownActiveIds = useRef<Set<string> | null>(null);
  const runs = useQuery({
    queryKey: ["runs", "slurm-jobs"],
    queryFn: () => api<Run[]>("/runs?limit=1000&include_scheduler_metadata=true"),
    refetchInterval: 5_000,
  });
  const jobs = useMemo(
    () => (runs.data ?? [])
      .filter((run) => run.scheduler_system === "slurm" || run.scheduler_job_id?.startsWith("SLURM_JOB_ID="))
      .sort((left, right) => new Date(right.started_at ?? right.created_at).getTime() - new Date(left.started_at ?? left.created_at).getTime()),
    [runs.data],
  );
  const activeJobs = useMemo(() => jobs.filter((run) => ACTIVE_STATUSES.has(run.effective_status)), [jobs]);
  const stoppedJobs = useMemo(
    () => jobs.filter((run) => !ACTIVE_STATUSES.has(run.effective_status)).slice(0, 20),
    [jobs],
  );
  const activeClusters = useMemo(() => {
    const grouped = new Map<string, Run[]>();
    activeJobs.forEach((run) => {
      const cluster = run.scheduler_details.cluster?.trim() || "Unknown cluster";
      grouped.set(cluster, [...(grouped.get(cluster) ?? []), run]);
    });
    return [...grouped.entries()];
  }, [activeJobs]);
  const activeKey = activeJobs.map((run) => run.id).join(",");

  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1_000);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    const current = new Set(activeKey ? activeKey.split(",") : []);
    if (knownActiveIds.current === null) {
      knownActiveIds.current = current;
      return;
    }
    const arrivals = new Set([...current].filter((id) => !knownActiveIds.current?.has(id)));
    knownActiveIds.current = current;
    if (!arrivals.size) return;
    setNewJobIds(arrivals);
    const timer = window.setTimeout(() => setNewJobIds(new Set()), 1_100);
    return () => window.clearTimeout(timer);
  }, [activeKey]);

  const runningCount = activeJobs.filter((run) => run.effective_status === "running").length;
  const startingCount = activeJobs.filter((run) => run.effective_status === "starting").length;
  const unreachableCount = jobs.filter((run) => run.effective_status === "unreachable").length;

  if (runs.isPending) return <div className="center-state"><span className="spinner" />Opening SLURM monitor…</div>;
  if (runs.isError) return <div className="error-panel">The SLURM job monitor could not be loaded.</div>;

  return (
    <div className="jobs-page">
      <header className="page-header jobs-header">
        <h1>Running jobs</h1>
        <div className="jobs-live" data-refreshing={runs.isFetching}><i /><span>Live · 5 second refresh</span></div>
      </header>

      <section className="jobs-summary" aria-label="SLURM job summary">
        <div><strong>{runningCount}</strong><span>Running</span></div>
        <div><strong>{startingCount}</strong><span>Starting</span></div>
        <div data-attention={unreachableCount > 0}><strong>{unreachableCount}</strong><span>Unreachable</span></div>
        <div><strong>{stoppedJobs.length}</strong><span>Recent stops</span></div>
      </section>

      {activeClusters.map(([cluster, clusterJobs]) => (
        <section className="job-section" aria-live="polite" key={cluster}>
          <div className="job-section-heading"><h2>On {cluster} now</h2><span>{clusterJobs.length} {clusterJobs.length === 1 ? "job" : "jobs"}</span></div>
          <JobTable jobs={clusterJobs} now={now} newJobIds={newJobIds} />
        </section>
      ))}

      {!activeJobs.length && (
        <section className="job-section" aria-live="polite">
          <div className="job-section-heading"><h2>Active</h2><span>0 jobs</span></div>
          <div className="jobs-empty"><strong>No active SLURM jobs</strong></div>
        </section>
      )}

      <section className="job-section recent-jobs">
        <div className="job-section-heading"><h2>Recent stops</h2><span>{stoppedJobs.length} jobs</span></div>
        {stoppedJobs.length ? <JobTable jobs={stoppedJobs} now={now} /> : <div className="jobs-empty"><span>None</span></div>}
      </section>
    </div>
  );
}
