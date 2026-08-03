export default function MetadataTable({ records }: { records: { name: string; values: Record<string, string> }[] }) {
  const keys = Array.from(new Set(records.flatMap((record) => Object.keys(record.values)))).sort();
  return (
    <div className="table-scroll">
      <table className="data-table metadata-table">
        <thead><tr><th>Field</th>{records.map((record) => <th key={record.name}>{record.name}</th>)}</tr></thead>
        <tbody>{keys.map((key) => {
          const values = records.map((record) => record.values[key] ?? "");
          const changed = new Set(values).size > 1;
          return <tr key={key} className={changed ? "changed" : ""}><td>{key}</td>{values.map((value, index) => <td key={`${key}-${records[index].name}`}>{value || <span className="muted">—</span>}</td>)}</tr>;
        })}</tbody>
      </table>
    </div>
  );
}
