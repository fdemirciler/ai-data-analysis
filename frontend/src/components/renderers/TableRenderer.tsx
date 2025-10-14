import React from "react";
import { ChevronsUpDown, ChevronUp, ChevronDown } from "lucide-react";
import { cn } from "../ui/utils";

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
  const [currentPage, setCurrentPage] = React.useState(1);
  const rowsPerPage = 25;

  const colMetas: ColMeta[] = React.useMemo(() => {
    if (!rows || rows.length === 0) return [];
    // Use all rows for column detection (no artificial limit)
    const sample = rows;
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
    setCurrentPage(1); // Reset to first page when sorting
  };

  const sortedRows = React.useMemo(() => {
    // Use all rows provided (no artificial limit)
    if (!rows || rows.length === 0) return [];
    if (!sortBy) return rows;
    const copy = rows.slice();
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

  // Pagination logic
  const totalPages = Math.ceil(sortedRows.length / rowsPerPage);
  const startIdx = (currentPage - 1) * rowsPerPage;
  const endIdx = startIdx + rowsPerPage;
  const paginatedRows = sortedRows.slice(startIdx, endIdx);

  // Reset to page 1 if current page exceeds total pages
  React.useEffect(() => {
    if (currentPage > totalPages && totalPages > 0) {
      setCurrentPage(1);
    }
  }, [currentPage, totalPages]);

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
    <div className="w-full overflow-hidden">
      <div className="overflow-x-auto overflow-y-auto max-h-[420px]">
        <table className="w-full text-sm">
          <thead className="sticky top-0 z-10 bg-background">
            <tr>
              {cols.map((c, idx) => {
                const isActive = sortBy === c;
                const icon = !isActive ? (
                  <ChevronsUpDown className="h-3.5 w-3.5 opacity-60" />
                ) : sortDir === "asc" ? (
                  <ChevronUp className="h-3.5 w-3.5" />
                ) : (
                  <ChevronDown className="h-3.5 w-3.5" />
                );
                return (
                  <th 
                    key={c} 
                    className={cn(
                      "text-left py-3 font-semibold whitespace-nowrap border-b border-border",
                      idx === 0 ? "pl-8 pr-6" : idx === cols.length - 1 ? "pr-8 pl-6" : "px-6",
                      !metaByCol[c]?.isText && "text-right"
                    )}
                  >
                    <button
                      type="button"
                      className={cn(
                        "inline-flex items-center gap-1.5 cursor-pointer select-none transition-opacity",
                        "hover:opacity-80 hover:underline underline-offset-2"
                      )}
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
          <tbody>
            {paginatedRows.map((r, i) => (
              <tr key={i} className="border-b border-border/10 last:border-b-0 hover:bg-accent/30 transition-colors duration-150">
                {cols.map((c, idx) => (
                  <td 
                    key={c} 
                    className={cn(
                      "py-3 whitespace-nowrap max-w-[320px] overflow-hidden text-ellipsis",
                      idx === 0 ? "pl-8 pr-6 font-medium" : idx === cols.length - 1 ? "pr-8 pl-6" : "px-6",
                      !metaByCol[c]?.isText && idx !== 0 && "text-right"
                    )}
                  >
                    {renderCell(c, (r as any)?.[c])}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {sortedRows.length > rowsPerPage && (
        <div className="flex items-center justify-between px-8 py-3 border-t border-border/10 text-xs text-muted-foreground">
          <div>
            Showing {startIdx + 1}-{Math.min(endIdx, sortedRows.length)} of {sortedRows.length} rows
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={() => setCurrentPage(p => Math.max(1, p - 1))}
              disabled={currentPage === 1}
              className={cn(
                "px-3 py-1 rounded-md transition-colors",
                currentPage === 1
                  ? "text-muted-foreground/50 cursor-not-allowed"
                  : "text-foreground hover:bg-accent cursor-pointer"
              )}
            >
              Previous
            </button>
            <span className="text-xs">
              Page {currentPage} of {totalPages}
            </span>
            <button
              onClick={() => setCurrentPage(p => Math.min(totalPages, p + 1))}
              disabled={currentPage === totalPages}
              className={cn(
                "px-3 py-1 rounded-md transition-colors",
                currentPage === totalPages
                  ? "text-muted-foreground/50 cursor-not-allowed"
                  : "text-foreground hover:bg-accent cursor-pointer"
              )}
            >
              Next
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
