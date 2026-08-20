import { compactPathValues } from "../comparisonPaths";

export default function MetadataTable({
  records,
  hideSimilar = false,
}: {
  records: { name: string; values: Record<string, string> }[];
  hideSimilar?: boolean;
}) {
  const keys = Array.from(new Set(records.flatMap((record) => Object.keys(record.values))))
    .filter((key) => !hideSimilar || new Set(records.map((record) => record.values[key] ?? "")).size > 1)
    .sort();
  return (
    <div className="table-scroll">
      <table className="data-table metadata-table" style={{ minWidth: `${180 + records.length * 240}px` }}>
        <colgroup><col className="comparison-field-column" />{records.map((record) => <col className="comparison-value-column" key={record.name} />)}</colgroup>
        <thead><tr><th>Field</th>{records.map((record) => <th key={record.name}>{record.name}</th>)}</tr></thead>
        <tbody>{!keys.length && <tr><td className="comparison-table-empty" colSpan={records.length + 1}>{hideSimilar ? "All similar rows are hidden." : "No comparison data is available."}</td></tr>}{keys.map((key) => {
          const values = records.map((record) => record.values[key] ?? "");
          const displayValues = compactPathValues(key, values);
          const changed = new Set(values).size > 1;
          return <tr key={key} className={changed ? "changed" : ""}><td>{key}</td>{values.map((value, index) => <td key={`${key}-${records[index].name}`} title={value || undefined}>{value ? <span className={displayValues[index] === value ? "comparison-cell-value" : "comparison-cell-value comparison-path-value"}>{displayValues[index]}</span> : <span className="muted">—</span>}</td>)}</tr>;
        })}</tbody>
      </table>
    </div>
  );
}
