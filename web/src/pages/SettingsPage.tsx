import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api";
import type { ApiToken } from "../types";

export default function SettingsPage() {
  const queryClient = useQueryClient();
  const tokens = useQuery({ queryKey: ["tokens"], queryFn: () => api<ApiToken[]>("/auth/tokens") });
  const [name, setName] = useState("My workstation");
  const [created, setCreated] = useState<string | null>(null);
  const create = useMutation({
    mutationFn: () => api<ApiToken>("/auth/tokens", { method: "POST", body: JSON.stringify({ name }) }),
    onSuccess: (token) => { setCreated(token.token ?? null); queryClient.invalidateQueries({ queryKey: ["tokens"] }); },
  });
  const revoke = useMutation({
    mutationFn: (id: string) => api(`/auth/tokens/${id}`, { method: "DELETE" }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["tokens"] }),
  });
  const logout = async () => { await api("/auth/logout", { method: "POST" }); window.location.assign("/login"); };
  return (
    <>
      <header className="page-header"><div><p className="eyebrow">ACCOUNT</p><h1>Settings</h1><p>Credentials for the web dashboard and <code>zph</code>.</p></div><button className="button" onClick={logout}>Sign out</button></header>
      <section className="panel settings-panel"><div className="panel-heading"><div><h2>CLI tokens</h2><p>Tokens grant the same access as your account. Store them like passwords.</p></div></div>
        <div className="inline-form token-create"><input value={name} onChange={(event) => setName(event.target.value)} placeholder="Token name" /><button className="button button-primary" disabled={!name || create.isPending} onClick={() => create.mutate()}>Create token</button></div>
        {created && <div className="token-reveal"><strong>Copy this token now — it will not be shown again.</strong><code>{created}</code><button className="button" onClick={() => navigator.clipboard.writeText(created)}>Copy</button></div>}
        <div className="compact-list token-list">{tokens.data?.map((token) => <div key={token.id}><span className="token-icon">⌘</span><span><strong>{token.name}</strong><small>zph_{token.prefix}_… · created {new Date(token.created_at).toLocaleDateString()}{token.last_used_at ? ` · used ${new Date(token.last_used_at).toLocaleDateString()}` : ""}</small></span><button className="button button-danger" disabled={Boolean(token.revoked_at)} onClick={() => revoke.mutate(token.id)}>{token.revoked_at ? "Revoked" : "Revoke"}</button></div>)}</div>
      </section>
      <section className="panel cli-help"><h2>Connect a workstation</h2><pre><span>$</span> pipx install zph{"\n"}<span>$</span> zph login {window.location.origin}</pre></section>
    </>
  );
}
