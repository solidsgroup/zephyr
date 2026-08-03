import { useState, type ReactNode } from "react";
import { Link, useLocation } from "wouter";
import type { User } from "../types";
import RunBrowser from "./RunBrowser";

function RailIcon({ name }: { name: "runs" | "compare" | "projects" | "settings" }) {
  if (name === "runs") return <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 6.5h14M5 12h14M5 17.5h14" /><circle cx="8" cy="6.5" r="1" /><circle cx="16" cy="12" r="1" /><circle cx="10" cy="17.5" r="1" /></svg>;
  if (name === "compare") return <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8 5v14M16 5v14M5 8l3-3 3 3M13 16l3 3 3-3" /></svg>;
  if (name === "projects") return <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4.5 7.5h6l2-2h7v13h-15z" /></svg>;
  return <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="3" /><path d="M12 3.5v2M12 18.5v2M3.5 12h2M18.5 12h2M6 6l1.5 1.5M16.5 16.5 18 18M18 6l-1.5 1.5M7.5 16.5 6 18" /></svg>;
}

export default function Layout({ user, children }: { user: User; children: ReactNode }) {
  const [location] = useLocation();
  const [runBrowserOpen, setRunBrowserOpen] = useState(false);
  const runWorkspace = location === "/" || location.startsWith("/runs/");
  const active = (path: string, exact = false) =>
    exact ? location === path : location === path || location.startsWith(`${path}/`);
  return (
    <div className={`shell${runWorkspace ? " runs-layout" : ""}`}>
      <aside className="app-rail">
        <Link href="/" className="rail-brand" title="Zephyr">
          <span className="brand-mark">Z</span>
        </Link>
        <nav aria-label="Primary navigation">
          <Link href="/" aria-label="Runs" data-label="Runs" className={active("/", true) || active("/runs") ? "active" : ""} onClick={(event) => {
            if (runWorkspace) {
              event.preventDefault();
              setRunBrowserOpen(true);
            }
          }}><RailIcon name="runs" /></Link>
          <Link href="/compare" aria-label="Compare" data-label="Compare" className={active("/compare") ? "active" : ""}><RailIcon name="compare" /></Link>
          <Link href="/projects" aria-label="Projects" data-label="Projects" className={active("/projects") ? "active" : ""}><RailIcon name="projects" /></Link>
        </nav>
        <div className="rail-bottom">
          <Link href="/settings" aria-label="Settings" data-label="Settings" className={active("/settings") ? "active rail-settings" : "rail-settings"}><RailIcon name="settings" /></Link>
          <Link href="/settings" className="rail-user" title={user.name || user.email}>
            {user.picture_url ? <img src={user.picture_url} alt="" /> : <span className="avatar">{user.name[0] ?? "Z"}</span>}
          </Link>
        </div>
      </aside>
      {runWorkspace && <RunBrowser open={runBrowserOpen} onClose={() => setRunBrowserOpen(false)} />}
      <main className={`content${runWorkspace ? " run-detail-content" : ""}`}>
        {runWorkspace && <button className="run-panel-toggle" onClick={() => setRunBrowserOpen(true)}>☰ <span>Runs</span></button>}
        {children}
      </main>
    </div>
  );
}
