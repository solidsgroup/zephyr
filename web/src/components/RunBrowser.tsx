import { useEffect, useMemo, useRef, useState, type CSSProperties, type MouseEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useLocation } from "wouter";
import { api } from "../api";
import { isVideoContentType, isVisualContentType } from "../artifacts";
import { selectionRange, useShiftPressed } from "../selection";
import type { Project, ProjectFolder, ProjectLayout, Run, RunFacets } from "../types";
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

function folderOptions(folders: ProjectFolder[]) {
  const children = new Map<string, ProjectFolder[]>();
  for (const folder of folders) {
    const key = folder.parent_id ?? "";
    children.set(key, [...(children.get(key) ?? []), folder]);
  }
  for (const values of children.values()) values.sort((a, b) => a.position - b.position || a.name.localeCompare(b.name));
  const options: Array<{ id: string; label: string }> = [];
  const visit = (parentId: string, depth: number) => {
    for (const folder of children.get(parentId) ?? []) {
      options.push({ id: folder.id, label: `${"　".repeat(depth)}${depth ? "↳ " : ""}${folder.name}` });
      visit(folder.id, depth + 1);
    }
  };
  visit("", 0);
  return options;
}

function projectSlug(value: string) {
  return value
    .toLocaleLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 100);
}

function mutationError(error: unknown, fallback: string) {
  return error instanceof Error && error.message ? error.message : fallback;
}

