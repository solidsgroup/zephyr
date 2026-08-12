import { useEffect, useMemo, useRef, useState, type CSSProperties, type MouseEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useLocation } from "wouter";
import { api } from "../api";
import { isVideoContentType, isVisualContentType } from "../artifacts";
import { selectionRange, useShiftPressed } from "../selection";
import type { Project, Run, RunFacets } from "../types";
import LazyVideo from "./LazyVideo";
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
          {artifact.download_url && isVideoContentType(artifact.content_type) && artifact.id === run.thumbnail_artifact_id
            ? <LazyVideo src={artifact.download_url} label={artifact.logical_name} />
            : artifact.download_url && isVideoContentType(artifact.content_type)
              ? <span>▶</span>
            : artifact.download_url && isVisualContentType(artifact.content_type)
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
  const queryClient = useQueryClient();
  const [search, setSearch] = useState("");
  const [searchQuery, setSearchQuery] = useState("");
  const [status, setStatus] = useState("");
  const [site, setSite] = useState("");
  const [thumbnail, setThumbnail] = useState("");
  const [selected, setSelected] = useState<Record<string, boolean>>({});
  const selectionAnchor = useRef<string | null>(null);
  const shiftPressed = useShiftPressed();
  const [hoveredRunId, setHoveredRunId] = useState<string | null>(null);
  const [showProjectPicker, setShowProjectPicker] = useState(false);
  const [projectId, setProjectId] = useState("");
  const [projectNotice, setProjectNotice] = useState("");
  useEffect(() => {
    const timer = window.setTimeout(() => {
      const value = search.trim();
      setSearchQuery(value.length >= 2 ? value : "");
    }, 400);
    return () => window.clearTimeout(timer);
  }, [search]);
  const runsPath = useMemo(() => {
    const query = new URLSearchParams();
    if (searchQuery) query.set("search", searchQuery);
    if (status) query.set("status", status);
    if (site) query.set("site", site);
    if (thumbnail) query.set("has_thumbnail", thumbnail);
    const suffix = query.toString();
    return `/runs${suffix ? `?${suffix}` : ""}`;
  }, [searchQuery, site, status, thumbnail]);
  const runs = useQuery({
    queryKey: ["runs", "browser", searchQuery, status, site, thumbnail],
    queryFn: ({ signal }) => api<Run[]>(runsPath, { signal }),
    refetchInterval: 15_000,
    placeholderData: (previous) => previous,
  });
  const facets = useQuery({
    queryKey: ["runs", "facets"],
    queryFn: ({ signal }) => api<RunFacets>("/runs/facets", { signal }),
    refetchInterval: 60_000,
  });
  const data = useMemo(() => runs.data ?? [], [runs.data]);
  const sites = facets.data?.sites ?? [];
  const selectedIds = data.filter((run) => selected[run.id]).map((run) => run.id);
  const rangeAnchorId = selectionAnchor.current && selected[selectionAnchor.current]
    ? selectionAnchor.current
    : selectedIds.at(-1) ?? null;
  const rangePreviewIds = useMemo(
    () => shiftPressed ? selectionRange(data.map((run) => run.id), rangeAnchorId, hoveredRunId) : new Set<string>(),
    [data, hoveredRunId, rangeAnchorId, shiftPressed],
  );
  const projects = useQuery({
    queryKey: ["projects", "editable"],
    queryFn: () => api<Project[]>("/projects?editable=true"),
    enabled: selectedIds.length >= 2 && showProjectPicker,
  });
  const addToProject = useMutation({
    mutationFn: () => api<{ added: number; already_present: number }>(`/projects/${projectId}/runs/batch`, {
      method: "POST",
      body: JSON.stringify({ run_ids: selectedIds }),
    }),
    onSuccess: (result) => {
      const project = projects.data?.find((item) => item.id === projectId);
      const existing = result.already_present ? `; ${result.already_present} already there` : "";
      setProjectNotice(`Added ${result.added} to ${project?.name ?? "project"}${existing}`);
      setShowProjectPicker(false);
      queryClient.invalidateQueries({ queryKey: ["project-runs", projectId] });
    },
  });

  function chooseRun(event: MouseEvent<HTMLAnchorElement>, run: Run) {
    if (event.shiftKey || event.ctrlKey || event.metaKey) {
      event.preventDefault();
      event.stopPropagation();
    }
    if (event.shiftKey) {
      const range = selectionRange(data.map((item) => item.id), rangeAnchorId ?? run.id, run.id);
      if (range.size) {
        setSelected((current) => {
          const next = event.ctrlKey || event.metaKey ? { ...current } : {};
          for (const id of range) next[id] = true;
          return next;
        });
      }
      return;
    }
    selectionAnchor.current = run.id;
    if (event.ctrlKey || event.metaKey) {
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
          <input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search names, paths, files" aria-label="Search runs" />
        </label>
        <div className="run-filter-row">
          <select value={status} onChange={(event) => setStatus(event.target.value)} aria-label="Filter run status">
            <option value="">Any status</option>
            <option>starting</option>
            <option>running</option>
            <option>completed</option>
            <option>failed</option>
            <option>interrupted</option>
            <option>unreachable</option>
          </select>
          <select value={site} onChange={(event) => setSite(event.target.value)} aria-label="Filter storage site">
            <option value="">Any site</option>
            {sites.map((facet) => <option value={facet.site} key={facet.site}>{facet.site} ({facet.run_count})</option>)}
          </select>
          <select value={thumbnail} onChange={(event) => setThumbnail(event.target.value)} aria-label="Filter thumbnail">
            <option value="">Any preview</option>
            <option value="true">Has thumbnail</option>
            <option value="false">No thumbnail</option>
          </select>
        </div>
      </div>
      <div className="run-browser-list" aria-label="Runs">
        {runs.isPending ? <div className="run-browser-state"><span className="spinner" />Loading runs…</div> :
          runs.isError ? <div className="run-browser-state error-text">Could not load runs.</div> :
          data.map((run) => {
            const active = location === `/runs/${run.id}`;
            const chosen = Boolean(selected[run.id]);
            return (
              <div
                className="run-browser-item"
                data-active={active}
                data-selected={chosen}
                data-range-preview={rangePreviewIds.has(run.id) || undefined}
                key={run.id}
                onMouseEnter={() => setHoveredRunId(run.id)}
                onMouseLeave={() => setHoveredRunId((current) => current === run.id ? null : current)}
              >
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
        {selectedIds.length >= 2 ? <>
          {showProjectPicker && <div className="run-project-picker">
            <strong>Add {selectedIds.length} runs to project</strong>
            {projects.isPending ? <span>Loading projects…</span> : projects.data?.length ? <>
              <select value={projectId} onChange={(event) => setProjectId(event.target.value)} aria-label="Choose project">
                <option value="">Choose project…</option>
                {projects.data.map((project) => <option value={project.id} key={project.id}>{project.name}</option>)}
              </select>
              <button className="button button-primary" disabled={!projectId || addToProject.isPending} onClick={() => addToProject.mutate()}>{addToProject.isPending ? "Adding…" : "Add runs"}</button>
              {addToProject.isError && <span className="error-text">Could not add these runs.</span>}
            </> : <span>No editable projects. <Link href="/projects">Create one</Link></span>}
          </div>}
          {projectNotice && !showProjectPicker && <span className="run-project-notice">{projectNotice}</span>}
          <div className="run-selection-actions">
            <button className="button" aria-expanded={showProjectPicker} onClick={() => { setShowProjectPicker((value) => !value); setProjectNotice(""); }}>Add to project</button>
            <button className="button button-primary" onClick={() => navigate(`/compare?ids=${selectedIds.join(",")}`)}>Compare {selectedIds.length}</button>
          </div>
        </> :
          <span>{selectedIds.length === 1 ? "Shift-click a range or Ctrl/Cmd-click another run" : "Shift-click a range · Ctrl/Cmd-click individual runs"}</span>}
      </footer>
    </aside>
  );
}
