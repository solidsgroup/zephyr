import { useEffect, useMemo, useRef, useState, type CSSProperties, type DragEvent, type MouseEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useLocation } from "wouter";
import { api, currentUser } from "../api";
import { ArtifactStack } from "../components/RunBrowser";
import PathTail from "../components/PathTail";
import StatusPill from "../components/StatusPill";
import { selectionRange, useShiftPressed } from "../selection";
import { RunRecord } from "./RunPage";
import type {
  Project,
  ProjectFolder,
  ProjectLayout,
  ProjectRunPlacement,
  Run,
} from "../types";

interface Member {
  id: string;
  user_id: string;
  email: string;
  name: string;
  role: string;
}

const ROOT = "__project_root__";
const EMPTY_RUN_IDS = new Set<string>();
const COLLAPSED_FOLDERS_KEY = "zephyr:collapsed-project-folders";

function projectPath(project: Project, runId?: string | null) {
  const base = `/projects/${encodeURIComponent(project.slug)}`;
  return runId ? `${base}/runs/${encodeURIComponent(runId)}` : base;
}

function projectSelectionFromLocation(location: string) {
  const match = location.match(/^\/projects\/([^/]+)(?:\/runs\/([^/]+))?\/?$/);
  if (!match) return { projectSlug: null, runId: null };
  try {
    return {
      projectSlug: decodeURIComponent(match[1]),
      runId: match[2] ? decodeURIComponent(match[2]) : null,
    };
  } catch {
    return { projectSlug: null, runId: null };
  }
}

function collapsedFoldersKey(projectId: string) {
  return `${COLLAPSED_FOLDERS_KEY}:${projectId}`;
}

function storedCollapsedFolders(projectId: string) {
  try {
    const value = JSON.parse(window.localStorage.getItem(collapsedFoldersKey(projectId)) ?? "[]");
    return new Set<string>(Array.isArray(value) ? value.filter((id): id is string => typeof id === "string") : []);
  } catch {
    return new Set<string>();
  }
}

function storeCollapsedFolders(projectId: string, collapsed: Set<string>) {
  try {
    window.localStorage.setItem(collapsedFoldersKey(projectId), JSON.stringify([...collapsed]));
  } catch {
    // Folder state is a convenience; keep the project usable if browser storage is unavailable.
  }
}

function parentKey(folderId: string | null) {
  return folderId ?? ROOT;
}

function FolderIcon({ open }: { open: boolean }) {
  return <span className="project-folder-icon" aria-hidden="true">{open ? "▾" : "▸"}<i>{open ? "▰" : "▱"}</i></span>;
}

function ProjectRunRow({
  placement,
  active,
  selected,
  rangePreview,
  canEdit,
  dragging,
  onSelect,
  onDragStart,
  onDragEnd,
  onHover,
}: {
  placement: ProjectRunPlacement;
  active: boolean;
  selected: boolean;
  rangePreview: boolean;
  canEdit: boolean;
  dragging: boolean;
  onSelect: (event: MouseEvent<HTMLButtonElement>) => void;
  onDragStart: (event: DragEvent<HTMLButtonElement>) => void;
  onDragEnd: () => void;
  onHover: (hovered: boolean) => void;
}) {
  const run = placement.run;
  return (
    <button
      className="project-run-row"
      data-active={active}
      data-selected={selected}
      data-range-preview={rangePreview || undefined}
      data-dragging={dragging}
      aria-pressed={selected}
      draggable={canEdit}
      onClick={onSelect}
      onDragStart={onDragStart}
      onDragEnd={onDragEnd}
      onMouseEnter={() => onHover(true)}
      onMouseLeave={() => onHover(false)}
      title={canEdit ? "Drag this run into a folder" : run.name}
    >
      <span className="project-run-grip" aria-hidden="true">⋮⋮</span>
      <span className="project-run-thumb"><ArtifactStack run={run} /></span>
      <span className="project-run-copy">
        <span><StatusPill status={run.effective_status} /><strong>{run.name}</strong></span>
        <small>{run.output_path ? <PathTail value={run.output_path} /> : run.host ?? "No output path"}</small>
      </span>
    </button>
  );
}

