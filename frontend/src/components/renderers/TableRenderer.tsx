import React from "react";
import { ChevronsUpDown, ChevronUp, ChevronDown } from "lucide-react";

type ColMeta = {
  name: string;
  isText: boolean;
  isPercent: boolean;
  orderIdx: number;
};

const isPercentName = (name: string) => {
  const n = name.toLowerCase();
  return (
    n.includes("pct") ||
    n.includes("percent") ||
    n.includes("percentage") ||
    n === "pct_change" ||
    n.endsWith("_pct")
  );
};

const formatNumber = (val: number, asPercent: boolean): string => {
  const nf0 = new Intl.NumberFormat(undefined, { maximumFractionDigits: 0 });
  const nf2 = new Intl.NumberFormat(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  if (asPercent) return `${nf2.format(val)}%`;
  return Number.isInteger(val) ? nf0.format(val) : nf2.format(val);
};

export function TableRenderer({ rows }: { rows: any[] }) {
  const colMetas: ColMeta[] = React.useMemo(() => {
    if (!rows || rows.length === 0) return [];
    const sample = rows.slice(0, 50);
    const seenOrder: Record<string, number> = {};
    const metas: Record<string, ColMeta> = {} as any;
    let idxCounter = 0;
    for (const r of sample) {
      Object.keys(r || {}).forEach((k) => {
        if (!(k in seenOrder)) seenOrder[k] = idxCounter++;
      });
    }
    for (const [name, orderIdx] of Object.entries(seenOrder)) {
      let isText = false;
      let isPercent = isPercentName(name);
      for (const row of sample) {
        const v = (row as any)?.[name];
        if (v === null || v === undefined) continue;
        if (typeof v === "string") {
          // string with % implies percent col if not flagged yet
          if (v.trim().endsWith("%")) isPercent = true;
          // treat as text if not purely numeric
          const n = Number.parseFloat(v);
          if (!Number.isFinite(n) || String(n) !== v.replace(/[,\s%]/g, "").trim()) {
            isText = true;
            break;
          }
        } else if (typeof v !== "number") {
          isText = true;
          break;
        }
      }
      metas[name] = { name, isText, isPercent, orderIdx };
    }
    // Reorder: text first, prioritize 'metric' column to be first among text
    const arr = Object.values(metas);
    arr.sort((a, b) => {
      const aMetric = a.name.toLowerCase() === "metric" ? 0 : 1;
      const bMetric = b.name.toLowerCase() === "metric" ? 0 : 1;
      const aGroup = a.isText ? 0 : 1;
      const bGroup = b.isText ? 0 : 1;
      if (aGroup !== bGroup) return aGroup - bGroup; // text first
      if (aGroup === 0 && aMetric !== bMetric) return aMetric - bMetric; // 'metric' first within text
      return a.orderIdx - b.orderIdx; // stable by first-seen order
    });
    return arr;
  }, [rows]);

  const cols = React.useMemo(() => colMetas.map((m) => m.name), [colMetas]);
  const metaByCol = React.useMemo(() => Object.fromEntries(colMetas.map((m) => [m.name, m])), [colMetas]);

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

  const renderCell = (col: string, value: any) => {
    if (value === null || value === undefined) return "";
    const meta = metaByCol[col];
    const asPercent = !!meta?.isPercent;
    if (typeof value === "number") return formatNumber(value, asPercent);
    const s = String(value);
    if (s.trim().endsWith("%")) {
      // normalize percentage string to two decimals
      const n = Number.parseFloat(s.replace(/%/g, ""));
      if (Number.isFinite(n)) return `${new Intl.NumberFormat(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(n)}%`;
      return s;
    }
    const n = Number.parseFloat(s.replace(/[,\s]/g, ""));
    if (Number.isFinite(n)) return formatNumber(n, asPercent);
    return s;
  };

  return (
    <div className="relative inline-block max-w-full max-h-[420px] overflow-auto border rounded-xl">
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
                  {renderCell(c, (r as any)?.[c])}
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
