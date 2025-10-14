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
  TooltipProps,
} from "recharts";
import { ValueType, NameType } from "recharts/types/component/DefaultTooltipContent";

export interface Series {
  label: string;
  data: number[];
}

export interface ChartData {
  kind: string; // 'bar' | 'line'
  labels: string[];
  series: Series[];
}

// Adaptive number formatting: no decimals for large numbers (>=1000), 2 decimals for small
const formatNumber = (val: any): string => {
  if (typeof val !== "number" || isNaN(val)) return String(val ?? "");
  if (Math.abs(val) >= 1000) {
    return new Intl.NumberFormat("en-US", {
      minimumFractionDigits: 0,
      maximumFractionDigits: 0,
    }).format(val);
  }
  return new Intl.NumberFormat("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(val);
};

// Custom tooltip with backdrop blur and formatted numbers
const CustomTooltip = ({ active, payload, label }: TooltipProps<ValueType, NameType>) => {
  if (!active || !payload || !payload.length) return null;

  return (
    <div className="bg-background/95 border border-border rounded-lg shadow-md p-3 backdrop-blur-sm">
      <p className="font-medium text-sm mb-2">{label}</p>
      {payload.map((entry, index) => (
        <p key={index} className="text-sm" style={{ color: entry.color }}>
          <span className="font-medium">{entry.name}:</span> {formatNumber(entry.value)}
        </p>
      ))}
    </div>
  );
};

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

  // Chart color palette - multiple distinct colors
  const getChartColor = (index: number): string => {
    const colors = [
      '#8884d8', // Purple-blue
      '#82ca9d', // Teal-green
      '#ffc658', // Orange-yellow
      '#ff7c7c', // Coral-red
      '#8dd1e1', // Sky blue
      '#d084d0', // Lavender
      '#a4de6c', // Light green
    ];
    return colors[index % colors.length];
  };

  return (
    <div className="w-full border rounded-xl p-6 bg-gray-50/30 dark:bg-gray-800/20 shadow-sm hover:shadow-md transition-shadow duration-300">
      <div className="w-full h-96">
        <ResponsiveContainer width="100%" height="100%">
          {isBar ? (
            <BarChart data={data} margin={{ top: 10, right: 20, left: 0, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="currentColor" strokeOpacity={0.1} />
              <XAxis dataKey="label" stroke="currentColor" strokeOpacity={0.5} />
              <YAxis axisLine={false} stroke="currentColor" strokeOpacity={0.5} tickFormatter={(v) => formatNumber(v)} />
              <Tooltip content={<CustomTooltip />} cursor={false} />
              <Legend />
              {chartData.series.map((s, idx) => (
                <Bar key={idx} dataKey={`s${idx}`} name={s.label || `Series ${idx + 1}`} fill={getChartColor(idx)} />
              ))}
            </BarChart>
          ) : (
            <LineChart data={data} margin={{ top: 10, right: 20, left: 0, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="currentColor" strokeOpacity={0.1} />
              <XAxis dataKey="label" stroke="currentColor" strokeOpacity={0.5} />
              <YAxis axisLine={false} stroke="currentColor" strokeOpacity={0.5} tickFormatter={(v) => formatNumber(v)} />
              <Tooltip content={<CustomTooltip />} cursor={false} />
              <Legend />
              {chartData.series.map((s, idx) => (
                <Line key={idx} type="monotone" dataKey={`s${idx}`} name={s.label || `Series ${idx + 1}`} stroke={getChartColor(idx)} strokeWidth={2} dot={false} activeDot={{ r: 6 }} />
              ))}
            </LineChart>
          )}
        </ResponsiveContainer>
      </div>
    </div>
  );
}
