import { useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { useParams } from "wouter";
import { api, currentUser } from "../api";

interface DeviceApproval {
  status: "approved";
  device_name: string;
}

export default function ConnectPage() {
  const { code = "" } = useParams();
  const user = useQuery({
    queryKey: ["me"],
    queryFn: currentUser,
    retry: false,
  });
  const approval = useQuery({
    queryKey: ["device-approval", code],
    queryFn: () =>
      api<DeviceApproval>(`/auth/device/${encodeURIComponent(code)}/approve`, {
        method: "POST",
      }),
    enabled: user.isSuccess && Boolean(code),
    retry: false,
  });

  useEffect(() => {
    if (user.isError) {
      const next = encodeURIComponent(window.location.pathname);
      window.location.replace(`/api/v1/auth/login?next=${next}`);
    }
  }, [user.isError]);

  let content = (
    <div className="connect-state"><span className="spinner" />Connecting this device…</div>
  );
  if (approval.isError) {
    content = (
      <div className="connect-state connect-error">
        <strong>This login link is invalid, expired, or already used.</strong>
        <span>Return to the terminal and start <code>zph login</code> again.</span>
      </div>
    );
  } else if (approval.data) {
    content = (
      <div className="connect-state connect-success">
        <span className="connect-check">✓</span>
        <strong>{approval.data.device_name} is connected.</strong>
        <span>You can close this tab and return to the terminal.</span>
      </div>
    );
  }

  return (
    <div className="login-page">
      <div className="login-atmosphere" />
      <section className="login-card connect-card">
        <div className="login-logo">Z</div>
        <p className="eyebrow">ZPH DEVICE LOGIN</p>
        <h1>Connect to Zephyr.</h1>
        {content}
      </section>
    </div>
  );
}