function FolderNode({
  folder,
  depth,
  childFolders,
  runsByFolder,
  collapsed,
  activeRunId,
  selectedRunIds,
  rangePreviewRunIds,
  draggedRunIds,
  dropTarget,
  canEdit,
  onToggle,
  onSelectRun,
  onHoverRun,
  onStartRunDrag,
  onEndRunDrag,
  onDragOverFolder,
  onDropRun,
  onNewFolder,
}: {
  folder: ProjectFolder;
  depth: number;
  childFolders: Map<string, ProjectFolder[]>;
  runsByFolder: Map<string, ProjectRunPlacement[]>;
  collapsed: Set<string>;
  activeRunId: string | null;
  selectedRunIds: Set<string>;
  rangePreviewRunIds: Set<string>;
  draggedRunIds: Set<string>;
  dropTarget: string | null;
  canEdit: boolean;
  onToggle: (id: string) => void;
  onSelectRun: (event: MouseEvent<HTMLButtonElement>, id: string) => void;
  onHoverRun: (id: string, hovered: boolean) => void;
  onStartRunDrag: (event: DragEvent<HTMLButtonElement>, id: string) => void;
  onEndRunDrag: () => void;
  onDragOverFolder: (event: DragEvent, id: string) => void;
  onDropRun: (event: DragEvent, id: string) => void;
  onNewFolder: (parentId: string) => void;
}) {
  const isCollapsed = collapsed.has(folder.id);
  const runs = runsByFolder.get(folder.id) ?? [];
  const children = childFolders.get(folder.id) ?? [];
  const descendantCount = runs.length + children.length;
  return (
    <div className="project-folder-node" style={{ "--folder-depth": depth } as CSSProperties}>
      <div
        className="project-folder-row"
        data-drop-target={dropTarget === folder.id}
        onDragOver={(event) => onDragOverFolder(event, folder.id)}
        onDrop={(event) => onDropRun(event, folder.id)}
      >
        <button onClick={() => onToggle(folder.id)} aria-expanded={!isCollapsed}>
          <FolderIcon open={!isCollapsed} />
          <strong>{folder.name}</strong>
          <small>{descendantCount}</small>
        </button>
        {canEdit && <button className="project-folder-add" title={`New folder inside ${folder.name}`} aria-label={`New folder inside ${folder.name}`} onClick={() => onNewFolder(folder.id)}>+</button>}
      </div>
      {!isCollapsed && (
        <div className="project-folder-contents">
          {children.map((child) => (
            <FolderNode
              key={child.id}
              folder={child}
              depth={depth + 1}
              childFolders={childFolders}
              runsByFolder={runsByFolder}
              collapsed={collapsed}
              activeRunId={activeRunId}
              selectedRunIds={selectedRunIds}
              rangePreviewRunIds={rangePreviewRunIds}
              draggedRunIds={draggedRunIds}
              dropTarget={dropTarget}
              canEdit={canEdit}
              onToggle={onToggle}
              onSelectRun={onSelectRun}
              onHoverRun={onHoverRun}
              onStartRunDrag={onStartRunDrag}
              onEndRunDrag={onEndRunDrag}
              onDragOverFolder={onDragOverFolder}
              onDropRun={onDropRun}
              onNewFolder={onNewFolder}
            />
          ))}
          {runs.map((placement) => (
            <ProjectRunRow
              key={placement.run.id}
              placement={placement}
              active={activeRunId === placement.run.id}
              selected={selectedRunIds.has(placement.run.id)}
              rangePreview={rangePreviewRunIds.has(placement.run.id)}
              canEdit={canEdit}
              dragging={draggedRunIds.has(placement.run.id)}
              onSelect={(event) => onSelectRun(event, placement.run.id)}
              onDragStart={(event) => onStartRunDrag(event, placement.run.id)}
              onDragEnd={onEndRunDrag}
              onHover={(hovered) => onHoverRun(placement.run.id, hovered)}
            />
          ))}
          {!children.length && !runs.length && <div className="project-empty-folder">Drop runs here</div>}
        </div>
      )}
    </div>
  );
}

