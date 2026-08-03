import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useLocation } from "wouter";
import { api } from "../api";

export default function LoginPage() {
  const [, navigate] = useLocation();
  const queryClient = useQueryClient();
  const meta = useQuery({
    queryKey: ["meta"],
    queryFn: () => api<{ development_login: boolean }>("/meta"),
  });
  const devLogin = async () => {
    await api("/auth/dev-login", { method: "POST" });
    await queryClient.invalidateQueries({ queryKey: ["me"] });
    navigate("/");
  };
  return (
    <div className="login-page">
      <div className="login-atmosphere" />
      <section className="login-card">
        <div className="login-logo">Z</div>
        <p className="eyebrow">SOLID MECHANICS RESEARCH GROUP</p>
        <h1>Keep every ALAMO run in sight.</h1>
        <p className="login-copy">Execution health, provenance, results, and reproducible artifacts in one shared workspace.</p>
        <a className="button button-primary button-large" href="/api/v1/auth/login">Continue with Google</a>
        <p className="login-note">Access is limited to <strong>@solids.group</strong> accounts.</p>
        {meta.data?.development_login && <button className="button button-quiet" onClick={devLogin}>Local developer login</button>}
      </section>
    </div>
  );
}
