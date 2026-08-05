import type { Run } from "./types";

export function slurmJobId(run: Run) {
  const raw = run.scheduler_job_id?.replace(/^SLURM_JOB_ID=/, "");
  if (!raw) return null;
  const task = run.scheduler_details.array_task_id;
  return task ? `${raw}_${task}` : raw;
}

function resourceNumber(raw: string | undefined) {
  if (!raw) return null;
  if (/^\d+$/.test(raw)) return Number(raw);
  const parts = raw.split(",");
  if (parts.every((part) => /^\d+$/.test(part))) return parts.length;
  const counts = parts.map((part) => part.match(/(?:^|:)(\d+)$/)?.[1]);
  if (counts.some((count) => count == null)) return null;
  return counts.reduce((sum, count) => sum + Number(count), 0);
}

export function slurmGpuCount(run: Run) {
  const details = run.scheduler_details;
  const total = resourceNumber(details.gpus ?? details.job_gpu_ids);
  if (total != null) return String(total);
  const perNode = resourceNumber(details.gpus_per_node ?? details.gpus_on_node);
  return perNode == null ? null : `${perNode}/node`;
}

export function alamoOutputDirectory(run: Run) {
  if (run.output_path) return run.output_path;
  const details = run.scheduler_details;
  const submit = details.submit_directory?.replace(/\/+$/, "");
  const plotFile = details.plot_file?.replace(/^['"]|['"]$/g, "");
  if (plotFile?.startsWith("/")) return plotFile;
  if (submit && plotFile && plotFile !== ".") return `${submit}/${plotFile.replace(/^\.\//, "")}`;
  if (submit && plotFile === ".") return submit;
  return submit ?? null;
}

export function formatSlurmMemory(raw: string | undefined) {
  if (!raw) return null;
  const megabytes = Number(raw);
  if (!Number.isFinite(megabytes)) return raw;
  if (megabytes >= 1024 && megabytes % 1024 === 0) return `${megabytes / 1024} GiB`;
  return `${megabytes.toLocaleString()} MiB`;
}
