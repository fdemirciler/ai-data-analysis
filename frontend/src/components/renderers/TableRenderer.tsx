import React from "react";
import { ChevronsUpDown, ChevronUp, ChevronDown } from "lucide-react";

export function TableRenderer({ rows }: { rows: any[] }) {
  const cols: string[] = React.useMemo(() => {
    if (!rows || rows.length === 0) return [];
    const keys = new Set<string>();
    for (const r of rows.slice(0, 50)) {
      Object.keys(r || {}).forEach((k) => keys.add(k));
    }
    return Array.from(keys);
  }, [rows]);

  const [sortBy, setSortBy] = React.useState<string | null>(null);
  const [sortDir, setSortDir] = React.useState<"asc" | "desc">("asc");

  const onToggleSort = (col: string) => {
    if (sortBy !== col) {
      setSortBy(col);
      setSortDir("asc");
    } else {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    }
  };

  const sortedRows = React.useMemo(() => {
    const sample = rows ? rows.slice(0, 50) : [];
    if (!sortBy) return sample;
    const copy = sample.slice();
    copy.sort((a: any, b: any) => {
      const av = a?.[sortBy];
      const bv = b?.[sortBy];
      // Try numeric compare if both parseable
      const an = typeof av === "number" ? av : Number.parseFloat(av);
      const bn = typeof bv === "number" ? bv : Number.parseFloat(bv);
      const bothNumeric = Number.isFinite(an) && Number.isFinite(bn);
      let cmp = 0;
      if (bothNumeric) {
        cmp = an === bn ? 0 : an < bn ? -1 : 1;
      } else {
        const as = String(av ?? "").toLowerCase();
        const bs = String(bv ?? "").toLowerCase();
        cmp = as === bs ? 0 : as < bs ? -1 : 1;
      }
      return sortDir === "asc" ? cmp : -cmp;
    });
    return copy;
  }, [rows, sortBy, sortDir]);

  if (!rows || rows.length === 0) {
    return (
      <div className="text-sm text-muted-foreground">No rows to display.</div>
    );
  }

  return (
    <div className="relative w-full max-w-full max-h-[420px] overflow-auto border rounded-xl">
      <table className="min-w-max text-sm">
        <thead className="bg-muted/40 sticky top-0 z-10">
          <tr>
            {cols.map((c) => {
              const isActive = sortBy === c;
              const icon = !isActive ? (
                <ChevronsUpDown className="h-3.5 w-3.5 opacity-60" />
              ) : sortDir === "asc" ? (
                <ChevronUp className="h-3.5 w-3.5" />
              ) : (
                <ChevronDown className="h-3.5 w-3.5" />
              );
              return (
                <th key={c} className="text-left px-3 py-2 font-medium whitespace-nowrap bg-muted/40">
                  <button
                    type="button"
                    className="inline-flex items-center gap-1 hover:underline decoration-dotted cursor-pointer select-none"
                    aria-sort={isActive ? (sortDir === "asc" ? "ascending" : "descending") : "none"}
                    onClick={() => onToggleSort(c)}
                  >
                    <span>{c}</span>
                    {icon}
                  </button>
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody className="divide-y divide-border">
          {sortedRows.map((r, i) => (
            <tr key={i} className="odd:bg-background hover:bg-muted/30">
              {cols.map((c) => (
                <td key={c} className="px-3 py-2 whitespace-nowrap max-w-[320px] overflow-hidden text-ellipsis">
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