function ProjectSettings({ project, owner, onDeleted }: { project: Project; owner: boolean; onDeleted: () => void }) {
  const queryClient = useQueryClient();
  const [email, setEmail] = useState("");
  const members = useQuery({
    queryKey: ["project-members", project.id],
    queryFn: () => api<Member[]>(`/projects/${project.id}/members`),
    enabled: owner,
  });
  const addMember = useMutation({
    mutationFn: () => api(`/projects/${project.id}/members`, { method: "POST", body: JSON.stringify({ email, role: "viewer" }) }),
    onSuccess: () => { setEmail(""); queryClient.invalidateQueries({ queryKey: ["project-members", project.id] }); },
  });
  const removeProject = useMutation({
    mutationFn: () => api(`/projects/${project.id}`, { method: "DELETE" }),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ["projects"] }); onDeleted(); },
  });
  return (
    <div className="project-settings-view">
      <p className="eyebrow">PROJECT SETTINGS</p>
      <h1>{project.name}</h1>
      <p>{project.description || "No project description yet."}</p>
      <div className="project-settings-grid">
        <section><h2>Sharing</h2>{owner ? <><div className="inline-form"><input type="email" value={email} onChange={(event) => setEmail(event.target.value)} placeholder="colleague@solids.group" /><button className="button" disabled={!email || addMember.isPending} onClick={() => addMember.mutate()}>Invite</button></div><div className="compact-list">{members.data?.map((member) => <div key={member.id}><span className="avatar small">{member.name[0]}</span><span>{member.email}<small>{member.role}</small></span></div>)}</div></> : <p className="muted">Shared with you by the project owner.</p>}</section>
        <section><h2>Access</h2><p><strong>{project.visibility}</strong> visibility</p>{project.visibility === "public" && <a className="button" href={`/public/${project.slug}`}>Open public page ↗</a>}</section>
      </div>
      {owner && <button className="button button-danger" onClick={() => window.confirm(`Delete project ${project.name}? Runs will remain in Zephyr.`) && removeProject.mutate()}>Delete project</button>}
    </div>
  );
}

