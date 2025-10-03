import React from "react";

export function TableRenderer({ rows }: { rows: any[] }) {
  const cols: string[] = React.useMemo(() => {
    if (!rows || rows.length === 0) return [];
    const keys = new Set<string>();
    for (const r of rows.slice(0, 50)) {
      Object.keys(r || {}).forEach((k) => keys.add(k));
    }
    return Array.from(keys);
  }, [rows]);

  if (!rows || rows.length === 0) {
    return (
      <div className="text-sm text-muted-foreground">No rows to display.</div>
    );
  }

  return (
    <div className="w-full overflow-x-auto border rounded-xl">
      <table className="min-w-full text-sm">
        <thead className="bg-muted/40">
          <tr>
            {cols.map((c) => (
              <th key={c} className="text-left px-3 py-2 font-medium whitespace-nowrap">
                {c}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.slice(0, 50).map((r, i) => (
            <tr key={i} className="odd:bg-background">
              {cols.map((c) => (
                <td key={c} className="px-3 py-2 whitespace-nowrap">
                  {String(r?.[c] ?? "")}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {rows.length > 50 && (
        <div className="text-xs text-muted-foreground p-2">Showing first 50 rows of {rows.length}.</div>
      )}
    </div>
  );
}
