import { useQuery } from "@tanstack/react-query";
import { Redirect } from "wouter";
import { api } from "../api";
import type { Run } from "../types";

export default function RunsPage() {
  const runs = useQuery({
    queryKey: ["runs"],
    queryFn: () => api<Run[]>("/runs"),
    refetchInterval: 15_000,
  });

  if (runs.isPending) return <div className="workspace-state"><span className="spinner" />Opening workspace…</div>;
  if (runs.isError) return <div className="error-panel">The run workspace could not be loaded.</div>;
  if (runs.data.length) return <Redirect to={`/runs/${runs.data[0].id}`} replace />;

  return (
    <div className="workspace-welcome">
      <span className="welcome-mark">Z</span>
      <p className="eyebrow">ALAMO WORKSPACE</p>
      <h1>Your runs will appear here</h1>
      <p>Post a simulation with <code>--post</code>, or add existing output from your terminal.</p>
      <pre><span>$</span> zph add output/</pre>
    </div>
  );
}