function ProjectWorkspace({
  project,
  canEdit,
  selectedRunId,
  onSelectRun,
  onDeleted,
}: {
  project: Project;
  canEdit: boolean;
  selectedRunId: string | null;
  onSelectRun: (runId: string | null, replace?: boolean) => void;
  onDeleted: () => void;
}) {
  const queryClient = useQueryClient();
  const me = useQuery({ queryKey: ["me"], queryFn: currentUser });
  const layout = useQuery({ queryKey: ["project-layout", project.id], queryFn: ({ signal }) => api<ProjectLayout>(`/projects/${project.id}/layout`, { signal }) });
  const [selectedRunIds, setSelectedRunIds] = useState<Set<string>>(() => new Set());
  const selectionAnchor = useRef<string | null>(null);
  const shiftPressed = useShiftPressed();
  const [hoveredRunId, setHoveredRunId] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [searchQuery, setSearchQuery] = useState("");
  const [collapsed, setCollapsed] = useState<Set<string>>(() => storedCollapsedFolders(project.id));
  const [draggedRunIds, setDraggedRunIds] = useState<string[]>([]);
  const [dropTarget, setDropTarget] = useState<string | null>(null);
  const [showAddRun, setShowAddRun] = useState(false);
  const [showNewFolder, setShowNewFolder] = useState(false);
  const [showSettings, setShowSettings] = useState(false);
  const [folderName, setFolderName] = useState("");
  const [folderParent, setFolderParent] = useState<string | null>(null);
  const [runId, setRunId] = useState("");
  const [runFolder, setRunFolder] = useState<string | null>(null);
  const allRuns = useQuery({
    queryKey: ["runs", "project-candidates"],
    queryFn: ({ signal }) => api<Run[]>("/runs?limit=1000", { signal }),
    enabled: canEdit && showAddRun,
  });
  const searchResults = useQuery({
    queryKey: ["project-run-search", project.id, searchQuery],
    queryFn: ({ signal }) => api<Run[]>(`/runs?project_id=${encodeURIComponent(project.id)}&search=${encodeURIComponent(searchQuery)}&limit=1000`, { signal }),
    enabled: Boolean(searchQuery),
  });
  useEffect(() => {
    const timer = window.setTimeout(() => setSearchQuery(search.trim()), 250);
    return () => window.clearTimeout(timer);
  }, [search]);
  useEffect(() => storeCollapsedFolders(project.id, collapsed), [collapsed, project.id]);
  useEffect(() => {
    if (selectedRunId) setShowSettings(false);
  }, [selectedRunId]);

  const moveRuns = useMutation({
    mutationFn: ({ runIds, folderId }: { runIds: string[]; folderId: string | null }) => api<ProjectRunPlacement[]>(`/projects/${project.id}/runs/placement/batch`, {
      method: "PUT",
      body: JSON.stringify({ run_ids: runIds, folder_id: folderId, position: 0 }),
    }),
    onMutate: async ({ runIds, folderId }) => {
      await queryClient.cancelQueries({ queryKey: ["project-layout", project.id] });
      const previous = queryClient.getQueryData<ProjectLayout>(["project-layout", project.id]);
      const positions = new Map(runIds.map((id, position) => [id, position]));
      queryClient.setQueryData<ProjectLayout>(["project-layout", project.id], (current) => current ? {
        ...current,
        runs: current.runs.map((placement) => positions.has(placement.run.id) ? { ...placement, folder_id: folderId, position: positions.get(placement.run.id)! } : placement),
      } : current);
      return { previous };
    },
    onError: (_error, _variables, context) => queryClient.setQueryData(["project-layout", project.id], context?.previous),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ["project-layout", project.id] }),
  });
  const createFolder = useMutation({
    mutationFn: () => api<ProjectFolder>(`/projects/${project.id}/folders`, { method: "POST", body: JSON.stringify({ name: folderName, parent_id: folderParent }) }),
    onSuccess: (folder) => {
      setFolderName("");
      setShowNewFolder(false);
      setCollapsed((current) => { const next = new Set(current); if (folder.parent_id) next.delete(folder.parent_id); return next; });
      queryClient.invalidateQueries({ queryKey: ["project-layout", project.id] });
    },
  });
  const addRun = useMutation({
    mutationFn: () => api(`/projects/${project.id}/runs`, { method: "POST", body: JSON.stringify({ run_id: runId, folder_id: runFolder }) }),
    onSuccess: () => { setRunId(""); setShowAddRun(false); queryClient.invalidateQueries({ queryKey: ["project-layout", project.id] }); },
  });

  const folders = useMemo(() => layout.data?.folders ?? [], [layout.data?.folders]);
  const placements = useMemo(() => layout.data?.runs ?? [], [layout.data?.runs]);
  const childFolders = useMemo(() => {
    const result = new Map<string, ProjectFolder[]>();
    for (const folder of folders) {
      const key = parentKey(folder.parent_id);
      result.set(key, [...(result.get(key) ?? []), folder]);
    }
    for (const values of result.values()) values.sort((a, b) => a.position - b.position || a.name.localeCompare(b.name));
    return result;
  }, [folders]);
  const runsByFolder = useMemo(() => {
    const result = new Map<string, ProjectRunPlacement[]>();
    for (const placement of placements) {
      const key = parentKey(placement.folder_id);
      result.set(key, [...(result.get(key) ?? []), placement]);
    }
    for (const values of result.values()) values.sort((a, b) => a.position - b.position || a.run.name.localeCompare(b.run.name));
    return result;
  }, [placements]);
  const searchView = useMemo(() => {
    if (!searchQuery) return null;
    const serverMatches = new Set((searchResults.data ?? []).map((run) => run.id));
    const folderById = new Map(folders.map((folder) => [folder.id, folder]));
    const normalized = searchQuery.toLocaleLowerCase();
    const matchedFolderRoots = new Set(folders.filter((folder) => folder.name.toLocaleLowerCase().includes(normalized)).map((folder) => folder.id));
    const isInsideMatchedFolder = (folderId: string | null) => {
      let current = folderId;
      while (current) {
        if (matchedFolderRoots.has(current)) return true;
        current = folderById.get(current)?.parent_id ?? null;
      }
      return false;
    };
    const runIds = new Set(placements.filter((placement) => serverMatches.has(placement.run.id) || isInsideMatchedFolder(placement.folder_id)).map((placement) => placement.run.id));
    const folderIds = new Set<string>();
    const addAncestors = (folderId: string | null) => {
      let current = folderId;
      while (current) {
        if (folderIds.has(current)) break;
        folderIds.add(current);
        current = folderById.get(current)?.parent_id ?? null;
      }
    };
    for (const folder of folders) if (isInsideMatchedFolder(folder.id)) addAncestors(folder.id);
    for (const placement of placements) if (runIds.has(placement.run.id)) addAncestors(placement.folder_id);
    return { runIds, folderIds };
  }, [folders, placements, searchQuery, searchResults.data]);
  const shownChildFolders = useMemo(() => {
    return childFolders;
  }, [childFolders]);
  const shownRunsByFolder = useMemo(() => {
    if (!searchView) return runsByFolder;
    const result = new Map<string, ProjectRunPlacement[]>();
    for (const [key, values] of runsByFolder) result.set(key, values.filter((placement) => searchView.runIds.has(placement.run.id)));
    return result;
  }, [runsByFolder, searchView]);
  const effectiveCollapsed = searchQuery ? EMPTY_RUN_IDS : collapsed;
  const selectedPlacement = selectedRunId
    ? placements.find((placement) => placement.run.id === selectedRunId) ?? null
    : placements[0] ?? null;
  useEffect(() => {
    if (layout.isSuccess && !showSettings && !selectedRunId && selectedPlacement) {
      onSelectRun(selectedPlacement.run.id, true);
    }
  }, [layout.isSuccess, onSelectRun, selectedPlacement, selectedRunId, showSettings]);
  const visibleRunIds = useMemo(() => {
    const result: string[] = [];
    const visitFolder = (folder: ProjectFolder) => {
      if (effectiveCollapsed.has(folder.id)) return;
      for (const child of shownChildFolders.get(folder.id) ?? []) visitFolder(child);
      for (const placement of shownRunsByFolder.get(folder.id) ?? []) result.push(placement.run.id);
    };
    for (const folder of shownChildFolders.get(ROOT) ?? []) visitFolder(folder);
    for (const placement of shownRunsByFolder.get(ROOT) ?? []) result.push(placement.run.id);
    return result;
  }, [effectiveCollapsed, shownChildFolders, shownRunsByFolder]);
  const selectedIds = placements.filter((placement) => selectedRunIds.has(placement.run.id)).map((placement) => placement.run.id);
  const rangeAnchorId = selectionAnchor.current && selectedRunIds.has(selectionAnchor.current) && visibleRunIds.includes(selectionAnchor.current)
    ? selectionAnchor.current
    : visibleRunIds.filter((id) => selectedRunIds.has(id)).at(-1) ?? (selectedPlacement && visibleRunIds.includes(selectedPlacement.run.id) ? selectedPlacement.run.id : null);
  const rangePreviewRunIds = useMemo(
    () => shiftPressed ? selectionRange(visibleRunIds, rangeAnchorId, hoveredRunId) : EMPTY_RUN_IDS,
    [hoveredRunId, rangeAnchorId, shiftPressed, visibleRunIds],
  );
  const draggedRunIdSet = useMemo(() => new Set(draggedRunIds), [draggedRunIds]);
  const included = new Set(placements.map((placement) => placement.run.id));
  const candidates = (allRuns.data ?? []).filter((run) => run.owner_id === me.data?.id && !included.has(run.id));

  function startRunDrag(event: DragEvent<HTMLButtonElement>, id: string) {
    const collection = selectedRunIds.has(id) && selectedIds.length > 1 ? selectedIds : [id];
    if (!selectedRunIds.has(id)) {
      onSelectRun(id);
      setSelectedRunIds(new Set([id]));
      selectionAnchor.current = id;
    }
    event.dataTransfer.effectAllowed = "move";
    event.dataTransfer.setData("application/x-zephyr-run", id);
    event.dataTransfer.setData("application/x-zephyr-runs", JSON.stringify(collection));
    event.dataTransfer.setData("text/plain", `${collection.length} Zephyr ${collection.length === 1 ? "run" : "runs"}`);
    setDraggedRunIds(collection);
  }
  function dragOverFolder(event: DragEvent, folderId: string) {
    if (!draggedRunIds.length || !canEdit) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = "move";
    setDropTarget(folderId);
  }
  function dropRun(event: DragEvent, folderId: string | null) {
    event.preventDefault();
    let ids = draggedRunIds;
    if (!ids.length) {
      try {
        const transferred = JSON.parse(event.dataTransfer.getData("application/x-zephyr-runs"));
        if (Array.isArray(transferred)) ids = transferred.filter((id): id is string => typeof id === "string");
      } catch {
        const id = event.dataTransfer.getData("application/x-zephyr-run");
        ids = id ? [id] : [];
      }
    }
    if (ids.length && canEdit) {
      moveRuns.mutate({ runIds: ids, folderId });
      if (folderId) setCollapsed((current) => { const next = new Set(current); next.delete(folderId); return next; });
    }
    setDraggedRunIds([]);
    setDropTarget(null);
  }
  function beginFolder(parentId: string | null) {
    setFolderParent(parentId);
    setShowNewFolder(true);
    setShowAddRun(false);
  }
  function selectRun(event: MouseEvent<HTMLButtonElement>, id: string) {
    event.preventDefault();
    onSelectRun(id);
    setShowSettings(false);
    if (event.shiftKey) {
      const range = selectionRange(visibleRunIds, rangeAnchorId ?? id, id);
      if (range.size) {
        setSelectedRunIds((current) => {
          const next = event.ctrlKey || event.metaKey ? new Set(current) : new Set<string>();
          for (const runId of range) next.add(runId);
          return next;
        });
      }
      return;
    }
    selectionAnchor.current = id;
    if (event.ctrlKey || event.metaKey) {
      setSelectedRunIds((current) => {
        const next = new Set(current);
        if (next.has(id)) next.delete(id); else next.add(id);
        return next;
      });
      return;
    }
    setSelectedRunIds(new Set([id]));
  }
  function hoverRun(id: string, hovered: boolean) {
    setHoveredRunId((current) => hovered ? id : current === id ? null : current);
  }

  return (
    <div className="project-workspace-shell">
      <aside className="project-data-sidebar">
        <div className="project-tree-actions">
          <div><span>{searchView ? `${searchView.runIds.size} of ${placements.length} runs` : `${placements.length} runs`}</span><span>{folders.length} folders</span></div>
          {canEdit && <div><button title="Add a run" onClick={() => { setShowAddRun(!showAddRun); setShowNewFolder(false); }}>＋ Run</button><button title="New folder" onClick={() => beginFolder(null)}>＋ Folder</button></div>}
        </div>
        <label className="project-tree-search">
          <span aria-hidden="true">⌕</span>
          <input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search this project" aria-label="Search project runs" />
          {(search !== searchQuery || searchResults.isFetching) && <i className="spinner" aria-label="Searching project" />}
          {search && <button aria-label="Clear project search" onClick={() => { setSearch(""); setSearchQuery(""); }}>×</button>}
        </label>
        {showNewFolder && <div className="project-sidebar-form"><strong>New folder</strong><input autoFocus aria-label="Folder name" value={folderName} onChange={(event) => setFolderName(event.target.value)} placeholder="Folder name" onKeyDown={(event) => event.key === "Enter" && folderName.trim() && createFolder.mutate()} /><select aria-label="Parent folder" value={folderParent ?? ""} onChange={(event) => setFolderParent(event.target.value || null)}><option value="">Project root</option>{folders.map((folder) => <option key={folder.id} value={folder.id}>{folder.name}</option>)}</select><div><button onClick={() => setShowNewFolder(false)}>Cancel</button><button className="primary" disabled={!folderName.trim() || createFolder.isPending} onClick={() => createFolder.mutate()}>Create</button></div>{createFolder.isError && <small>Could not create folder.</small>}</div>}
        {showAddRun && <div className="project-sidebar-form"><strong>Add run</strong><select aria-label="Run to add" value={runId} onChange={(event) => setRunId(event.target.value)}><option value="">Choose an owned run…</option>{candidates.map((run) => <option key={run.id} value={run.id}>{run.name}</option>)}</select><select aria-label="Destination folder" value={runFolder ?? ""} onChange={(event) => setRunFolder(event.target.value || null)}><option value="">Project root</option>{folders.map((folder) => <option key={folder.id} value={folder.id}>{folder.name}</option>)}</select><div><button onClick={() => setShowAddRun(false)}>Cancel</button><button className="primary" disabled={!runId || addRun.isPending} onClick={() => addRun.mutate()}>Add</button></div></div>}
        <div className="project-tree-scroll">
          <div
            className="project-root-drop"
            data-drop-target={dropTarget === ROOT}
            onDragOver={(event) => dragOverFolder(event, ROOT)}
            onDrop={(event) => dropRun(event, null)}
          ><span>Project root</span>{draggedRunIds.length > 0 && <small>Drop {draggedRunIds.length === 1 ? "run" : `${draggedRunIds.length} runs`} here</small>}</div>
          {layout.isPending && <div className="project-tree-state"><span className="spinner" />Loading project…</div>}
          {layout.isError && <div className="project-tree-state error-text">Could not load this project.</div>}
          {(shownChildFolders.get(ROOT) ?? []).map((folder) => <FolderNode key={folder.id} folder={folder} depth={0} childFolders={shownChildFolders} runsByFolder={shownRunsByFolder} collapsed={effectiveCollapsed} activeRunId={showSettings ? null : selectedPlacement?.run.id ?? null} selectedRunIds={selectedRunIds} rangePreviewRunIds={rangePreviewRunIds} draggedRunIds={draggedRunIdSet} dropTarget={dropTarget} canEdit={canEdit} onToggle={(id) => setCollapsed((current) => { const next = new Set(current); if (next.has(id)) next.delete(id); else next.add(id); return next; })} onSelectRun={selectRun} onHoverRun={hoverRun} onStartRunDrag={startRunDrag} onEndRunDrag={() => { setDraggedRunIds([]); setDropTarget(null); }} onDragOverFolder={dragOverFolder} onDropRun={(event, id) => dropRun(event, id)} onNewFolder={beginFolder} />)}
          {(shownRunsByFolder.get(ROOT) ?? []).map((placement) => <ProjectRunRow key={placement.run.id} placement={placement} active={!showSettings && selectedPlacement?.run.id === placement.run.id} selected={selectedRunIds.has(placement.run.id)} rangePreview={rangePreviewRunIds.has(placement.run.id)} canEdit={canEdit} dragging={draggedRunIdSet.has(placement.run.id)} onSelect={(event) => selectRun(event, placement.run.id)} onHover={(hovered) => hoverRun(placement.run.id, hovered)} onDragStart={(event) => startRunDrag(event, placement.run.id)} onDragEnd={() => { setDraggedRunIds([]); setDropTarget(null); }} />)}
          {!layout.isPending && !searchQuery && !folders.length && !placements.length && <div className="project-tree-empty"><strong>No simulation data yet</strong><span>Add runs, then group them into folders.</span></div>}
          {!layout.isPending && searchQuery && !searchResults.isFetching && searchView?.runIds.size === 0 && searchView?.folderIds.size === 0 && <div className="project-tree-empty"><strong>No matching runs</strong><span>Search covers metadata, paths, and artifact filenames.</span></div>}
          {searchResults.isError && <div className="project-tree-state error-text">Could not search this project.</div>}
        </div>
        <div className="project-sidebar-footer">
          {selectedIds.length > 1 && <div className="project-selection-summary"><span title="Drag any selected run to move the collection">{selectedIds.length} selected · drag together</span><button onClick={() => setSelectedRunIds(new Set())}>Clear</button><Link href={`/compare?ids=${selectedIds.join(",")}`}>Compare</Link></div>}
          {moveRuns.isError && <div className="project-move-error">Could not move the selected runs.</div>}
          <button className="project-settings-button" data-active={showSettings} onClick={() => { setShowSettings(true); onSelectRun(null); }}><span>⚙</span><span>Project settings</span></button>
        </div>
      </aside>
      <main className="project-data-main">
        <header className="project-data-heading"><div><p className="eyebrow">{project.visibility.toUpperCase()} PROJECT</p><h2>{project.name}</h2><p>{project.description || "Simulation workspace"}</p></div>{project.visibility === "public" && <a href={`/public/${project.slug}`}>Public page ↗</a>}</header>
        {showSettings ? <ProjectSettings project={project} owner={me.data?.id === project.owner_id} onDeleted={onDeleted} /> : selectedPlacement ? <RunRecord key={selectedPlacement.run.id} runId={selectedPlacement.run.id} embedded /> : selectedRunId && layout.isSuccess ? <div className="project-main-empty"><span>⌁</span><h1>Run not in this project</h1><p>This project permalink no longer points to an available run.</p></div> : <div className="project-main-empty"><span>⌁</span><h1>Build this project</h1><p>Add a run from the sidebar, then drag it into folders as the study grows.</p></div>}
      </main>
    </div>
  );
}

