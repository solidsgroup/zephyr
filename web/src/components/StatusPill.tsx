export default function StatusPill({ status }: { status: string }) {
  return <span className={`status status-${status}`}><i />{status}</span>;
}
