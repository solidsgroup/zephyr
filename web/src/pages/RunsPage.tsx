import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { createColumnHelper, flexRender, getCoreRowModel, useReactTable } from "@tanstack/react-table";
import { Link, useLocation } from "wouter";
import { api } from "../api";
import StatusPill from "../components/StatusPill";
import type { Run } from "../types";

const column = createColumnHelper<Run>();

function age(value: string | null) {
  if (!value) return "—";
  const seconds = Math.max(0, (Date.now() - new Date(value).getTime()) / 1000);
  if (seconds < 60) return `${Math.round(seconds)}s ago`;
  if (seconds < 3600) return `${Math.round(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.round(seconds / 3600)}h ago`;
  return `${Math.round(seconds / 86400)}d ago`;
}

export default function RunsPage() {
  const [, navigate] = useLocation();
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("");
  const [selected, setSelected] = useState<Record<string, boolean>>({});
  const runs = useQuery({
    queryKey: ["runs"],
    queryFn: () => api<Run[]>("/runs"),
    refetchInterval: 15_000,
  });
  const data = useMemo(() => (runs.data ?? []).filter((run) =>
    (!status || run.effective_status === status) &&
    (!search || `${run.name} ${run.alamo_hash ?? ""} ${run.host ?? ""}`.toLowerCase().includes(search.toLowerCase())),
  ), [runs.data, search, status]);
  const columns = useMemo(() => [
    column.display({
      id: "select",
      header: ({ table }) => <input aria-label="select all" type="checkbox" checked={table.getIsAllPageRowsSelected()} onChange={table.getToggleAllPageRowsSelectedHandler()} />,
      cell: ({ row }) => <input aria-label={`select ${row.original.name}`} type="checkbox" checked={row.getIsSelected()} onChange={row.getToggleSelectedHandler()} onClick={(event) => event.stopPropagation()} />,
      size: 36,
    }),
    column.accessor("name", { header: "Run", cell: ({ row, getValue }) => <div className="run-name"><Link href={`/runs/${row.original.id}`}>{getValue()}</Link><small>{row.original.alamo_hash ?? row.original.id}</small></div> }),
    column.accessor("effective_status", { header: "Status", cell: (info) => <StatusPill status={info.getValue()} /> }),
    column.accessor("progress", { header: "Progress", cell: ({ getValue }) => getValue() == null ? <span className="muted">—</span> : <div className="progress-cell"><span><i style={{ width: `${getValue()}%` }} /></span>{getValue()}%</div> }),
    column.accessor("host", { header: "Host", cell: (info) => info.getValue() ?? <span className="muted">—</span> }),
    column.accessor("git_commit", { header: "Code", cell: (info) => info.getValue() ? <code>{info.getValue()!.slice(0, 9)}</code> : <span className="muted">—</span> }),
    column.accessor("last_heartbeat", { header: "Heartbeat", cell: (info) => age(info.getValue()) }),
  ], []);
  const table = useReactTable({
    data,
    columns,
    state: { rowSelection: selected },
    onRowSelectionChange: setSelected,
    getRowId: (row) => row.id,
    enableRowSelection: true,
    getCoreRowModel: getCoreRowModel(),
  });
  const selectedIds = Object.keys(selected).filter((id) => selected[id]);
  return (
    <>
      <header className="page-header">
        <div><p className="eyebrow">WORKSPACE</p><h1>Runs</h1><p>Every posted ALAMO execution, live and archived.</p></div>
        {selectedIds.length >= 2 && <button className="button button-primary" onClick={() => navigate(`/compare?ids=${selectedIds.join(",")}`)}>Compare {selectedIds.length} runs</button>}
      </header>
      <div className="toolbar">
        <div className="search"><span>⌕</span><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search names, hashes, or hosts" /></div>
        <select value={status} onChange={(event) => setStatus(event.target.value)}><option value="">All statuses</option><option>running</option><option>completed</option><option>failed</option><option>interrupted</option><option>unreachable</option></select>
        <span className="toolbar-count">{data.length} runs</span>
      </div>
      <section className="panel table-panel">
        {runs.isPending ? <div className="center-state"><span className="spinner" />Loading runs…</div> : runs.isError ? <div className="error-panel">Could not load runs.</div> :
          <div className="table-scroll"><table className="data-table runs-table"><thead>{table.getHeaderGroups().map((group) => <tr key={group.id}>{group.headers.map((header) => <th key={header.id} style={{ width: header.getSize() }}>{flexRender(header.column.columnDef.header, header.getContext())}</th>)}</tr>)}</thead><tbody>{table.getRowModel().rows.map((row) => <tr key={row.id} data-selected={row.getIsSelected()} onClick={() => navigate(`/runs/${row.original.id}`)}>{row.getVisibleCells().map((cell) => <td key={cell.id}>{flexRender(cell.column.columnDef.cell, cell.getContext())}</td>)}</tr>)}{!data.length && <tr><td colSpan={7}><div className="empty-panel">No runs match this view. Start with <code>zph import .</code></div></td></tr>}</tbody></table></div>}
      </section>
    </>
  );
}