export default function ProjectsPage() {
  const queryClient = useQueryClient();
  const [location, navigate] = useLocation();
  const routeSelection = projectSelectionFromLocation(location);
  const projects = useQuery({ queryKey: ["projects"], queryFn: () => api<Project[]>("/projects") });
  const editableProjects = useQuery({ queryKey: ["projects", "editable"], queryFn: () => api<Project[]>("/projects?editable=true") });
  const [showCreate, setShowCreate] = useState(false);
  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const [visibility, setVisibility] = useState<Project["visibility"]>("private");
  const create = useMutation({
    mutationFn: () => api<Project>("/projects", { method: "POST", body: JSON.stringify({ name, slug, visibility }) }),
    onSuccess: (project) => {
      queryClient.setQueryData<Project[]>(["projects"], (current) => [...(current ?? []).filter((item) => item.id !== project.id), project]);
      queryClient.invalidateQueries({ queryKey: ["projects"] });
      navigate(projectPath(project));
      setShowCreate(false);
      setName("");
      setSlug("");
    },
  });
  const selected = routeSelection.projectSlug
    ? projects.data?.find((project) => project.slug === routeSelection.projectSlug)
    : projects.data?.[0];
  const editableIds = new Set((editableProjects.data ?? []).map((project) => project.id));
  useEffect(() => {
    if (!routeSelection.projectSlug && selected) navigate(projectPath(selected), { replace: true });
  }, [navigate, routeSelection.projectSlug, selected]);
  return (
    <div className="projects-page">
      <header className="project-selector-bar">
        <div>
          <p className="eyebrow">PROJECT WORKSPACE</p>
          {selected ? <select aria-label="Select project" value={selected.id} onChange={(event) => {
            const project = projects.data?.find((item) => item.id === event.target.value);
            if (project) navigate(projectPath(project));
          }}>{projects.data?.map((project) => <option value={project.id} key={project.id}>{project.name}</option>)}</select> : <h1>Projects</h1>}
        </div>
        <button onClick={() => setShowCreate(!showCreate)}>＋ New project</button>
      </header>
      {showCreate && <div className="project-create-bar"><label>Name<input autoFocus value={name} onChange={(event) => { const next = event.target.value; setName(next); setSlug(next.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "")); }} /></label><label>URL slug<input value={slug} onChange={(event) => setSlug(event.target.value)} /></label><label>Visibility<select value={visibility} onChange={(event) => setVisibility(event.target.value as Project["visibility"])}><option value="private">Private</option><option value="group">Group</option><option value="public">Public</option></select></label><button onClick={() => setShowCreate(false)}>Cancel</button><button className="primary" disabled={!name || slug.length < 3 || create.isPending} onClick={() => create.mutate()}>Create project</button></div>}
      {projects.isPending ? <div className="workspace-state"><span className="spinner" />Loading projects…</div> : routeSelection.projectSlug && !selected ? <div className="project-main-empty"><span>⌁</span><h1>Project not found</h1><p>This project permalink is unavailable or you no longer have access.</p></div> : selected ? <ProjectWorkspace key={selected.id} project={selected} canEdit={editableIds.has(selected.id)} selectedRunId={routeSelection.runId} onSelectRun={(runId, replace = false) => navigate(projectPath(selected, runId), { replace })} onDeleted={() => {
        queryClient.setQueryData<Project[]>(["projects"], (current) => current?.filter((project) => project.id !== selected.id));
        navigate("/projects", { replace: true });
      }} /> : <div className="project-main-empty"><span>⌁</span><h1>Create your first project</h1><p>Projects organize simulation records into a shared working space.</p></div>}
    </div>
  );
}
