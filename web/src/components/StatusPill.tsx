export default function StatusPill({ status }: { status: string }) {
  return <span className={`status-dot status-${status}`} aria-label={status} title={status}><i /></span>;
}
