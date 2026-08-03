import type { ReactNode } from "react";
import { Link, useLocation } from "wouter";
import type { User } from "../types";

export default function Layout({ user, children }: { user: User; children: ReactNode }) {
  const [location] = useLocation();
  const active = (path: string, exact = false) =>
    exact ? location === path : location === path || location.startsWith(`${path}/`);
  return (
    <div className="shell">
      <aside className="sidebar">
        <Link href="/" className="brand">
          <span className="brand-mark">Z</span>
          <span><strong>Zephyr</strong><small>ALAMO workspace</small></span>
        </Link>
        <nav>
          <Link href="/" className={active("/", true) || active("/runs") ? "active" : ""}><span>⌁</span> Runs</Link>
          <Link href="/compare" className={active("/compare") ? "active" : ""}><span>⌇</span> Compare</Link>
          <Link href="/projects" className={active("/projects") ? "active" : ""}><span>◇</span> Projects</Link>
        </nav>
        <div className="sidebar-bottom">
          <Link href="/settings" className="user-card">
            {user.picture_url ? <img src={user.picture_url} alt="" /> : <span className="avatar">{user.name[0] ?? "Z"}</span>}
            <span><strong>{user.name || user.email}</strong><small>{user.email}</small></span>
          </Link>
        </div>
      </aside>
      <main className="content">{children}</main>
    </div>
  );
}
