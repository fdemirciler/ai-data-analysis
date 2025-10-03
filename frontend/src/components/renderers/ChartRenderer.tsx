import React from "react";
import {
  ResponsiveContainer,
  BarChart,
  Bar,
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
} from "recharts";

export interface Series {
  label: string;
  data: number[];
}

export interface ChartData {
  kind: string; // 'bar' | 'line'
  labels: string[];
  series: Series[];
}

export function ChartRenderer({ chartData }: { chartData: ChartData }) {
  if (!chartData || !Array.isArray(chartData.labels)) {
    return <div className="text-sm text-muted-foreground">No chart data.</div>;
  }

  const data = React.useMemo(() => {
    const rows: any[] = [];
    const { labels, series } = chartData;
    const maxLen = Math.max(0, ...series.map((s) => s.data.length));
    const L = Math.max(labels.length, maxLen);
    for (let i = 0; i < L; i++) {
      const row: any = { label: labels[i] ?? String(i) };
      series.forEach((s, idx) => {
        row[`s${idx}`] = typeof s.data[i] === "number" ? s.data[i] : 0;
      });
      rows.push(row);
    }
    return rows;
  }, [chartData]);

  const isBar = (chartData.kind || "bar").toLowerCase() === "bar";

  return (
    <div className="w-full h-72 border rounded-xl p-2 bg-background">
      <ResponsiveContainer width="100%" height="100%">
        {isBar ? (
          <BarChart data={data} margin={{ top: 10, right: 20, left: 0, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="label" />
            <YAxis />
            <Tooltip />
            <Legend />
            {chartData.series.map((s, idx) => (
              <Bar key={idx} dataKey={`s${idx}`} name={s.label || `Series ${idx + 1}`} fill={idx === 0 ? "#8884d8" : "#82ca9d"} />
            ))}
          </BarChart>
        ) : (
          <LineChart data={data} margin={{ top: 10, right: 20, left: 0, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="label" />
            <YAxis />
            <Tooltip />
            <Legend />
            {chartData.series.map((s, idx) => (
              <Line key={idx} type="monotone" dataKey={`s${idx}`} name={s.label || `Series ${idx + 1}`} stroke={idx === 0 ? "#8884d8" : "#82ca9d"} dot={false} />
            ))}
          </LineChart>
        )}
      </ResponsiveContainer>
    </div>
  );
}