function selectedRunsFromLocation() {
  if (window.location.pathname === "/runs/compare") {
    return Object.fromEntries((new URLSearchParams(window.location.search).get("ids") ?? "").split(",").filter(Boolean).map((id) => [id, true]));
  }
  const match = window.location.pathname.match(/^\/runs\/([^/]+)$/);
  return match ? { [decodeURIComponent(match[1])]: true } : {};
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
  const [uncategorized, setUncategorized] = useState(false);
  const [selected, setSelected] = useState<Record<string, boolean>>(selectedRunsFromLocation);
  const selectionAnchor = useRef<string | null>(null);
  const shiftPressed = useShiftPressed();
  const [hoveredRunId, setHoveredRunId] = useState<string | null>(null);
  const [showProjectPicker, setShowProjectPicker] = useState(false);
  const [projectId, setProjectId] = useState("");
  const [projectFolderId, setProjectFolderId] = useState("");
  const [projectNotice, setProjectNotice] = useState("");
  const [showCreateProject, setShowCreateProject] = useState(false);
  const [newProjectName, setNewProjectName] = useState("");
  const [newProjectSlug, setNewProjectSlug] = useState("");
  const [newProjectVisibility, setNewProjectVisibility] = useState<Project["visibility"]>("private");
  const [showCreateFolder, setShowCreateFolder] = useState(false);
  const [newFolderName, setNewFolderName] = useState("");
  const [newFolderParentId, setNewFolderParentId] = useState("");
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
    if (uncategorized) query.set("uncategorized", "true");
    const suffix = query.toString();
    return `/runs${suffix ? `?${suffix}` : ""}`;
  }, [searchQuery, site, status, thumbnail, uncategorized]);
  const runs = useQuery({
    queryKey: ["runs", "browser", searchQuery, status, site, thumbnail, uncategorized],
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
  const selectedIds = useMemo(() => Object.keys(selected).filter((id) => selected[id]), [selected]);
  useEffect(() => {
    const match = location.match(/^\/runs\/([^/]+)$/);
    if (!match || match[1] === "compare") return;
    const runId = decodeURIComponent(match[1]);
    setSelected((current) => {
      const currentIds = Object.keys(current).filter((id) => current[id]);
      return currentIds.length === 1 && currentIds[0] === runId ? current : { [runId]: true };
    });
  }, [location]);
  useEffect(() => {
    if (selectedIds.length >= 2) {
      const target = `/runs/compare?ids=${selectedIds.map(encodeURIComponent).join(",")}`;
      const current = `${location}${window.location.search}`;
      if (current !== target) navigate(target, { replace: location === "/runs/compare" });
    } else if (location === "/runs/compare") {
      navigate(selectedIds.length === 1 ? `/runs/${selectedIds[0]}` : "/", { replace: true });
    }
  }, [location, navigate, selectedIds]);
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
    enabled: selectedIds.length >= 1 && showProjectPicker,
  });
  const projectLayout = useQuery({
    queryKey: ["project-layout", projectId],
    queryFn: ({ signal }) => api<ProjectLayout>(`/projects/${projectId}/layout`, { signal }),
    enabled: showProjectPicker && Boolean(projectId),
  });
  const destinationFolders = useMemo(() => folderOptions(projectLayout.data?.folders ?? []), [projectLayout.data?.folders]);
  const createProject = useMutation({
    mutationFn: () => api<Project>("/projects", {
      method: "POST",
      body: JSON.stringify({ name: newProjectName.trim(), slug: newProjectSlug, visibility: newProjectVisibility }),
    }),
    onSuccess: (project) => {
      queryClient.setQueryData<Project[]>(["projects", "editable"], (current) => {
        if (current?.some((item) => item.id === project.id)) return current;
        return [...(current ?? []), project].sort((left, right) => left.name.localeCompare(right.name));
      });
      setProjectId(project.id);
      setProjectFolderId("");
      setShowCreateProject(false);
      setNewProjectName("");
      setNewProjectSlug("");
      setNewProjectVisibility("private");
      queryClient.invalidateQueries({ queryKey: ["projects"] });
    },
  });
  const createFolder = useMutation({
    mutationFn: () => api<ProjectFolder>(`/projects/${projectId}/folders`, {
      method: "POST",
      body: JSON.stringify({ name: newFolderName.trim(), parent_id: newFolderParentId || null }),
    }),
    onSuccess: (folder) => {
      queryClient.setQueryData<ProjectLayout>(["project-layout", projectId], (current) => ({
        folders: [...(current?.folders ?? []), folder],
        runs: current?.runs ?? [],
      }));
      setProjectFolderId(folder.id);
      setShowCreateFolder(false);
      setNewFolderName("");
      setNewFolderParentId("");
      queryClient.invalidateQueries({ queryKey: ["project-layout", projectId] });
    },
  });
  const addToProject = useMutation({
    mutationFn: () => api<{ added: number; already_present: number }>(`/projects/${projectId}/runs/batch`, {
      method: "POST",
      body: JSON.stringify({ run_ids: selectedIds, folder_id: projectFolderId || null }),
    }),
    onSuccess: (result) => {
      const project = projects.data?.find((item) => item.id === projectId);
      const existing = result.already_present ? `; ${result.already_present} already there` : "";
      setProjectNotice(`Added ${result.added} to ${project?.name ?? "project"}${existing}`);
      setShowProjectPicker(false);
      setProjectFolderId("");
      setShowCreateProject(false);
      setShowCreateFolder(false);
      queryClient.invalidateQueries({ queryKey: ["project-layout", projectId] });
      queryClient.invalidateQueries({ queryKey: ["runs", "browser"] });
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
        <button className="run-category-filter" aria-pressed={uncategorized} onClick={() => setUncategorized((value) => !value)}>
          <span aria-hidden="true">⌁</span>
          <strong>Uncategorized only</strong>
          <small>Not in any project</small>
        </button>
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
        {showProjectPicker && selectedIds.length >= 1 && <div className="run-project-picker" role="dialog" aria-label="Add selected runs to project">
          <header>
            <span aria-hidden="true">＋</span>
            <div><strong>Add to project</strong><small>{selectedIds.length} {selectedIds.length === 1 ? "run" : "runs"} selected</small></div>
            <button aria-label="Close project picker" onClick={() => setShowProjectPicker(false)}>×</button>
          </header>
          {projects.isPending ? <div className="run-project-picker-state"><span className="spinner" />Loading projects…</div> : projects.isError ? <div className="run-project-picker-state error-text">Could not load projects.</div> : <>
            <div className="run-project-field">
              <div><span>Project</span><button onClick={() => { setShowCreateProject((value) => !value); setShowCreateFolder(false); createProject.reset(); }}>＋ New project</button></div>
              <select value={projectId} onChange={(event) => { setProjectId(event.target.value); setProjectFolderId(""); setShowCreateFolder(false); setNewFolderParentId(""); addToProject.reset(); createFolder.reset(); }} aria-label="Choose project">
                <option value="">Choose project…</option>
                {projects.data?.map((project) => <option value={project.id} key={project.id}>{project.name}</option>)}
              </select>
            </div>
            {showCreateProject && <div className="run-project-create">
              <strong>New project</strong>
              <label><span>Name</span><input autoFocus value={newProjectName} onChange={(event) => { const name = event.target.value; setNewProjectName(name); setNewProjectSlug(projectSlug(name)); }} aria-label="New project name" placeholder="Parameter study" /></label>
              <label><span>URL slug</span><input value={newProjectSlug} onChange={(event) => setNewProjectSlug(projectSlug(event.target.value))} aria-label="New project slug" placeholder="parameter-study" /></label>
              <label><span>Visibility</span><select value={newProjectVisibility} onChange={(event) => setNewProjectVisibility(event.target.value as Project["visibility"])} aria-label="New project visibility"><option value="private">Private</option><option value="group">Group</option><option value="public">Public</option></select></label>
              {createProject.isError && <p className="error-text">{mutationError(createProject.error, "Could not create this project.")}</p>}
              <div><button className="button" onClick={() => setShowCreateProject(false)}>Cancel</button><button className="button button-primary" disabled={!newProjectName.trim() || newProjectSlug.length < 3 || createProject.isPending} onClick={() => createProject.mutate()}>{createProject.isPending ? "Creating…" : "Create project"}</button></div>
            </div>}
            {!projects.data?.length && !showCreateProject && <p>No editable projects yet. Create one here to organize these runs.</p>}
            <div className="run-project-field">
              <div><span>Destination</span><button disabled={!projectId || projectLayout.isPending || projectLayout.isError} onClick={() => { setShowCreateFolder((value) => !value); setShowCreateProject(false); setNewFolderParentId(projectFolderId); createFolder.reset(); }}>＋ New folder</button></div>
              <select value={projectFolderId} onChange={(event) => setProjectFolderId(event.target.value)} aria-label="Choose project folder" disabled={!projectId || projectLayout.isPending || projectLayout.isError}>
                <option value="">{projectId && projectLayout.isPending ? "Loading folders…" : "Project root"}</option>
                {destinationFolders.map((folder) => <option value={folder.id} key={folder.id}>{folder.label}</option>)}
              </select>
            </div>
            {showCreateFolder && projectId && <div className="run-project-create">
              <strong>New folder</strong>
              <label><span>Name</span><input autoFocus value={newFolderName} onChange={(event) => setNewFolderName(event.target.value)} aria-label="New folder name" placeholder="Cases" /></label>
              <label><span>Inside</span><select value={newFolderParentId} onChange={(event) => setNewFolderParentId(event.target.value)} aria-label="New folder parent"><option value="">Project root</option>{destinationFolders.map((folder) => <option value={folder.id} key={folder.id}>{folder.label}</option>)}</select></label>
              {createFolder.isError && <p className="error-text">{mutationError(createFolder.error, "Could not create this folder.")}</p>}
              <div><button className="button" onClick={() => setShowCreateFolder(false)}>Cancel</button><button className="button button-primary" disabled={!newFolderName.trim() || createFolder.isPending} onClick={() => createFolder.mutate()}>{createFolder.isPending ? "Creating…" : "Create folder"}</button></div>
            </div>}
            {projectId && !projectLayout.isPending && !projectLayout.isError && !destinationFolders.length && <p>This project has no folders yet. Runs will be added at the root.</p>}
            {projectLayout.isError && <p className="error-text">Could not load this project’s folders.</p>}
            {addToProject.isError && <p className="error-text">Could not add the selected {selectedIds.length === 1 ? "run" : "runs"}.</p>}
            <div className="run-project-picker-actions">
              <button className="button" onClick={() => setShowProjectPicker(false)}>Cancel</button>
              <button className="button button-primary" disabled={!projectId || projectLayout.isPending || projectLayout.isError || createProject.isPending || createFolder.isPending || addToProject.isPending} onClick={() => addToProject.mutate()}>{addToProject.isPending ? "Adding…" : `Add ${selectedIds.length === 1 ? "run" : `${selectedIds.length} runs`}`}</button>
            </div>
          </>}
        </div>}
        {projectNotice && <span className="run-project-notice">{projectNotice}</span>}
        {selectedIds.length >= 1 ? <>
          <div className="run-selection-actions" data-single={selectedIds.length === 1 || undefined}>
            <button className="button" aria-expanded={showProjectPicker} onClick={() => { setShowProjectPicker((value) => !value); setProjectNotice(""); addToProject.reset(); }}><span aria-hidden="true">＋</span> Add to project</button>
            {selectedIds.length >= 2 && <button className="button button-primary" onClick={() => navigate(`/compare?ids=${selectedIds.join(",")}`)}>Compare {selectedIds.length}</button>}
          </div>
        </> :
          <span>Shift-click a range · Ctrl/Cmd-click individual runs</span>}
      </footer>
    </aside>
  );
}
