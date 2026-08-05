import { useEffect, useRef, useState } from "react";

export default function CopyButton({ value, label, compact = false }: { value: string; label: string; compact?: boolean }) {
  const [copied, setCopied] = useState(false);
  const timer = useRef<number | null>(null);
  useEffect(() => () => {
    if (timer.current != null) window.clearTimeout(timer.current);
  }, []);
  const copy = async () => {
    await navigator.clipboard.writeText(value);
    setCopied(true);
    if (timer.current != null) window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => setCopied(false), 1_500);
  };
  return (
    <button className="copy-button" data-compact={compact} type="button" title={`Copy ${label}`} aria-label={`Copy ${label}`} onClick={copy}>
      <span aria-hidden="true">{copied ? "✓" : "⧉"}</span>{!compact && (copied ? "Copied" : "Copy")}
    </button>
  );
}
