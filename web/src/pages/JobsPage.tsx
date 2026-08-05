import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "wouter";
import { api } from "../api";
import StatusPill from "../components/StatusPill";
import type { Run } from "../types";

const ACTIVE_STATUSES = new Set(["starting", "running", "unreachable"]);

function jobId(run: Run) {
  const raw = run.scheduler_job_id ?? "";
  const id = raw.replace(/^SLURM_JOB_ID=/, "") || "Unknown";
  const task = run.scheduler_details.array_task_id;
  return task ? `${id}_${task}` : id;
}

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

function allocation(run: Run) {
  const details = run.scheduler_details;
  const parts: string[] = [];
  if (details.node_count) parts.push(`${details.node_count} node${details.node_count === "1" ? "" : "s"}`);
  if (details.task_count) parts.push(`${details.task_count} tasks`);
  if (details.cpus_per_task) parts.push(`${details.cpus_per_task} CPU/task`);
  else if (details.cpus_on_node) parts.push(`${details.cpus_on_node} CPU/node`);
  if (details.gpus_on_node) parts.push(`${details.gpus_on_node} GPU/node`);
  else if (details.gpus) parts.push(`${details.gpus} GPUs`);
  return parts.length ? parts.join(" · ") : "Allocation details unavailable";
}

function JobRow({ run, now, isNew = false }: { run: Run; now: number; isNew?: boolean }) {
  const details = run.scheduler_details;
  const active = ACTIVE_STATUSES.has(run.effective_status);
  const start = run.started_at ?? run.created_at;
  const end = active ? null : (run.ended_at ?? run.updated_at);
  const output = run.output_path ?? details.submit_directory;
  return (
    <Link className="job-row" data-new={isNew} href={`/runs/${run.id}`}>
      <div className="job-identity">
        <div className="job-state-line"><StatusPill status={run.effective_status} /><strong>{run.name}</strong></div>
        <small>{details.job_name && details.job_name !== run.name ? details.job_name : run.host ?? "Unknown host"}</small>
      </div>
      <div className="job-slurm">
        <code>{jobId(run)}</code>
        <small>{details.partition ?? "Unknown partition"}{details.qos ? ` · ${details.qos}` : ""}</small>
      </div>
      <div className="job-allocation">
        <strong title={details.node_list}>{details.node_list ?? run.host ?? "Nodes unavailable"}</strong>
        <small>{allocation(run)}</small>
        {details.constraints && <small>Constraint: {details.constraints}</small>}
      </div>
      <div className="job-timing">
        <strong>{active ? duration(start, null, now) : `Ran ${duration(start, end, now)}`}</strong>
        <small>{active ? `Started ${timestamp(start)}` : `Stopped ${timestamp(end)}`}</small>
      </div>
      <div className="job-output">
        <code title={output}>{output ?? "Output path unavailable"}</code>
        <small>{details.submit_directory && output !== details.submit_directory ? `Submitted from ${details.submit_directory}` : "ALAMO output directory"}</small>
      </div>
    </Link>
  );
}

export default function JobsPage() {
  const [now, setNow] = useState(Date.now());
  const [newJobIds, setNewJobIds] = useState<Set<string>>(new Set());
  const knownActiveIds = useRef<Set<string> | null>(null);
  const runs = useQuery({
    queryKey: ["runs", "slurm-jobs"],
    queryFn: () => api<Run[]>("/runs?limit=1000"),
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
  const unreachableCount = activeJobs.filter((run) => run.effective_status === "unreachable").length;

  if (runs.isPending) return <div className="center-state"><span className="spinner" />Opening SLURM monitor…</div>;
  if (runs.isError) return <div className="error-panel">The SLURM job monitor could not be loaded.</div>;

  return (
    <div className="jobs-page">
      <header className="page-header jobs-header">
        <div><p className="eyebrow">SLURM MONITOR</p><h1>Running jobs</h1><p>Live allocation, runtime, and output locations for posted ALAMO jobs.</p></div>
        <div className="jobs-live" data-refreshing={runs.isFetching}><i /><span>Live · 5 second refresh</span></div>
      </header>

      <section className="jobs-summary" aria-label="SLURM job summary">
        <div><strong>{runningCount}</strong><span>Running</span></div>
        <div><strong>{startingCount}</strong><span>Starting</span></div>
        <div data-attention={unreachableCount > 0}><strong>{unreachableCount}</strong><span>Unreachable</span></div>
        <div><strong>{stoppedJobs.length}</strong><span>Recent stops</span></div>
      </section>

      <section className="job-section" aria-live="polite">
        <div className="job-section-heading"><div><p className="eyebrow">ACTIVE ALLOCATIONS</p><h2>On the cluster now</h2></div><span>{activeJobs.length} jobs</span></div>
        <div className="job-column-head"><span>Run</span><span>SLURM</span><span>Allocation</span><span>Timing</span><span>Output</span></div>
        <div className="job-list">
          {activeJobs.map((run) => <JobRow key={run.id} run={run} now={now} isNew={newJobIds.has(run.id)} />)}
          {!activeJobs.length && <div className="jobs-empty"><strong>No active SLURM jobs</strong><span>New jobs posted with <code>--post</code> will appear here within five seconds.</span></div>}
        </div>
      </section>

      <section className="job-section recent-jobs">
        <div className="job-section-heading"><div><p className="eyebrow">RECENT STOPS</p><h2>Finished and interrupted jobs</h2></div><span>Latest {stoppedJobs.length}</span></div>
        <div className="job-column-head"><span>Run</span><span>SLURM</span><span>Allocation</span><span>Timing</span><span>Output</span></div>
        <div className="job-list">
          {stoppedJobs.map((run) => <JobRow key={run.id} run={run} now={now} />)}
          {!stoppedJobs.length && <div className="jobs-empty"><span>No stopped SLURM jobs have been recorded yet.</span></div>}
        </div>
      </section>
    </div>
  );
}
